# Character Status Skill

## 模块描述
用于查询玩家当前的修炼状态与章节推进条件。

- 玩家侧适用场景：查看自身属性、修为、当前状态。
- Story Agent 侧适用场景：编剧规划章节、判断下一重境界、生成章节扩展时读取玩家修炼进度。

## 可用 Tools

### query_player_status
- 功能：查询玩家当前的角色状态与修炼进度。
- 主要返回：
  - `player_profile`
  - `attributes`
  - `chapter_progress`

## Story Agent 约定
- 在 Agent-First 的 story prompt 中，这个工具只提供精简快照，不会重复携带整份玩家资料。
- `player_profile` 只保留：
  - `character_id`
  - `name`
- `attributes` 只保留：
  - `realm`
  - `spiritual_root`
  - `main_technique`
  - `current_chapter_realm`
  - `next_chapter_realm`
  - `chapter_transition_requirement`

## 使用约束
- 章节规划优先关注 `attributes` 里的境界与章节推进字段，不要把它当成完整角色档案。
- 场景信息请改用 `scene_skill`。
- 角色清单与配角分配请改用 `character_roster_skill`。
