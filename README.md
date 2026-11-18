# TraceAnchor 0.2.0

把原生程序、APK 或本地 JS 材料变成**实际专业工具证据、可解释的接口合同，以及可检查的独立实现**。当前智能体宿主负责推理和编写候选；产品负责工具执行、来源、预算、比较、差异、恢复与清理。不是只记录任务的管理底座，也不内置第二个模型循环。

[源码](https://github.com/gthubtom1/traceanchor) · [发行下载](https://github.com/gthubtom1/traceanchor/releases) · [修订3完整合同](docs/goal/CONTRACT-R3.md) · [当前门状态](docs/goal/status.json)

## 可以拿它做什么

| 你的问题 | 实际工作链 | 主要输出 |
|---|---|---|
| “这个原生程序如何报价，实际走了哪个分支？” | GNU objdump机器码/调用边 → GDB实际断点回调、参数和调用栈 | 函数/指令位置、运行条件、原始证据和未知 |
| “这个APK的关键Java调用和输入错误在哪里？” | JADX实际DEX反编译 → Java语义位置；自建资格另用dexdump交叉核验 | 类/方法、条件/错误/未解析区域，不宣称已在设备运行 |
| “这个JS交互为何改变状态并发出这条请求？” | Node/V8 inspector → 实际交互/状态 → loopback HTTP请求ID/调用栈/服务回执 | 有因果绑定的执行位置、请求响应及状态合同 |
| “按这些观察独立实现并维护接口” | 冻结规格 → 宿主独立候选 → 双侧运行 → 差异 → 修正/回归 | 分维裁决、保留历史、隐藏边界和资料暴露记录 |
| “开发项目只需要研究一个旧组件” | 有限子研究 → 合同/夹具回流 → 父功能实现 → 参考版本变化后增量更新 | 可复用结论、相关旧验证失效，不重启整套重建工程 |

真实资格与支持边界见 [专业使用指南](docs/professional-guide.md)、[支持矩阵](docs/r3-support.md)。Node观察不是浏览器DOM/扩展运行时，APK静态链不是设备安装/插桩。高级保护、所有平台和任意软件等价不是本产品承诺。

## 最短使用路径

Python3.11+。核心运行时仅标准库；专业功能依赖用户明确选择的已有工具，不捆绑、不自动下载它们。先从Release下载并核对SHA256SUMS，或clone源码。以下为Bash/Git Bash命令，每块一条；Windows路径可用正斜杠并加引号。

```bash
git clone https://github.com/gthubtom1/traceanchor.git
```

```bash
python -m venv traceanchor-env
```

Windows隔离环境安装已审阅本地源码；源码目录应是包含pyproject.toml的产品根：

```bash
./traceanchor-env/Scripts/python.exe -m pip install --no-index --no-deps --no-build-isolation ./traceanchor
```

Linux/macOS将解释器换成环境内bin/python，不由此取得未测动态资格。也可用同一pip命令安装实际下载的本地wheel。

```bash
./traceanchor-env/Scripts/python.exe -m traceanchor doctor
```

doctor只诊断入口和工具可发现性，不启动专业工具或安装大组件，更不是一次真实分析通过。

### 交给你熟悉的宿主

例如：“分析我选择的程序里报价分支与库存限制；若静态证据不足，按当前任务边界做有限运行时实验。给出具体位置、证据与未知。”

宿主读取适用的`knowledge.get`领域包，使用统一CLI/MCP的`case.create/source.add/professional.run`；你无需手写整套底层JSON。接线、项目局部预览/应用与卸载见[宿主文档](docs/hosts.md)。当前宿主与独立候选工作者确实进行了本次分析/实现/差异修正试验；这不冒充所有Claude/Codex版本的自动接入资格。

### 不用宿主也能直接分析

```bash
./traceanchor-env/Scripts/python.exe -m traceanchor --workspace "[NEW_WORKSPACE]" inspect "[SELECTED_PROGRAM]" --method native.disassemble --question "定位报价与库存检查的函数调用" --allow-execute
```

`inspect`自动建立有限任务、登记所选原件并通过受管工具执行；不会把观察成功变成独立重建通过。用`--tools "[TOOLS_JSON]"`显式选择可信工具，用`--options "[SCENARIO_JSON]"`选择有限断点/JS交互。APK选`apk.analyze`；本地JS选`web.observe`并明确`--allow-network`。完整实例见[指南](docs/professional-guide.md)。

## 可重放的真实例子

以下从源码产品根运行（不是四份研究快照），输出放新建`.validation`独立目录，保留原始命令、输出、工具版本、输入身份及失败恢复；不接真实外部目标。

```bash
python -I -B tools/qualify_professional.py
```

这会实际编译原创原生样本、反汇编并用GDB观察运行参数/状态。APK需显式Java/JADX/D8/aapt2/android.jar路径，参数见[APK方法包](docs/knowledge/apk.md)，不运行或安装APK。

```bash
python -I -B tools/qualify_web.py
```

```bash
python -I -B tools/replay_reconstruction.py
```

最后一条重放真实宿主独立写出的两版候选：V1参考/V1候选通过 → V2参考/V1候选真实失败 → 修正候选回归通过，共42次受管执行。输入在原评估时封存，现在公开用于复现；重放不是一次新的盲模型评测。原参考源码由集成者知道，独立候选工作者只获专业输出/公开观察；共享文件系统隔离是协作纪律，不是OS强保密。

父开发例子见`tools/qualify_development.py --help`：批量订单工具仅委派旧接口研究，取回合同/证据后继续开发；版本变化使旧验证stale，未变父源码字节一致复用，更新相关证据并回归。

旧`demo`计数器保留为工程测试，**不计作修订3专业产品或陌生任务重建成绩**。

## 证据、空间与维护

L1关键资产自动清理跳过；L2工作材料须验收/归档/无恢复依赖；L3须终态、清理完成且无引用/lease/pin。恢复材料不是一个metadata备注：真实字节先归档才可解除保护。`workspace.usage`分别显示CAS、SQLite/WAL、work、检查点、导出、日志、缓存和未知文件；超额停止新工作，专业及普通采集监测工作目录增长，保留残留与恢复点。

先预览再有界清理；未知文件、链接和共享材料保守保留。轮询增长可能超量，**不是OS磁盘/网络沙箱**。离线数据库回退不撤销外部副作用。[完整维护与迁移](docs/r3-maintenance.md)。

## 状态与来源

本版按FOUR-SOURCE-PRODUCT-R3的P01—P05/G01—G10验收；旧A表和0.1.1有限核心成功只保留历史。通过/失败/跳过/未执行/blocked/stale分开；最终源码、包、CI、Release及下载逐项见资格和发布附件，候选状态不提前宣称远程成功。

四方知识/工具适配/迭代价值与本地实现、验证、刻意差异见[谱系](docs/provenance/README.md)。无四仓整包、上游代码/提示词/品牌素材或运行依赖复制；成熟工具是可替换的外部组件，许可证另核。未来复评交接见[UPSTREAM-REVIEW-PROMPT.md](UPSTREAM-REVIEW-PROMPT.md)。产品许可证MIT；不承诺持续追版或效果优于上游。
