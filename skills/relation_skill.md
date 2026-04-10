# Relation Skill

## 模块描述
处理玩家与指定角色之间的关系、好感和互动标记查询。

## 触发词
关系、好感、亲密、relation、favor、affection

## 可用 Tools

### query_relation
- 功能：查询玩家与指定角色的关系分数与状态。
- 参数：
  - `target_name`：角色名称或角色 id。
- 返回：`display_name`、`score`、`life_status`、`is_on_stage`、`dialogue_flags`。

## 使用约束
- 必须先提供明确目标角色。
- 若输入中没有目标角色名，应优先从当前登场角色中推断。
