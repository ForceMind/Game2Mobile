# Game2Mobile 构建、验收与首版发布清单

> 状态：**源码维护中，尚未独立产出 Game2Mobile 的可安装 Release**。本清单不涉及分发任何商业游戏文件。原项目历史测试数据不视作本项目的新验证结果。

## 1. 代码层验证（Linux / macOS 均可执行）

```bash
python3 scripts/release_checks.py source
python3 -m unittest discover -s scripts/tests -v
python3 dm/ios/tools/dm_i18n.py --check
```

GitHub Actions 还会运行不需要游戏资源的 Python/C 单测。绿色检查只证明离线静态与单元测试通过，不证明能在 iPhone、iPad、Mac 上运行。

### Apple Silicon 原生检查：已实际运行

本项目使用 [`apple-native.yml`](../.github/workflows/apple-native.yml) 在 GitHub 提供的 **`macos-26` ARM64 Runner** 上运行：

- Xcode / iOS 与 macOS SDK 检查；Apple Silicon 原生 C 控制输入、宿主状态及图形辅助代码编译/单测；
- **生产图形主文件** `dm/gfx/nvn/nvn_mtl.m` 在 macOS 26 Metal 4、macOS 15 M3、iOS 26 Metal 4、iOS 18 M3 四种目标上进行 `clang -fsyntax-only` 检查；
- iOS UIKit 前端 `front_ios.m` 与启动模块 `main.m` 的 ARM64 iOS SDK 交叉语法检查；
- Swift 下载扩展 `RomfsDownloader.swift` 按 iOS 26.0 目标进行 Swift 6 类型检查；
- 使用 macOS 原生 `sips` + `iconutil` 生成并校验 `Game2Mobile.icns`；
- `scripts/tests/test_project_variants.py` 覆盖正式/免费账号 × Metal 4/M3 四种工程生成组合。

以上均是**无需商业游戏文件的实际构建/编译检查**，并不等于 Xcode 完整 target 链接成功或真机运行通过。

