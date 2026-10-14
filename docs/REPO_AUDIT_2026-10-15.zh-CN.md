# Game2Mobile 源码审查与发布准备（2026-10-15）

> 本文是针对 `ForceMind/Game2Mobile` 的源码级审查记录。不能将 GitHub Actions 的 Linux 静态测试通过，等同于 Apple 平台编译通过或真机运行通过。

## 1. 核实范围与结论

- 核实分支：`main`，审查起点 `8b1c51248084266e8ce3487d6bd1e215a36e2cc4`。
- 原始上传包 `d2r-mobile-main.zip`：1,024 个文件，ZIP 完整性检测无错误；上游基线 commit `685d3ddef8bf75768fd4c51228566f2e8d2a5182`，Git 树 `59ab9da0b9726a699d7e45a855ea4cf5c0ee00a2`。
- 前次给出的更名版离线 ZIP：原 1,024 个文件全部保留，额外 2 个文件、修改 32 个文件，第三方源码内容未改；**不是**远端 main 的逐字节归档：前者 1,026 个文件，远端审查起点为 1,027 个文件，仓库上的脚本和 CI 文件与离线包不同。以 GitHub `main` 为权威。
- 完整性结论：原项目受版本约束的代码模块和构建脚本均已迁入；无证据表明从原 ZIP 丢失了某个受版本管理的源文件。但无法证明整个产品已可构建、可部署或可运行。
- 许可证：原 MIT 文件与 `dm/third_party` 许可证保留。商业游戏源文件和资源不得加入公开仓库。

## 2. 实际技术架构

1. `dm/tools/patch_nso.py`：离线改写 Switch ARM64 NSO 模块 `main`、`sdk`、`subsdk0`，针对 `x18`、线程寄存器、`svc`、系统计数器等进行补丁/门表生成。
2. `dm/host/loader.c`、`main.c`、`hle*.c`：装载、重定位、初始化 `nnMain` 并提供 Horizon 的本机 HLE 服务；网络模式不在范围内。
3. `dm/gfx/nvn/hle_nvn.c`、`nvn_mtl.m`：NVN 指令层到 Apple Metal 的转换；`dm/gfx/tools/dmsh_xlate` 与第三方 Ryujinx 着色器编译组件。
4. `dm/ios/Sources` 和 `dm/host/front_mac.m`：触摸、控制器、画面、资源管理与 macOS 前端。
5. `dm/verify`、`dm/{host,gfx,ios}/tests`：验证与回归，而不只是示例占位文件。
6. `dm/PRODUCT` 当前为 `3.3.94012-r44`；仅围绕特定版本游戏设计，**不属于支持任意游戏的一键移植产品**。

## 3. 无游戏文件时的实际检查（Linux）

| 检查 | 实测 |
|---|---|
| `dm_i18n.py --check` | PASS，348 条 |
| `scan_literals.py` | PASS |
| `native_write_scan.py --selftest` / `mode_scan.py` | PASS |
| `test_input_pair_check.py` | PASS，67 项 |
| `test_tbdr_budget.py` | PASS，5 项 |
| `test_l3reg.py` | PASS，2 项 |
| `t_touch_controls` | PASS，47/47 组，1599/1599 项 |
| `t_binding_freshness` | PASS，15/15 项 |
| `t_portal_sequence` | PASS，36/36 项 |
| `test_touch_receipt.py --source ...` | PASS |
| `test_native_binding_seam.py`、`test_native_art_capture.py`、`test_skill_aim_front.py` | BLOCKED：缺少构建时生成的 `Sources/dm_touch_native_art.c` |
| `t_native_binding` | BLOCKED：需要公开仓库不分发的真实映射夹具 `mapping.bin` / `bindings.bin` |
| 其他部分 C 单测 | Linux 的 Darwin/Mach 读内存实现缺席，或者 GCC `-pedantic` 与目标 Apple clang 编译行为不同；不应未经验证就判定原生 Apple 构建失败 |
| 完整 Xcode/macOS 编译与真机测试 | NOT RUN：缺少 Apple SDK、签名、合法游戏资源和真机 |

**重要：** `dm/ios/Sources/dm_touch_native_art.c` 是根据用户自己合法提供的游戏资源，由 `dm/ios/tools/native_art/generate.py` 生成且被 gitignore 排除，并非漏传的源码。类似的 `Gen/`、内嵌镜像、贴图及着色器亦需要构建时生成。

## 4. 已发现的发布风险

| 优先级 | 问题 | 解决条件 |
|---|---|---|
| P0 | 无 Game2Mobile 自己发布的 IPA、macOS App 或无游戏内容安装壳；无独立真机数据 | 在 Apple Silicon Mac 使用合法 ExeFS / RomFS 和 Xcode 完成构建、签名、冒烟，并记录版本/设备 |
| P0 | 当前 `AppIcon1024.png` 沿用商业游戏的 II MOBILE 图像，不是 Game2Mobile 独立视觉 | 以完全原创且不冒用游戏商标的 1024×1024 不透明新图替换、核对打包 |
| P1 | 部分 README / NO_XCODE 语句将上游 Releases 链接描述为本项目的 Game2Mobile 壳文件，顶部说明与正文互相冲突 | 改正文：明确上游产物不是本项目构建，不混用 shell 和 manifest；本项目发布壳前先本机构建 |
| P1 | 默认 `dm/ios/project.yml` iOS 26 / Metal 4，旧系统需 `DM_IOS_M3=1`；`OTHER_CFLAGS` 中 `-mcpu=apple-a18` 需要在声称支持的较旧硬件上验证 | 分档编译并记录 iOS 18/26、A16 和 A17 Pro+ 真机结果 |
| P1 | 当前 CI 未含真正的 Apple 构建，原先只做 Python 语法/配置检查 | 添加免资产 C/Python 单测；日后配置 macOS runner 与自有资源环境的构建任务 |
| P2 | 原有 README 的 44 台设备、帧率、功耗和 TestFlight 经历是原项目历史说明，非 Game2Mobile 新构建的结论 | 本项目独立实测后更新设备矩阵与数值 |

## 5. 首个可安装版本的正确路径

1. 在 **Apple Silicon Mac** 上先运行 `./setup.sh check`，准备 Xcode、xcodegen、dotnet、spirv-cross、Python 与合法游戏 `ExeFS`（`main/sdk/subsdk0`）和 `RomFS`。
2. 使用 `./setup.sh` 生成 NSO 改写产物、图形翻译链与着色器库；正式出包前逐项通过关键验证。
3. 准备 `dm/ios/local.env` 中的 `DM_TEAM_ID` 和 `DM_BUNDLE_ID`，执行 `cd dm/ios && ./run.sh build`。免费开发者账号按文档设置 `DM_FREE_ACCOUNT=1` 和设备 UDID。
4. iOS 18–25 使用 `DM_IOS_M3=1`；A16 及更老机型另外需要根据游戏文件制作的 ASTC 补充包。不要把“支持”理解为已由 Game2Mobile 独立验证。
5. 首个安装壳可通过 `dm/ios/tools/shell_build.sh` 在具备 Apple 构建工具和用户自有资源的 Mac 上生成；公开发布前核验包内**不含游戏二进制、贴图、着色器或资源**。
6. 先做可复现的 iOS 实机与 Apple Silicon macOS 冒烟，再考虑公开发布二进制、TestFlight 和更大范围的设备兼容声明。

## 6. 审查边界

当前没有用 Apple SDK 编译，也没有获取、上传、下载或操作任何商业游戏资产。对没有执行的集成路径保留未验证状态。
