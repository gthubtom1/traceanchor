# R3 工作区、恢复与版本维护

适用：**0.2.0 候选**，2026-11-18，合同 [FOUR-SOURCE-PRODUCT-R3](goal/CONTRACT-R3.md)。本篇按当前 workspace / lifecycle / maintenance / service 实现说明操作，不表示新候选包已经通过最终安装、迁移、故障或发布资格。旧 0.1.1 包/标签及其资格记录保留历史身份；最新门状态见 [goal/status.json](goal/status.json)。

专业场景见 [professional-guide.md](professional-guide.md)，已测工具与平台边界见 [r3-support.md](r3-support.md)。以下所有 Bash 块都是独立单命令，先用编辑器准备所示请求 JSON，将路径和 ID 换成自己的值。维护 JSON 是机器入口参数，不要求普通分析用户先手写整套 case JSON。

## 1. 程序、接线和业务资产分开

为什么：卸载或回退程序不应顺带丢掉长期证据。

- 程序在用户选择的 Python 环境；工作区在环境与源码树之外。
- 项目宿主配置和 `.traceanchor-hosts/` 回执由明确项目的 host helper 管理，不修改全局模型、认证、权限或 trust；回执可能含原配置备份，按私有配置保管。
- 产品只管理显式 `--workspace`、带合法 marker 的目录，不扫描全盘、不接管未知大目录。

```text
[WORKSPACE]/
  traceanchor.workspace.json   工作区所有权与 schema
  state.sqlite3*              合同、历史、引用、租约、登记及可能的 WAL/SHM
  objects/                   内容寻址字节（可共享，L1/L2/L3）
  work/                      已登记执行目录、工具缓存和失败/超额残留
  checkpoints/               数据库检查点清单及 staging
  exports/ logs/ cache/      若存在，分别计量
```

外部原件/候选文件与宿主配置不包含在单个数据库检查点里；迁移时另行保留。目录名字叫 work/cache 不自动证明其中每个文件可删。未知文件、链接、junction/reparse point、硬链接及归属不清的内容保守处理，不用递归删除替代生命周期判断。

## 2. 先看整工作区，再看登记对象

为什么：CAS 配额只覆盖登记对象，数据库、工具输出、缓存和失败残留同样占磁盘。

`empty.json`：

```json
{}
```

```bash
traceanchor --workspace "[WORKSPACE]" call workspace.usage --input empty.json
```

```bash
traceanchor --workspace "[WORKSPACE]" call storage.usage --input empty.json
```

| 诊断 | 统计范围 / 字段 | 读数限制 |
|---|---|---|
| workspace.usage | `registered_objects`、`unregistered_objects`、`database`（SQLite/WAL 等）、`work`、`checkpoints`、`exports`、`logs`、`cache`、`control`、`unknown`；`total_bytes`、`reserved_bytes`、阈值及 issues | 只在所选 marker 工作区内；不是全盘或外部源计量 |
| storage.usage | L1/L2/L3 逻辑字节、去重 `physical_registered_bytes`、CAS limits 和 leases | 不能当整工作区总量；同一物理对象的多个登记会重复逻辑计数 |

census 遇条目上限、链接未跟随或不可读位置时 `complete=false`，报告 `issues` / `unscanned`，用量只是保守下界，新工作 admission 被阻止。并发删除的临时文件记录 `vanished-during-census`，不假装读到已消失字节；工具仍持有文件时用新句柄取大小，避免 Windows 目录枚举缓存的零大小漏计。census 不跟随链接，不根据扫描结果自动删除未知项。

默认最多扫描 100000 条目。可给 `workspace.usage` 传 `max_entries`，范围 1–1000000；缩小扫描不会把未扫描部分变成零空间。

## 3. 两层预算、预留与真实增长

为什么分两层：对象入库和执行目录有不同生命周期；调大 work 限额不等于调大 CAS，也不等于系统还有空闲磁盘。

