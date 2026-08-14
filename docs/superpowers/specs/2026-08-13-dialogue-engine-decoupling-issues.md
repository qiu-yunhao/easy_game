# 对话引擎解耦 — 问题与决策记录

> 用途:重构过程中遇到的错误、卡点、拿不准但已先行处理的判断,统一沉淀在此。
> 用户后续 review。格式:每条含【阶段】【类型:错误/判断/待确认】【处理】。

---

## 阶段 1: CharacterRepository

### 判断-1:Repository 兼容策略
- **背景**:大量测试用 `GraphDependencies(character_profiles={dict})` 传裸 dict 构造;62 处读点把整个 profiles 当 dict 用。
- **判断**:`CharacterRepository` 实现 `Mapping` 协议(`.get()`/`[]`/`in`/迭代 全兼容),既能当只读 dict 传给既有读路径,又提供具名写方法。`GraphDependencies.character_profiles` 做成 property:构造时传 dict 自动包成 repo,读时返回 repo。测试构造代码无需改动。
- **状态**:已采用。若后续发现某读点依赖 dict 独有方法(如 `.items()` 之外的 mutate),再评估。

### 判断-2:Repository 暂继承 MutableMapping(而非纯只读)
- **背景**:测试与生产存在 `repo.clear()` / `repo.update()` / `repo[x]=` 等就地写;若 Repository 只读会大面积崩。
- **判断**:阶段1 让 `CharacterRepository` 继承 `MutableMapping`,**兼容**所有既有 dict 写法,同时提供具名写方法(`set_profile`/`update_field`/`bulk_update`/`replace_all`)作为**推荐入口**。已把 4 处生产写点(nodes.py 突破改 realm、contextual_scene_handoffs 发物品、story_cast_nodes 重建 cast)收敛到具名方法。
- **待确认(后续阶段)**:是否要进一步**禁用** `__setitem__`/`update`/`clear`,强制只走具名方法。目前保留兼容以支撑渐进迁移。若你要求"硬单一写入口",阶段4/5 时可收口。

### 错误-1:序列化路径不认识 Repository
- **现象**:`_export_runtime_snapshot_unlocked` 把 repo 直接 `json.dumps` → `TypeError: CharacterRepository is not JSON serializable`;`store_snapshot` 又用 `require_snapshot_value(..., dict)` 强校验。
- **处理**:在 `web_session.py` 加 `_profiles_as_dict()` helper,导出前把 repo 解包为底层 dict。已修复,测试全绿。


