# R3 支持、资格与可选工具

适用：**0.2.0 候选**，2026-11-18。以当前源码和实际有限试验说明能力，不是 0.2.0 Release 通告或全平台支持承诺。0.1.1 包、标签和旧资格记录保持历史核心版定位；旧 [support.md](support.md)、[qualification.json](qualification.json) 与安装/发布记录不自动获得 R3 身份。最新合同和门状态分别在 [CONTRACT-R3.md](goal/CONTRACT-R3.md)、[status.json](goal/status.json)。

首次使用先读 [professional-guide.md](professional-guide.md)；存储、残留和升级见 [r3-maintenance.md](r3-maintenance.md)。

## 1. 资格按层读，不用一格“支持”包办

为什么：工具在 PATH、适配器实现、真实执行、宿主协作和发布包验证证明的是不同事情。

| 层级 | 证明什么 | 不代表什么 |
|---|---|---|
| implemented | 当前源码有入口和实现 | 该工具/平台已实际运行 |
| static-checked | 格式、配置或方法说明已核对 | 宿主已加载、业务成功 |
| available-unprobed | 可见某工具路径；doctor 不运行探针 | 版本兼容、工具实际完成任务 |
| real-tool / real-service-tested | 指定环境与输入上真实调用工具，或经实际 service 链执行 | 任意目标、全部分支、其他环境或发布包已合格 |
| host-workflow-observed | 当前宿主真实分工、读证据、写候选和修正 | 所有 MCP 宿主/版本均端到端验证 |
| current-artifact-qualified | 当前源码/构建包摘要绑定的安装与业务/维护检查 | 仅凭旧包或测试数量自动授予此级 |
| not-run / not-qualified / experimental | 该范围尚无对应资格；有路线时说明路线 | 可以由 mock、文档、manifest 或 Node 成功补成绿色 |

运行记录还区分 pass、fail、blocked、partial、stale、skip、not-run。`professional.status=complete/succeeded` 是方法的采集状态，不是重建 verdict，也不是完整 Goal 完成。

## 2. 静态、动态与工具的实际矩阵

| 输入 / 方法 | 当前实现与真实证据 | 工具与范围 | 保留的边界 |
|---|---|---|---|
| native / `native.disassemble` | 实际机器码反汇编、函数地址、直接符号 call 边、原始反汇编；真实适配器和 service 链已跑 | Windows x64 自建带符号 PE；GNU objdump **2.45** | 头/字符串不是专业分析；没有完整间接调用图、通用反编译或原始源码恢复资格 |
| native / `native.trace` | 实际 GDB 断点、参数、栈与变量；内置 `Breakpoint.stop` 回调回执，不信任目标 stdout 命中标记；修复后重跑资格通过 | GNU GDB **16.3**；样本以 GCC **15.2.0** 构建 | 仅命中场景；调试影响时序；无 GUI、任意表达式求值、内存转储或任意受保护程序资格 |
| APK / `apk.analyze` | 实际 JADX CLI 反编译、新鲜 Java 源、方法与语法调用提示；真实 service 链；代表关键路径另由 dexdump 核 DEX invoke/位置 | JADX **1.5.6**、Java **21.0.12.1**；自建样本使用 Android Build-Tools **34.0.0**，D8 报告 **8.2.2-dev**；所选 android.jar 来自 API **28** | 非自动完整调用图；Java 行号非 DEX 地址；反射/动态 DEX/JNI 等可能未解析；API 28 构建桩非设备运行资格 |
| APK 设备运行 / 重包 / 重签 / 安装 / 插桩 | 各自 **not-qualified** | 当前代表 APK 未签名、未安装 | 静态 complete 不授予上述任何一项资格 |
| JS/Web / `web.observe` | Node inspector 真实加载源核对、函数调用/coverage、前后状态及实际 loopback HTTP 因果链；代表场景 6 次交互、4 条关联请求，真实 service 链已跑 | Node **24.20.0**，有限夹具协议的自建模块 | 非任意网页 URL；无 DOM/渲染/截图资格；依赖闭包及目标直接 I/O 不封存 |
| 浏览器扩展 | `analyze` 有界读取 manifest JSON/文本线索；doctor 明列运行时未资格 | **manifest 静态与 extension runtime 分开** | Node、manifest、网页观察都不替代扩展生命周期、background/service worker/content-script、消息与注入验证 |
| 协议/开发组件/普通文件 | 完整文件身份、适用 Python AST/JSON/HTTP 材料、有限 capture/loopback HTTP、父子研究合同 | 原确定性核心继续复用 | 不是所有格式语义、任意远程服务或任意依赖工程自动构建资格 |