| 策略 | 当前默认值 | 配置入口 |
|---|---|---|
| 登记对象 CAS | hard 256 MiB、soft 192 MiB；L3 temp 64 MiB | 新工作区 `init --hard-bytes / --soft-bytes / --temp-bytes`，创建后冻结 |
| 整工作区 | hard 1 GiB、soft 768 MiB、work 128 MiB、max_entries 100000 | `workspace.configure`；无活动租约时显式修改 |

新空工作区设置默认等值 CAS 预算：

```bash
traceanchor --workspace "[NEW_WORKSPACE]" init --hard-bytes 268435456 --soft-bytes 201326592 --temp-bytes 67108864
```

`workspace-limits.json`：

```json
{"limits":{"hard_bytes":1073741824,"soft_bytes":805306368,"work_bytes":134217728,"max_entries":100000}}
```

```bash
traceanchor --workspace "[WORKSPACE]" call workspace.configure --input workspace-limits.json
```

- 四项为正整数，soft/work 不高于 hard。当前 configure 按默认值合并传入字段，**省略字段会采用默认值，不是沿用先前自定义值**；维护时建议一次显式写全四项，并核对返回值。已有活动 lease 返回 resource-busy，不按 TTL 抢占。
- 控制内的目标复制、夹具输入和选定产物归档使用 admission / reservation，预留关联持久 owner；对象 `Store.put_bytes` 在事务内也核整工作区实量和活动预留，而非只检查 CAS。预留数与实占均需读；预留可以在复制期间与新实占保守重叠，不承诺恰好用满预算。
- soft 是预警；hard / work 超额或 census 不完整会拒绝新工作/对象入库。CAS 另报 disk-budget / temp-budget。必要时只回收合格 L3，仍不足就停，L1 不作牺牲品。
- **普通 capture 和专业工具执行均约每 50ms 检查受管工作区增长并协作取消。** 外部工具在轮询间隔可以写超量；启动、收集、SQLite 控制日志也有开销。该机制不是 OS 强配额或严格实时硬截止。
- 目标进程在工作区外写文件、使用直接网络或动态依赖，不受该计量机制拦截。效果 allowlist 和 Windows Job/进程族所有权不等于文件/网络沙箱；严格全系统隔离需另有实际 OS 资格。
- 诊断事件有单条/条数界限，记录历史、数据库和 L1 仍会增长；census 计入它们，不声称自动压缩数据库或无限日志轮转。检查点 staging 也占磁盘，离线 snapshot 不是所有中间字节都受 OS 强制限制的证明。

### 超额后留下什么

超额取消不会把残留从计量中隐藏：run 保留资源错误、清理状态及工作目录归属，workspace-item 保留恢复用途。若大文件超过当前 work_bytes，终态 inventory 可能不完整，只记字节下界并保留实物，避免无界哈希读取。

当预算阻止完整原始流入 CAS 时，普通 capture 与专业命令会在持久 run 的 `recovery_stream_prefixes` 留每流最多 **4096 字节**的精确 Base64 前缀、`full_size`、`full_sha256` 和 `complete`。这里 full 指执行器实际返回的已捕获流；若此前输出限额已截断，它不是进程无限输出的完整摘要。前缀以外字节未由这项回执存下，**不能把 prefix 或摘要当完整 stdout/stderr、完整 observation 或 pass**。

恢复时先看 cleanup 和真实 owner，再进行容量/策略修正与残留重盘点。不要继续重复启动同一大采集，也不要删数据库登记掩盖占用。

## 4. work 目录：list → reconcile → 实物 archive → 预览 → clean

为什么单独管理：失败、超时、超额或发布证据中断都可能保留目录；它不是无人负责的垃圾。专业目录创建为 L2，普通 capture 目录通常 L3；两者均有 owner、run、理由和恢复状态。

```bash
traceanchor --workspace "[WORKSPACE]" call workspace.work.list --input empty.json
```

读取 `items` 中 workspace-item 的 `id`（这才是 work_id，不是 run_id）、`path`、`run_id`、`tier`、`status`、`cleanup`、`inventory_complete`、`recovery` 和 `directory_retired`。已退休目录无需再次归档。

### 4.1 只对已清理的终态残留 reconcile

