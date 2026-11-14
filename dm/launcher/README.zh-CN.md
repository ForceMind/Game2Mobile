# Game2Mobile Operator · macOS 本机图形工程工具（S2-08 第一阶段）

这是独立、可编译的 **SwiftUI macOS 工程操作器**，不是 D2R 游戏客户端，也不是通用模拟器或已验收的游戏启动器。它使用原有 `scripts/g2mctl.py` 和 `m1_local_pipeline.py`，不另写一套构建器，不在后台自动安装、同步或搜索游戏数据。

## 构建

在安装 Xcode/命令行工具和 Python 3 的 Apple Silicon Mac 上，从仓库根目录执行：

```bash
swift test --package-path dm/launcher/MacOperator
bash dm/launcher/build_mac_operator.sh
open dm/launcher/MacOperator/out/Game2MobileOperator.app
```

`build_mac_operator.sh` 用 Swift Package 构建并生成本机可用、**临时 ad-hoc 签名**的 `.app`。不会访问 Apple Developer 凭据，不产生真实游戏 App、iPhone IPA 或打包第三方游戏资源。输出位于忽略跟踪的 `dm/launcher/MacOperator/out/`；没有在 CI 中证明双击打开 GUI 后的用户交互，CI 验证的是编译、测试、bundle 和签名结构。

## 使用与授权范围

1. 点击 **选择源码仓库** 指向包含 `scripts/g2mctl.py` 与 `scripts/m1_local_pipeline.py` 的真实 Game2Mobile Git 工作树（不能选择独立 App 包）。
2. **查看能力**、**查看阶段计划**只读；点击 **选择启动日志**、**选择 M1 阶段记录**后可查询*明确指定*的本机文件。不会枚举全部私有路径，不显示文件原始内容，也不会直接绘制含私有数据的诊断 JSON。
3. 若需要构建，在 **选择私有工作区** 中选择仓库外的 `$HOME/dm-work`，确定 `metal4 / m3` 与 `preflight / prepare / headers / verify / build / all`。点击 **确认并运行**后，系统再次弹出明确授权确认；只有确认后才以进程参数数组启动 `g2mctl.py build --execute-local ...`。默认阶段是 `preflight`，不是完整构建。
4. **请求取消**向本机 Python 构建进程发送 SIGTERM；已安装的构建器负责当前阶段的子进程组清理和取消快照。收到取消结果以前不能将状态认定为成功。普通关闭窗口不会丢失运行中的构建控制器；重新打开窗口仍可请求取消。若使用者强制退出整个 GUI、结束其进程或关机，操作器本身不保证构建器已经停止；本机必须按 M1 手册核对执行和快照。

操作器从固定已知本机路径查找 Python 3（`/opt/homebrew/bin/python3`、`/usr/local/bin/python3`、`/usr/bin/python3`），通过 `Foundation.Process` **直接执行程序和参数数组**，不用 shell 拼接；显式把 `/opt/homebrew/bin`、`/usr/local/bin` 等构建工具目录置于原有 `PATH` 前面，避免 Finder 启动时找不到 `xcodegen`、`spirv-cross`，并过滤可能导致当前目录搜索的空 PATH 项。stdout 限长并只解码 `game2mobile.operator.v1` 白名单字段，stderr 不会在 UI 回显；命令、运行标识、退出码必须与请求匹配。没有 HTTP 服务、远程控制、日志/资源上传、自动安装、自动启动游戏或读写签名凭据功能。用户需在本机检查私有的详细日志。

**关键区分**：

- `preflight` 通过 ≠ `all` 构建通过；完整阶段通过 ≠ 签名安装通过。
- `first_present_observed` ≠ 画面正确；UI 返回 `ok` ≠ 游戏可玩。
- 所有界面与 CLI 测试只使用非游戏的无资源数据；未执行设备真实运行、音频、触摸、存档或 30 分钟游玩。

## 测试和继续集成

纯协议/命令行为位于 `MacOperator/Tests/OperatorCoreTests`，macOS CI 在 15 和 26 两套 Apple Silicon Runner 执行 `swift build`、`swift test` 和 `build_mac_operator.sh`。后续要实现统一构建任务持久化、可恢复的跨 UI 会话取消、GUI 级别可用性/无障碍测试和真正的游戏 App 安装，需要另行开发及签名/实体设备验收。详见 [S2Arm 整合计划](../../docs/S2ARM_INTEGRATION_PLAN.zh-CN.md)。

## 只读构建环境检查（新增）

在源码根目录运行 `python3 scripts/g2mctl.py doctor`，或在 GUI 选择仓库后点击 **检查构建环境**。它只检查 Apple Silicon 平台、公开工具（Python、Git、Make、XcodeGen、SPIRV-Cross、.NET）、Git 源码是否干净，以及 Xcode、iPhoneOS SDK、Metal 编译器是否能被本机找到。工具使用固定参数和有限超时，不运行 `setup.sh`、不修改源码或资产、不读取任何游戏数据和密钥。不会查询钥匙串签名身份或设备。

结果只有 `ready / missing / blocked / unknown / unsupported / not_checked` 等枚举值，不包含源码私有路径或工具诊断原文。`LOCAL_TOOLCHAIN_READY` **只表示公开工具条件已满足**，不代表游戏文件正确、签名有效、已完成 92/92 编译或真机可玩；对应的游戏资源、签名与设备永远显示“未检查”。若提示源码未清洁，先在本机使用 Git 检查，再由使用者处理，不会自动修改或清理工作区。

## 本地磁盘映像（未公证，不是游戏安装包）

Apple Silicon Mac 上可执行：

```bash
bash dm/launcher/package_mac_operator.sh
cd dm/launcher/MacOperator/out
shasum -a 256 -c Game2Mobile-Operator-local.dmg.sha256
```

生成 `Game2Mobile-Operator-local.dmg`（只包含 SwiftUI 工程操作器）及 SHA-256 校验文件。此 DMG 只采用本地 ad-hoc 应用签名，**没有 Apple Developer 签名或 Apple 公证**；Gatekeeper 可能阻止直接打开。它不会绕过系统安全机制，不建议将未经公证的构建宣传为普通用户免警告安装包。若同名磁盘映像已经存在，脚本会拒绝覆盖；需由所有者检查并自行处理。两套 Apple Silicon CI 只上传**无商业游戏资源**的工程工具 DMG，且自动化构建成功并不等于 Finder 安装/启动体验已人工验收。
