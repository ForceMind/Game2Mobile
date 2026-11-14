# Game2Mobile 本机操作、诊断与验收接口

所有命令通过 `python3 scripts/g2mctl.py` 调用，普通响应为单行 JSON。没有 HTTP 服务、远程端口、自动安装、自动启动、凭据查询或上传。普通状态命令只读；构建必须显式指定 `--execute-local` 和工作区，导出必须显式指定目标路径。

## 1. 只读查询

```bash
python3 scripts/g2mctl.py capabilities
python3 scripts/g2mctl.py build-plan
python3 scripts/g2mctl.py status --log "/private/local/boot.txt"
python3 scripts/g2mctl.py next --log "/private/local/boot.txt"
python3 scripts/g2mctl.py diagnose --log "/private/local/boot.txt"
python3 scripts/g2mctl.py job-status --status-file "/private/local/run-xxx/m1-job-status.json"
python3 scripts/g2mctl.py status --log "/private/local/boot.txt" \
  --app "/private/local/DmIOS.app" --profile metal4 --require-clean
```

`status/next/diagnose` 可用 `--run-id` 选定 32 位小写十六进制运行标识；不指定日志时沿用 `$DM_ROOT/run/ios/out/boot.txt`，默认工作区为 `~/dm-work`。不同运行不会互相补足证据。`status --app` 和 `--profile` 必须成对提供，调用现有真实字节核验器，而不只检查清单名称。没有指定 App 时，身份状态是 `not_checked`。

日志和状态输入必须是普通文件；符号链接、管道、设备文件及超限输入被拒绝，管道不会使工具无限等待。状态文件版本为 `game2mobile.m1-job-status.v2`，仍读取已有 v1 文件。v2 增加 `cancelled` 终态，并检查日期和构建/签名/步骤标记的一致性。

`job-status` 只读取显式路径，不遍历私有证据目录。返回的是**最后保存的状态快照**，不是进程心跳；`job_liveness=not_checked`。关机或 `SIGKILL` 后留下的 `running` 不能解释为任务仍在运行，更不能解释为成功。

## 2. 显式执行本机构建

```bash
# 在具备合法匹配资源、Xcode 和本地签名的 Apple Silicon Mac 上执行。
python3 scripts/g2mctl.py build --execute-local \
  --workspace "$HOME/dm-work" --profile metal4 --stage all

# 单阶段检查；成功只表示这一阶段通过。
python3 scripts/g2mctl.py build --execute-local \
  --workspace "$HOME/dm-work" --profile m3 --stage preflight
```

调用的就是 `m1_local_pipeline.py`，没有第二套构建判断逻辑。只执行 `g2mctl.py build` 仍返回 `NOT_SUPPORTED`，不会悄悄开始构建。`capabilities` 中 `build=false` 表示不允许无授权的自动构建，`build-local-explicit=true` 表示支持上述显式模式。

同一 Git 公共元数据目录以独占文件锁串行构建，防止并行任务覆盖共享 `Gen` 和派生表头。每个阶段子进程拥有独立 POSIX 会话；失败、超时和取消时清理该会话，不搜索或终止无关进程。默认阶段超时为 7200 秒，可通过 `DM_M1_STAGE_TIMEOUT_SECONDS` 设置 1–86400 秒的有限值。Ctrl-C 和 SIGTERM 生成取消终态，退出码为 130；程序异常、损坏阶段报告不会保留为成功。SIGKILL/断电不可捕获，重跑必须建立全新的证据目录，不能沿用旧包。

这不是签名授权代理。用户在本机显式执行构建时，才通过原流程使用其已有的签名配置。工具不会自动安装或向公开仓库上传 App、日志或资源。

## 3. 诊断包：仅导出摘要

```bash
umask 077
python3 scripts/g2mctl.py bundle --log "/private/local/boot.txt" \
  --job-status-file "/private/local/run-xxx/m1-job-status.json" \
  --output "/private/local/diagnostics.zip"
python3 scripts/g2mctl.py inspect-bundle "/private/local/diagnostics.zip"
```