需要原因：超额时可能无法完成 inventory。核实可用空间并显式调整策略后，才能有界重盘点；这不是证明进程已退出的入口。

`work-reconcile.json`：

```json
{"work_id":"[WORK_ITEM_ID]"}
```

```bash
traceanchor --workspace "[WORKSPACE]" call workspace.work.reconcile --input work-reconcile.json
```

当前 service/CLI 和 MCP 的 `traceanchor_storage` 均包含此操作。它要求**生产者 run 已终态、cleanup.state=complete，且没有该 run/目录的活动 lease**，再用现有策略刷新目录 inventory。它不结束活跃进程、不偷租约、不把 cleanup.unknown 改成 complete。若单文件仍超当前 work_bytes，继续保留并说明缺口；不要编辑库存摘要凑齐完整清单。

`run.reconcile` 是另一操作：对中断的 preparing/running/collecting 记录标 abandoned、cleanup unknown，不清租约、不杀旧 PID、不证明外部副作用已清理。未知清理必须独立核实；没有已证实的清理回执时，work reconcile/归档路径继续阻断。

### 4.2 归档真实 payload，而非只保存一张报告

`work-archive.json`：

```json
{"work_id":"[WORK_ITEM_ID]","reason":"终态清理已核实，保存真实恢复内容后退役执行目录"}
```

```bash
traceanchor --workspace "[WORKSPACE]" call workspace.work.archive --input work-archive.json
```

archive 要求目录终态 completed/failed、cleanup.complete 和完整 inventory；逐文件检查普通路径、单硬链接及与 inventory 一致的摘要。**实际文件内容复制为带 recovery_use 的 L2 payload**，workspace-item 引用这些材料；另建 L1 索引，索引列出 payload 身份和理由。只有实物复制/校验完成才解除目录本身的 recovery 门。

该过程可能暂时同时占 work 和 CAS 两份空间，必须有归档余量；超预算就保留原件，不先删唯一副本。仅有 manifest/report JSON、文件名或哈希清单，不算 payload 已归档。work 副本可退役不等于 CAS 恢复材料立即可回收，后者仍受恢复引用保护。

### 4.3 预览和执行分别调用

`work-preview.json`：

```json
{"work_id":"[WORK_ITEM_ID]","apply":false}
```

```bash
traceanchor --workspace "[WORKSPACE]" call workspace.work.clean --input work-preview.json
```

`work-clean.json`：

```json
{"work_id":"[WORK_ITEM_ID]","apply":true}
```

```bash
traceanchor --workspace "[WORKSPACE]" call workspace.work.clean --input work-clean.json
```

执行前重检 archive/payload 可读、pin/recovery、终态清理和租约；逐文件再次检查当前摘要和硬链接。只删已登记、未变的 inventory 文件，目录只在空时移除。**新出现的未知文件、变更文件、链接/归属不明内容保留**，结果可为 `interrupted-or-unknown-retained`，不能把目录还在说成全部已回收。

取消保留 pending 和已回收字节，之后重新 list/预览；不是无界递归清理。当前 work clean 的取消检查以文件为单位，没有单独 max_seconds 参数，单个文件读取/OS 调用也不是严格实时保证。预览只是当前条件估算；执行仍可能因变化而保留文件。不要复用旧预览当永久许可。

## 5. L1/L2/L3 与 CAS 清理

为什么以引用裁决：结束聊天不等于任务终态，更不等于恢复义务解除。来源、理由、大小、owner、run、再生成/恢复用途、pin 与引用共同决定去留。

| 级别 | 典型资产 | 清理条件 |
|---|---|---|
| L1 长期 | 来源身份、关键证据、冻结规格/回归、验收/恢复归档和检查点 | 自动清理始终跳过；晋升先校验字节并更新引用，再处理旧副本 |
| L2 项目期 | 非关键可重建工作、归档的 work payload | owning case 已 accepted/closed 且归档完整，无恢复义务/引用/活动/租约/pin 后，才可按明确 ID 回收 |
| L3 短期 | 执行快照副本、短期重试材料 | 生产者终态、cleanup.complete，无引用/恢复/活动/租约/pin，满足 min_age 后可回收 |

