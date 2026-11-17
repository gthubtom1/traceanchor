# TraceAnchor

**0.1.0：宿主驱动的逆向分析、证据管理与有限行为重建工作台。**

[源码仓库](https://github.com/gthubtom1/traceanchor) · [发布与下载](https://github.com/gthubtom1/traceanchor/releases) · [问题反馈](https://github.com/gthubtom1/traceanchor/issues)

获取源码（运行目录由你选择，不要求研究目录）：

```bash
git clone https://github.com/gthubtom1/traceanchor.git
```

模型宿主负责分析问题和编写独立候选；确定性核心负责操作效果、预算、运行生命周期、证据及判定。没有内部第二模型循环，也没有产品自行发起的付费模型 API 请求。

实际发布状态以 GitHub Release 和 docs/release-verification.json 为准。本地完整资格及逐项结果见 [docs/qualification.json](docs/qualification.json)，隔离包安装维护旅程见 [docs/install-qualification.json](docs/install-qualification.json)。远程发布与下载核对另见发布记录；本地资格不替代远程成功。

## 1. 支持范围与前置条件

- Python **3.11+**，运行时仅标准库，没有第三方 Python 运行依赖。安装需要所选环境中的 pip。宿主、模型订阅和外部工具另算，不会自动安装。
- 六种任务合同：`analysis`、`protocol`、`reconstruct`、`diagnose-modify`、`version-diff`、`dev-subtask`。登记任务类型不是全领域能力承诺。
- 静态能力：有限文件读取/哈希、Python AST、JS 文本线索、扩展 manifest、APK ZIP 清单、原生可执行头识别、JSON/HTTP 材料。不是反编译器。
- 动态能力：明确选择的可信单文件 Python/命令程序、有限 loopback HTTP 采样。通用 GUI、Android 设备、扩展运行时、浏览器截图、调试器集成尚未支持。
- `pass` 只覆盖冻结输入、观测面和义务，不是全软件等价。原件派生修改与独立候选分开登记。
- 进程所有权及超时清理**不是文件系统、网络、权限或内存沙箱**。`allowed_effects` 控制核心发起哪些操作，不约束已运行程序的全部系统行为。
- Windows 10 x64 / Python 3.12 是当前核心与 runner 候选验证环境；Linux/macOS 在真实资格齐备前为实验性。MCP 协议、静态配置和真实宿主工作流分别评级。

详见 [支持矩阵](docs/support.md)、[架构](docs/architecture.md)、[宿主接入](docs/hosts.md)。

## 2. 本地安装

以下使用 **Bash / Git Bash** 语法，每个 bash 块只有一条命令。先把方括号占位符替换成自己的路径。Windows 路径用正斜杠并加双引号。无需激活环境，每次直接调用其解释器。业务工作区与程序环境放在不同目录。

| 占位路径 | 含义 |
|---|---|
| `C:/[Python目录]/python.exe` | Python 3.11+ |
| `C:/[工具目录]/traceanchor-env/Scripts/python.exe` | 专用环境解释器，后文均使用它 |
| `C:/[产品源码目录]` | 含 pyproject.toml、_build.py、traceanchor/ 的产品根 |
| `C:/[安装包目录]` | 已取得并核对来源与校验值的本地文件目录 |
| `C:/[工作目录]` | 业务数据目录 |
| `C:/[请求目录]` | 用编辑器保存 UTF-8 JSON 请求的目录 |

Linux/macOS 用自己的绝对路径和 `环境目录/bin/python` 替换；这不提升平台资格。

### 2.1 创建隔离环境

为什么：重装程序不应删除项目或证据。

```bash
"C:/[Python目录]/python.exe" --version
```

```bash
"C:/[Python目录]/python.exe" -m venv "C:/[工具目录]/traceanchor-env"
```

### 2.2 安装本地 wheel

为什么：从明确的本地产物安装，不依赖尚未公布的远程仓库或包索引。文件名须与实际取得的候选包一致。

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m pip install --no-index --no-deps "C:/[安装包目录]/traceanchor-0.1.0-py3-none-any.whl"
```

### 2.3 从本地源码安装

为什么：没有 wheel 时可用已审阅的产品源码。这会运行产品自己的 PEP 517 后端，不是研究快照。后端不声明外部构建依赖。

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m pip install --no-index --no-deps --no-build-isolation "C:/[产品源码目录]"
```

wheel 与源码路线任选其一。当前不承诺 `pip install -e`；不要把研究上游安装器当作产品安装步骤。

## 3. 诊断、初始化与一次完整 demo

为什么：doctor 仅报告能力入口，不会启动目标，也不颁发运行资格。可先于 init 执行。

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --version
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/evidence" doctor
```

确认版本、`runtime_dependencies: []`、operation 列表和 unsupported。不要把 `core: available` 或 containment 名称当真实实验通过。

为什么：显式创建产品拥有的空工作区，避免接管已有非空目录。

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/evidence" init
```

为什么：demo 用自建 JSON 计数器完成真实进程闭环，并同时保留错误候选负控和修正后的有限验收。

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor demo --directory "C:/[工作目录]/demo-01"
```

`demo-01` 必须尚不存在。demo 使用其内部 `evidence/`，不是上一步的工作区；同名目录重跑会冲突，请用新的 `demo-02`，不会覆盖旧成果。

demo 实际执行的顺序是：

1. 写入分别实现的 reference 和 candidate，候选故意把负数增量取绝对值。
2. 建立 reconstruct/protocol 合同、登记原始身份并静态分析。
3. 冻结三组输入：正负增量/get；reset/未知操作；空序列。
4. 在分离工作目录运行双方并发现差异，负控应为 fail。
5. 明确替换候选实现、刷新候选身份，重新运行并比较。
6. 当前有限 verdict 为 pass 且资源清理 complete 后，关闭并归档 case。

正常摘要的关键字段是 `status: passed-finite-scope`、`fixtures: 3`、`actual_process_runs: 12`、`model_calls: 0`；输出 ID 每次不同。这是预期值，不是本篇文档替你运行的结果。目录内保留 `reference.py`、修正后的 `candidate.py`、`summary.json` 和证据工作区；历史错误候选快照、运行和 verdict 仍在证据中。

此例检查 behavior、state、side-effects、structure；visual 因冻结合同声明无视觉输出而不适用。它既不是通用视觉等价，也不授予桌面/APK/浏览器运行资格。demo 的修复是显式预写代码，不是产品内部自主调用模型。

## 4. 手动 call：从 JSON 到有限验收

为什么：实际项目需要读懂合同、证据和 ID，而非只运行演示。先运行上面的 demo，下面复用其中两个自建样本，但在另一个新工作区创建独立任务。用编辑器预先创建请求目录，逐份保存以下 UTF-8 JSON（无注释、无重复键）。

每个返回记录具有 `id`、`revision`、`data` 等字段。把下文 `[CASE_ID]`、`[REFERENCE_ID]`、`[ANALYSIS_ID]`、`[CANDIDATE_ID]`、`[SPEC_ID]` 替换成相应命令返回的**实际 id**。它们不是可跨工作区复用的常量。

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/manual-evidence" init
```

### 4.1 建立任务合同

保存为 `C:/[请求目录]/case.json`：

```json
{
  "mode": "reconstruct",
  "target_kind": "protocol",
  "objective": "独立实现有限 JSON 计数器，覆盖负数增量、reset 和未知操作",
  "non_goals": ["全输入空间等价", "GUI、Android 或远程业务服务"],
  "allowed_effects": ["read", "execute", "write-candidate"],
  "budgets": {"max_runs": 12, "max_seconds": 180, "max_bytes": 1048576, "output_limit": 1048576}
}
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/manual-evidence" call case.create --input "C:/[请求目录]/case.json"
```

保存返回 `[CASE_ID]`。默认只读合同不会因 mode 名称自动获得 execute。预算在任务开始时冻结，重试不会重置累计次数/时间。

### 4.2 登记原件与证据

保存 `reference.json`：

```json
{"case_id":"[CASE_ID]","path":"C:/[工作目录]/demo-01/reference.py","role":"reference"}
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/manual-evidence" call source.add --input "C:/[请求目录]/reference.json"
```

保存返回 `[REFERENCE_ID]`。保存 `analyze.json`：

```json
{"case_id":"[CASE_ID]","source_id":"[REFERENCE_ID]"}
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/manual-evidence" call analyze --input "C:/[请求目录]/analyze.json"
```

保存 `[ANALYSIS_ID]`。此证据是静态事实/带标签推断；执行行为仍须由 verify 的实际双边运行回答。真实项目应补充必要参考观测，不能从字符串猜业务已运行。

### 4.3 冻结有限规格

保存 `spec.json`：

```json
{
  "case_id": "[CASE_ID]",
  "reference_id": "[REFERENCE_ID]",
  "evidence_ids": ["[ANALYSIS_ID]"],
  "requirements": ["有符号增量", "reset", "get", "未知操作错误", "state.json 状态"],
  "scope": "只覆盖三组冻结输入序列及工作目录内声明的观测面",
  "fixtures": [
    {"id":"signed","stdin":"[{\"op\":\"add\",\"amount\":5},{\"op\":\"add\",\"amount\":-2},{\"op\":\"get\"}]","state_files":["state.json"]},
    {"id":"reset-error","stdin":"[{\"op\":\"add\",\"amount\":-1},{\"op\":\"reset\"},{\"op\":\"wat\"},{\"op\":\"get\"}]","state_files":["state.json"]},
    {"id":"empty","stdin":"[]","state_files":["state.json"]}
  ],
  "plan": {"obligations": [
    {"id":"response","dimension":"behavior","comparator":"json","blocking":true},
    {"id":"exit","dimension":"behavior","comparator":"exact","selector":"exit_code","blocking":true},
    {"id":"stderr","dimension":"behavior","comparator":"exact","selector":"stderr","blocking":true},
    {"id":"state","dimension":"state","comparator":"exact","blocking":true},
    {"id":"effects","dimension":"side-effects","comparator":"exact","blocking":true},
    {"id":"shape","dimension":"structure","comparator":"json-shape","blocking":true},
    {"id":"visual","dimension":"visual","comparator":"ppm","blocking":false,"not_applicable_reason":"冻结的计数器合同没有视觉输出"}
  ]}
}
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/manual-evidence" call spec.freeze --input "C:/[请求目录]/spec.json"
```

保存 `[SPEC_ID]`。这里显式比较 stderr；demo 自带 plan 的实际义务以 demo 源码为准。缺失的已请求维度不会自动记为不适用。每次 verify 对三组输入运行双方，共六次，不会用一次执行覆盖全部义务。

### 4.4 登记独立候选并验证

保存 `candidate.json`：

```json
{"case_id":"[CASE_ID]","path":"C:/[工作目录]/demo-01/candidate.py","role":"candidate"}
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/manual-evidence" call source.add --input "C:/[请求目录]/candidate.json"
```

保存 `[CANDIDATE_ID]`，再保存 `verify.json`：

```json
{"case_id":"[CASE_ID]","spec_id":"[SPEC_ID]","candidate_id":"[CANDIDATE_ID]"}
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/manual-evidence" call verify --input "C:/[请求目录]/verify.json"
```

读取返回的 `data.status`、各 fixture 的 `pairs[].result.obligations`、differences、coverage 与 limitations。CLI 返回 0 只表示请求成功，**verdict 仍可能为 fail/blocked/inconclusive/stale**；结构化业务结果必须单独检查。

若自己开发的候选出现差异：保留失败 verdict，修改候选文件后通过 `source.refresh` 建立新身份，再用新的 candidate id 重验，不能把旧 verdict 当作修改后的资格。刷新请求示例：

```json
{"case_id":"[CASE_ID]","source_id":"[CANDIDATE_ID]"}
```

将其保存为 `refresh.json` 后执行：

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/manual-evidence" call source.refresh --input "C:/[请求目录]/refresh.json"
```

此手动任务的 12 次运行预算容纳两轮完整 verify。候选、证据和绑定不变的失败检查最多允许两次，再次重复会得到 no-progress；改判据只为掩盖错误不算修复。

### 4.5 查看报告与有限归档

保存 `case-id.json`：

```json
{"case_id":"[CASE_ID]"}
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/manual-evidence" call report --input "C:/[请求目录]/case-id.json"
```

只有当前有限 acceptance 为 pass、无阻断未知项且运行清理完成时再归档：

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/manual-evidence" call case.close --input "C:/[请求目录]/case-id.json"
```

`case.close` 创建 L1 报告归档，不自动删除 L2。纯静态分析/版本差异任务也可获取 report；当前 close 是有当前 passing verdict 的验收关闭入口，不宣称所有模式都有专用完成判据。

## 5. 继续使用与维护

`call OP --input FILE` 读取 UTF-8 JSON 对象；`FILE` 为 `-` 时读取标准输入（需发送 EOF），默认也是 `-`。CLI 输入上限 4 MiB；不要把交互停在 stdin 等待当死锁。错误以 stderr JSON 返回，常规结构化错误退出 2，Ctrl+C 退出 130。

- [架构与状态](docs/architecture.md)：六任务、多目标、前置条件、身份、比较和失效。
- [存储与维护](docs/storage-maintenance.md)：三级资产、清理预览、离线检查点、导出迁移、升级/重装/卸载/回退。
- [支持与排查](docs/support.md)：平台、工具、预算、非沙箱边界和最短诊断路径。
- [宿主接入](docs/hosts.md)：CLI/MCP 共用核心，项目局部 Claude Code/Codex 模板、静态与真实资格分开。
- [发布政策](docs/release-policy.md)：候选版到正式发布的验收门、公开检查和维护规则。
- [实施契约](docs/IMPLEMENTATION-CONTRACT.md)：冻结范围与 A01–A20 验收要求，合同不是通过记录。
- [来源谱系](docs/provenance/README.md) 与 [未来复评交接](UPSTREAM-REVIEW-PROMPT.md)：固定来源基线、机制映射、取舍和独立维护。不依赖上游运行时，不承诺 API 兼容或自动跟随更新。

没有受控效果评测时，不声称本产品优于研究来源或其他工具；工程可用性、有限正确性与效果优越性是不同结论。