日志和状态至少选一个。输出父目录必须存在，目标必须在仓库之外，不覆盖旧文件。ZIP 以 0600 权限原子发布，仅包含 `manifest.json`、`summary.json`：运行 ID、分析结果、阶段状态、计数和 SHA-256。它不复制原始日志、输入路径、游戏文件、签名或任意自由文本错误信息。仍须由文件所有者审查后再分享。

`inspect-bundle` 检查条目白名单、大小、重复条目和摘要哈希，拒绝额外文件及路径穿越。输出 `bundle_integrity_verified=true` 只证明包内字节和清单自洽；**不证明来源真实、设备执行过或游戏可玩**。

## 4. 真机验收记录

在同一份干净源码、真实最终 App 和对应启动日志下生成模板：

```bash
umask 077
python3 scripts/g2mctl.py acceptance-template \
  --app "/private/local/DmIOS.app" --profile metal4 \
  --log "/private/local/boot.txt"
```

返回 JSON 的 `template` 字段可保存为私有 `acceptance.json`。工具先验证实际 App 模块、运行表和 shader 字节，模板据此绑定源码提交、构建指纹、游戏 Build ID、运行 ID 和原日志哈希。模板不预先勾选任何真机项目。

所有者填写设备型号、系统版本、声明的连续游玩秒数（至少 1800），以及主菜单、触控、手柄、图形、音频、退出后存档恢复、后台恢复七项人工观察。附件标签固定为 `frame/session_log/save_reload_log`，每项填写位于记录目录内的相对路径和 SHA-256。附件必须是普通文件，禁止符号链接、目录外路径或超限文件；图像容器要求 PNG/JPEG。原帧图像和完整日志保留本机，不进入诊断摘要包。

```bash
python3 scripts/g2mctl.py acceptance-check \
  --record "/private/local/acceptance.json" \
  --app "/private/local/DmIOS.app" --profile metal4 \
  --log "/private/local/boot.txt"
```

检查器再次核对**真实 App 字节**、明确选择的同次启动、原日志哈希、构建/系统版本和附件字节。缺失、失败、旧运行、旧 App 或少于 30 分钟的声明均不能形成完整记录。

即使返回 `ACCEPTANCE_RECORD_COMPLETE`，其范围也只是记录一致性。人工填写的勾选、时长、截图和日志不具备设备签名真实性；工具不识别截图是否正确、不测音频、不证明真实游玩。结果固定包含 `device_execution_verified_by_tool=false`、`authenticity=not_attested` 和 `playability=requires_manual_review`。不得据此自动关闭 M1 或发布可玩版。

## 5. 返回码与安全边界

顶层协议仍为 `game2mobile.operator.v1`。`0` 表示该命令范围内完成；`1` 表示尚未完成或明确失败；`2` 表示参数/证据异常；`3` 表示未授权或未支持操作；`130` 表示取消。`ok=true` 绝不统一代表可玩性。单阶段构建的成功与完整 `all` 构建分别返回 `M1_STAGE_PARTIAL` 和 `M1_STAGES_PASSED`。

旧的启动观察命令保留原有行为和退出码。模板/验收、归档完整性、阶段进度、App 身份与真机可玩性是不同结论。单测只使用合成日志、匿名 Mach-O、普通文本与无害子进程，不包含商业游戏资源。

## 6. 公开工具链体检（2026-11）

```bash
python3 scripts/g2mctl.py doctor
```

这是只读操作（`CAPABILITIES.doctor=true`）。只输出已知工具与环境状态枚举；检查源码清洁时禁用 Git 可选锁和 fsmonitor，子进程限时并丢弃工具路径/错误输出。返回 `LOCAL_TOOLCHAIN_READY`（退出 0）仅表示公开 M1 构建工具看起来已就绪，`LOCAL_TOOLCHAIN_INCOMPLETE`（退出 1）表示至少一项缺失、源码有改动或状态未知。**游戏资源、签名、真实设备一律 `not_checked`**，不会读取密钥或任何私有游戏字节。GUI 中的“检查构建环境”与此命令使用同一个协议。构建仍必须额外由所有者明确授权。
