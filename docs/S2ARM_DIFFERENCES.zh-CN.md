# S2Arm 与 Game2Mobile 源码差分清单

记录日期：2026-11-09（America/Los_Angeles）。用途：决定逐项研究和采用范围，不是功能完成证明或整库合并清单。执行次序见 [整合计划](S2ARM_INTEGRATION_PLAN.zh-CN.md)。

## 1. 对照版本与证据范围

- Game2Mobile：`14af5aa48358063ccb38b5b6b6bb504a5cb7db95`。
- S2Arm：`cf1f19c5c9d80abf78b1296cb8d436a4deab3978`。
- 两者共同技术来源：`jhaizhou-ops/d2r-mobile`；Game2Mobile 导入源为 `685d3ddef8bf75768fd4c51228566f2e8d2a5182`。[本项目来源][g2-status]、[S2Arm 来源][s2-readme]。
- S2Arm 后续主线 `779bcf69c639c8680fabad6d0d97903720bbe8ab` 只作观察记录。以下源码结论不自动适用于该版本。
- 目前完成的是人工源码/文档对照，未完成两套运行时对同一份 D2R 原件的差分执行。候选收益均须以实际调用、反例或设备故障确认。

## 2. 实现映射与采用问题

| 领域 | Game2Mobile 已有路径与能力 | S2Arm 固定源码中观察到的实现 | 候选收益与风险 | 下一步证据 / 对应工作包 |
|---|---|---|---|---|
| ARM64 改写 | [patch_nso.py][g2-rw]：x18 线程槽、TLS、SVC、PC 相对、跳转表和独占窗口均已有 | [rewriter.c][s2-rw] / [说明][s2-rw-doc]：C 库与 CLI；到达定义/间接跳转分析、前后补丁区、远跳陷阱、缺口报告及旧产物清理 | 可比较边界覆盖与失败语义；换 C 不能单独证明正确或更快。默认开启的 acquire/release 补强会改变并发语义，需单变量验证 | 合成指令反例；真实 `main/sdk/subsdk0` 的改写点与完整产物对照；S2-04 |
| 模块加载 / ABI | [loader.c][g2-loader]、[gen_embed.py][g2-embed]：模块符号/重定位、Mach-O 嵌入、代码 RX / 数据 RW、线程槽初始化已有 | [loader.c][s2-loader]、[reloc_class.h][s2-reloc]：按类别处理重定位，TLS 类交游戏 SDK；16 KB 共页处理、签名前处理 NRO 后按摘要识别加载 | 可补具体布局/重定位缺口；不能把现有静态模块装载当作未实现。NRO 是否为 D2R 所需尚未证明 | 构造有效/无效模块布局，核目标 D2R 的实际重定位集合；Apple 与 iOS 布局对照；S2-04/12 |
| HLE / 系统服务 | [hle.c][g2-hle]、[hle_table.c][g2-hle-table]、`dm/host/hle_*.c`：目标游戏的系统与库接管 | [gate.c][s2-gate]、[services/README.md][s2-services]：原生线程/内存 SVC 与 NativeAOT C# 服务接入，未实现调用明确返回错误 | 有利于比较服务语义；替换整层会同时改变依赖、生命周期、线程与内存行为。服务更多不等于 D2R 初始化必然通过 | 先记录目标游戏实际调用/等待，再比较对应实现及返回值；S2-02/04 |
| NVN / Metal | [hle_nvn.c][g2-nvn]、[nvn_mtl.m][g2-metal]：真实命令录制/回放、PSO、贴图与 Metal 3/4 分支；[已知限制][g2-gfx]明确列出空实现 | [nvn_mtl.m][s2-metal]、[nvn_be.h][s2-backend]：直连路径按系统与 GPU family 选择 Metal 3/4，可强制 M3 对照 | 可逐接口研究参数绑定、同步与设备能力判断；巨大后端文件不适合整体覆盖。先查 D2R 实际调用，不能把所有新接口列为必需 | 实际调用与缺口表；同场景同设备 M3/M4 对照；S2-06 |
| GPU 资源一致性 | [nvn_dirty.h][g2-dirty] 及对应实现已有脏页接口；现有纹理上传/缓存路径需共同审查 | [nvn_dirty.h][s2-dirty]：映射代次、内存池更换与追踪失败后的保守判断 | 可比较失效边界，不能把脏页追踪整体算新增。错误缓存会表现为花屏或旧贴图 | 内存池销毁/替换、CPU 写入、保护失败反例及图形实测；S2-06 |
| 着色器 / 游戏配置 | [Program.cs][g2-xlate]、[shader_facts.tsv][g2-facts]、[dmsh_chain.py][g2-chain]：Maxwell→SPIR-V→MSL、事实表、链指纹和完整库检查已有 | [README.profile.md][s2-profile]：从静态信号生成带来源指纹的游戏配置，默认值与未知项分开；[pack/contracts][s2-contract]还记载首遇编译路径 | 可减少未来游戏手工配置；自动推断不等于正确覆盖，运行时补编也不能替代本项目 M1 的完整性要求 | D2R 每项配置的来源与差异；库缺失/反射不匹配反例；S2-03/11 |
| 启动 / 故障诊断 | [main.c][g2-main]、[crash.c][g2-crash]、[项目状态][g2-status]：已有启动计时、线程现场和运行回执 | [frame_replay.md][s2-frame]：私有帧录放、逐笔截断/跳过与顶点抓取；对应诊断资料支持按层定位 | 本轮补稳定的结构化阶段记录和同次运行分析；帧录放适合首帧之后的错图，不能解决所有首帧前等待 | 原生并发/一次性事件、混合旧局/截断日志反例；真实首帧与私有帧回放另验；S2-02/07 |
| 构建 / 启动器 | [m1_local_pipeline.py][g2-pipeline]、[product.sh][g2-product]：阶段执行、完整改写回执、干净源码和独立构建证据已有 | [pack/jobs/main.py][s2-jobs]、[pack/contracts/README.md][s2-contract]：共享任务层及 JobRequest / JobEvent / ArtifactManifest / Target 契约；新 target 入口仍在逐步接入 | 可把已存在的脚本状态统一给 UI；不能把契约文件存在当成完整多平台插件已完成 | 中断、取消、产物失配、错误码与下一步；所有前端复用同一判断；S2-03/08 |
| AI 控制 | 目前可由外部工具调用现有脚本，未在基线找到同等的统一启动器控制客户端 | [s2armctl.py][s2-ctl]：本机令牌控制口，状态、next、任务等待、错误、诊断等接口 | 适合机器读取真实任务状态；需要限定本机权限、版本兼容和错误恢复，不能让 CLI/UI 各自维护任务真相 | 先交只读命令，后接现有构建执行器；当前运行标识、稳定 JSON、失败退出码；S2-09 |
| 应用壳 / 多游戏 | [shell_build.sh][g2-shell]：已有无游戏内容的壳构建；本项目当前仍聚焦单款 | [pack/shell/README.md][s2-shell]、[APP_BUNDLE.md][s2-app]：按指定壳身份验证缓存、组装与签名阶段分离，支持游戏库方向 | 适合第二款游戏后复用；壳完整性不证明真实签名/安装，也不消除游戏代码与产物版本匹配问题 | 壳 ID、缓存破坏、组装失败及真实安装分别验收；S2-11/12 |

