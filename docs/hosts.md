# MCP 与项目局部宿主接入

TraceAnchor 的 MCP 是 stdio 服务，不包含内部模型循环。宿主提出操作，`service.dispatch(root, operation, arguments, cancel=Event)` 检查 case 的效果、预算、身份与状态；工具组白名单不是运行授权。Python >=3.11，运行时仅标准库；先在你选择的隔离 Python 环境安装本产品，宿主启动时也必须使用该解释器。

## 验证分层（2026-11-18）

| 范围 | 状态与证据 | 未覆盖 |
|---|---|---|
| 协议隔离测试 | `tests/test_mcp.py` ProtocolTests：真实帧解析、线程、initialize/version 协商、initialized、list/call、错误、取消、EOF、限额；dispatcher 是显式 stub | 不冒充真实 service 或宿主端到端 |
| 真实服务协议回归 | `tests/test_mcp.py` ServiceIntegrationTests：独立进程 stdio → 实际 serve → dispatch → 临时 Store；具体结果见本次测试输出 | 不等于 Claude/Codex 模型工作流或全产品验收 |
| 配置文件事务 | `tests/test_hosts.py`：临时项目内真实写入/回读/重装/卸载/故障回退 | 从未更改真实宿主配置、安装宿主或启动真实宿主任务 |
| MCP 官方规范静态核对 | 官方 2025-11-25 transports 页面由可信 curl 读取，核对 UTF-8、每行完整 JSON-RPC、stdout 专用与 stderr 日志 | 不是任意客户端兼容承诺 |
| Claude Code 配置静态核对 | 官方页面由可信 curl 读取，核对项目根 `.mcp.json` / `mcpServers`、stdio 与项目加载/审批边界 | 真实 Claude 工作流端到端未执行 |
| Codex 配置 | 官方网页/curl 曾遇 HTTP 403 与 DNS 失败；随后主代理通过已登录 GitHub CLI 读取官方 `openai/codex` schema 与配置加载测试，核对 `mcp_servers`、stdio `command/args` 及项目 `.codex/config.toml` 路线；TOML 与本地事务通过 | 真实 Codex 工作流端到端未执行；具体版本信任/加载行为仍需宿主资格，模板列实验性 |

本轮实际回归：`test_mcp.py` 的 14 项协议隔离测试、4 项真实 service/stdio 集成，`test_hosts.py` 的 15 项临时项目配置事务、4 项谱系静态检查，合计 **37 项通过**（其中一次完整执行 1.279 秒）；四个 Python 文件独立语法编译通过。真实集成实际运行自建 sleeper，通知取消与 EOF 取消后持久 run 均为 cancelled、cleanup=complete；另测超长帧、重复键及只读 case 执行拒绝。符号链接创建分支取决于平台创建权限，硬链接拒绝必测；该测试集不授予未测平台资格。

WebFetch 对官方域名的安全验证失败，随后仅用保留 TLS 验证的可信 curl 读取官方 URL；未安装依赖、修改认证或规避证书检查。宿主版本、策略与项目可信状态会改变实际加载结果。工具名称出现在配置或列表中也不等于一次完整业务任务通过。

官方链接：