`preview.json`：

```json
{"min_age":3600,"max_items":1000}
```

```bash
traceanchor --workspace "[WORKSPACE]" call storage.preview --input preview.json
```

查看每项 `eligible` / `reason` / `physical_bytes`、预计回收和 `truncated`。共享 CAS 对象的多个登记不等于多份物理空间；最后有效登记退休才可能物理回收。未知未登记对象保持保留，由 workspace census 显示，不由 CAS GC 猜着删。

`clean-l3.json`（未传 ids 时仅选合格 L3）：

```json
{"min_age":3600,"max_items":100,"max_seconds":5}
```

```bash
traceanchor --workspace "[WORKSPACE]" call storage.clean --input clean-l3.json
```

`clean-selected.json`（显式选当前有界预览中的材料 ID，也仍须符合全部条件）：

```json
{"ids":["[MATERIAL_ID]"],"min_age":3600,"max_items":1000,"max_seconds":5}
```

```bash
traceanchor --workspace "[WORKSPACE]" call storage.clean --input clean-selected.json
```

事务内再次重检。默认上限 100 项/5 秒，可选至多 1000 项/60 秒；支持协作取消。`pending` 非空时保留 interrupted 记录，下一轮重新预览。tombstone 后中断可出现 `retired-retained-bytes`，即登记已退休但物理字节保守残留，不伪称已释放磁盘，也不自动按目录名清孤儿。

### 恢复保护的显式解除

`recovery_use=true` 不只是说明文字：入库创建机械恢复引用，GC 同时检查 metadata 和 refs。要解除 CAS 恢复义务，先完成 accepted/closed 的 case 归档、确认生产者终态/cleanup.complete 且无 lease，再给出审查理由。

`recovery-release.json`：

```json
{"material_id":"[RECOVERY_MATERIAL_ID]","reason":"任务验收归档已核对，恢复内容转长期归档后解除旧副本义务"}
```

```bash
traceanchor --workspace "[WORKSPACE]" call storage.recovery.release --input recovery-release.json
```

该操作读取**实际恢复字节**并归档为 L1、验证可读，建立 case 引用，之后才设置旧材料 recovery_use=false 并解除 recovery-protection 引用。其他业务/共享引用仍保留，原副本不一定立刻 eligible。仅有 case.close 的报告 JSON 不代替恢复内容；缺内容、损坏归档、活动生产者或 lease 都保留保护。

需要把选定关键材料晋升 L1 时，使用 `storage.promote`（参数 material_id，可附 owner）；pin 则用 `storage.pin`（material_id、pinned）。它们都先校验当前字节，不能把损坏材料靠改级别变成有效证据。

## 6. 离线检查点、完整备份与迁移

为什么离线：数据库检查点、整个工作区备份和外部业务回滚是三件事，单次 lease 查询不锁住所有其他宿主。

**先停全部使用该工作区的 CLI/MCP/宿主与写者，确认目标退出和真实资源清理，检查无活动租约。** 不手工删除 lease、破锁或按旧 PID 盲杀；run.reconcile 不能完成这一步。

```bash
traceanchor --workspace "[WORKSPACE]" maintenance snapshot
```

保存返回 checkpoint ID。实现使用 SQLite backup / integrity_check，把数据库字节归档 L1，并在 checkpoints 中保留外部可定位的 schema/摘要/大小清单。检查点位于同一工作区，不能防整区丢失/盘损；还需独立备份。

```bash
traceanchor --workspace "[WORKSPACE]" maintenance restore --checkpoint "[CHECKPOINT_ID]"
```

恢复核对清单、对象字节、schema、SQLite 完整性及无 lease，先建恢复前 snapshot，再替换数据库；返回 `rollback_to` 供回退本次恢复。只回退数据库，保留对象字节；旧库不认识的新对象可变为未登记材料，census 仍应显示并保守保留。外部来源/候选文件、目标副作用、服务和宿主配置不会一起回滚。当前 schema=1，没有通用跨 schema 自动迁移或热恢复保证。