这些是**已测版本点**，不是未经过对照的最低/最高兼容区间。其他版本须记录实际工具、目标和执行证据；路径可见或版本号相近不会自动授予资格。

工具调用统一经过 `tool_runner`，记录目标摘要、工具输出、环境、run/子 run、原始流与选定产物。native 记录所选 executable 摘要/版本输出；APK 记录所选 JADX JAR 摘要及版本，Java/SDK 完整身份由资格记录另保存；Web 记录 Node 版本、helper 和 inspector 实际源摘要。不能把其中某一项当全部环境依赖已密封。

### 浏览器/扩展的明确接入路线

后续 adapter 应使用单独合格的 browser/CDP 或 Playwright、全新受管 profile、明确页面与 extension ID，分别记录导航、DOM/网络、worker/content-script 可达性、消息边界和 profile 清理。诊断分别为 missing、available-unprobed、probe-failed、qualified。当前没有这条真实运行资格，也不会自动安装浏览器或复用个人 profile。路线细节见 [knowledge/web.md](knowledge/web.md)。

## 3. P01—P05 已有事实与证据索引

为什么保留索引而不只给“通过”：每次资格都绑定自己的源码/目标/工具和原始输出；本地 `.validation` 是私有工作材料位置，不保证随 wheel 分发，也不应原样公开。

| 门 | 已实际观察的有限结果 | 索引与最终边界 |
|---|---|---|
| P01 | objdump 专业静态 + GDB 实际运行时；service 链与断点权威负控回归 | `tests/test_tool_runner.py`、`tools/qualify_professional.py`；本地 `.validation/native-c85a89382ca2/qualification.json` 及修复后 `.validation/native-1c79bb4301f7/qualification.json`；最终当前源码/包门另核 |
| P02 | 自建 APK 关键语义静态链、DEX invoke 核对和真实 service 链 | `tools/qualify_apk.py`、`tests/test_apk_adapter.py`；本地 `.validation/apk-fe9f3ef27c95472493432bf3debbaf9c/qualification.json`、`apk-service-23b5d0cb49db/qualification.json`；非设备资格 |
| P03 | Node inspector 交互/状态/网络链与真实 service 链 | `tools/qualify_web.py`、`tests/test_web_adapter.py`；本地 `.validation/web-bed16b5cd8e046f3ad865a5c0abb1c99/summary.json`、`web-service-af0dfdbee69f/qualification.json`；非 DOM/扩展资格 |
| P04 | 新鲜候选从机器码/调试/观察独立重建，V1 首轮通过；参考 V2 造成真实差异后只改 3 常量，协调者实际判分 6 组开发 + 7 组含 sealed 终验通过 | 公开 `assessments/native-parcel/packet/`、`packet-v2/`、候选 notes / notes_v2；本表引用公开结果，不公开/读取封存判分输入和期望；最终当前身份绑定另核 |
| P05 | 父批量报价工具实际使用子研究；V2 子来源变化使旧父验收 stale，增量通过且父代码字节未变 | `tools/qualify_development.py`、`examples/development/quote_batch.py`；本地 `.validation/development-f9a73296953d/qualification.json`；显式审查的开发验收见证，不是盲重建 |

P04 隔离是协作角色和材料纪律，不是 OS 强保密。V1 首轮成功没有人工造错；V2 才是真实差异来源。公开两组差异、候选自测和独立判分分开计数，封存题目不进入用户指南。输入/规格范围外的 CRT 极端解析、溢出等未知仍保留。

## 4. 平台、宿主和包分别评级

