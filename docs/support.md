# 支持矩阵、诊断与已知限制

适用版本：**0.1.0 候选版**。本篇基于实际实现描述能力；完整本地测试见 [qualification.json](qualification.json)，实际隔离包旅程见 [install-qualification.json](install-qualification.json)。本地通过不替代远程发布核对。安装与完整 JSON 流程见 [README](../README.md)。

## 1. 资格等级怎么读

为什么：静态核对、核心真实运行、宿主工作流和效果比较是不同证据。

| 等级 | 含义 |
|---|---|
| implemented | 当前源码有入口/实现；尚不代表目标环境成功 |
| static-checked | 文档/格式/配置已核对；不代表工具已加载或业务运行 |
| real-integration-tested | 指定版本/环境下执行过真实集成；以具体结果为准 |
| host-e2e-tested | 指定宿主版本、加载/信任配置、真实工具任务已端到端运行 |
| experimental / not-run | 有设计/实现但该环境未取得实际资格 |
| unsupported | 当前没有所需集成；不能用 mock、配置或说明替代 |

本产品不使用一张“全部支持”表合并这些层次。

## 2. 平台与宿主

| 项目 | 当前声明 | 不外推的部分 |
|---|---|---|
| Python | 要求 >=3.11；当前候选环境 Python 3.12 | 不是每个未来 Python 版本已测 |
| Windows 10 x64 | 核心/Job Object runner 候选验证平台 | 同机新 venv 不叫全新机器 |
| Linux/macOS | 实验性，等待实际 CI/本机资格 | POSIX session 不封锁主动脱离的后代 |
| CLI | JSON 入口实际实现，共用 service | 请求成功不等于 acceptance 通过 |
| MCP stdio | 真实协议/服务集成与 stub 测试分开，见 hosts | 不等于任意客户端或模型工作流通过 |
| Claude Code | 官方配置静态核对、临时项目安装事务；真实工作流未执行的部分明确 not-run | 配置存在/工具列出不是业务 READY |
| Codex | 项目配置模板实验性，官方来源核对范围见 hosts；真实工作流未执行 | TOML 语法通过不等于宿主加载或信任 |
| 其他宿主 | 未取得资格，按实际 stdio 协议自行验证 | 不猜简称或承诺通用兼容 |

宿主模板、版本协商、busy/cancel/EOF 语义、回执与冲突见 [hosts.md](hosts.md)。宿主使用所安装环境的绝对 Python 路径；不修改全局模型、权限、认证或 trust。

## 3. 六任务与多目标矩阵

六模式在 [architecture.md](architecture.md) 逐项说明；所有模式都不能自动增加效果。目标支持如下：

| 对象 | 可用观察 | 首版未支持/未取得资格 |
|---|---|---|
| desktop/native | 完整文件身份；PE/ELF/Mach-O 头；明确可信单文件可尝试 runner | GUI、反编译、调试器、进程内存、全应用安装流程 |
| APK | ZIP 有界条目/哈希，适用时文本 manifest，不自动解包 | binary AXML、设备运行、重签/重包/安装/插桩 |
| extension | manifest JSON、文本关联 | 真实浏览器扩展生命周期和交互 |
| JS/Web | import/endpoint 文本提示（inferred） | JS 执行、浏览器采集、一般页面视觉等价 |
| protocol | JSON/HTTP 材料、有限 loopback HTTP、单文件协议样本 | 任意远程服务、自动识别全协议、缺失会话/数据的业务行为 |
| development-component | Python AST、文件材料、有限受控 CLI、父子研究合同 | 自动理解/构建任意依赖工程 |
| generic file | 有界文件读取、哈希及适用静态检查 | 未知格式的万能语义恢复 |

Python AST 是静态事实，JS 文本命中是线索；只读材料不证明运行行为。能启动、进入 UI、功能可运行、目标行为已验收必须分开。缺测试账户/数据/服务/运行时条件保留 blocked/unknown，不编造服务端能力。派生对象与独立实现不能互相替代交付目标。

## 4. 资源、输入与停止条件

为什么：首版保证有界尝试，不承诺无限修复或零资源开销。

- 默认 case：100 次 run、300 秒累计预留/使用时间、max_bytes=64 MiB、每流 output_limit=1 MiB。case 可在创建时给出有界预算；之后修改预算被 budget-frozen 阻止，重试不重置累计量。
- service capture 默认 timeout=10 秒、idle_timeout=5 秒；fixture 可设置正数 timeout<=30、idle<=timeout。底层 run_process API 默认 30 秒/10 秒，不能把它当 CLI capture 默认值。空闲指 stdout/stderr 无字节，不是 CPU 空闲；清理/drain 另有有界耗时，OS 调用不提供严格实时保证。
- 单个 stdin<=1 MiB；arguments 最多 64 项且单项长度有界；声明 state_files 最多 20 个相对路径。输出超限/非法 UTF-8 不产生完整文本验收通过；原始字节按采集结果保留。
- capture 的工作目录副作用清单有文件数/总字节上限；不能据此声称整个系统没有其他副作用。状态文件读取和 visual 有独立大小上限。
- HTTP 仅明确 loopback 采样，拒绝重定向，体积/时限受控；进程与 HTTP 均须计入 case run/time 预算。缺失服务不自动启动替代业务服务。
- verify 最多 20 fixture、50 义务；一轮次数是 fixture 数×2。同一绑定已连续两次失败/阻断/不确定，再次重复报 no-progress。
- CLI JSON 输入<=4 MiB；MCP 输入/输出帧<=1 MiB，最多两个工具 worker，无无限队列。数据量过大会返回限制错误，不承诺自动分片。
- storage.usage 只统计登记对象，不包括 SQLite/work/未登记材料；容量和初始化限额见 [存储维护](storage-maintenance.md)。

