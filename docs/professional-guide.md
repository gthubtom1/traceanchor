# 专业分析与独立实现使用指南

适用范围：**0.2.0 候选 / FOUR-SOURCE-PRODUCT-R3**，核对日期 2026-11-18。这里介绍当前源码中的专业入口，不表示 0.2.0 已发布或最终资格已通过。版本元数据、最终源码/包绑定、安装旅程及发布结果由集成资格单独确认；旧 0.1.1 包和标签保留其“有限核心版”身份，不能据此认定 R3 完成。最新门状态见 [goal/status.json](goal/status.json)，完整标准见 [R3 合同](goal/CONTRACT-R3.md)。

## 1. 先说你想弄清的事

TraceAnchor 用来把一个具体逆向问题变成可追溯的工具证据，并按需要继续接口研究、独立实现、差异修正或版本维护。它不是要求你先填写整套 case JSON 的记录器，也不是一次扫描就还原任意程序的自动解答器。

在熟悉的智能体宿主中，可以直接这样提问：

> 这是我构建的 parcel.exe。请找出报价的重量进位、区域费和预留库存规则。静态材料解释不了实际区域选择时，再用调试器观察一次远区报价；给出具体位置、原始证据和未知项，先别修改原件。

> 这是 Shipping.apk。请解释从界面入口到报价、确认的关键调用链，指出状态检查和错误分支；反编译结果与 DEX 核验分别说明，设备运行另列未验证。

> 我想知道 reservation.mjs 在库存不足、成功预留、提交和重复提交时，客户端/服务端状态以及实际 HTTP 请求分别怎样变化。请观察有限场景，不把 Node 结果说成浏览器 DOM 或扩展运行结果。

> 我在写批量订单报价工具。只研究现有后端需要的报价命令、错误和状态接口，把合同、证据、未知和夹具交回父任务，再继续我的功能开发。后端更新后只复查受影响部分。

为什么先限定问题：静态分析、运行时观察、重建、原件诊断修改和开发子任务是不同交付。研究遇到缺口时，交付目标不会自动切换；例如独立实现失败不会变成“改原件成功”。

### 宿主实际走的路线

宿主负责理解目标、读方法包、选择实验和编写候选；产品负责身份、效果、预算、执行、证据和验收。**产品默认没有内部第二模型循环，也不会自动调用另一个付费模型服务。** 当前宿主的推理和协作仍消耗宿主自己的额度。

1. **自然语言问题 → `doctor`**：诊断已有入口、PATH 中工具可见性和明确未验证能力。doctor 不启动目标、不安装工具，也不授予专业资格。
2. **`knowledge.get`**：按 `native`、`apk`、`web` 取所需方法包。知识是导航，不是另一套主控或执行许可。
3. **`case.create` → `source.add`**：宿主把问题、任务模式和明确效果登记，冻结完整单文件身份。原件、派生诊断对象、独立候选分别记账。
4. **按问题选择 `professional.run`**：需要时先用 `plan` 记录可达性与缺口；并非每个任务都要静态→动态→实现。执行统一经过 service / tool_runner，使用登记的工作目录和同一进程 owner。
5. **读证据再形成结论**：指出方法、位置、观测条件、支持/反证、未知和下一实验。完整采集不是独立候选验收；要重建时另冻有限规格并实际比较。

MCP 中，`doctor` / `knowledge.get` 位于 `traceanchor_system`，`professional.run` 位于 `traceanchor_source`；输入为 `{"operation":"...","arguments":{...}}`。CLI 的 `call` 只接收 arguments 本体。项目接线、协议与配置事务见 [hosts.md](hosts.md)；该文件的旧资格描述不替代 [R3 支持矩阵](r3-support.md)。当前宿主协作试验也不等于所有 MCP 客户端都已端到端加载验证。

## 2. 不用手写 case JSON 的 CLI 入口

为什么用 `inspect`：普通单问题分析由入口创建 analysis case、登记来源并执行所选工具，用户只提供文件、问题、方法和效果；场景确有参数时再补一个小 JSON 文件。

以下命令假定已在你选择的 Python 环境安装**包含新入口的候选源码/包**。在已审阅的源码目录安装可用下列单命令；安装候选源码树不代表获得已正式发行的 0.2.0；本轮只读核对时 pyproject、构建 backend、service/doctor 均已报告 0.2.0，最终包资格仍须另验。