| 层 | 当前范围 | 尚待的资格 |
|---|---|---|
| Python / 核心 | Python >=3.11；当前本地 CPython 3.12、Windows 10 x64；核心运行时使用标准库 | 非每个 Python/OS 版本已测 |
| Windows 执行 | Job Object owner/进程族清理、真实工具切片及负控 | Job 非文件系统/网络沙箱；需实际 cleanup 回执 |
| Linux / macOS | POSIX session 实现及历史 CI 机制 | R3 专业链、宿主和安装维护未测组合为 experimental/not-run |
| CLI / service | inspect 与 call 共用 service；真实专业 service 链已跑 | 最终 wheel 安装后的同等业务旅程另核 |
| MCP stdio | 实际协议/真实 service 与 stub 测试分开；knowledge / professional / workspace 已接白名单 | 非所有客户端实际加载；也非任意大产物传输资格 |
| 当前宿主协作 | P04 新鲜工作者独立编写及 V2 维护实际发生 | 非其他模型/宿主效果或受控优越性证明 |
| Claude Code 接线 | 项目 .mcp.json 官方格式静态核对、临时项目配置事务 | 指定客户端真实 MCP 加载/信任/专业任务须单列，协作写候选不替代此项 |
| Codex 接线 | 官方 schema/项目加载源码静态核对，项目 .codex/config.toml 模板和事务 | 指定版本实际加载/信任/专业任务未由模板取得资格，保持实验性 |
| 包和版本 | 历史 0.1.1 已有自己的安装/发布记录；本次准备 0.2.0 候选 | 新元数据、源码/包摘要、隔离安装维护、CI/Release/下载须绑定新版本 |

宿主配置只限显式项目和回执管理，不修改全局模型、认证、权限或 trust。当前宿主负责推理，没有内部第二模型；产品不新增外部模型 API。宿主已有额度仍是实际成本。

## 5. 工具配置、许可与分发边界

为什么按需配置：缺一个工具只影响该方法，不强制用户安装整套专业环境。doctor 只报告能力/PATH 可见性，不运行工具资格探针、不联网安装；导入模块和读取知识也不安装组件。映射见 [专业指南](professional-guide.md)，所有路径由用户填自己的绝对路径。

| 外部组件 | 用途 / 何时需要 | 许可身份与处理 |
|---|---|---|
| GNU binutils / objdump | 原生静态分析 | GNU GPL 系列，具体构建通常 GPL-3.0-or-later；核对所选发行版 notices |
| GNU GDB | 原生运行时断点观察 | GPL-3.0-or-later 及所带组件条款；由用户已有工具提供 |
| GCC | 仅构建自建原生资格样本，不是分析已有文件的必需项 | GPL-3.0-or-later，运行库有对应例外；不把例外套用于所有组件 |
| Java 21 / OpenJDK 构建 | 启动 JADX；javac 仅构建样本 | 所选 OpenJDK 构建通常 GPL-2.0 with Classpath Exception，厂商及附带组件另核；不泛指所有 Java 发行版同一许可 |
| JADX | APK/DEX 静态语义反编译 | Apache-2.0；所选 all-JAR 的依赖/notice 另核 |
| Android SDK Build-Tools / android.jar | 自建 APK 构建、AXML 和 DEX 独立核验；普通 JADX 分析不强制需要 | D8 等开源组件含 Apache-2.0，SDK 包/平台桩/附带资产按具体组件及 SDK 条款核对，不用单一 Apache 标签包办 |
| Node.js | V8 inspector 和有限本地 HTTP 观察 | Node.js 主体 MIT，V8/OpenSSL 等附带第三方许可分别保留 |

**以上工具的二进制、JAR、SDK、安装器都不随 TraceAnchor 分发，也不自动下载或安装。** 本产品 MIT/标准库运行时的声明不覆盖这些外部组件。自主维护指主控、合同、证据、验收和适配由本方掌握，不意味着零专业依赖。四源机制谱系和许可边界见 [provenance/README.md](provenance/README.md)、[provenance/notices.md](provenance/notices.md)；不分发四方整树、私配、provider 或研究快照。

## 6. 执行、资源与证据边界

