# Host-worker record (path-redacted)

Original SHA256: f90882c5189d048fb14b3be9f72b3454f022a8a7c52affff9416b80f29743689

This is the implementation worker record, not an independent oracle. Coordinator judgments and now-public replay are separate.

# native-parcel V2 增量维护

Owner: candidate-r3
Claim: claim_a300925005d0434ab9fc99b3436d5042

## 具体差异与修正

协调者报告V1真实判分通过、旧候选对V2有4组差异。公开反馈只披露normal、remote两组；另两组输入和任何隐藏/封存期望均未读取。

新版disassembly定点证据：

- 第311行、0x140001458：重量比较常量0x3a98=15000，随后有符号jg进入错误分支。candidate.py 上限由20000改15000。
- 第332行、0x14000149d：add eax,0x113=275。基础费由250改275。
- 第336行、0x1400014ab：zone==2分支加0xdc=220。remote附加费由180改220。
- 加499后除500的指令、每档75分、优先件300+20*n保持不变；reserve_parcels、dispatch_command、main相关逻辑也未见改动。

公开normal报价325→350，差25对应基础费变化；remote优先501g报价920→985，差65=基础差25+remote差40。新版GDB轨迹reserve 3、quote 501 1、state依次输出库存9/3、报价985且zone2、库存9/3，与规则一致。

仅修改candidate.py三个数值常量。当前n=(grams+499)//500，重量1..15000，cents=275+75*n+(zone==2?220:0)+(priority==1?300+20*n:0)。解析、预留状态、输出结构和退出逻辑未修改，也没有版本自动识别或用例特判。

## 实际测试

先用新证据编写测试并实际运行未修改的V1候选：5个测试方法，退出1，6个失败断言。观察normal/remote和公开反馈normal/remote分别失败，另有新重量上限及有效报价域失败；两组公开输入被两个来源覆盖，不算4组独立用例。

修改三个常量并扩展回归后：11个测试方法全部通过，退出0。覆盖3组V2观察的逐字节stdout/stderr/exit、2组公开差异、GDB序列、60000种有效报价、15001..20000克的20000种区域/优先级组合拒绝、15000/15001边界、2000次库存转换、解析默认参数、NUL、环境精确匹配、大小写、长行和EOF。

旧notes.md、selftest.py原样保留，未删除或修改其断言。它们记录V1历史，旧价格及重量断言只适用V1；不声称旧套件对当前V2通过。当前使用selftest_v2.py。

```text
python -I -B [PRODUCT]/assessments/native-parcel/candidate/selftest_v2.py [PRODUCT]/assessments/native-parcel/packet-v2/observations.json [PRODUCT]/assessments/native-parcel/packet-v2/version-update-feedback.json
```

自测不等于双边判分。本轮没有参考程序运行权限，也没有运行参考程序。无需额外观察即可交付本次三处更新。scanf格式串/整数溢出/CRT极端输入的V1未知项仍保留，未借助新隐藏数据作推断。

## 本轮确切读取清单

新增任务资料只读取以下五份：

- [PRODUCT]/assessments/native-parcel/packet-v2/TASK.md
- [PRODUCT]/assessments/native-parcel/packet-v2/disassembly.txt
- [PRODUCT]/assessments/native-parcel/packet-v2/runtime-trace.txt
- [PRODUCT]/assessments/native-parcel/packet-v2/observations.json
- [PRODUCT]/assessments/native-parcel/packet-v2/version-update-feedback.json

disassembly仅Grep四个函数头并Read第302–561行；未整份回读旧巨量汇编。旧V1四份资料已在旧notes.md列明，本轮未回读。

自身目录内，本轮Read/执行/导入读取：

- [PRODUCT]/assessments/native-parcel/candidate/candidate.py
- [PRODUCT]/assessments/native-parcel/candidate/selftest_v2.py

本notes_v2.md仅写入未回读。协调器tools/claims.py仅按授权命令执行，未阅读其源码；自动导入由协调器处理。未读取reference源码/binary、private、评估或封存夹具、比较器、主代理文件、其他项目data；未联网、未派生、未提交。隔离为协作纪律，不声称OS强制隔离。