```bash
python -I -B -m pip install "[PRODUCT_CHECKOUT]"
```

```bash
traceanchor --version
```

```bash
traceanchor inspect --help
```

```bash
traceanchor --workspace "[WORKSPACE]" doctor
```

`[WORKSPACE]` 是你明确选择的业务数据目录，放在源码和 Python 环境之外。首次 `inspect` 可创建空工作区；既有非空、无合法 marker 的目录会保守停止。doctor 和知识读取无需先创建工作区。若旧包没有 `inspect`，先核对实际安装来源，而不是把旧 CLI 当新功能资格。

```bash
traceanchor --workspace "[WORKSPACE]" call knowledge.get --input "native-knowledge.json"
```

`native-knowledge.json`：

```json
{"domain":"native"}
```

通用形状如下，每个 Bash 块都是独立单命令；方括号内容均由用户替换，不是产品内置路径。

```text
traceanchor --workspace "[WORKSPACE]" inspect "[INPUT_FILE]" --method [METHOD] --question "[具体问题]" --allow-execute [--allow-network] [--tools mapping.json] [--options scenario.json]
```

- 方法恰为 `native.disassemble`、`native.trace`、`apk.analyze`、`web.observe` 之一。
- 运行专业静态工具也会启动进程，所以四种方法均需 `--allow-execute`；`web.observe` 还需 `--allow-network`，即使仅观察本地 loopback 服务。
- `--options` 是对应适配器的参数对象，不是 case 合同。普通问题无需用户手写 case/source/spec/record 全套 JSON。
- 每次 `inspect` 创建新 case；要在同一任务累积静态和动态证据、接回父任务或重验候选，由宿主通过共享 service/MCP 继续使用已返回 ID。
- stdout 是 JSON；`case_id`、`source_id` 和 `observation` 可供后续查看。请求退出 0 不等于采集完整或验收通过，必须读取结果状态。

### 配置可信的可选工具

为什么显式映射：工具来自用户已有可信安装，不随 TraceAnchor 包分发，也不由导入、doctor、知识读取或 inspect 自动安装。映射仅用于这次任务，不修改全局配置。

用编辑器保存 `mapping.json`，替换为本机实际**绝对路径**；这里没有开发机器私有路径：

```json
{
  "objdump":"[TOOLS_ROOT]/gnu/bin/objdump.exe",
  "gdb":"[TOOLS_ROOT]/gnu/bin/gdb.exe",
  "java":"[TOOLS_ROOT]/jdk-21/bin/java.exe",
  "jadx_jar":"[TOOLS_ROOT]/jadx/lib/jadx-1.5.6-all.jar",
  "node":"[TOOLS_ROOT]/node/node.exe"
}
```

native 工具未配置时可从 PATH 解析；native 入口选择真实可执行文件，不接 `.bat` / `.cmd` 等 shell wrapper。APK 请显式配置 Java 与 JADX JAR，Web 请显式配置 Node；doctor 的 PATH 可见性不代表已经验证这份映射。GCC、Android 构建工具只在构建自建样本时需要，并非每次分析的强制依赖。各工具已测版本、许可和未覆盖范围见 [r3-support.md](r3-support.md)。

## 3. 场景一：原生程序报价在哪里，运行时到底选了哪个区域

**输入**：明确选择的自建/可信单文件 PE/ELF；当前代表资格是 Windows x64、带符号的自建包裹报价程序。公开构建源码在 `examples/native/parcel.c`，有报价、库存预留/取消、状态和错误输入，不是计数器 demo。

如果要自己构建该公开样本，先准备自己的空输出目录，然后执行：

```bash
"[GCC_EXECUTABLE]" -g -O0 -fno-inline -o "[OUTPUT_DIR]/parcel.exe" "[PRODUCT_CHECKOUT]/examples/native/parcel.c"
```

### 先定位机器码，再按缺口做动态实验

为什么：头信息与字符串不足以解释重量进位和库存分支；而机器码含某个分支，也不证明本次部署实际走过它。

```bash
traceanchor --workspace "[WORKSPACE]" inspect "[OUTPUT_DIR]/parcel.exe" --method native.disassemble --question "定位重量进位、区域附加费和库存预留检查，给出函数地址与直接调用关系" --allow-execute --tools mapping.json --options native-static.json
```

`native-static.json`：

