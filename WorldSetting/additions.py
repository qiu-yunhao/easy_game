from __future__ import annotations

from copy import deepcopy
from typing import Any


def append_world_additions(
    world_setting: dict[str, Any],
    additions: dict[str, Any] | None,
) -> dict[str, Any]:
    """Append only new facts/locations; never replace an established world fact."""
    setting = deepcopy(world_setting)
    additions = additions or {}
    facts = list(setting.get("incremental_facts", []) or [])
    for fact in additions.get("facts", []) or []:
        text = str(fact or "").strip()
        if text and text not in facts:
            facts.append(text)
    setting["incremental_facts"] = facts

    places = list(setting.get("factions_geography", []) or [])
    known = {str(item.get("name", "") or "").strip() for item in places if isinstance(item, dict)}
    for location in additions.get("locations", []) or []:
        name = str(location or "").strip()
        if name and name not in known:
            places.append({"name": name, "kind": "location", "description": "章节中新增的地点。"})
            known.add(name)
    setting["factions_geography"] = places
    return setting
