# 存储生命周期与离线维护

适用版本：**0.1.0 有限能力首版**。本地资格见 [qualification.json](qualification.json)，隔离包维护实测见 [install-qualification.json](install-qualification.json)，合同见 [实施契约](IMPLEMENTATION-CONTRACT.md)。bash 块均为独立单命令；替换路径/ID，占位解释见 [README](../README.md)。

## 1. 程序、宿主接线与业务数据分离

为什么：卸载程序不应删除用户长期资产。

- 程序由独立虚拟环境内的 pip 管理，业务工作区放在环境外。
- 项目局部 `.mcp.json` / `.codex/config.toml` 及 `.traceanchor-hosts/` 回执由 host helper 管理；回执可能含原配置备份，按私有配置保管。
- 显式 `--workspace` 下保存所有权 marker、数据库、对象和工作材料，默认不随程序卸载。

```text
workspace/
  traceanchor.workspace.json   所有权及 schema
  state.sqlite3               合同/来源/历史/引用/租约/登记
  objects/哈希前缀/完整哈希     内容寻址字节，可共享
  work/                       受控操作暂存及残留
  checkpoints/                检查点清单与短期 staging
```

不要根据 tmp/cache/work 名称猜可删，不直接改 SQLite、refs/leases 或材料级别。未知/未登记文件默认保留。工具只管理产品明确拥有的材料，不扫描全盘或接管既有大目录。

## 2. L1/L2/L3 保留条件

为什么：清理依据身份、引用及生命周期，不依据对话是否结束。

| 级别 | 例子 | 规则 |
|---|---|---|
| L1 长期资产 | 来源快照、关键输出、状态、证据、归档、数据库检查点 | 自动清理始终跳过 |
| L2 项目材料 | 可重建产物、非关键输出 | case 已 accepted/closed，L1 archive 校验正常，无引用/恢复依赖、活动或租约，才可能按明确 ID 清理 |
| L3 短期材料 | 执行快照副本、重试材料 | 生产者终态且 cleanup=complete，无引用/活动/租约/pin，满足 min_age 才可回收 |

共享对象最后一个有效登记退休后才有物理回收空间。结束聊天不等于租约释放。当前 min_age 默认为 0，没有后台定时清理；需要保留窗口时显式传入秒数。

storage.register 只接收明确选择的 work/ 内相对普通文件，复制并登记，不代表原 work 文件已经删除。promote 校验字节后转为 L1，可附 owner 引用，不先删唯一副本。

## 3. 用量、预览和有界清理

为什么：先看每项 keep/delete 原因与预计空间，再决定执行。用编辑器保存请求文件；每个命令显式使用同一工作区。

`empty.json`：

```json
{}
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/evidence" call storage.usage --input "C:/[请求目录]/empty.json"
```

`preview.json`：

```json
{"min_age":3600,"max_items":1000}
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/evidence" call storage.preview --input "C:/[请求目录]/preview.json"
```

preview 是只读选择：查看 items 的 eligible/reason/physical_bytes、estimated_reclaim_bytes 及 truncated。预算内只展示部分登记；预计值不是空间保证，同一对象共享或并发变化都会影响结果。

`clean.json`（不传 ids 时只选择合格 L3）：

```json
{"min_age":3600,"max_items":100,"max_seconds":5}
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/evidence" call storage.clean --input "C:/[请求目录]/clean.json"
```

清理 L2 必须显式选用当前有界预览中的 ID，仍须通过资格重检。例如另存 `clean-selected.json`：

```json
{"ids":["[MATERIAL_ID]"],"min_age":3600,"max_items":1000,"max_seconds":5}
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/evidence" call storage.clean --input "C:/[请求目录]/clean-selected.json"
```

执行不把预览当永久许可：事务中重检引用、生产者、租约、哈希和普通文件身份。默认 100 项/5 秒，最多 1000 项/60 秒，可协作取消。返回 gc 记录的 data.results、pending、reclaimed_bytes；interrupted 需重新预览后续选，不重放旧预览。tombstone 提交后中断可能保守留下字节；retired-retained-bytes 不等于真正回收，也不承诺自动扫掉孤儿。不要手动删数据库行掩盖残留。

`pin.json`：

```json
{"material_id":"[MATERIAL_ID]","pinned":true}
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/evidence" call storage.pin --input "C:/[请求目录]/pin.json"
```

`promote.json`：

```json
{"material_id":"[MATERIAL_ID]","owner":"[CASE_ID]"}
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/evidence" call storage.promote --input "C:/[请求目录]/promote.json"
```

## 4. 容量预算的实际边界

为什么：登记对象配额不是整个磁盘的写入隔离。

