from __future__ import annotations

"""启动环境自动加载与完备性检查。

对外单一入口 ``ensure_environment()``：先幂等加载项目根 ``.env``，再分组校验
运行 StoryTemplate 真集成所需的外部依赖（DeepSeek LLM / MySQL / PostgreSQL+pgvector
/ bge 模型缓存）。检查深度=变量存在 + 真实连通性探测。

失败策略为 fail-fast：收集**全部**缺口后一次性抛 ``EnvironmentError``，异常信息带
中文修复指引，避免一个个试错。各 ``require_*`` 开关允许只用部分依赖的入口（如仅测
切块逻辑）跳过无关分组。
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# bge 模型 HuggingFace 缓存目录（探测权重是否已下载，不加载模型以免拉起 torch）。
_BGE_CACHE_DIR = (
    Path.home() / ".cache" / "huggingface" / "hub" / "models--BAAI--bge-small-zh-v1.5"
)


@dataclass
class GroupResult:
    """单个依赖分组的检查结果。"""

    name: str
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class EnvReport:
    """整体环境检查报告，供调用方打印 ✓/✗ 清单。"""

    groups: list[GroupResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(group.ok for group in self.groups)

    def all_errors(self) -> list[str]:
        errors: list[str] = []
        for group in self.groups:
            errors.extend(group.errors)
        return errors

    def __str__(self) -> str:
        lines = ["环境检查报告："]
        for group in self.groups:
            mark = "✓" if group.ok else "✗"
            suffix = f"（{group.detail}）" if group.detail else ""
            lines.append(f"  {mark} {group.name}{suffix}")
            for err in group.errors:
                lines.append(f"      - {err}")
        return "\n".join(lines)


def _check_llm() -> GroupResult:
    result = GroupResult(name="DeepSeek LLM")
    base_url = (os.getenv("LLM_BASE_URL") or "").strip()
    api_key = (os.getenv("LLM_API_KEY") or "").strip()
    model = (os.getenv("LLM_MODEL_ID") or "").strip()

    if not api_key:
        result.errors.append(
            "LLM_API_KEY 未填：去 DeepSeek 控制台生成 sk-xxx 后写入 .env"
        )
    if not base_url.startswith("http"):
        result.errors.append(
            f"LLM_BASE_URL 不是合法 URL（当前：{base_url!r}），应形如 https://api.deepseek.com"
        )
    if not model:
        result.errors.append("LLM_MODEL_ID 未填，应形如 deepseek-chat")

    if result.errors:
        result.ok = False
    else:
        result.detail = f"{model} @ {base_url}"
    # 不实际打 API：省 token，真实连通性留给首次调用暴露。
    return result


def _check_mysql() -> GroupResult:
    result = GroupResult(name="MySQL")
    url = (os.getenv("MYSQL_URL") or "").strip()
    if not url:
        result.ok = False
        result.errors.append("MYSQL_URL 未配置，应形如 mysql+pymysql://root@localhost:3306/easygame_test")
        return result

    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        result.detail = url
    except Exception as exc:  # noqa: BLE001 - 汇总所有连接问题给用户
        result.ok = False
        result.errors.append(
            f"MySQL 连接失败：{exc}\n"
            "      修复：pip install pymysql；"
            'mysql -u root -e "CREATE DATABASE IF NOT EXISTS easygame_test CHARACTER SET utf8mb4;"'
        )
    return result


def _check_pg() -> GroupResult:
    result = GroupResult(name="PostgreSQL + pgvector")
    url = (os.getenv("PG_URL") or "").strip()
    if not url:
        result.ok = False
        result.errors.append("PG_URL 未配置，应形如 postgresql+psycopg://<user>@localhost:5432/easygame_test")
        return result

    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            has_vector = conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            ).first()
        engine.dispose()
        if not has_vector:
            result.ok = False
            result.errors.append(
                "pgvector 扩展未启用。修复："
                'psql -d easygame_test -c "CREATE EXTENSION IF NOT EXISTS vector;"'
            )
        else:
            result.detail = url
    except Exception as exc:  # noqa: BLE001
        result.ok = False
        result.errors.append(
            f"PostgreSQL 连接失败：{exc}\n"
            "      修复：确认 PG 已启动且库存在，"
            'psql -d postgres -c "CREATE DATABASE easygame_test;"'
        )
    return result


def _check_bge() -> GroupResult:
    result = GroupResult(name="bge 模型缓存")
    # 探测缓存目录下是否有权重实体（快照里的 model.safetensors），不加载模型。
    weights = list(_BGE_CACHE_DIR.glob("snapshots/*/model.safetensors")) + list(
        _BGE_CACHE_DIR.glob("snapshots/*/pytorch_model.bin")
    )
    if not weights:
        result.ok = False
        result.errors.append(
            f"bge-small-zh-v1.5 未下载到 {_BGE_CACHE_DIR}。修复：设置 "
            "HF_ENDPOINT=https://hf-mirror.com 后运行任一 embedding 集成测试触发下载"
        )
    else:
        result.detail = "BAAI/bge-small-zh-v1.5"
    return result


def ensure_environment(
    *,
    require_llm: bool = True,
    require_mysql: bool = True,
    require_pg: bool = True,
    require_bge: bool = True,
) -> EnvReport:
    """加载 .env 并校验运行所需环境；任一必需项缺失即抛 EnvironmentError。

    各 require_* 开关关闭时跳过对应分组（如只测切块逻辑可全部关闭）。
    """
    load_dotenv()  # 幂等加载项目根 .env

    report = EnvReport()
    if require_llm:
        report.groups.append(_check_llm())
    if require_mysql:
        report.groups.append(_check_mysql())
    if require_pg:
        report.groups.append(_check_pg())
    if require_bge:
        report.groups.append(_check_bge())

    if not report.ok:
        errors = "\n".join(f"  - {err}" for err in report.all_errors())
        raise EnvironmentError(f"环境不完备，无法启动：\n{errors}\n\n{report}")

    return report


if __name__ == "__main__":  # pragma: no cover - 手动排查用
    print(ensure_environment())
