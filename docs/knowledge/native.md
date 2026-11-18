# 原生程序：从机器码问题到运行时反证

适用：明确选择的自建/可信 PE/ELF 单文件。静态入口 `professional.run(method=native.disassemble)`；动态入口 `native.trace`。工具从PATH或任务tools映射显式选择，不安装、不执行研究快照或旧项目。

## 问题 → 方法 → 证据

先问一个具体问题，例如“报价的重量进位与库存检查在哪里，当前部署实际走哪个区域费率？”冻结目标完整SHA256、编译/工具版本与输入。objdump必须产生真实函数指令、地址及调用关系；头信息与字符串只用于定位。

- `objdump -d -M intel --no-show-raw-insn` 返回函数VA和直接call目标。定位分支中的比较、跳转、参数搬运与返回值，再沿调用者确认路径；间接call、虚表、尾调用、异常边、内联不是已解析的直接边。
- Windows x64整数参数常见RCX/RDX/R8/R9，返回值RAX；不要套用Linux SysV的RDI/RSI参数顺序。栈局部槽位需结合函数序言和指令宽度；32位有符号比较与无符号比较不同。反汇编出现乘法魔数/移位可能是常量除法优化，必须验证算术及边界，不从常量外观猜业务。
- PE中的VA、RVA和文件偏移分开：RVA=VA−首选映像基址；映射到节的文件偏移需节VirtualAddress/PointerToRawData。ASLR后的运行地址又依赖实际加载基址。符号偏移不是文件偏移；本适配器返回的instruction_address是工具报告VA，不擅自换算成文件地址。
- 符号名和调试信息帮助定位，但它们不是原始源码正确性的保证。去符号、加壳、动态加载、自修改及其他ABI须另取材料，当前不作全覆盖承诺。

## 静态不足时的实际实验

对“这次输入的实际参数/状态是什么”调用GDB。适配器只接收有限符号断点、简单变量名、测试参数与TRACEANCHOR测试环境，不提供任意GDB求值/调用函数的快捷通道。脚本禁用个人init，记录命中、info args、bt及选定变量；所有进程由同一owner/Job管理，输出、时间与受管目录增长有界。

实验前记录静态假设、观测值会支持/推翻什么。例：`quote_parcel`中存在zone条件只证明程序含该分支；GDB在运行时命中且参数zone=2、grams=501、priority=1才证明该输入走了远区/加急路径。函数返回的报价和后续state响应再核业务效果。未命中、调试失败或清理不完整保持partial/blocked，工具exit0不是成功证据。

断点会改变时序，因此它是单独的观测条件/派生环境；不得把调试状态推广到未观测输入。对有并发、反调试或外部服务的目标，这个方法包不是自动解答器。

## 产品用法

普通用户向宿主提出问题并选择程序即可；宿主读取此包、登记任务效果并调用professional.run。CLI也有不要求手写case JSON的入口：`inspect <program> --method native.disassemble --question <question> --allow-execute`。`--tools`可指向项目局部可信工具映射；GDB的有限场景通过`--options`传入。只读case不会因知识包或工具可见而取得execute效果。

`tools/qualify_professional.py`是可重复工具资格，不是P04盲重建成绩：GCC构建原创包裹报价/预留样本，objdump核调用，GDB核环境分支、状态与错误，全部原始输出和失败记录在独立attempt保留。P04另用独立宿主候选与预先冻结的隐藏输入判分。

## 四源吸收与刻意差异

独立提炼，不复制上游脚本或提示词。Reverse Skills固定提交ce675096e6a2cd4789a76f9bd618feddc2b6f333的`skills/reverse-engineering/tools.md:53-91,535-545`及`references/re-agent-workflow.md:127-169`提供专业工具/证据路线；REA的Ghidra目标快照、provider真实采集与unknown原则落实为本产品的输入快照、工具原始输出与未解析边界；Seep的PE控制变量/写后核验落实为命中和结果双核；Craft的差异回流用于后续独立候选修正，而不是把工具成功或Ready当行为等价。

objdump/GDB/GCC是用户已有的可选工具；本产品不分发其二进制。GNU工具许可证和已测版本单独列于依赖与资格记录。其他工具、GUI自动化和任意复杂保护须独立资格。
