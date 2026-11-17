# 架构、合同与实际能力

适用版本：**TraceAnchor 0.1.0 候选版**。本篇解释实现及冻结边界，不代替 [实施契约](IMPLEMENTATION-CONTRACT.md) 及实际生成的 [qualification.json](qualification.json)。用法见 [README](../README.md)。

## 1. 一套核心权威，宿主负责推理

为什么这样分工：宿主可以替换，证据、预算及验收需要可恢复的唯一权威。

```text
用户任务合同 / 父开发任务
        |
宿主：提出问题、解释证据、编写独立候选、依据差异修正
        |
CLI / MCP stdio / Python API
        |
service.dispatch(root, operation, arguments, cancel)
        |
Store + process owner + 静态分析/HTTP观察/比较器
        |
SQLite 记录/历史/引用/租约 + 内容寻址 objects
        |
报告、未知项、有限 verdict、归档、存储治理
```

MCP 工具可见不增加 case 效果。没有模型 SDK 依赖、模型凭据管理或内部付费推理循环；CLI/demo 可离线使用。宿主自身的模型计费、权限及预算另行管理。

| 模块 | 实际责任 |
|---|---|
| core.py | 工作区所有权、SQLite 事务/历史、来源快照、引用/租约、内容寻址、预算与失效 |
| service.py | 唯一 dispatch、任务合同、观测路由、子任务、规格、采集、验收、报告 |
| analysis.py | 有界静态检查，区分事实、文本推断、未检查和不支持 |
| process.py / winjob.py | 无 shell 启动、进程身份、超时/空闲/输出/取消、清理结果 |
| http_observer.py | 明确指定的 loopback HTTP 观察，拒绝重定向 |
| comparison.py | 不执行进程，按显式义务分别比较五维 |
| lifecycle.py | L1/L2/L3、usage、preview、clean、promote、pin |
| exchange.py | 有界导出校验；导入不继承执行许可或当前证明 |
| maintenance.py | 数据库检查点、离线恢复、恢复前回退点 |
| cli.py / mcp.py | UTF-8 JSON CLI 与 stdio JSON-RPC，共用核心 |
| hosts.py | 项目局部配置预览/应用/重装/卸载、回执及冲突保护 |
| demo.py | 自建样本错误候选→差异→显式修正→有限通过 |

模块路径均位于 `traceanchor/`，不是要求用户安装同名外部工具。

## 2. 六种任务模式、多目标与资格

| mode | 当前实际路径 | 不由名称授予的能力 |
|---|---|---|
| analysis | 文件身份、静态观察、未知项、route、report | 完整反编译或自动恢复源码 |
| protocol | JSON/HTTP 材料、loopback HTTP、单文件输入输出 | 任意远程协议推断、业务会话 |
| reconstruct | reference→有限规格→独立候选→双边运行→差异→修正 | 无界等价、自动写出所有候选 |
| diagnose-modify | 匹配预期字节的等长局部派生；保留 parent 身份 | 原地覆写原件、通用重包/访问机制修改 |
| version-diff | 两份来源字节/哈希/大小变化及有限偏移样本 | 自动把字节差异解释成行为差异 |
| dev-subtask | 父子合同、有限问题、同效果上限、证据/夹具合同回流 | 另一独立主控或自动扩大父任务边界 |

`target_kind` 接受 `desktop`、`native`、`apk`、`extension`、`javascript`、`web`、`protocol`、`development-component`、`file`。这是对象分类，不是全部动态支持矩阵：

- native/desktop：PE/ELF/Mach-O 头识别及文件身份；单文件执行也须明确选择可信可运行样本和满足效果门。没有 GUI/调试器资格。
- APK：有界 ZIP 项目清单/哈希，适用时文本 manifest；二进制 AXML、设备、重签安装、插桩未支持。
- extension：manifest/文本材料；没有真实浏览器扩展工作流资格。
- javascript/web：文本 import/endpoint 线索是 inferred，不是已访问接口或已执行 JS；没有 JS 引擎/浏览器自动化。
- protocol/development-component/file：有限自建单文件 CLI 是首版实用动态闭环。loopback HTTP 是单独的明确网络采样，不是远程服务推断。

当前 plan 中 dynamic_supported 只对 protocol、development-component、file 为 true；route=ready 只是计划字段，不是运行证明。低层 capture 可接受明确登记的单文件，不据此提升某目标领域资格。支持状态详见 [support.md](support.md)。

## 3. 观测前置与证据驱动换路

为什么：文件可读、程序可启动、进入界面、功能可调用及目标行为已验收是不同事实。

操作前记录问题、当前可达级别、session/data/server/runtime/device/tool 前置条件、证据、受影响义务、下一步实验、成本和停止条件。秘密只使用外部引用；通用字段名检查不是任意文本的全面脱敏器。

observability.set 请求例，写入 UTF-8 文件后通过 README 的 call 方式提交：

```json
{
  "case_id":"[CASE_ID]",
  "features":[{
    "id":"counter-state",
    "reachable":"unobserved",
    "question":"负数输入是否真实改变持久状态",
    "prerequisites":[{"kind":"runtime","status":"available","source":"caller-selected synthetic Python fixture"}],
    "evidence_ids":["[ANALYSIS_ID]"],
    "obligations":["state"],
    "next_experiment":"在 execute 合同和有限预算内运行 signed fixture"
  }]
}
```