```json
{"symbols":["dispatch_command","quote_parcel","reserve_parcels"],"timeout":30}
```

**过程/输出**：实际运行 objdump 版本探测及机器码反汇编，保留原始输出、`disassembly.txt`、函数地址和符号可解析的直接 call 边。返回地址是工具报告的地址，不擅自当文件偏移；间接调用、内联和去符号路径仍可能未知。宿主阅读比较、跳转、参数与算术，才形成领域解释。

对“远区测试条件下，501 克加急实际怎样进入报价函数”做有界 GDB 实验：

```bash
traceanchor --workspace "[WORKSPACE]" inspect "[OUTPUT_DIR]/parcel.exe" --method native.trace --question "实际命中报价函数并核对远区参数、调用栈及输出，检验静态费率假设" --allow-execute --tools mapping.json --options native-trace.json
```

`native-trace.json`：

```json
{
  "breakpoints":["quote_parcel"],
  "expressions":["service_zone"],
  "arguments":["scenario.txt"],
  "input_files":{"scenario.txt":"quote 501 1\nstate\n"},
  "test_environment":{"TRACEANCHOR_PARCEL_ZONE":"remote"},
  "timeout":30
}
```

**过程/输出**：复制冻结目标到登记工作目录，生成有限 GDB 脚本和输入文件，禁用个人 init，取得真实断点回调、选中 frame、参数、栈和简单变量。命中权威是 **GDB 内置 Python `Breakpoint.stop` 回调的事件回执**，不是被调试程序自己打印的“命中”字符串。返回 `breakpoint_hits`、`runtime_trace`、工具版本及证据索引；正常 inferior 退出、实际命中、无截断和 cleanup.complete 都参与完整性判断。

公开 V1 自建样本的该输入曾得到 920 分；受控参考 V2 是 985 分。数值必须绑定具体目标摘要和版本，不能混用。断点改变时序，结论只适用于这次观测条件及输入。

**失败时**：缺符号、未命中、变量解析未知、超时或清理未完成保留 partial/失败及未知，不由 exit 0 晋级。去符号/加壳、GUI 全流程、任意表达式求值、全进程内存采集和其他 ABI 没有由此获得资格。详细方法见 [knowledge/native.md](knowledge/native.md)。

## 4. 场景二：APK 的报价与确认经过哪些方法

**输入**：一个明确选择的 APK。公开代表样本由 `examples/apk/` 原创 Java、manifest 及已安装构建工具重复构建；普通分析已有 APK 时，仅需 Java 和 JADX，不要求先安装整套 Android SDK。

为什么先做语义静态分析：ZIP 条目和包名线索解释不了状态检查。JADX 输出供宿主定位类/方法和错误分支；需要关键调用身份时再回 DEX 指令核对，而非把 Java 文本调用提示当已解析全图。

```bash
traceanchor --workspace "[WORKSPACE]" inspect "[INPUT_APK]" --method apk.analyze --question "追踪界面到报价和确认的调用链，列出状态条件、错误分支与未解析边界" --allow-execute --tools mapping.json --options apk-options.json
```

`apk-options.json`：

```json
{"max_files":200,"timeout":60}
```

**过程**：通过 `java -cp [JADX_JAR] jadx.cli.JadxCLI` 显式运行 CLI 主类，先取版本，再实际反编译。配置为 `--config none`，每次新建 attempt，把 JADX 配置/缓存/临时目录和 Java home/tmp 放在该受管 attempt，避免默认 GUI 入口和个人缓存干扰。

**输出**：新鲜生成 Java 源文件及摘要、方法声明、源路径/行号、`java-call-hint` 导航、原始 stdout/stderr、覆盖与 unknowns。当前采集默认最多 200 文件，单文件 4 MiB、合计 32 MiB、最多 10000 事实；到达限额或反编译诊断会变为 partial。

代表资格实际核对了 `ShippingActivity.onCreate → ShipmentSession.requestQuote → requireState → ShippingRules.quote` 及 confirm 路径、整数克数/分币、状态与错误，并由独立 dexdump 输出核对关键 invoke/DEX 位置。**这部分 DEX 核验是资格脚本中的实际检查，不是 `inspect` 对任意 APK 都会自动完成的完整调用图证明。** APK 中的 AXML、JNI/动态 DEX、反射及复杂 Kotlin 语义可能要求额外材料。