- 默认已登记对象去重后的 hard_bytes 为 256 MiB，soft_bytes 为 192 MiB；L3 temp_bytes 为 64 MiB。逻辑 tier bytes 可能重复计入共享对象，physical_registered_bytes 按有效路径去重。
- storage.usage 明确只统计已登记对象；不把 SQLite、work、未登记文件、外部源文件或检查点 staging 冒充已纳入容量。L1 增长也应检查；检查点是 L1，会消耗预算。
- 大对象入库前检查配额，必要时有界回收合格 L3，仍不足报 disk-budget；L3 超限报 temp-budget。不会为满足配额删 L1。硬盘实际耗尽还会报 write-error/database-error 等，配额并非文件系统空闲空间保证。
- case 的 max_bytes 主要限制来源读取和部分观测/采集，不是所有外部写入的累计字节配额。已运行目标能在目录外写入，产品不封锁此行为。
- CLI init 可在新建时设置 --hard-bytes/--soft-bytes/--temp-bytes，均为正整数，soft/temp 不高于 hard；已有 marker 时再次传限额会报 limits-frozen 并保留原工作区。开始新 case 不释放旧 L1；不要自行改数据库限额。
- core.event 的诊断日志单条最多 64 KiB，只保留最近 10000 条；记录历史和 L1 另行保留。这不是整个 SQLite 文件轮转或压缩保证，数据库大小仍未计入 CAS 配额。全工作区预留空间与任意目标进程写入硬配额尚未证实，须由发布门显式处理。

创建新工作区时设置默认等值限额的示例（目录须新建，不能对已有工作区改限额）：

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/bounded-evidence" init --hard-bytes 268435456 --soft-bytes 201326592 --temp-bytes 67108864
```

## 5. 离线 snapshot / restore

为什么：数据库回退与工作区完整备份是两件事；热恢复可能与其他写者冲突。

**先停所有连接该工作区的 CLI/MCP/宿主和写者，确认活动目标退出、租约及外部副作用已核实。** run.reconcile 只标 abandoned/cleanup unknown，不自动清掉租约或证明进程已退出。resource-busy 时检查真实所有者，不手工删 lease 行强行继续。

当前 CLI 已接入 `maintenance snapshot` 和 `maintenance restore --checkpoint ID`，调用 maintenance.py 的实际函数。入口存在不等于该安装包已完成维护旅程资格；以实际 `--help` 和最终资格记录为准。

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --help
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/evidence" maintenance snapshot
```

保存返回 checkpoint id。实现使用 SQLite backup 和 integrity_check，将数据库字节存为 L1 对象，清单置于 checkpoints/ 外部可定位处并含 SHA-256/大小/schema。它只复制数据库状态，不打包 objects/work、原始路径文件或外部服务。

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/evidence" maintenance restore --checkpoint "[CHECKPOINT_ID]"
```

恢复先校验清单/对象哈希/SQLite schema 与完整性，检查无活动租约，再建立恢复前 snapshot，返回 rollback_to 供撤销本次恢复。预算不足、对象丢失、较新 schema 或 unresolved leases 都应停止；不降低校验绕过错误。

重要边界：

1. 只回滚数据库；保留对象字节，旧数据库可能不再登记之后生成的对象。这些未登记字节默认保留，不代表数据损坏已自动修复。
2. 不回滚外部源文件、候选文件、目标副作用、宿主配置或环境；源路径内容若已变，旧 verdict 不自动恢复当前有效。
3. 必须离线；当前函数的检查不是跨进程热恢复协议，没有强制阻止所有外部写者的保证。
4. 检查点位于同一工作区，不能防工作区丢失/盘损。需独立完整备份，恢复时对象与 marker 也要存在。
5. 现版本 schema=1，没有通用跨 schema 自动迁移。快照/回退不是未来格式兼容承诺。

## 6. 导出、导入与完整迁移

为什么：可移植证据包适合有限 case 审阅，完整备份才保留整个工作区的恢复上下文。

### 6.1 有限 case 的证据交换

保存 `export.json`：

```json
{"case_id":"[CASE_ID]"}
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/evidence" call export --input "C:/[请求目录]/export.json" > "C:/[工作目录]/case-export.json"
```

该单命令将 stdout 保存为 JSON。返回恰有 payload 与 sha256，可在新工作区作为 import 输入；不要先重新格式化 payload 再以不兼容方式重算身份。导出不是全文脱敏工具：虽然 source.path 被清空，源内容/自填合同/证据仍可能有私密数据。分享前逐项审查。

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/imported-evidence" init
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/imported-evidence" call import --input "C:/[工作目录]/case-export.json"
```

导入校验摘要、对象大小/哈希、引用和单 case 边界；保留记录身份，冲突需新工作区。导入信任为 imported-untrusted、效果重置 read，verdict 过期、source 不带执行路径。要再执行，明确选择本地可信文件重新登记并审查合同/规格，重新验证，不自动继承执行许可。

