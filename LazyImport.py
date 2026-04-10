from __future__ import annotations

from importlib import import_module
from typing import Any


class LazySymbol:
    def __init__(self, module_name: str, attr_name: str) -> None:
        self.module_name = module_name
        self.attr_name = attr_name

    def _resolve(self) -> Any:
        module = import_module(self.module_name)
        return getattr(module, self.attr_name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._resolve()(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)

    def __repr__(self) -> str:
        return f"<lazy symbol {self.module_name}:{self.attr_name}>"
