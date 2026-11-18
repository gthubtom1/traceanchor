# Host-worker record (path-redacted)

Original SHA256: 16d1343b92802bf4ad9694dd13455278fc645ea2def6967ea733642471822c93

This is the implementation worker record, not an independent oracle. Coordinator judgments and now-public replay are separate.

# native-parcel 独立候选记录

Owner: candidate-r3
Claim: claim_5648349c096e4a8fa6963abad533f443

## 证据到规则

- quote_parcel 0x140001452–0x14000146d：有符号重量限制 1..20000，priority 仅 0/1，否则 weight-or-priority。
- 0x140001474–0x140001494：重量加 499 后使用魔数 0x10624dd3 除法，在有效范围得出档数 n=(grams+499)//500。
- 0x140001497–0x1400014ca：cents=250+75*n；zone=2 加180；priority=1 再加300+20*n。普通250g=325、remote优先501g=920，与观察一致。
- reserve_parcels 0x1400014dd–0x140001515：count>0 且 count<=available 才修改状态，否则 stock。成功 available 减 count，reserved 加 count。
- dispatch_command 0x140001617–0x14000167a：cancel 要求 count>0 且 count<=reserved，否则 reservation；成功返还库存。失败均保持状态。
- observations normal/errors 和 GDB 初始值：新进程 available=12，reserved=0。
- dispatch 的 strcmp 链结合观察：命令大小写敏感；未知命令 operation。state 忽略参数，quote 不改库存。
- main 0x140001767–0x14000179c 及 remote 观察：启动时环境变量 TRACEANCHOR_PARCEL_ZONE 值精确等于 remote 则 zone=2，否则 zone=0。
- main 0x1400017a8–0x140001809：每轮 a、b 先清零；sscanf 只要有至少一次赋值就分派。缺参沿用本轮默认零，扫描失败不产生单独格式错误。
- main 0x14000180e–0x140001832：fgets 容量128，每轮最多127个文本字节；长行可以分派多次。main 忽略 dispatch 返回码，EOF 返回0。
- JSON 字段、错误名、CRLF 和空 stderr：来自 observations.json。逐条输出并保留进程内状态，无持久化写入。

## 明确的推断和未知项

1. packet 没有 rdata 字节，sscanf 格式串没有直接显示。根据32字节 verb 栈区，选择常见的 %31s %d %d；宽度31及十进制而非自动进制仍属推断。按连续转换实现数字前缀、缺参默认零、尾随内容忽略、首个数字转换失败后停止后续转换。
2. 参数保存为32位有符号整数；超范围十进制暂按低32位回绕。超出 int 范围尤其超出64位的 UCRT 转换行为未直接观测，相关自测只验证实现假设。
3. 按目标 Windows CRT 文本模式实现 CRLF 折叠、Ctrl-Z EOF；NUL 结束本次 sscanf 可见内容，但 fgets 仍消费整块。CRT 极端输入行为没有原生直接观察。
4. 汇编显示原生 main 还有 argv[1] 文件输入分支；任务接口要求 stdin，本候选只实现 stdin，不扩展文件输入模式。
5. 有效领域规则证据充足，初稿可交付。若后续安排有限观察，优先确认 quote 0501 0、quote 0x1f5 1、超范围整数，以及127字节附近的行；不请求隐藏或最终测试。

## 自测结果

执行下述命令，21项测试全部通过。包括三组 packet 观察逐字节回归、GDB轨迹对应命令序列、全部80000种有效报价组合、2000次确定种子的库存状态转换、边界错误、缺参、数字前缀、状态重置、大小写、环境精确匹配、空输入和EOF、NUL及长行分块。

```text
python -I -B [PRODUCT]/assessments/native-parcel/candidate/selftest.py [PRODUCT]/assessments/native-parcel/packet/observations.json
```

自测不是双边判分；没有调用私有 oracle，没有执行参考 binary。

## 确切读取与执行清单

读取的任务资料只有以下四份，disassembly.txt 为实际 objdump 文本，并未沿其中路径访问文件：

- [PRODUCT]/assessments/native-parcel/packet/TASK.md
- [PRODUCT]/assessments/native-parcel/packet/disassembly.txt
- [PRODUCT]/assessments/native-parcel/packet/runtime-trace.txt
- [PRODUCT]/assessments/native-parcel/packet/observations.json

自己生成并由Python执行/导入读取的文件：

- [PRODUCT]/assessments/native-parcel/candidate/candidate.py
- [PRODUCT]/assessments/native-parcel/candidate/selftest.py

本 notes.md 为自己写入，未回读。初始 Glob 仅尝试列 candidate 目录，返回目录当时不存在。协调器 tools/claims.py 仅按授权命令执行，自动导入核心由协调器处理，未阅读其源码。reverse-workflow 工具返回薄入口说明；未继续读取其引用的 receipt、RULES、router，保持本任务材料范围。任务列表工具被宿主提示为子代理不可用后未重试。

未读取参考C源码、参考binary、private/判分脚本、其他 reports/tests/项目data或聊天历史；未联网、未派生额外代理、未commit/push。这里只记录实际读取和操作，不把协作边界描述为OS强制隔离。