## 3. 三个不能混用的结论

### 3.1 当前运行路径与历史设计

研究基线的 [gfxmode.c][s2-gfxmode] 已明确只走直连；历史“双轨”设计与旧通用 GAL 文件不能当作当前可回退路径。判断 Metal 3 能力应读取当前直连实现及设备选择，不能引用旧 GAL 未完成标志代替整个项目状态。

### 3.2 短时运行、首帧与可玩

[S2Arm 普查规则][s2-census]的“一次成功”包含出包、进局、不崩和不卡死，默认测试窗口约 300 秒；帧率、能耗和完整流程另行验证。不能将该口径缩成纯编译，也不能将总体比例映射为 D2R 当前版本的长期稳定性。

本项目基线的 [生产编译报告][g2-compile]是无资源源码编译证据，明确未完成真实游戏完整链接与设备验收。新 `G2M_BOOT` 首帧事件只表示相应观察点出现，不能证明截图内容、操作、存档、持续稳定性。

### 3.3 有效证据与缺失身份

[S2Arm 能力卡规则][s2-cap]将支持、启用、验证分开。值得采用其判定原则；但其中缺少包摘要或平台的历史记录必须保留范围限定。Game2Mobile 需要从实际产物建立身份，未知值不作通配符，不能用最新源码身份补写旧包。

## 4. 拟采用清单的记录格式

每项进入实现前记录以下字段，允许同一 PR 包含紧密相关的多项：

| 字段 | 要求 |
|---|---|
| 来源 | 仓库、完整 SHA、文件、原许可；纯思想借鉴也写来源 |
| 现有行为 | Game2Mobile 对应实现与固定基线，说明已有覆盖 |
| 目标问题 | 可复现故障或具体缺口，未复现时明确标注 |
| 改动范围 | 涉及哪类指令/模块/接口、是否只适用于指定 Build ID |
| 验证 | 独立反例、Linux/Apple 编译结果、真实游戏与设备结果分别列出 |
| 回归 / 撤回 | 原路径如何对照、何时撤回；不能静默放宽既有验收 |
| 公开边界 | 哪些结果可提交，哪些游戏派生文件/完整日志仅留私有环境 |

本轮 S2-02/03 已基于现有项目接口实现诊断与核验工具，并通过无游戏资源测试；使用方式见 [启动诊断与构建身份核验](STARTUP_DIAGNOSTICS.zh-CN.md)。Apple CI 结果待确认，真实输入与设备尚未验证。上述映射仍以固定基线为准。

本轮未直接搬入 S2Arm 源码。后续直接移入时必须逐文件复核 [S2Arm NOTICE][s2-notice] 与 [第三方许可表][s2-licenses]，保留原声明；根目录 Apache-2.0 不代表所有上游文件采用同一许可，也不能被本项目原有 MIT 声明覆盖。

## 固定源码索引

