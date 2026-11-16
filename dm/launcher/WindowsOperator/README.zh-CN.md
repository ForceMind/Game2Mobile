# Game2Mobile Operator — Windows 原生工程诊断版（首个可运行版本）

这是 **Windows 10/11 x64 原生 WinForms .NET 8 工具**，不是 Windows 版 D2R 游戏，也不是 iOS 构建器或远程 Mac 执行器。它可以离线检查从用户自己的 Apple Silicon Mac 转移过来的启动日志 `boot.txt`、M1 阶段快照 `m1-job-status.json`、以及 macOS 工程工具导出的摘要 ZIP。无需将私有游戏资产或签名提交到 GitHub，独立发布包为无资源工具。

## 本机开发、编译和运行

在 Windows 安装 .NET 8 SDK 后，从仓库根目录执行：

```powershell
$project = 'dm/launcher/WindowsOperator/App/Game2Mobile.Operator.Windows.csproj'
dotnet build $project -c Release
# 运行不需要 iOS SDK 或游戏资源
 dotnet run --project $project -c Release
# 资产无关的 Windows 原生测试
 dotnet run --project dm/launcher/WindowsOperator/Smoke/Game2Mobile.Operator.Smoke.csproj -c Release
```

GitHub Actions 的 `windows-2022` Runner 会执行相同的源代码编译与测试，并 `dotnet publish -r win-x64 --self-contained true -p:PublishSingleFile=true`，产出名为 `Game2Mobile-Operator-Windows-x64` 的 ZIP 和相应 SHA-256。**ZIP 包中的 exe 没有 Windows Authenticode 签名**；Windows SmartScreen 可能提示风险。这是可执行的技术预览，不是已签名的微软商店安装包。

## 功能、边界与操作说明

* **选择启动日志**：只读取用户明确选择的本地 UTF-8 `G2M_BOOT` 日志；限长、去重键、事件序列和同一次运行的宿主/客体入口/GPU/首次呈现约束检查。显示回调不证明像素正确，也不证明设备真实或游戏可玩。必要时仍以 Mac 原仓库 `boot_diagnostics.py` 为最终启动诊断。
* **选择 M1 状态**：支持当前 `game2mobile.m1-job-status.v2` 和旧 `v1`，拒绝不一致字段及假全量通过，显示阶段与记录状态，但不报告进程实时存活。
* **检查诊断 ZIP**：要求 ZIP **仅含** `manifest.json`、`summary.json` 两个文件，并检查 schema、未认证范围、解压上限、大小和 SHA-256；不提取档案、不显示原始私有数据，不认为 ZIP 完整性等于设备身份认证。
* **Windows 环境与能力**：明确提示可以离线查看证据，但 **Windows 本机不能调用 Xcode 生成/签名/安装 D2R iOS 游戏**。此工具没有网络侦听、SSH、云构建、游戏上传或隐式设备操作。
* **Mac 构建说明**：固定帮助文字，不含私人路径或外部 URL。
* **导出脱敏摘要**：将本次检查的枚举状态和可选合法 run ID 导出为 `game2mobile.windows-operator-summary.v1` JSON；目标已有文件则拒绝覆盖。分享前须人工审查，归档不证明可玩。

本程序目前不具备 Windows 上的构建队列、Mac 远程构建代理、Windows 编译 iOS、跨 App 重启任务恢复、自动设备安装、完整 GPU 帧录放和多款游戏适配包。这些不应以 UI 入口存在而视为已完成。原 M1 Issue #1 保持开放，直到合法 ExeFS/RomFS、完整签名、真实 iPhone 启动、触控/声音/存档和连续游玩等独立验收。

## 代码结构

| 目录 | 用途 |
|---|---|
| `Core` | 纯 .NET 8 只读校验库，无第三方 NuGet 依赖 |
| `App` | Windows WinForms 原生 UI，显式用户选文件，无脚本解释与远程执行 |
| `Smoke` | C# 合成输入回归，包括非重放首帧、假成功状态、篡改 ZIP 与重解析点 |
| `.github/workflows/windows-operator.yml` | Windows 真实编译、测试、无资源发布包及 SHA-256 工程证据 |

源代码采用仓库既有 MIT 许可，不引入第三方游戏二进制。Windows 解压版只包含本开源工程工具及其运行依赖，不包含游戏内容和签名凭据。
