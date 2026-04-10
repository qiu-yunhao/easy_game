# Memory Skill

## 模块描述
提供当前故事记忆、压缩历史、冲突线索与未解环节的只读查询。
当编剧或导演需要确认“最近发生了什么、有哪些冲突还没收束、哪些线索不能忘”时，应使用此技能。

## 可用 Tools

### 1. query_story_memory
- 功能：查询当前记忆状态，包括 scene memory、playwright memory、director memory 与最近历史片段。
- 典型用途：
  - 判断当前拍点应延续哪条冲突
  - 续写章节时避免遗忘已揭示事实
  - 给导演提供更稳定的 tension / focus 参考

## 使用约束
- 这是只读工具，不修改任何状态。
- 记忆结果用于保持连续性，不应覆盖当前 scene context 的实时事实。
- 如需决定具体谁能上场或某层角色是否已满，应优先结合 `character_roster_skill`。
