# TraceAnchor 0.2.0｜修订3交付摘要

**FOUR-SOURCE-PRODUCT-R3：P01—P05、G01—G10已满足合同规定的首版范围。** 在0.1.x有效核心上增量完成；原版本、失败、原始研究材料及发布字节保留。

[源码与首次使用](../../README.md) · [0.2.0发行下载](https://github.com/gthubtom1/traceanchor/releases/tag/v0.2.0) · [逐门证据](gates.json) · [当前状态](status.json) · [发布/下载回执](../release-verification.json)

## 实际能办的事

| 场景 | 已执行的专业链与结果 | 可复现入口（源码产品根） |
|---|---|---|
| 原生报价/库存分析 P01 | GCC15.2构建；objdump2.45机器码和直接调用；GDB16.3真实回调、参数/栈确认remote分支及920分报价 | `tools/qualify_professional.py` |
| APK调用/条件分析 P02 | Java21/JADX1.5.6真实DEX反编译；onCreate→requestQuote→requireState→quote，DEX invoke描述符交叉核查 | `tools/qualify_apk.py --help`，显式选工具 |
| JS状态/请求分析 P03 | Node24.20/V8 inspector，6交互、4HTTP请求，真实函数位置/状态/调用栈/服务回执 | `tools/qualify_web.py` |
| 独立实现 P04 | 独立宿主工作者只获批准的专业材料；V1首轮通过；真实V2更新产生4组差异，修3常量后开发6/封存最终7组通过 | `tools/replay_reconstruction.py`，42次受管进程，pass/fail/pass |
| 正常开发与维护 P05 | 批量报价父功能委派有限子研究；V2改变使旧验收stale，增量研究后同一父代码字节复用并通过 | `tools/qualify_development.py --help` |

P04参考源码由集成者知道，未提供给独立实现者；材料暴露清单、封存身份和独立判分分开留存。共享文件系统是协作隔离；重放输入现已公开，不是新一轮盲模型成绩。旧计数器demo仅为工程测试。

## 验收与发布

- 当前本地 **200/200、0跳过**；[实现CI](https://github.com/gthubtom1/traceanchor/actions/runs/44211220636)及[主分支重复CI](https://github.com/gthubtom1/traceanchor/actions/runs/44211828679)均全绿。Windows3.11/3.12/3.13每组200通过；Linux156通过、44跳过，仅静态资格。
- 最终包 **52步**隔离安装/维护通过：4种专业方法、wheel/源码包、实际0.1.1升级、配套旧数据回退、卸载重装及资产保留。实际GitHub下载后，新同机venv的4种专业方法再通过；同机环境不是干净机器。
- 新上下文审核6个真实反例已修复并原样复验；原始流损坏阻断当前验收，目标stdout不再冒充断点，子任务受父效果限制。整工作区计量、实际增长取消、实物归档后清理、pin/引用/恢复保护和Windows长Java路径均有回归。
- 两次失败CI完整保留，原始确切原因未知；增加失败进程诊断，将终态输出测试的静默期限对齐已有总时限。总时限、清理和业务比较保留；没有删失败测试凑全绿。
- 发行标签：`b3f200b940f0f3f6bb61bf8c5b2c8134e97aaedb`。源码包/Git字节对应，重复构建一致；校验见[SHA256SUMS](../../SHA256SUMS)。冻结包中的发布前状态保留历史身份，后续回执不替换发行资产。

## 最短使用路径

从Release取得wheel并核对校验和；以下为Windows Git Bash，每块一条命令：

```bash
python -m venv traceanchor-env
```

```bash
./traceanchor-env/Scripts/python.exe -m pip install --no-index --no-deps "[DOWNLOADED_WHEEL]"
```

```bash
./traceanchor-env/Scripts/python.exe -m traceanchor doctor
```

随后向当前宿主提出具体问题并选择材料，或直接运行：

```bash
./traceanchor-env/Scripts/python.exe -m traceanchor --workspace "[NEW_WORKSPACE]" inspect "[SELECTED_PROGRAM]" --method native.disassemble --question "定位报价分支和库存检查" --allow-execute
```

[专业指南](../professional-guide.md) · [宿主接线](../hosts.md) · [空间/恢复/升级回退](../r3-maintenance.md) · [支持矩阵](../r3-support.md)

## 范围、维护与恢复

核心仅标准库；成熟工具按需明确选择，不捆绑JAR/SDK/研究仓库，不自动安装。未授予Android设备、浏览器DOM/扩展运行时、任意保护或全软件等价资格；增长轮询不是OS强制磁盘/网络沙箱。没有新增外部付费模型API或修改全局宿主/模型/凭据，宿主与子代理仍消耗现有额度。

G01身份、G02专业链、G03独立实现、G04开发复用、G05核心、G06存储、G07恢复协作、G08公共使用、G09维护谱系、G10审核发布均有独立证据；合同门无未满足项，范围外能力仍保留明确未知。

未来接手从[短恢复入口](RESUME.md)与[完整合同](CONTRACT-R3.md)开始；四方取舍/许可和双向映射见[谱系](../provenance/README.md)，静态复评入口为[UPSTREAM-REVIEW-PROMPT](../../UPSTREAM-REVIEW-PROMPT.md)。全部代理与文件claim在收尾时显式释放，私有原始证据留在研究根，不公开整份研究快照。
