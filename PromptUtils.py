from __future__ import annotations

import json
from typing import Any


def render_json_instruction(instruction: str, payload: Any) -> str:
    return f"{instruction.rstrip()}\n\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