[g2-status]: https://github.com/ForceMind/Game2Mobile/blob/14af5aa48358063ccb38b5b6b6bb504a5cb7db95/docs/PROJECT_STATUS.md
[g2-rw]: https://github.com/ForceMind/Game2Mobile/blob/14af5aa48358063ccb38b5b6b6bb504a5cb7db95/dm/tools/patch_nso.py
[g2-loader]: https://github.com/ForceMind/Game2Mobile/blob/14af5aa48358063ccb38b5b6b6bb504a5cb7db95/dm/host/loader.c
[g2-embed]: https://github.com/ForceMind/Game2Mobile/blob/14af5aa48358063ccb38b5b6b6bb504a5cb7db95/dm/ios/tools/gen_embed.py
[g2-hle]: https://github.com/ForceMind/Game2Mobile/blob/14af5aa48358063ccb38b5b6b6bb504a5cb7db95/dm/host/hle.c
[g2-hle-table]: https://github.com/ForceMind/Game2Mobile/blob/14af5aa48358063ccb38b5b6b6bb504a5cb7db95/dm/host/hle_table.c
[g2-nvn]: https://github.com/ForceMind/Game2Mobile/blob/14af5aa48358063ccb38b5b6b6bb504a5cb7db95/dm/gfx/nvn/hle_nvn.c
[g2-metal]: https://github.com/ForceMind/Game2Mobile/blob/14af5aa48358063ccb38b5b6b6bb504a5cb7db95/dm/gfx/nvn/nvn_mtl.m
[g2-gfx]: https://github.com/ForceMind/Game2Mobile/blob/14af5aa48358063ccb38b5b6b6bb504a5cb7db95/dm/gfx/README.zh-CN.md
[g2-dirty]: https://github.com/ForceMind/Game2Mobile/blob/14af5aa48358063ccb38b5b6b6bb504a5cb7db95/dm/gfx/nvn/nvn_dirty.h
[g2-xlate]: https://github.com/ForceMind/Game2Mobile/blob/14af5aa48358063ccb38b5b6b6bb504a5cb7db95/dm/gfx/tools/dmsh_xlate/Program.cs
[g2-facts]: https://github.com/ForceMind/Game2Mobile/blob/14af5aa48358063ccb38b5b6b6bb504a5cb7db95/dm/gfx/nvn/shader_facts.tsv
[g2-chain]: https://github.com/ForceMind/Game2Mobile/blob/14af5aa48358063ccb38b5b6b6bb504a5cb7db95/dm/gfx/tools/dmsh_chain.py
[g2-main]: https://github.com/ForceMind/Game2Mobile/blob/14af5aa48358063ccb38b5b6b6bb504a5cb7db95/dm/host/main.c
[g2-crash]: https://github.com/ForceMind/Game2Mobile/blob/14af5aa48358063ccb38b5b6b6bb504a5cb7db95/dm/host/crash.c
[g2-pipeline]: https://github.com/ForceMind/Game2Mobile/blob/14af5aa48358063ccb38b5b6b6bb504a5cb7db95/scripts/m1_local_pipeline.py
[g2-product]: https://github.com/ForceMind/Game2Mobile/blob/14af5aa48358063ccb38b5b6b6bb504a5cb7db95/dm/tools/product.sh
[g2-shell]: https://github.com/ForceMind/Game2Mobile/blob/14af5aa48358063ccb38b5b6b6bb504a5cb7db95/dm/ios/tools/shell_build.sh
[g2-compile]: https://github.com/ForceMind/Game2Mobile/blob/14af5aa48358063ccb38b5b6b6bb504a5cb7db95/docs/PRODUCTION_COMPILE_COVERAGE.md
[s2-readme]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/README.md
[s2-rw]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/runtime/rewriter/rewriter.c
[s2-rw-doc]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/runtime/rewriter/README.md
[s2-loader]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/runtime/src/loader.c
[s2-reloc]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/runtime/src/reloc_class.h
[s2-gate]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/runtime/src/gate.c
[s2-services]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/services/README.md
[s2-metal]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/graphics/nvn/gfx/nvn/nvn_mtl.m
[s2-backend]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/graphics/nvn/gfx/nvn/nvn_be.h
[s2-dirty]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/graphics/nvn/gfx/nvn/nvn_dirty.h
[s2-profile]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/graphics/nvn/tools/README.profile.md
[s2-contract]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/pack/contracts/README.md
[s2-frame]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/graphics/nvn/docs/frame_replay.md
[s2-jobs]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/pack/jobs/main.py
[s2-ctl]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/launchers/macos/s2armctl.py
[s2-shell]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/pack/shell/README.md
[s2-app]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/pack/APP_BUNDLE.md
[s2-gfxmode]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/runtime/src/gfxmode.c
[s2-census]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/tools/census/census.py
[s2-cap]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/docs/能力卡_数据口径.md
[s2-notice]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/NOTICE
[s2-licenses]: https://github.com/jhaizhou-ops/S2Arm/blob/cf1f19c5c9d80abf78b1296cb8d436a4deab3978/THIRD_PARTY_LICENSES.md