- 默认 case 为 100 次 run、300 秒累计预留/使用、来源/采集 max_bytes 64 MiB、每流 output_limit 1 MiB；预算在创建时选择，重试不重置。专业命令默认 timeout 30 秒，可显式设置正数且至多 60 秒，idle_timeout 为 min(timeout,15)。版本探测也占用真实子 run 预算。
- capture 默认 10 秒/空闲 5 秒，fixture timeout 至多 30 秒；原生调试参数、断点、简单变量和 TRACEANCHOR 测试环境均有界，不是通用 shell/GDB 表达式入口。
- CLI JSON 输入上限 4 MiB；MCP 输入/输出帧 1 MiB，最多 2 个 worker、无无限队列；忙时返回 busy。专业产物过大也可能超 MCP 响应限额，应读有界记录，而非把传输错误视为工具没运行。
- `storage.usage` 是登记对象层，`workspace.usage` 才区分整受管工作区的数据库/WAL、work、检查点、缓存和未知文件。对象入库事务也做整工作区 admission；普通 capture 与专业执行均轮询增长。
- 约每 50ms 增长检查会取消超额执行，期间可以超量；控制记录/SQLite 增长也不是 OS quota。工作目录外的目标写入和直接网络 I/O 不受该策略拦截。Job/process ownership、效果白名单与严格 OS 文件/网络隔离是不同保证。
- 超额后 run 可保留每流最多 4096 字节精确前缀、已捕获全流大小与摘要；这不是完整 raw 证据或采集成功。失败残留仍归属于 workspace-item，保守恢复流程见维护指南。
- 原始 stdout/stderr 等被引用证据缺失/损坏会阻止当前验收；来源/规格/候选/执行器/环境/比较器/子研究变化触发 stale。旧 verdict 保留历史，不以删除失败或重新填 true 修复。
- 观察只覆盖选定输入和受管观察面，不证明全系统无副作用。源码、原始输出、合同、宿主回执可能含私人数据；公开前按具体内容检查，portable 路径清空不是全面脱敏。

## 7. 最终资格仍逐门核对

为什么不提前全绿：本表记录已取得的专业切片和审查修复事实；完整完成由 R3 合同 G01—G10 同时成立决定，不由文档、旧 A 表或单次测试数量决定。

| 门 | 当前文档可引用的进展 | 最终核对仍需 |
|---|---|---|
| G01 产品身份 | 场景、专业层/核心/宿主职责和四源取舍已有文档/实现 | 集成者核对当前完整交付 |
| G02 专业实用性 | 三条真实工具链及 service 记录 | 当前源码/工具/包的最终绑定 |
| G03 独立重建 | P04 V1 和真实 V2 差异修正，有限开发/封存通过 | 独立材料纪律、证据身份与最终复核 |
| G04 开发与维护 | P05 子研究消费、stale 和字节不变增量复用 | 当前集成结果复核 |
| G05 核心可靠性 | 引用证据完整性、子研究失效、GDB 回调权威等负控已修复回归 | 最终源码一致性及全核心回归 |
| G06 存储 | 整 workspace census/admission、真实增长取消、恢复实物归档、残留流程 | 当前快照完整回归和维护旅程 |
| G07 长任务协作 | 合同恢复入口、claim 冲突与转交制度及演练 | 活跃 owner/锁、当前恢复点核对 |
| G08 公共使用 | inspect、可选工具、宿主模板和用户场景已说明 | 新候选包安装/使用/卸载重装、适用回退资格 |
| G09 可维护性 | 谱系、工具许可边界、版本迁移与复评说明 | 当前分发清单与兼容声明复核 |
| G10 独立质量与发布 | 新上下文只读审查与已确认问题修复回归 | 最终源码/包、公开审计、真实 CI/Release/下载核验 |

本指南不把任一“待最终核对”改成 pass，也不代写资格 JSON。本轮只读核对时 pyproject、构建 backend、service/doctor 的版本已为 0.2.0；这一元数据一致性本身不创造最终包或发布资格。最终状态以当时 [status.json](goal/status.json) 及绑定证据为准，历史本地路径不存在时不能假装可复现。

## 8. 排查与问题报告

以下每块为独立单命令：

```bash
traceanchor --version
```

```bash
traceanchor inspect --help
```

```bash
traceanchor --workspace "[WORKSPACE]" doctor
```

核对实际安装/解释器、方法、映射、效果和版本，再读具体 observation/run 的 status、unknowns、cleanup 与 report。工具日志出现完成字样、CLI 退出 0 或 MCP list 出现工具，都不替代业务验收。

报错请给维护渠道最小自建复现：产品/包摘要与安装方式、OS/架构/Python、所选工具版本及映射占位、单条命令、case/run/observation/verdict ID、预期与实际有限行为、结构化 code/message/details、cleanup、资源限制及是否仍有写者。不要直接附整个 workspace、环境变量、凭据、个人路径或私有题库。本文件不虚构支持邮箱、SLA 或未建立的 issue 地址。
