# APK / DEX 专业静态方法包

本包回答“关键行为在哪个类/方法、哪些输入和状态通向它、有哪些尚未解析的边界”。成熟工具负责DEX语义反编译，TraceAnchor负责有界执行、目标身份和证据，不把ZIP条目或manifest字符串当成业务分析。

## 实际入口

Python适配器是 `traceanchor.apk_adapter.analyze(target, directory, execute, *, java, jadx_jar, max_files=200)`。`directory`由调用方预先登记和持有；每次建立全新attempt，返回 `status/facts/artifacts/unknowns/limitations/tool/runs/coverage`。产物路径相对该目录。`execute(argv, input_bytes=b'', env=None)`承担进程、超时、取消、目录增长监测及清理，适配器不另开进程、不创建第二个Store。

- 实际入口使用 `java -cp <jadx.jar> jadx.cli.JadxCLI`。某些JADX all-JAR的Manifest默认入口是GUI；`java -jar`不等于CLI。
- 每次先运行 `--version`，再真实反编译。显式 `--config none`跳过个人配置；JADX_CONFIG_DIR、JADX_CACHE_DIR、JADX_TMP_DIR和Java的user.home/java.io.tmpdir均指向当前attempt。
- status=complete仅表示当前工具采集完整；qualification_level明确为static-decompiler-output; runtime-unobserved，业务行为仍未观察。
- 原始stdout/stderr和生成的Java代码分别保留哈希、相对路径。工具非零、超时、清理未知、缺产物、反编译诊断、超文件/字节限额分别留下缺口，不靠“finished”字符串晋级。
- 默认最多200文件、单文件4MiB、合计32MiB、10000事实；这是采集边界，工具写目录期间的增长治理属于执行owner，不宣称OS级磁盘隔离。

## 为什么按这个顺序分析

### 1. 身份和入口

先冻结完整APK哈希；用成熟AXML工具（例如aapt2 dump badging）获得包名、版本、入口组件和SDK。查每个classes*.dex及ABI，标明本次覆盖哪些DEX。二进制manifest中像包名的ASCII片段只是线索。当前JADX适配器本身不解析AXML、不安装APK。

### 2. 先定位拥有业务的代码，再读语义

从入口组件/方法、接口DTO、资源引用定位具体类；JADX导出Java用于理解控制逻辑。按完整类名、方法名及参数/返回类型区分重载。调用链要写出调用者、调用点、被调用者、输入条件及错误分支。适配器的java-call-hint只是反编译文本中的导航锚点，字符串引用、同名方法和动态分派不自动成为真实调用链。

### 3. 关键分支回到DEX核验

用Android Build-Tools的dexdump，或Apktool/baksmali生成的smali，检查关键invoke、if/分支、move-result、字段读写、异常及return。DEX方法身份是 `L包/类;->方法(参数描述符)返回描述符`；DEX code_item偏移、指令code-unit偏移和文件字节偏移分开标记。不要用反编译Java行号代替DEX地址。

参数寄存器位于方法寄存器区高端；实例方法含this，long/double占两个寄存器。invoke-static/direct/virtual/interface有不同解析边界；反射、接口实现集合、JNI和动态类加载是明确未知，不从可读Java直接推断已在设备运行。

Kotlin的协程Continuation、状态机label、lambda/桥接方法、空值检查和内联结果可能改变源码外观；JADX的空方法、WARN/ERROR或Method not decompiled应触发smali/DEX核对，不解释成原业务为空。

### 4. 分开声明静态与设备资格

Java/Kotlin -> native声明、System.loadLibrary、JNI静态导出/RegisterNatives分别定位；关键路径进入native时转到对应ABI的专业工具。动态DEX、Flutter/Dart AOT和Unity/IL2CPP应另列材料与工具缺口。静态路径只证明程序包含该控制逻辑；安装、启动、方法命中和业务成功分别评级。

本首版夹具不依赖设备；APK未签名，不包含运行或重包成功声明。若后续做修改，先有原版/零改动重包对照，再做align/sign/verify/install及功能检查；签名正确与业务正确分开。

## 可重复的自建专业切片

`examples/apk/`包含原创Java和manifest：

- ShippingActivity.onCreate -> ShipmentSession.requestQuote -> requireState -> ShippingRules.quote；随后confirm。
- 配送区域LOCAL/REMOTE、整数克数与分币报价、500克进位、加急附加费及REMOTE超5kg限制。
- DRAFT -> QUOTED -> CONFIRMED；报价失败不先推进状态；错误包括重量范围、未知区域、不可加急、状态错误、价款不符、订单号无效、确认后reset。

运行 `python -I -B tools/qualify_apk.py`，显式提供 `--java --javac --jadx-jar --d8-jar --aapt2 --android-jar --dexdump` 七个本机绝对路径。无需Gradle/网络/设备：javac编译原创源码，D8生成DEX，aapt2 link编译manifest，再合成APK。每次结果只写产品 `.validation/apk-<attempt>/`。

qualification.json保存工具版本命令/工具摘要、输入摘要、全部实际命令与原始输出、JADX反编译产物、关键调用点/状态和错误条件。独立dexdump输出同时核对关键invoke，记录完整描述符和字节码位置。参考源码暴露明确披露；这属于P02自建静态资格，不是P04盲重建效果。

## 来源与刻意差异

独立实现，不复制上游脚本：

- Reverse Skills 固定提交 `ce675096e6a2cd4789a76f9bd618feddc2b6f333`，`skills/apk-reverse/SKILL.md:212-265,315-338` 的Java/smali/native分流，`references/high-difficulty-android-playbook.md:5-24,38-72`的身份和未知。
- Seep固定提交 `1ea9399ccb4dd8db5849a5ff62d963bf4abbe35e`，`Tool/skill/apkseep/references/toolchain.md:29-40,182-198,219-230`的成熟DEX工具/独立读取器/反编译器边界，`recon.md:19-37,124-142`的真实manifest与业务所在层，`SKILL.md:250-300`的基线控制。
- 不继承全盘工具搜索、自动安装、个人配置读取、默认GUI/浮动npx、含stdout的失败当成功或全树重包修改。上游历史测量和“无壳”命名启发式不当作本方实证。

## 已知边界

JADX适配器返回的调用提示尚未解析完整重载/虚调用图；生产APK的DEX级全图、设备运行、重包重签和native解析是独立能力。当前自建链的DEX核对由资格脚本完成，不能外推到任意APK自动证明。

首次资格调试发现JAR默认GUI入口导致两次有限超时，第一次日志选用了用户LOCALAPPDATA缓存路径；实际创建文件范围未核查，不扫描或删除用户缓存。修正为显式CLI主类、跳过个人配置并项目内缓存目录后，保留原失败而非覆盖历史。
