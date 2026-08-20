from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Sequence
from typing import Any, TypedDict

from dotenv import load_dotenv

from PromptUtils import render_json_instruction


llm_perf_logger = logging.getLogger("llm.perf")

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency in local smoke tests
    OpenAI = None


load_dotenv()


class AgentMessage(TypedDict):
    speaker: str
    content: str


DEFAULT_NETWORK_TIMEOUT_SECONDS = 300


class BaseAgent:
    # 记住每个 endpoint 是否支持结构化 response_format(json_schema)。
    # 首次探测到 unavailable 后缓存,后续同 endpoint 直接走 fallback,
    # 省掉「必失败的第一趟请求」。key = base_url。
    _response_format_unsupported: set[str] = set()

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        system_prompt: str = "",
        client: Any | None = None,
        **kwargs: Any,
    ) -> None:
        self.base_url = base_url or os.getenv("LLM_BASE_URL")
        self.api_key = api_key or os.getenv("LLM_API_KEY")
        self.model = model or os.getenv("LLM_MODEL_ID")
        self.temperature = kwargs.get("temperature", 0.6)
        self.max_tokens = kwargs.get("max_tokens")
        self.timeout = kwargs.get(
            "timeout",
            float(os.getenv("LLM_TIMEOUT_SECONDS", str(DEFAULT_NETWORK_TIMEOUT_SECONDS))),
        )
        self.system_prompt = system_prompt
        self._client = client

    def _build_client(self) -> Any:
        if self._client is not None:
            return self._client

        if OpenAI is None:
            raise RuntimeError(
                "The `openai` package is not installed. Install it with `python -m pip install openai` "
                "before using model-backed agents."
            )

        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
        )
        return self._client

    def command(
        self,
        instruction: str,
        history: Sequence[AgentMessage] | None = None,
        response_format: str | dict[str, Any] | None = None,
    ) -> Any:
        started = time.perf_counter()
        perf_flags = {"fallback": False, "repair": False}
        try:
            return self._command_inner(instruction, history, response_format, perf_flags)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            llm_perf_logger.info(
                "LLM %s %.0fms%s%s",
                type(self).__name__,
                elapsed_ms,
                " +fallback" if perf_flags["fallback"] else "",
                " +repair" if perf_flags["repair"] else "",
            )

    def _command_inner(
        self,
        instruction: str,
        history: Sequence[AgentMessage] | None,
        response_format: str | dict[str, Any] | None,
        perf_flags: dict[str, bool],
    ) -> Any:
        client = self._build_client()
        messages = [
            {
                "role": "system",
                "content": self.system_prompt,
            },
            *(
                [
                    {
                        "role": "user",
                        "content": f"[{item['speaker']}] {item['content']}",
                    }
                    for item in history
                ]
                if history
                else []
            ),
            {"role": "user", "content": instruction},
        ]

        params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }

        if self.max_tokens:
            params["max_tokens"] = self.max_tokens

        if response_format == "json":
            params["response_format"] = {"type": "json_object"}
        elif isinstance(response_format, dict):
            params["response_format"] = response_format

        endpoint = self.base_url or ""

        def _run_fallback() -> Any:
            perf_flags["fallback"] = True
            fallback_params = dict(params)
            fallback_params.pop("response_format", None)
            fallback_messages = list(messages)
            fallback_messages[-1] = {
                "role": "user",
                "content": self._build_json_fallback_instruction(instruction, response_format),
            }
            fallback_params["messages"] = fallback_messages
            return client.chat.completions.create(**fallback_params)

        structured = response_format is not None and "response_format" in params
        if structured and endpoint in self._response_format_unsupported:
            # 已知该 endpoint 不支持结构化 response_format:跳过必失败的第一趟。
            response = _run_fallback()
        else:
            try:
                response = client.chat.completions.create(**params)
            except Exception as exc:
                if response_format is None or not self._is_response_format_unsupported(exc):
                    raise
                if endpoint:
                    self._response_format_unsupported.add(endpoint)
                response = _run_fallback()

        content = response.choices[0].message.content

        if not content:
            raise ValueError("LLM returned an empty response.")

        if response_format is None:
            return content

        try:
            return self._parse_json_payload(content)
        except json.JSONDecodeError:
            try:
                perf_flags["repair"] = True
                repaired_content = self._repair_json_response(
                    client=client,
                    instruction=instruction,
                    malformed_content=content,
                    response_format=response_format,
                )
                return self._parse_json_payload(repaired_content)
            except Exception as repair_exc:
                raise ValueError(self._format_invalid_json_error(content)) from repair_exc

    def _is_response_format_unsupported(self, exc: Exception) -> bool:
        error_text = str(exc).lower()
        return "response_format" in error_text and "unavailable" in error_text

    def _parse_json_payload(self, content: str) -> Any:
        text = self._extract_json_text(content)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            repaired = self._repair_json_text_locally(text)
            return json.loads(repaired)

    def _repair_json_response(
        self,
        *,
        client: Any,
        instruction: str,
        malformed_content: str,
        response_format: str | dict[str, Any],
    ) -> str:
        repair_messages = [
            {
                "role": "system",
                "content": (
                    "You repair malformed or truncated JSON outputs. "
                    "Return only valid JSON. Do not use markdown fences."
                ),
            },
            {
                "role": "user",
                "content": (
                    "The following model output was intended to satisfy an instruction and a JSON response format, "
                    "but it was malformed or truncated. Rewrite it as complete, valid JSON only.\n\n"
                    "Original instruction:\n"
                    f"{instruction}\n\n"
                    f"{render_json_instruction('Required response format:', {'type': 'json_object'} if response_format == 'json' else response_format)}\n\n"
                    "Malformed output:\n"
                    f"{self._extract_json_text(malformed_content)}"
                ),
            },
        ]
        repair_params: dict[str, Any] = {
            "model": self.model,
            "messages": repair_messages,
            "temperature": min(float(self.temperature), 0.2),
        }
        if self.max_tokens:
            repair_params["max_tokens"] = self.max_tokens
        response = client.chat.completions.create(**repair_params)
        content = response.choices[0].message.content
        if not content:
            raise ValueError("LLM returned an empty repair response.")
        return content

    def _repair_json_text_locally(self, content: str) -> str:
        stripped = self._extract_json_fragment(content)
        if not stripped:
            return content

        chars: list[str] = []
        closers: list[str] = []
        in_string = False
        escaped = False

        for char in stripped:
            chars.append(char)
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                closers.append("}")
            elif char == "[":
                closers.append("]")
            elif char in "}]":
                if closers and closers[-1] == char:
                    closers.pop()

        repaired = "".join(chars).rstrip()
        if in_string:
            repaired += '"'

        repaired = re.sub(r",\s*$", "", repaired)
        repaired += "".join(reversed(closers))
        repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
        return repaired

    def _extract_json_fragment(self, content: str) -> str:
        stripped = content.strip()
        object_start = stripped.find("{")
        array_start = stripped.find("[")

        starts = [index for index in (object_start, array_start) if index != -1]
        if not starts:
            return stripped
        start = min(starts)
        return stripped[start:].strip()

    def _format_invalid_json_error(self, content: str) -> str:
        compact = " ".join(self._extract_json_text(content).split())
        if len(compact) > 240:
            compact = compact[:240] + "..."
        return f"Expected valid JSON, but the model returned malformed or truncated content: {compact}"

    def _build_json_fallback_instruction(
        self,
        instruction: str,
        response_format: str | dict[str, Any],
    ) -> str:
        if response_format == "json":
            return f"{instruction}\n\nReturn only a valid JSON object. Do not use markdown fences."

        return (
            f"{instruction}\n\n"
            "Return only valid JSON. Do not use markdown fences or explanatory text.\n\n"
            f"{render_json_instruction('Follow this response format specification:', response_format)}"
        )

    def _extract_json_text(self, content: str) -> str:
        stripped = content.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()
        return stripped