**新增 Apple 目标码验证：** [`fc5bb87e` 的双系统 CI](https://github.com/ForceMind/Game2Mobile/actions/runs/38613049859) 在 macOS 26 Runner 上成功生成并核对 **10 份实际 ARM64 Mach-O `.o`**，包含图形 Metal4/M3 的 macOS/iOS 四种目标、iOS `front_ios.m`/`main.m`，以及装载器 `dm/host/loader.c` 与宿主入口 `dm/host/main.c` 的 iOS/macOS 目标。另在**真实 macOS 15 ARM64 Runner**上编译旧图形 M3 目标码并运行无资产的输入/GFX 测试。这些结论来自工作流实际执行与架构检查，而不是 README 的历史设备性能声明。[查看已通过的 Apple Silicon 验证](https://github.com/ForceMind/Game2Mobile/actions/runs/38612203914)。

原项目的 iOS 主 App 使用 26.0 部署目标，但下载扩展此前设为 26.4。已在 Swift 类型检查确认 26.0 编译目标可行后将扩展统一为 26.0。**iOS 26.0 实机上的 Apple-hosted 资源下载行为仍需单独验证**；M3/免费账号构建会按原脚本移除托管资源扩展。

### XcodeGen 四档工程生成：已实测通过

在 Apple Silicon macOS 26 Runner 上使用 **XcodeGen 2.46.0 / Xcode 26.6**，不仅执行 YAML 变体脚本，还执行真实的 `xcodegen generate`、`xcodebuild -list -json` 和 `xcodebuild -showBuildSettings -json`，确认四套 Xcode 工程均成功生成、由 Xcode 解析，部署版本、CPU 参数与下载扩展目标符合预期。

- 付费账号 / Metal 4（iOS 26）：包含 `RomfsDownloader`，部署目标 26.0
- 免费账号 / Metal 4（iOS 26）：无 `RomfsDownloader`
- 付费账号 / M3（iOS 18）：无 `RomfsDownloader`，CPU 为 apple-a14
- 免费账号 / M3（iOS 18）：无 `RomfsDownloader`，CPU 为 apple-a14

[真实 CI 验证](https://github.com/ForceMind/Game2Mobile/actions/runs/38667796078) · [验证脚本](../scripts/ci_xcodegen_profiles.py) · [原理与限制](XCODEGEN_CI.md)

**进一步实测：** [最新真实宿主源码 CI](https://github.com/ForceMind/Game2Mobile/actions/runs/38668287937) 已从 `dm/host/Makefile` 执行 `gen_build.py`，生成 **90 条真实源码符号链接及 `Gen/main/main.c`**，随后全部四档 Xcode 工程生成、Xcode 参数检查通过。为避免暴露用户资源，检查脚本只复制 Git 已跟踪的 `dm/` 源文件，游戏资源目录仍使用标注为 CI 的占位内容。

**注意：** 真实的是宿主源码路径和工程生成过程，不是商业游戏二进制、资产、着色器或已链接 App。M1 内部测试包仍未产出。

### 独立 iOS 构建诊断 App（不含游戏）

已在 [Apple Silicon CI](https://github.com/ForceMind/Game2Mobile/actions/runs/38736461658) 中使用真实 Xcode 完整编译、链接、封装 **iPhoneOS ARM64** 和 **iOS Simulator ARM64** 两套诊断 App（使用 Game2Mobile 原创图标）；包结构、Bundle ID、资源过滤均通过自动检查，并产出注明 **NON-PLAYABLE** 的临时 ZIP 和 JSON 报告。代码位于 [ci/ios-diagnostics](../ci/ios-diagnostics/README.md)。这套独立测试 App 只能验证 Apple App 构建/打包链，不链接实际游戏宿主。

模拟器实际安装运行仍然**未获通过**：在 [首次运行尝试](https://github.com/ForceMind/Game2Mobile/actions/runs/38736867676) 中，`simctl bootstatus` 通过，但 `simctl install` 超过 120 秒超时，因此没有成功启动或获取运行截图；这是当前 runner 的安装超时现象，尚未证明应用本身存在或不存在启动缺陷。后续将模拟器运行作为单独手动触发的限时任务，不阻断已验证的 App 二进制构建交付。

### 生产源码 ARM64 全面检查：两个系统均通过

2026-10-15 已使用 [真实 Apple Silicon 双系统严格 CI](https://github.com/ForceMind/Game2Mobile/actions/runs/38744154022) 完成 **91 个真实宿主编译单元** 的逐文件检查（按原 `dm/host/Makefile` 与 `gen_build.py` 产生的 90 条源码链接 + 单独入口）。Apple Clang 实际生成 Mach-O `.o` 并检查为 ARM64。

| 构建路径 | 生成 ARM64 对象 | 游戏派生表头缺失 | 其他编译错误 |
|---|---:|---:|---:|
| macOS 26 Apple Silicon / iOS 26 Metal 4 | **88 / 91** | 3 | **0** |
| macOS 15 Apple Silicon / iOS 18 Metal M3 | **88 / 91** | 3 | **0** |

两侧唯一阻塞的三个编译单元是 `host/diag.c`（`dm_hud_exp.h`）、`host/dm_bright.c`（`dm_bright_levels.inc`）和 `host/dm_vault_ui.c`（`dm_vault_tab.h`）。这三项由合法游戏 RomFS 数据生成，不属于漏传的源码；本项目不会为公开 CI 伪造真实游戏数据。

本结果说明 **两套平台路径合计 176 个真实源文件目标码编译成功，其他源文件编译错误清零**；**不表示**游戏 App 已完整链接、生成可安装包、已在模拟器运行或真机验证。详见[逐文件编译覆盖报告与复现说明](PRODUCTION_COMPILE_COVERAGE.md)。

### M1 真正游戏构建：已建立私有执行流程（未在公开 CI 中执行）

基于此前公开 CI 的 **88/91 ARM64 源码编译**和三项 RomFS 派生表头阻塞，现已提供 [`m1_local_pipeline.py`](../scripts/m1_local_pipeline.py)：

```bash
python3 scripts/m1_local_pipeline.py plan
# 只有在自己的 Apple Silicon Mac 已配置合法游戏文件和签名时：
python3 scripts/m1_local_pipeline.py all --profile metal4
```

流程在本地验证游戏版本和 Apple 工具链，从用户自己的 RomFS **重新生成** `dm_hud_exp.h`、`dm_bright_levels.inc`、`dm_vault_tab.h`，以真实文件进行严格 **91/91** ARM64 编译，然后调用原有 `DmIOS` 完整 App 构建并检查本地签名。游戏内容、私有日志和 App 不会上传至 GitHub。

**防止旧包误判：** 每轮使用新的 `DM_ROOT/m1-private-evidence/<commit>/<profile>/run-*/derived-data/`，清除 `DM_GEN_ONLY` 及其他旧产物路径覆盖项；本轮没有实际生成 App 就不能通过。日志在执行开始前设为 `0600`，单独执行某个阶段只记录 `partial`，不宣称整条构建链通过。

**当前尚未取得 91/91 私有验证成功或真实游戏 App 签名成功的运行记录。** 公开 CI 只确认本地操作脚本、边界校验、报告隐私保护和原有 88/91 编译路径。请阅读 [完整 M1 私有构建手册](M1_PRIVATE_BUILD.zh-CN.md)，勿将私有游戏文件上传到仓库。

## 2. Apple 构建机准备（由持有者在 Mac 上执行）

至少需要 Apple Silicon Mac、适合目标系统版本的 Xcode/Apple SDK、XcodeGen、.NET SDK、spirv-cross、Python，以及用户自己合法取得且**版本匹配**的《暗黑破坏神 II：狱火重生》Switch 版 `ExeFS/main`、`sdk`、`subsdk0` 与 `RomFS/data`。

```bash
./setup.sh check             # 检查机型、工具、磁盘、ExeFS 哈希、RomFS 和签名配置
./setup.sh                   # 处理游戏程序、编译翻译器与派生资源
cd dm/ios
cp local.env.example local.env
# 将 DM_TEAM_ID / DM_BUNDLE_ID 设成个人实际 Apple 开发配置
./run.sh build               # 先生成设备可安装构建
```

不要把 `dm/ios/local.env`、签名身份、合法游戏资源、编译出的游戏派生素材加入 Git。

## 3. 首版验收矩阵

| 检查 | 要求 | 当前状态 |
|---|---|---|
| 完整文件树 | 无丢失的源文件、第三方许可证 | 已核实 |
| 品牌图标 | 独立 RGB iOS 图标和 macOS `.icns` 链路 | Apple Silicon CI 已转换验证；完整 App 尚未打包 |
| 源码 CI | i18n、Python、C 单测和发包门禁 | 已部署，持续回归 |
| iOS 编译 | 用固定版本游戏文件，在 Apple 工具链编译无错误 | **未验证** |
| 设备启动 | 真机启动到菜单并进入游戏 | **未验证** |
| 渲染 / 输入 / 音频 / 存档 | 至少一条功能路径完整通关 | **未验证** |
| macOS 编译 | `dm/tools/mac_app.sh` 生成、签名、启动 | **未验证** |
| 公开安装壳 | 禁止携带商业游戏二进制、贴图、着色器和衍生数据 | **未构建** |
| 公测发布 | 署名、依赖授权、设备分档、崩溃反馈 | **未发布** |

## 4. 发包安全验证

`dm/ios/tools/shell_build.sh` 仍保留原有的离线模块节检查、衍生资源移除与内容扫描，并增加独立的 ZIP/Info.plist/文件路径结构校验：

```bash
# 仅在已经本机构建出没有游戏内容的 shell 之后：
python3 scripts/release_checks.py shell /path/to/Game2Mobile-shell.ipa

# macOS App 生成以后：
python3 scripts/release_checks.py macapp /path/to/Game2Mobile.app
```

**注意：** `release_checks.py shell` 是第二道自动化防线，不能独立证明不存在所有商业游戏内容，也不能代替合法资源来源核验、手工包检查和实际设备测试。

## 5. 版本门禁

- `M0`：源码与品牌整理完成；不发布二进制。
- `M1`：Apple Silicon Xcode 干净构建通过，产出内部测试包；提供构建日志与产物哈希。
- `M2`：至少一台 iOS 26 真机的安装、启动、画面、输入、音频、存档冒烟通过，并记录机型与系统版本。
- `M3`：验证旧系统适配和 macOS、修复明显回归后，考虑公开无游戏内容的安装壳。

发 Release 时需明确 `dm/PRODUCT` 版本、源代码提交 SHA、目标 Apple OS/硬件架构、签名方式、是否包含衍生资产、游戏文件自备方式。**没有达到 M1/M2 时不要发布“可玩版”或宣称 TestFlight 已验证。**