CLI 输入上限 4 MiB，MCP 帧上限 1 MiB；Base64 会膨胀体积。大 export 即使生成成功也未必能从 CLI 导入。底层导入也有记录/材料/引用/容量界限。超限时保留原工作区完整备份；当前没有流式大包传输入口，不用删证据凑成“迁移通过”。复杂父子依赖、检查点、全局历史或未登记文件也不由单 case export 完整涵盖。

### 6.2 整个工作区离线备份/迁移

1. 停所有写者，记录包版本、schema、近期 report、来源文件版本和当前恢复点。检查无活动目标/租约。
2. 用系统文件管理器将**整个工作区**复制到独立备份目录，包含 marker、数据库、objects、checkpoints 及必要 work；如存在 SQLite sidecar 也一起保留。不要只复制 state.sqlite3。
3. 外部参考/候选源码、项目宿主配置及所有权回执另行私有备份。先验证备份副本可读、哈希/数量与容量符合预期，再处理原目录。
4. 在目的环境从同一可信包安装，指向复制的工作区运行 doctor 和只读 report/storage.usage。doctor 不作全库证据完整性证明。
5. 旧 source 仍可能绑定原机器路径；迁移并未重写这些路径。重新选择本地文件建立身份，审查新环境并重验，不能把旧 pass 当目的机器运行资格。
6. 宿主接线的绝对 Python/workspace 路径另按 hosts 的 receipt-backed 重装流程更新；不要盲目复制开发者路径。保留原备份直到新的有限工作流和维护验证完成。

当前没有一条命令完成整机迁移与全内容证明；以上是操作步骤，不是已经完成的新机器测试。

## 7. 升级、重装、回退和卸载

为什么：先有可恢复的数据和旧包，再替换程序。安装成功不证明旧项目仍兼容。

### 升级

先离线完整备份并创建数据库检查点，保存旧 wheel 和校验值，阅读新包兼容说明。下文新版本/旧版本文件名是实际取得文件的占位，不表示已发布。

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m pip install --no-index --no-deps --upgrade "C:/[安装包目录]/[新版本wheel].whl"
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor --workspace "C:/[工作目录]/evidence" doctor
```

再用新目录运行 demo、检查旧项目 report/freshness，必要时重验。没有受测 migration 时，不让新包改唯一工作副本。0.1.0 拒绝写入不兼容 schema，不承诺未来格式自动降级。

### 同版本重装

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m pip install --no-index --no-deps --force-reinstall "C:/[安装包目录]/traceanchor-0.1.0-py3-none-any.whl"
```

仅重装包，不重建数据库。解释器路径变化时，项目接线按 hosts 的 receipt-backed 重装，默认先预览，再显式 apply；用户修改冲突时保持用户字节。

### 回退

停所有写者、备份当前状态，用兼容版本离线 restore 到升级前检查点，或把升级前完整备份复制到另一个新目录，再安装保留的旧包。

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m pip install --no-index --no-deps --force-reinstall "C:/[安装包目录]/[已保留旧版本wheel].whl"
```

程序回退与数据库回退分别核对。仅安装旧 wheel 不撤销数据库变更。无兼容恢复器时，用原版本加升级前完整备份，不强改 user_version；来源、环境与验收仍需重新检查。

### 卸载

若安装过项目局部宿主接线，先在旧解释器仍可用时预览卸载，再显式 apply：

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor host uninstall --host claude --project "C:/[宿主项目目录]"
```

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m traceanchor host uninstall --host claude --project "C:/[宿主项目目录]" --apply
```

Codex 将 --host 值改为 codex。helper 仅处理合法回执且未被外部更改的 owned 配置；冲突先人工对比，不删回执接管。

```bash
"C:/[工具目录]/traceanchor-env/Scripts/python.exe" -m pip uninstall -y traceanchor
```

pip 卸载默认保留环境外工作区、用户项目和 L1。程序卸载不等于缓存/长期证据删除；不附带递归删除工作区命令。专用虚拟环境确认不再使用后可由用户单独管理，先确保其中没有业务资产。

## 8. 中断和故障恢复检查表

- write-error/disk-budget：保留已有 L1、run 和未知材料，检查系统剩余空间与 usage，先 preview 合格 L3；不要重复启动同一大采集。
- gc interrupted：保存 gc ID/results/pending，重新预览；已退休对象可能仍有字节，默认不擅自删除孤儿。
- cleanup unknown / active lease：核对记录的 gate/target 身份和真实资源，不凭旧 PID 终止无关进程，不把 reconcile 当清理成功。
- checkpoint integrity/schema 错误：保留原件和错误，用兼容包及独立备份恢复；不编辑摘要或 schema 来“修复”。
- 数据库损坏：不重新 init 覆盖原工作区；先完整备份损坏现场，选择兼容恢复路径。
- 配置 prepared/lock：按 hosts 故障章节确认写者与原字节；不自动破锁。

这些步骤不是已经验证所有故障的成绩；最终 pass/fail/skip/not-run 由资格记录分别列出。
