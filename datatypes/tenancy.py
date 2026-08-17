from __future__ import annotations

"""租户前缀约定（集中一处，杜绝各模块各写一份）。

云端多用户下 scene_id 由 chapter+序号拼成、各玩家共用同一套，若不加租户前缀，
不同玩家的同名场景会生成相同 doc_id，upsert 时互相覆盖造成跨租户数据丢失。
这是既有 code review 踩过的致命坑，故统一在此提供，所有模块必须复用。
"""


def tenant_prefix(user_id: int, player_id: int) -> str:
    """返回 ``u{user}:p{player}:`` 形式的租户前缀。"""
    return f"u{user_id}:p{player_id}:"


def template_prefix(template_id: int, user_id: int, player_id: int) -> str:
    """模板层在租户前缀前再加 ``tmpl:{template_id}:`` 段，隔离多模板。"""
    return f"tmpl:{template_id}:{tenant_prefix(user_id, player_id)}"


def template_scope_prefix(template_id: int) -> str:
    """全局共享模板的向量前缀 ``tmpl:{template_id}:``（不带 user/player）。

    情节模板是平台级共享资产，所有游戏/存档均可选用，与 per-player 回忆租户
    解耦，故只按 template_id 隔离多模板，不叠加 user/player 前缀。
    """
    return f"tmpl:{template_id}:"
