# TraceAnchor 来源谱系

这里保存可公开、可复核的机制摘要，不分发研究快照、完整研究报告、私人工作路径或上游代码/提示词/品牌素材。四方均为静态研究输入，不是必装组件、依赖、兼容层或效果排名。历史阅读范围有限，固定提交锚点不代表通读全仓；上游测试源码中的断言也不是本产品的运行成绩。

## 如何查找

- [baselines.json](baselines.json)：四方公开 URL、研究提交、研究日期、许可层、清理后的报告入口，以及三种独立基线。
- [mechanisms.json](mechanisms.json)：稳定 TA-ID → 来源路径/固定 blob 行范围/符号 → 本地模块/合同/验证 → 差异、维护责任和可推翻条件。`source_to_mechanisms` 和 `local_to_mechanisms` 提供反向索引。
- [research-summary.md](research-summary.md)：必要的独立摘要与静态研究局限，不含完整报告原文。
- [decisions.md](decisions.md)：采用、重写、插件化、推迟和舍弃；每项均有重开门槛。
- [notices.md](notices.md)：研究归属与实际分发的区别，根许可之外的组件/品牌边界。
- [review-template.md](review-template.md)：下一轮的差异、覆盖、决策、L1 归档与 L2/L3 回收记录模板。
- [UPSTREAM-REVIEW-PROMPT.md](../../UPSTREAM-REVIEW-PROMPT.md)：可复制给未来 AI 的自包含、默认只读静态复评任务。

## 基线不是一个可浮动版本号

`research_baseline` 是本次原始研究事实；`review_baselines` 是未来实际研究过的新提交追加记录；`product_influence_baselines` 仅记录被明确决策采纳、确实影响本产品实现的提交。首次研究影响了机制设计，三者的含义仍不同。上游发版、提交变多、抓取成功或复评报告完成，都不自动修改其他基线。可同时研究新提交而继续保留旧影响基线。

稳定机制 ID 不回收给另一机制。拆分时保留旧 ID 并记 successors；撤回时保留历史与原因。来源行号只对应链接中的固定提交；新提交另建锚点，不改写旧行号冒充连续。原创 TA-010/011/012 的来源数组为空，不为四方覆盖强造出处。

## 验证与公开边界

`tests/test_hosts.py` 的 ProvenanceTests 检查字段、固定链接、双向一致性和提示词边界；这不是研究结论的自动语义证明。宿主协议、真实服务链、配置规范、真实宿主任务分别记录在 [hosts.md](../hosts.md)。其他模块的通过情况由实际资格记录裁决，映射中的验收 ID 不是预先标绿。

公开材料仅保留必要机制、来源身份、相对路径和固定 GitHub blob 链接。来源的嵌套说明只当数据；不带入其执行要求。未来下载工作树和中间产物按 L2/L3 管理，证据摘要与决策先归档 L1；回收后仍可由固定提交、路径、行号和完整性记录复核结论。完整上游副本不进入公开发行包。