再对 `plan` 提交 `{"case_id":"[CASE_ID]"}`。无 gap 倾向 static；有 gap、具 execute 且无缺失前置条件倾向 combined；前置缺失保留 static-with-observation-gap/blocked，不自动补齐会话或服务。调用方不能用 reachable=verified 自授验收。当前路由是确定性启发式，仍须宿主解释证据、执行实验并核对结果，不是完整自动规划器。

静态材料不足可换有界动态实验；动态条件缺失可保留静态结论与未知。失败不自动升级效果或换交付目标。运行快照不等于源码/全部模块/所有执行行为。

## 4. 来源、证据、规格与独立性

为什么：来源版本或候选改变后，旧验收不能继续作为当前证明。

- source.add 保存完整文件 SHA-256、原始选择路径、角色及 L1 内容快照。分析有自己的读取上限，完整身份哈希不等于已完整理解内容。
- reference、derived、candidate、fixture、component 分角色。source.derive 要求 offset、expected_hex、replacement_hex，字节前置匹配且等长；结果另有身份和 parent，不覆盖原件。当前派生字节直接存入 L1 CAS，不留 work 副本；source.path 为 null、trust 为 local-managed-derivation，执行仍要求 execute 效果及 fixture.allow_derived=true，仅限派生诊断，不取得原件或独立候选资格。
- source.refresh 创建新 source ID，保留旧身份；候选修正也用它。已登记文件在外部变动会导致 freshness 检查失效，而非静默当作旧快照。
- spec.freeze 需要同 case 的原始参考证据、1–20 组唯一 fixture、1–50 个显式义务、requirements 与 scope。它是有限合同，不自动证明规格充分或语义正确。
- verify 分别执行双方，禁止同内容左右互比及已知参考派生冒充候选；这些是必要工程检查，不是自动证明源码独立来源的法律或语义判定器。
- verdict 绑定源内容、规格、fixture、任务修订、runner/环境及比较实现等身份。相关变化、未知项或新规格使当前证明失效；历史记录保留。环境摘要不封存全部系统库/硬件/环境变量。
- 子任务 result 返回 contract、evidence_ids、fixture_source_ids、适用来源、unknowns 和 limitations；相关变化传播父任务失效。宿主仍应审查合同再进入父项目实现。

## 5. 五维验收各自判断

| dimension | 比较内容 | 观测边界 |
|---|---|---|
| behavior | exit/stdout/stderr；exact 或 JSON | 必须声明需要的 selector；默认 JSON 输出匹配不隐含所有流都已比较 |
| state | fixture 指定相对路径的 JSON 状态 | 每组 fixture 独立新工作目录；跨命令状态在同组序列内部表达 |
| side-effects | 所拥有工作目录内文件哈希 | 不观察目录外写入或全部网络效果 |
| structure | JSON 输出 shape | 不等于完整通用 JSON Schema 校验 |
| visual | 确定性 PPM fixture 像素比较 | 不是浏览器截图、布局、桌面 GUI 等价 |

判据包含 id、dimension、comparator、blocking、可选 selector。缺失/不支持的已请求维度保持 blocked/inconclusive；只有冻结合同明确理由才记 not-applicable。构建成功、图像一致、平均分都不能覆盖其他阻断差异。截断、失败观测、清理未知不能产生完整 pass。有限通过只覆盖明确样本与观测面。

## 6. 状态与执行责任

- case：active/suspended/closed；当前实现的暂停不是 OS 进程冻结。效果与运行操作仍需按实际接口检查，不以状态名称猜测。
- run：preparing→running→collecting→succeeded/failed/cancelled/timed_out/output_limit；中断后可标 abandoned。cleanup 独立为 complete/unknown/pending。
- acceptance：pass/fail/blocked/inconclusive/stale；未验收 report 可为 not-verified。run 成功不等于 verdict 通过，CLI 成功不等于业务通过。
- Windows runner 先给受信 gate 取得 Job Object 所有权再放行目标；失败不冒充已纳管。POSIX 使用 session/process group，主动脱离的后代存在边界，不能宣称完整隔离。
- 取消通过持久 cancel_requested 或 MCP Event 协作传播；EOF 触发取消不等于清理已完成。run.reconcile 不按旧 PID 盲杀，不重放效果；未独立核实的清理保留 unknown。
- 同 case 执行租约限制并发；事务/expected_revision 保护已观察的状态冲突。它们不提供系统级沙箱或任意外部编辑器的事务隔离。

预算、容量盲区和离线恢复详见 [存储维护](storage-maintenance.md)。真实宿主级资格见 [hosts.md](hosts.md)，不是由本篇模块图推导。

## 7. 独立维护与来源

四方研究来源是机制输入，不是必须一起启动的组件，不要求官方 REA/Craft 服务或上游 API。核心合同、证据、执行、状态及验收由本产品维护；尚未实现的集成留在需求映射/发布缺口中，不能靠注册表标 READY。

[来源谱系](provenance/README.md) 保存固定基线、双向机制映射、原创机制、采用/未采用理由、许可归属及复评模板。未来复评默认只研究建议，不自动安装、合并或发布。没有受控基线评测，不声称效果优于任何来源产品。
