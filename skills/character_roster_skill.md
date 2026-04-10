# Character Roster Skill

## 模块描述
供编剧、导演、角色创建等 Agent 查询当前角色清单与层级容量。

## 触发词
角色清单、角色列表、roster、cast、layer

## 可用 Tools

### query_character_roster
- 功能：查询当前存档的角色清单、层级统计与容量提示。
- 参数：
  - `player_id`：可选，默认使用当前激活存档。
  - `layer_filter`：可选，支持 `L1`、`L2`、`ActorAgent`、`all`。
- 返回：`summary`、`characters`、`decision_hints`。

## 使用约束
- 这是只读查询。
- 角色创建前应先读取该技能，确认当前层级容量是否足够。
