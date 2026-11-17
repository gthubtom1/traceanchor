# 研究来源与许可边界

本产品运行时为 Python 标准库独立实现。当前谱系记录不登记任何上游代码、提示词、技能正文、表数据、测试夹具、品牌、图像、字体或二进制的复制分发；四方是研究来源。机制学习与复制实现分开记账；这里的来源归属也不是授权把上游整树纳入产品。

四方项目名称仅用于准确识别研究来源，不作为本产品品牌或背书。根许可不覆盖所有嵌入目录、外部依赖、资产和商标。固定提交与逐层锚点见 [baselines.json](baselines.json)。

| 来源 | 固定研究版本的许可身份 | 本产品处理 |
|---|---|---|
| Reverse Skills | 根 MIT；CTF-Sandbox-Orchestrator 子树 GPLv3 | 仅机制摘要和固定链接；不带技能文本、sidecar 或 bootstrap |
| REA | 根 MIT；THIRD_PARTY_NOTICES 与逐组件许可另计；五个 gitlink 未递归审阅 | 不带源码、生成表、桥接器、native runtime 或 gitlink；未来依赖另审 |
| Craft Anything | 固定提交声明 MIT OR Apache-2.0；NOTICE、品牌/图标/字体等有单独条款 | 不带代码、提示、vendor 补丁、图标、字体或品牌；不沿用历史单一 Apache 元数据 |
| Seep Reverse Lab | 根 GPLv3；包 GPL-3.0-or-later；部分嵌入 skill 自述 MIT；若干 Web 来源许可仍未知 | 不带镜像、档案、案例、代码、凭据类材料或资产；未知许可材料保持排除 |

## 实际分发清单与后续门槛

当前 `code_reuse`、`prompt_reuse`、`asset_reuse`、`upstream_runtime_dependency` 均为空。Python 解释器与标准库由用户可信环境提供，不将研究快照中的依赖复制进包。产品自身许可证及最终发布文件清单由发布维护者维护，本文不替代最终包/历史公开审计，也不推断四方中所有组件均已审清。

未来若确实引入第三方实现或依赖，先建条目：来源 URL、固定版本/提交、精确路径/内容摘要、作者及 notice、逐组件许可、修改范围、分发形态、安装副作用、许可证义务、验证与维护 owner。只有许可清楚且独立安装/维护/资格验收落实，才调整本清单和发布包。原来机制级的 independent-implementation 记录不得悄悄变成 code-reuse。未经核对的根许可证、GitHub 自动标签或“已开源”措辞不是逐项归属记录。
