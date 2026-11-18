# JS/Web 运行时切片：实际交互、状态与 HTTP 因果

## 先选适用边界

当前适配器在 Node 的真实 V8 inspector 中观察调用，不是浏览器截图或 DOM 自动化。适用输入是调用者明确选择、允许执行的自建 JS 模块；模块提供有限夹具接口。`examples/web/reservation.mjs` 是有库存约束、预留/提交状态、错误输入的公开教学材料，绝非 P04 隐藏题库、预写坏候选或模型效果成绩。

宿主先提出问题，例如“预留被拒绝时客户端和服务端状态各怎么变化；提交究竟调用了哪条接口”。集成入口应先检查 execute 和 network 效果、预算、目标身份及受管目录，再调用：

```python
observe(target, directory, execute, node=node_executable, scenario=scenario)
```

`execute(argv, input_bytes=b'', env=None)` 由产品唯一进程 owner 注入。适配器不启动其他进程、不写 Store、不替宿主创建模型循环。Node 使用调用者配置的路径；不下载、安装或扫描账户与凭据。

## 有限输入与真实观察

模块导出 `createSession({request, baseUrl})`、`createService()`。前者返回 `dispatch(action)` 与 `snapshot()`，后者返回 `handle({method,path,body})` 与 `snapshot()`。scenario 只接受 1–12 个唯一 ID 的 JSON action，不接受代码表达式、shell、外部 URL 或任意协议命令。目标本身的执行与 imports 并非 OS 沙箱；来源与执行资格由集成者负责。

helper 在一个受管进程中：

1. 用 `Debugger.enable`、`Debugger.getScriptSource` 验证 inspector 实际加载的目标源码摘要。
2. 用 `Debugger.setBreakpointOnFunctionCall` 观察 dispatch 入口，用 `Profiler.startPreciseCoverage/takePreciseCoverage` 取得真正执行过的函数、调用数和源码行列。
3. 顺序调用有限交互，独立读取每一步前后 snapshot，分别记录正常返回和业务异常。业务异常不是 collector 成功的同义词，也不会把进程失败升级为观察完成。
4. 启动 `127.0.0.1` 随机端口 HTTP 服务；目标的 request wrapper 真的 fetch 服务，服务真的调用模块 handler。step、实际请求 ID header、inspector 请求处调用栈、服务接收和应答共同组成因果链，不是 endpoint 正则命中。
5. 结束关闭 HTTP 连接、服务与 inspector；外层 runner 仍须给出进程族 cleanup=complete。缺观测、超时、截断、进程失败或来源变更保持 blocked/stale。

不能从“调用函数出现过”直接推导所有分支或所有参数的行为。precise coverage 是当前输入下的执行事实，函数位置是当前源码的定位材料；其他依赖、直接 I/O、浏览器、设备与未见输入保留未知。

## 输出与恢复

每次调用使用独立的空受管目录，已有同名产物不覆盖。返回的 artifacts 同时含 `path` 与 `relative_path`，二者都是目录内相对路径，并有 SHA256/size。产物是：

- `node.stdout.bin`、`node.stderr.bin`：原始工具输出。
- `node-run.json`：外层真实执行结果、退出状态与 cleanup。
- `web-trace.json`：helper 原始结构化观察、各 step、源位置、实际请求和状态。
- `web-contract.json`：由本次 trace 形成的有限接口/行为合同，注明 observed 范围，不授予全局等价或候选验收权威。

成功结果的 `status=succeeded` 仅代表这条实际观察链成立。结果内提供输入 source SHA256、helper SHA256、Node 版本、inspector 源摘要、step/request IDs 和原始产物索引。CLI/MCP 集成仍由 service 绑定自身版本、效果、预算、证据及验收，适配器不另造 pass。

重试新建输出目录。原始失败材料保留，避免覆盖成“最后一次成功”。源码、工具或 helper 变化后，旧观察保持历史身份，重新执行受影响切片。

## 本地复现

可信环境安装本产品后，在源码 checkout 中执行：

```text
python -I -B tools/qualify_web.py --node [NODE_EXECUTABLE]
python -I -B tests/test_web_adapter.py
```

qualifier 首先在新的 `.validation/web-*` 写 ownership/tier/reason/status，逐次保存所有工具 argv、stdin、stdout、stderr 和执行回执，最终登记 cleanup、摘要及检查结果。它使用公开自建样本，只证明 Node runtime 切片。路径可由工具参数提供，不固定本机私人路径。输出目录属于 L2 资格材料，清理前按产品归档制度保留必要源身份、原始输出及合同。

## 浏览器和扩展的接入路线与资格诊断

当前返回 `browser_dom=unqualified`、`extension_runtime=unqualified`，静态 manifest 阅读属于另一能力。Node 可执行、MCP 连通、manifest 可解析三者都不构成浏览器或扩展运行资格。

后续浏览器 adapter 应采用已安装且单独合格的 browser/CDP 或 Playwright：创建新的受管 profile 与 loopback 页面，保留导航/交互/DOM/网络事件全程，不在步骤中清空 run 事件队列；通过同一个 target/session 把脚本位置、request initiator、状态与交互绑定。对扩展还需记录 extension ID/manifest 版本、service worker/background/content-script 的分别可达性、注入页面、消息边界、浏览器版本与关闭 profile 的实际结果。每类分别诊断 missing / available-unprobed / probe-failed / qualified，不拿网页资格代替扩展资格。

缺浏览器、设备或真实扩展会话时交付范围内 Node 证据和最短下一实验，浏览器门继续未验证；不隐式安装组件或使用个人浏览器资料。
