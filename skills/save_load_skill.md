# Save Load Skill

## 模块描述
处理手动存档与读档请求。

## 触发词
存档、读档、保存、加载、save、load、checkpoint

## 可用 Tools

### save_checkpoint
- 功能：将当前会话快照写入手动存档。
- 参数：
  - `save_label`：可选，手动存档标签。
- 返回：存档结果和玩家槽位信息。

### load_checkpoint
- 功能：从最新存档或指定存档槽恢复会话。
- 参数：
  - `player_id`：可选，目标玩家存档 id。
  - `slot_name`：可选，目标存档槽名称。
- 返回：加载后的完整会话快照。

## 使用约束
- `load_checkpoint` 会直接覆盖当前内存会话。
- 若同时提供 `player_id` 与 `slot_name`，优先使用明确的 `player_id`。