### 完整工作区迁移

1. 停所有写者，保存实际程序/工具版本、工作区 schema、近期 report、源文件身份和恢复点；另保留旧包与校验值。
2. 复制整个工作区到独立备份位置，含 marker、数据库及必要 sidecar、objects、checkpoints、必要 work；别只复制 SQLite。另备份外部来源/候选、宿主项目配置和所有权回执。
3. 核对备份内容可读和摘要/数量/容量。目的地先用同一可信版本在副本上诊断，使用 workspace.usage / report 观察恢复状态，不能以 doctor 代替全库证据校验。
4. 目的机器的源绝对路径、工具和环境可能改变。明确重新选择本地文件、审查规格并重验受影响义务，旧 pass 不等于新机器运行资格。
5. 宿主接线按项目回执流程更新绝对解释器/workspace 路径；配置迁移不是业务库迁移。保留原备份直到新环境的有限业务和维护旅程通过。

### 有限 case 交换不是整区备份

`export.json`：

```json
{"case_id":"[CASE_ID]"}
```

```bash
traceanchor --workspace "[WORKSPACE]" call export --input export.json > "[EXPORT_FILE]"
```

```bash
traceanchor --workspace "[NEW_IMPORT_WORKSPACE]" init
```

```bash
traceanchor --workspace "[NEW_IMPORT_WORKSPACE]" call import --input "[EXPORT_FILE]"
```

导出返回 payload/sha256，源路径便携化不意味着内容脱敏；合同、代码、原始输出仍要逐项审查。导入检查摘要/对象/引用，保留身份，效果重置 read，旧 verdict 过期，执行路径须明确重挂。CLI 输入 4 MiB、MCP 帧 1 MiB，Base64 还会膨胀；大 export 成功生成不保证能通过该入口 import。父子依赖、未登记文件及检查点也不由单 case 完整涵盖。超限保留整区备份，不删证据凑“迁移成功”。

## 7. 版本更新、回退与卸载

为什么保留旧包：程序更新、数据变化和工具升级可以分别导致结果失效。旧 0.1.1 wheel/源码/标签留作历史，不删除或重写标签，也不把旧发布页面改成 R3 完成证据。

本轮名称为 **0.2.0 候选**。pyproject、构建 backend、service/doctor 元数据已由集成者更新，本轮只读核对均为 0.2.0；这不等于最终包或 Release 已合格。最终必须核对 CLI、包元数据、源码摘要与实际安装一致，随后才有安装/回归/公开发布资格。

### 升级和同版本重装

离线完整备份 + 检查点后，在选定隔离 Python 环境使用实际取得且已校验的新 wheel；占位文件名不表示已发布。

```bash
python -I -B -m pip install --no-index --no-deps --upgrade "[NEW_WHEEL_FILE]"
```

```bash
traceanchor --version
```

```bash
traceanchor --workspace "[WORKSPACE]" doctor
```

之后在新目录运行有意义的专业切片、检查旧 case 的 report/依赖新鲜度和适用恢复流程；不能只跑旧计数器 demo 就授予 R3 安装资格。同机新 venv 不是干净机器。新版本若无已测迁移，先在备份副本验证，不改唯一数据副本。

```bash
python -I -B -m pip install --no-index --no-deps --force-reinstall "[SAME_VERSION_WHEEL_FILE]"
```

同版本重装只替换程序，不重建业务库。解释器/workspace 路径变化时按 [hosts.md](hosts.md) 的回执重装接线，保留用户无关配置；冲突先保留现场，不移除回执后强行接管。

### 回退

停写者并保存当前现场，用兼容版本恢复升级前检查点，或把升级前完整备份复制到另一个新目录，再安装保留旧包：

```bash
python -I -B -m pip install --no-index --no-deps --force-reinstall "[RETAINED_OLD_WHEEL_FILE]"
```

程序回退不自动回滚数据库/外部目标；不改 schema 数字冒充兼容。回到 0.1.1 也不意味着仍可调用 R3 专业入口。CLI/MCP operation、schema、知识包和 helper 的兼容性分别核对；当前无对任意未来版本的无损降级承诺。