**失败/未知**：缺 JAR/Java、反编译失败、未生成源码、超额、清理未知和源变化分别保留原因。`qualification_level=static-decompiler-output; runtime-unobserved` 即使采集 complete 仍成立。代表 APK 未签名、未安装；设备/模拟器运行、重包、重签、安装、插桩分别未取得本链资格。详细方法见 [knowledge/apk.md](knowledge/apk.md)。

## 5. 场景三：JS 的交互、状态和真实请求怎样对应

**输入**：调用者选择并允许执行的自建 JS 模块；公开例子为 `examples/web/reservation.mjs`。当前不是任意网页 URL 输入器：模块需导出 `createSession({request, baseUrl})` 与 `createService()`，会话提供 dispatch/snapshot，服务提供 handle/snapshot。目标以单文件快照执行，相对依赖/环境闭包没有自动封存。

为什么用真实运行时：endpoint 正则命中只是线索；实际请求 ID、调用栈、服务接收与前后状态，才回答“这次交互发生了什么”。

```bash
traceanchor --workspace "[WORKSPACE]" inspect "[PRODUCT_CHECKOUT]/examples/web/reservation.mjs" --method web.observe --question "解释库存边界、预留和提交的客户端/服务端状态及实际 HTTP 因果链" --allow-execute --allow-network --tools mapping.json --options web-options.json
```

`web-options.json`（注意 `--options` 外层有 `scenario`；只把公开 `examples/web/scenario.json` 的 steps 直接当外层 options 会不匹配入口）：

```json
{
  "scenario":{
    "steps":[
      {"id":"commit-before-reserve","action":{"type":"commit"}},
      {"id":"invalid-quantity","action":{"type":"reserve","quantity":0}},
      {"id":"stock-boundary","action":{"type":"reserve","quantity":8}},
      {"id":"reserve","action":{"type":"reserve","quantity":3}},
      {"id":"commit","action":{"type":"commit"}},
      {"id":"repeated-commit","action":{"type":"commit"}}
    ]
  },
  "timeout":30
}
```

**过程**：Node 的真实 V8 inspector 验证已加载源摘要、观察 dispatch 函数调用和 precise coverage 的实际函数位置；在同一受管进程启动 `127.0.0.1` 随机端口服务，通过真实 fetch 请求关联 step、请求 ID header、inspector 栈、服务接收和应答。每步分别保留客户端/服务端 snapshot 与业务异常。

**输出**：`web-trace.json`、`web-contract.json`、原始 Node 流和执行回执，含目标/helper 摘要、Node 版本、步骤/请求 ID、已执行函数位置。代表链观察了 **6 次交互和 4 条具有因果关联的实际 HTTP 请求**。业务错误与采集器失败分开判。

**失败/未知**：scenario 仅接受 1–12 个唯一 ID、JSON action 的有限步骤；无状态变化、无关联请求、缺 inspector 观察、超时、截断或源变化均不形成完整链。Node imports/直接 I/O 不受 OS 文件或网络沙箱封锁。本结果不是浏览器 DOM、渲染/截图或扩展运行资格。详细边界与后续 browser/CDP 接入路线见 [knowledge/web.md](knowledge/web.md)。

## 6. 场景四：凭证据独立重建，再处理真实版本差异

为什么把研究包和判分分开：实现者读过参考源码再翻译，或预写一个坏候选再修正，都不足以证明陌生任务的独立重建效果。

P04 的实际旅程是：

- 一位新鲜宿主工作者只接收真实机器码反汇编、GDB 轨迹及选定运行观察，从证据独立编写有状态包裹协议候选；输入含报价、预留/取消、状态和错误边界。
- 参考源码/二进制与开发、封存判分材料在协作角色上隔离，封存输入预先冻结。材料暴露及读取清单如实记录；这是**协作材料隔离，不是 OS 强保密或同文件系统访问控制证明**。
- V1 候选首轮真实通过，没有人为植入缺陷来制造修正故事。
- 参考 V2 真实变更费率及重量上限，旧候选出现 4 组开发差异。维护者只接收新版专业证据和获准的两组公开差异，定点分析后仅修改 **3 个常量**：上限 20000→15000 克、基础费 250→275 分、远区附加费 180→220 分；解析和库存状态逻辑保持不变。
- 修正后协调者实际独立判分：**6 组开发通过，7 组含 sealed 的终验通过**。候选自己的 V2 自测另为 11 个方法通过；自测不是双边判分，不能把两类成绩合并计数。

