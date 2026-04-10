# Inventory Skill

## 模块描述
处理玩家背包、物品、道具相关查询。

## 触发词
背包、包里、包裹、物品、道具、inventory、backpack、item

## 可用 Tools

### query_inventory
- 功能：查询当前玩家背包中的物品与数量。
- 参数：无。默认使用当前激活存档。
- 返回：`items` 列表，包含 `item_id`、`item_name`、`quantity`、`icon`。

## 使用约束
- 这是只读查询。
- 若后续要扩展为使用/丢弃物品，应先查询库存再执行写操作。