- [MCP stdio transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports#stdio)
- [MCP lifecycle/version negotiation](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)
- [MCP tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- [Claude Code MCP/project scope](https://code.claude.com/docs/en/mcp#project-scope)
- [Claude Code local stdio server](https://code.claude.com/docs/en/mcp#option-3-add-a-local-stdio-server)
- [Codex MCP（本轮访问受阻）](https://developers.openai.com/codex/mcp)
- [Codex config reference（网页访问受阻）](https://developers.openai.com/codex/config-reference)
- [Codex 官方配置 schema 固定版本](https://github.com/openai/codex/blob/8011b92bc82d4cc1b6dc3f35c0cd28768c797c97/codex-rs/core/config.schema.json)：`mcp_servers` → `RawMcpServerConfig` → `command`/`args`。
- [Codex 项目配置加载测试固定版本](https://github.com/openai/codex/blob/8011b92bc82d4cc1b6dc3f35c0cd28768c797c97/codex-rs/core/src/config/config_loader_tests.rs#L249-L252)：项目 `.codex` 与 `config.toml`。历史状态 `static-doc-blocked` 已由官方源码静态核对部分解除，真实宿主资格仍未执行。

## 启动与协议

先初始化显式工作区，随后让宿主以如下 argv 启动：

```text
[PYTHON_ABSOLUTE] -m traceanchor --workspace [WORKSPACE_ABSOLUTE] init
[PYTHON_ABSOLUTE] -m traceanchor --workspace [WORKSPACE_ABSOLUTE] mcp
```

`doctor` 可在工作区创建前诊断；持久化 case/source 等操作需要已初始化工作区。命令不是 shell 字符串拼接：配置里的 command 为解释器绝对路径，args 每项独立。不复制整个环境，不写 API key/token，不自动安装反编译器、浏览器或宿主。

支持的 protocolVersion 明确为 `2025-11-25`、`2025-06-18`、`2025-03-26`、`2024-11-05`；请求支持版本则回同版本，未知版本回服务首选 `2025-11-25`，客户端应决定是否兼容。`initialize` 后先发送 `notifications/initialized` 才可使用 tools。`ping` 始终可用。仅暴露 tools 能力；不宣称 resources、prompts、sampling、HTTP、OAuth 或分页支持。

- UTF-8，每行一个完整 JSON 对象，1 MiB 输入/输出帧上限（输入含换行）；拒绝重复键、非有限数、batch、坏 UTF-8、坏 envelope/ID 和无终止换行帧。
- 超长帧有界读取并排空到换行；截断前缀/后缀从不作为另一条消息解析。超大响应返回完整错误帧，不输出 JSON 前缀。
- 最多 2 个工具 worker，**无待执行队列**。第三个请求立即得到 busy `-32001`；控制消息仍由读循环处理。活跃重复 ID 为错误。
- 未知方法 `-32601`；协议/工具 envelope/schema/组外 operation 错误 `-32602`；初始化次序/重复初始化 `-32600`；内部未知异常 `-32603`。这些是 JSON-RPC `error`。
- service `TraceError(code,message,details)` 是 `result.content` 中 JSON 文本并 `isError:true`；成功 `isError:false`。参数是合法工具形状，但业务缺字段/权限不足等，由 service 解释为工具错误。不给任意 records.create、shell 或通用 Python 求值接口。
- 通知（包括未知通知）无响应；`notifications/cancelled` 为活跃 requestId 设置 Event。EOF 同样取消所有活跃请求，总 join 上限 1 秒；晚完成结果关闭后丢弃。取消是协作式，Python worker 不被强杀；真实进程包含与清理由 process owner 负责，EOF 返回不等于进程清理已经 complete。
- stdout 只传协议。整个 serve 生命周期把 Python 普通 stdout 诊断导向 stderr；不把 stderr 本身视为业务失败。关闭后的非协作 worker 不提供完成证明。

## 固定工具组

每个工具输入恰好 `{"operation":"...","arguments":{...}}`，两个字段必需、拒绝外层多余字段。`arguments` 内部使用对应实际 service API，效果仍受核心 case 限制。

| 工具 | operation 白名单 |
|---|---|
| traceanchor_case | case.create/get/list/revise/close，subtask.create/result |
| traceanchor_source | source.add/get/refresh/derive，analyze，version-diff，professional.run |
| traceanchor_research | observability.set，observe.http，plan，unknown.add/resolve，report |
| traceanchor_spec | spec.freeze/get，compare，verify |
| traceanchor_run | capture，run.get/list/cancel/reconcile |
| traceanchor_storage | storage.usage/register/preview/clean/promote/pin，storage.recovery.release，workspace.usage/configure/work.list/work.archive/work.clean/work.reconcile |
| traceanchor_exchange | export，import |
| traceanchor_system | doctor，knowledge.get |

例：`traceanchor_case` 输入 `{"operation":"case.create","arguments":{"objective":"理解自建文件格式","mode":"analysis","target_kind":"file","allowed_effects":["read"]}}`。`traceanchor_run` 不接受 `storage.clean`。未被 case 授予 execute 的 capture 调用必须由核心拒绝，而非因 MCP 工具可见就放行。

## Claude Code：项目 `.mcp.json`

将占位符替换为实际绝对路径；Windows 可用 JSON 转义反斜杠或正斜杠。安装 helper 自动做正确字符串转义。

```json
{
  "mcpServers": {
    "traceanchor": {
      "type": "stdio",
      "command": "[PYTHON_ABSOLUTE]",
      "args": ["-m", "traceanchor", "--workspace", "[WORKSPACE_ABSOLUTE]", "mcp"]
    }
  }
}
```

放在所选项目根，不写用户全局 `.claude.json`。官方页面说明交互会话对项目服务器有审批行为；部分 headless/SDK/cloud 或 bypass 模式并不显示同一提示，项目可信与组织策略也影响加载。`--strict-mcp-config` 可使项目 `.mcp.json` 被跳过。TraceAnchor 不修改这些开关或自动批准项目。

用户实际加载后，可在宿主 MCP 状态中检查服务，再调用 doctor、创建只读 case 并查看持久记录；这是建议的宿主验证步骤，本轮未执行真实宿主工作流。不要只凭配置生成成功记录宿主端到端通过。

## Codex：项目 `.codex/config.toml`（实验性模板）

```toml
[mcp_servers.traceanchor]
command = "[PYTHON_ABSOLUTE]"
args = ["-m", "traceanchor", "--workspace", "[WORKSPACE_ABSOLUTE]", "mcp"]
```

项目根下 `.codex/config.toml`，不写全局配置。只写 command/args，不设置模型、provider、权限、认证、全局环境或 trust。当前 Python tomllib 可验证此 TOML 语法并保留其他配置；**官方 schema 与项目配置加载测试已静态核对；指定 Codex 版本的实际加载/可信限制仍待真实宿主验证**。不因 TOML 解析通过推断宿主已加载。

## 预览、应用与卸载 API

安装不激活服务、不启动宿主、不创建业务工作区，不复制 skill，不自动下载组件。显式 apply 才写。可在已安装 TraceAnchor 的可信 Python 中调用：

```python
from traceanchor.hosts import install_host, uninstall_host

preview = install_host(project, "claude", python_executable, workspace)
# 检查 preview.entry、摘要与目标项目后，显式应用：
result = install_host(project, "claude", python_executable, workspace, apply=True)
# Codex 使用 host="codex"，其当前验证等级见实验性说明。
uninstall_preview = uninstall_host(project, "claude")
restored = uninstall_host(project, "claude", apply=True)
```

`project` 必须是既有目录；解释器和 workspace 必须显式绝对路径。默认预览连 `.traceanchor-hosts/` 都不创建。保持无关配置和顶层值：Claude 保持 JSON 语义（重排格式）；Codex 保持原始文本并追加表。TOML 冲突/非法表、坏配置、同名外部条目、回执丢失/损坏均保守停止。软/硬链接、reparse/junction 和非普通配置文件不接管。

apply 的项目所有权文件为 `.traceanchor-hosts/{host}.json` 与短期 `.lock`。回执保存 schema、目标相对路径、原字节 base64 备份及摘要、安装后摘要、entry 和 phase。**回执不是秘密脱敏器**：原配置可能含本来就存在的敏感字段，回执仅保留在用户项目内，发布/提交前应按项目策略排除；本产品测试只用自建无秘密配置。

## 升级、重装、迁移与回退

- 幂等安装：配置/回执与请求相同则 unchanged；不会重写。
- 重装/更换解释器或 workspace：只有现有配置仍与回执安装后完整摘要一致才更新 owned entry；原始安装前备份保持不变，卸载仍恢复最初字节。
- 升级程序：先在用户选择的隔离环境更新包并运行 doctor；项目接线不因程序更新自动改变。如解释器路径变更，走 receipt-backed 重装。发布包安装/升级资格由发布维护者另行验证。
- 迁移项目/机器：先独立备份项目与业务 workspace；在目的地安装可信包、诊断、检查绝对解释器/workspace 路径，再按 owned 重装。配置迁移不是业务数据库迁移，不会自动恢复旧进程或获得新效果授权。
- 卸载：核对回执、配置后像和 owned entry，恢复原始字节；初次无配置则删除仅该配置文件。删除 owned receipt；保留业务 workspace、L1 和其他项目文件。空管理目录或 `.codex` 目录可保留。
- 失败回退：先持久 prepared 备份，再原子替换配置、回读，最后提交 installed receipt。正常异常仅在磁盘字节仍是我们写入时恢复前像；外部用户编辑始终保留。单文件写是原子的，但多文件不是 OS 原子事务。

## 故障排查与保守恢复

| 现象 | 处理 |
|---|---|
| host.conflict / 用户编辑后卸载失败 | 保留用户字节；手动比较本地回执中的安装后身份、原始备份与当前文件。不要删回执后强行重装 |
| host.receipt / 同名 entry 却无回执 | 不猜所有权；备份并人工确认，helper 不接管外部 entry |
| phase=prepared 或遗留 `.lock` | 视为中断事务；先确认没有仍运行的配置写者，再检查配置/备份摘要。工具不自动破锁或用 prepared 猜 installed |
| host.config / 坏 JSON/TOML / 非普通文件 | 修复合法配置后再预览；原字节不以默认空配置覆盖 |
| ImportError / 服务立即退出 | 确认 command 指向安装该包的解释器；不依赖宿主当前工作目录或私人 PYTHONPATH |
| busy -32001 | 两个工作请求在执行；取消已知 requestId 或待其结束后有界重试，不积累无限请求 |
| isError:true | 读取 content 中结构化 code/message/details，区分缺权限、坏输入、缺观测；不自行扩大 case 效果 |
| 传输成功但宿主没有工具 | 检查宿主版本、项目可信/加载策略及实际 initialize/list；配置存在不是 READY |

产品写者用排他锁从读取到提交协调；外部编辑器不共享此锁，写前摘要检查可发现已观察到的变化，但不承诺消除最后一次检查与 OS rename 之间的所有外部竞态。配置编辑时应避免同时让外部程序改同一文件。需要强跨编辑器事务时重新设计文件所有者合同，不用“atomic rename”冒充多写者串行化。
