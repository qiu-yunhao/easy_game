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

### Code Review 处理(阶段1)
- **中等-双引用漂移**:`web_session.character_profiles` 生命周期内曾在裸 dict/repo 间交替。已在 `_reload_dependencies` 赋值后加 `assert isinstance(..., CharacterRepository)`,消除隐式时序依赖。已修。
- **轻微-isinstance**:`_profiles_as_dict` 从 `getattr` 鸭子类型改为 `isinstance(profiles, CharacterRepository)`,意图更清晰。已修。
- **轻微-`__contains__` 冗余**:删除手写版,由 MutableMapping 基类派生。已修。
- **判断-bulk_update 保留(与 reviewer 建议相反)**:reviewer 建议删除无调用方的 `bulk_update`。我**保留**并注明"增量构建场景用",理由:它是 repo 的合法公共写方法,阶段2 拆 story_cast 时很可能用到,删了再加回来反而折腾。**待你定夺**:若你倾向严格 YAGNI,可删。