可公开复查的材料是 `assessments/native-parcel/packet/`、`packet-v2/` 和候选的 `notes.md` / `notes_v2.md`。本指南只引用协调者公开的判分结果，不公开封存输入和期望。V1 记录/失败及旧断言保留为历史，V2 使用相应新身份；有限输入通过不外推任意整数溢出、CRT 极端解析或全软件等价。

在自己的任务中向宿主提出“按已取得证据冻有限规格，另写独立候选，用分离夹具运行比较；有真实差异才修正”即可。底层 `spec.freeze` / `verify` 由宿主填写并执行；行为、状态、副作用、结构和视觉分别选适用义务，非视觉协议的视觉不适用需有理由，不能以构建成功或工具 complete 替代 verdict。

## 7. 场景五：正常开发只借一段研究，更新时复用未变部分

为什么不把整个父任务变成重建：批量报价功能只需要现有后端的有限接口，不必重写后端。

P05 已实际构建 `examples/development/quote_batch.py` 对应的批量订单报价工具：父任务委派原生命令/错误/状态研究，子任务返回合同、专业静态和实际运行证据、来源身份及未知；父工具使用所选原始后端取得逐项报价、整数分币合计、错误透传和最终后端状态。

参考升级 V2 后，父任务即使没有先人工读取子任务，`report` 也会检查已消费的子研究来源：**旧父验收机械失效为 stale**。随后刷新来源，只重访受影响的定价函数和报价观察，复用命令语法、错误封装及父实现；更新审查过的期望后增量验证通过，**父代码字节完全未变**。

本地记录索引为 `.validation/development-f9a73296953d/qualification.json`，其中 `old_parent_verification_became_stale=true`、`parent_code_reused_byte_identical=true`。该目录是本地资格材料，不保证出现在安装包中。父任务使用的是显式审查的开发验收见证，不是 P04 的盲重建 oracle。

## 8. 怎样读结果，失败后做什么

为什么分开读状态：CLI 请求成功、工具采集完成、业务行为观察、候选验收通过和整个 R3 完成是不同层级。

- `observation.data.professional`：方法专属状态、事实/函数/命中、工具信息、limitations / unknowns。
- `artifact_ids` / `raw_material_ids`：归档证据身份；run / child run：真实执行、超时/取消、清理、资源限制。
- `report.acceptance`：有限规格的当前 verdict；单纯 inspect 没有独立候选 verdict，通常仍是 not-verified，而不是分析失败。
- 源、候选、工具/环境、执行器、规格、比较器或消费的子研究变化后，相关旧结论须复核新鲜度；原始证据缺失/损坏也会阻止当前比较、report/case.close 沿用旧 pass。

| 现象 | 下一步 |
|---|---|
| 没有 inspect / 版本仍来自旧安装 | 核对解释器、实际包和候选元数据；旧 0.1.1 发布不包含本轮能力声明 |
| effect-not-granted | 核对当前任务效果；专业工具需 execute，Web 还需 network；工具可见不会自动扩大合同 |
| missing-tool / 工具路径错误 | 选择可信真实可执行文件/JAR，更新本任务映射；doctor 不自动安装 |
| partial / failed / blocked | 读原始输出、覆盖、unknowns 和 cleanup；不要只看退出码或最后一句工具日志 |
| task-budget / no-progress | 保存已有证据；有新证据/候选变化后再尝试，不原样无限重试 |
| stale-source / stale-specification / stale | 保留旧记录，刷新所选来源、审查合同/规格、重跑受影响部分 |
| work-budget / workspace-budget | 停新采集，检查整工作区与恢复残留；不为了过限额删 L1 或未知文件 |
| cleanup unknown / active lease | 核对真实 owner 与资源；reconcile 不会把未知清理变成已完成 |

增长超限后可能只在 run 中保留每流最多 4096 字节的精确前缀及完整已捕获流的大小/摘要；该前缀不是完整原始流，也不是完整观察成功。容量调整、残留 reconcile、实物归档及清理见 [r3-maintenance.md](r3-maintenance.md)。

三条真实专业链、P04/P05 的有限成功均不替代最终 G01–G10、当前源码/包资格及公开发布核验。具体已测/未测分层见 [r3-support.md](r3-support.md)。
