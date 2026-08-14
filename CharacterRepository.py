from __future__ import annotations

from typing import Iterator, Mapping, MutableMapping

from CharacterProfile import CharacterProfile


class CharacterRepository(MutableMapping[str, "CharacterProfile"]):
    """角色档案的单一持有者与读写入口。

    以 MutableMapping 协议对外兼容既有 dict 用法(``.get()`` / ``[]`` /
    ``in`` / 迭代 / ``.update()`` / ``.clear()``),因此可无缝替换原先散落的
    ``character_profiles`` dict。同时提供**具名写方法**作为推荐入口,
    后续阶段逐步把调用方的 ``repo[x] = ...`` 就地写收敛到具名方法,
    最终形成单一、可审计的写路径。
    """

    __slots__ = ("_profiles",)

    def __init__(self, profiles: Mapping[str, "CharacterProfile"] | None = None) -> None:
        self._profiles: dict[str, CharacterProfile] = dict(profiles or {})

    # --- MutableMapping 协议(兼容既有 dict 用法) ---

    def __getitem__(self, actor_id: str) -> CharacterProfile:
        return self._profiles[actor_id]

    def __setitem__(self, actor_id: str, profile: "CharacterProfile") -> None:
        self._profiles[actor_id] = profile

    def __delitem__(self, actor_id: str) -> None:
        del self._profiles[actor_id]

    def __iter__(self) -> Iterator[str]:
        return iter(self._profiles)

    def __len__(self) -> int:
        return len(self._profiles)

    def __contains__(self, actor_id: object) -> bool:
        return actor_id in self._profiles

    # --- 具名写入口(推荐) ---

    def set_profile(self, actor_id: str, profile: "CharacterProfile") -> None:
        """整档写入或替换单个角色。"""
        self._profiles[actor_id] = profile

    def update_field(self, actor_id: str, field: str, value: object) -> None:
        """基于现有档案更新单个字段。缺失角色则以该字段建档。"""
        current = dict(self._profiles.get(actor_id, {}))
        current[field] = value
        self._profiles[actor_id] = current  # type: ignore[assignment]

    def bulk_update(self, profiles: Mapping[str, "CharacterProfile"]) -> None:
        """批量合并档案(story cast 构建等场景)。"""
        self._profiles.update(profiles)

    def replace_all(self, profiles: Mapping[str, "CharacterProfile"]) -> None:
        """清空并以新档案集重建(整幕重铸 cast 的场景)。"""
        self._profiles.clear()
        self._profiles.update(profiles)

    def as_dict(self) -> dict[str, "CharacterProfile"]:
        """返回底层 dict(持久化 / 快照等需要真实 dict 的场景)。"""
        return self._profiles