预算耗尽、缺前置、未支持能力、无进展、用户取消都应停止当前路径并保留证据。另建 case 不代表可掩盖旧失败或扩大原授权边界。

## 5. 最短诊断步骤

以下每块为独立 Bash 命令；替换占位路径。

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --version
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/evidence" doctor
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --help
```

读取版本、operation 列表、unsupported 和错误 code；doctor 不执行目标、不检查每个已存对象、不授予平台资格。用 README 的全新目录 demo 区分包/runner 问题与自己的材料问题，再检查具体 case report。不要在同一个失败目录反复覆盖样本。

| 现象/code | 检查与动作 |
|---|---|
| ModuleNotFoundError | Python 路径是否为安装该包的环境；用同一解释器运行 pip，避免依赖当前目录导入 |
| workspace-missing | 对新的显式业务目录 init；不要在产品源码/虚拟环境根 init |
| ownership-unknown | 既有非空目录无有效 marker；保留原文件，选择新的空工作区 |
| limits-frozen / invalid-budget | 已有工作区限额不可在 init 偷改；新建前核对正整数和 soft/temp<=hard |
| invalid-input / invalid-operation | 检查 JSON 对象、实际 operation 和字段；不把 MCP 外层 operation/arguments 直接当 CLI args |
| effect-not-granted | 核对 case 的明确效果；只读任务不会因工具可见获得 execute/network/derive |
| stale-source / stale-specification / acceptance stale | 保留旧证据，刷新来源/审查并冻结新规格，重新验证 |
| not-independent / role-mismatch | 检查 original/derived/candidate 身份；不用同文件左右互比 |
| source-mismatch | ID 属于其他 case/工作区；回到原工作区或明确重新登记 |
| task-budget / no-progress | 保存结果并停止；改变有依据的候选/证据，而非原样无限重试 |
| timed_out / output_limit / cancelled | 先看 raw output、cleanup 和进程身份；不把非零退出直接当全部业务错误 |
| cleanup unknown / resource-busy | 核对真实所有者与外部效果；run.reconcile 不证明清理且不按旧 PID 盲杀 |
| disk-budget / temp-budget | 看 usage 和只读 preview，合格 L3 优先，保留 L1；不删除未知材料 |
| database-error / unsupported-schema | 先离线备份现场，用兼容版本/检查点恢复，不重新建空库遮盖 |
| CLI 返回 0 但结果 fail | 请求执行与验收分层，读取 verdict 的 data.status 和每个义务差异 |
| isError:true / MCP busy | 看结构化 content；busy 时取消已知请求或等现有任务结束，不无限排队 |
| host.conflict / receipt 错误 | 保留用户当前字节，按 hosts 文档对比备份/回执，不自动破锁接管 |

预期非零业务退出可由冻结 fixture 的 expect_exit 明确声明；必须实际符合且清理完成，不能用它忽略超时/截断/缺观察。

## 6. 执行与数据边界

**这是进程所有权和证据工作台，不是恶意样本执行沙箱。** 运行样本使用当前系统用户权限，能访问产品工作目录之外的文件、网络和系统接口。效果 allowlist 仅限制核心主动发起的入口，不能拦截目标进程的每个系统调用。选择可信自建单文件是 demo 和首版资格的前提。

Python 子进程用隔离解释器选项运行，避免从工作目录/PYTHONPATH 意外加载模块；不表示依赖已经封存。非 Python 原生文件可能受系统加载器、库和环境影响；不承诺多文件安装应用直接可重放。Windows Job 成功纳管、POSIX session 所有权与 cleanup 的真实结果分别记录，不能用平台名称替代结果。

source 的本地路径、用户填写合同、stdout/stderr、HTTP body、源码及宿主回执可能含用户私有数据。秘密字段检查、环境摘要和 portable source.path 清空都不是全面脱敏。只保存引用或脱敏身份；分享/公开前逐项检查。不要把运行工作区、主机回执、真实目标或整份上游快照提交到公开仓库。

## 7. 报告问题需要什么

当前候选文档不虚构 issue 地址、支持邮箱或服务 SLA。向取得产品的维护渠道提交最小可复现材料即可：

```text
产品版本 / 安装方式 / 包校验值：[填写]
操作系统类别、架构、Python版本：[填写，不含账户/机器名]
资格记录对应范围或缺失项：[填写]
执行命令：[替换私人路径/凭据后的命令]
operation / mode / target_kind：[填写]
case/run/verdict ID：[仅必要身份]
期望的有限行为与实际结果：[填写]
结构化 code/message/details：[脱敏]
cleanup / 数据是否保留 / 是否已停写者：[填写]
最小自建样本和fixture：[可公开版本]
```

不要直接打包整个 workspace 或环境变量/认证配置。完整路径只在私有排查确需时单独处理；公开问题用占位符。

## 8. 维护与效果声明

0.1.0 尚处候选，破坏性 schema 变化、兼容范围和停用计划须在发布记录明确说明，不用版本号暗示长期承诺。运行依赖为标准库不等于零维护成本；成熟外部工具以后只能作为明确可选适配，经真实资格后增加支持声明。

当前 demo 证明的只是三组自建计数器序列及明确义务。没有受控模型成本/正确性/恢复/磁盘/资源对照时，不声称优于上游、简单脚本或其他产品。没有新增付费模型循环；宿主推理的外部成本不计为产品“免费模型”。发布门见 [release-policy.md](release-policy.md)。