### 卸载

若安装过项目局部接线，在旧解释器还可用时先预览，再显式 apply：

```bash
traceanchor host uninstall --host claude --project "[HOST_PROJECT]"
```

```bash
traceanchor host uninstall --host claude --project "[HOST_PROJECT]" --apply
```

Codex 使用 `--host codex`。只有合法回执且配置未被外部修改时才恢复 owned 配置；prepared/lock 或用户编辑冲突按 hosts 文档核对所有者和摘要，不自动破锁。

```bash
python -I -B -m pip uninstall -y traceanchor
```

环境之外的业务 workspace、L1、用户项目与外部工具保持保留。本产品不附带递归删工作区、全局工具或旧大目录的卸载动作。

## 8. 更新参考版本与长期接手

为什么保持历史：新输入、参考/候选、工具/环境、规格或比较器变化，相关旧 verdict 应 stale，而不是覆盖旧“通过”文件。P05 已实测子来源升级使父验收失效，复用未变父代码并增量验证；P04 的 V1/V2 记录也分别保留。

接手/压缩恢复、范围切换、发布或宣布完成前，完整读 [goal/CONTRACT-R3.md](goal/CONTRACT-R3.md)、[goal/status.json](goal/status.json) 与短入口，核当前源码、活跃 run、owner/claim 和未满足门。聊天摘要不替代事实库，旧 0.1.1/旧 A 表不覆盖 P01—P05/G01—G10。当前源码变化后的新资格必须重绑受影响检查，最终发布前再核全核心回归与包旅程。

协作保持主代理加至多两个活跃工作者、每文件单写者。`tools/claims.py` 用 `python -I -B` 执行：领取/恢复精确所有权，写前 check；基线意外变化先核而非覆盖；owner 完成后带理由 checkpoint，再 check/release。不按 TTL 接管或用多 worktree 假设不存在逻辑冲突。claim 是协作者约束，不拦截任意外部编辑器。

四源复评使用 [UPSTREAM-REVIEW-PROMPT.md](../UPSTREAM-REVIEW-PROMPT.md) 与 [provenance/review-template.md](provenance/review-template.md)：恢复本地机制映射和版本，保留用户改动，隔离静态比较固定新版、删除/弃用和组件许可，评价收益/迁移成本；默认只研究建议，不自动下载执行、安装、合并或发布。关键决策和身份长期归档，临时源码/中间材料按 L2/L3 回收，不让长期引用只剩临时绝对路径。

## 9. 故障收尾检查表

| 现象 | 保留与下一步 |
|---|---|
| workspace-budget / work-budget / workspace-unmeasured | 保存 run/错误/prefix/残留，读 census，先停采集；有依据调整容量后，终态 cleanup.complete 且无 lease 才 reconcile → archive → clean |
| disk-budget / temp-budget | 同时检查 CAS 和整区；先 preview 合格 L3，不删 L1、恢复依赖或未知文件 |
| inventory 不完整 / oversized-file-retained | 保留实物与字节下界；核容量后显式策略修正、终态重盘点，不强造 inventory |
| cleanup unknown / active lease | 独立核真实资源/owner；不按旧 PID 盲杀、不删租约、不把 run.reconcile 当清理证明 |
| GC interrupted / retired-retained-bytes | 保存 gc results/pending，重新预览；保守残留不当已释放空间 |
| archive/integrity 错误 | 保留原始恢复字节和现场，核真实 payload；索引 JSON 本身不修复内容缺失 |
| SQLite/检查点损坏或 schema 不兼容 | 完整备份现场，用兼容版本/独立备份恢复；不 init 空库盖掉旧记录 |
| host prepared/lock/conflict | 核真实写者、回执备份和当前字节；保持用户修改，不自动破锁 |

整区增长、恢复实物归档、未知文件保留与终态残留流程已有实际回归；这不是所有 OS、故障和新包旅程全合格的声明。最终证据索引、源码绑定和仍未验证项由 R3 状态及最终资格记录裁决。
