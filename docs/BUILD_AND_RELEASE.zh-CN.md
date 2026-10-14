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

以上均是**无需商业游戏文件的实际构建/编译检查**，并不等于 Xcode 完整 target 链接成功或真机运行通过。[查看已通过的 Apple Silicon 验证](https://github.com/ForceMind/Game2Mobile/actions/runs/38612203914)。

原项目的 iOS 主 App 使用 26.0 部署目标，但下载扩展此前设为 26.4。已在 Swift 类型检查确认 26.0 编译目标可行后将扩展统一为 26.0。**iOS 26.0 实机上的 Apple-hosted 资源下载行为仍需单独验证**；M3/免费账号构建会按原脚本移除托管资源扩展。

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
