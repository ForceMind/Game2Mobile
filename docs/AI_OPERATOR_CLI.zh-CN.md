# Game2Mobile 只读 AI 操作入口（S2-09 第一阶段）

本页介绍与现有启动诊断、构建身份核验共用真实判断逻辑的**本机只读 JSON CLI**。代码位于 [scripts/g2mctl.py](../scripts/g2mctl.py)，不需要私有游戏资源即可询问当前日志状态。它并不是启动器、后台 Agent、HTTP 监听器或已经实现的 AI 自主构建服务。

## 使用

在仓库根目录运行：

```bash
python3 scripts/g2mctl.py capabilities
python3 scripts/g2mctl.py status --log "/private/local/boot.txt"
python3 scripts/g2mctl.py next --log "/private/local/boot.txt" --run-id 0123456789abcdef0123456789abcdef
python3 scripts/g2mctl.py diagnose --log "/private/local/boot.txt"
# 只有显式指定真实 App 与目标配置，才开始严格验证内嵌游戏/着色器字节：
python3 scripts/g2mctl.py status --app "/private/local/DmIOS.app" --profile metal4 --require-clean
```

没有 `--log` 时使用 `$DM_ROOT/run/ios/out/boot.txt`，如未设置 `DM_ROOT` 则使用 `~/dm-work/run/ios/out/boot.txt`。状态、诊断和下一步都只读取指定日志；`--run-id` 始终传给现有诊断器，不能混合不同启动的证据。缺失的日志返回错误码，不会推断游戏正在运行。命令不会隐式构建、安装、启动或访问网络。

仅 `status` 接受 `--app`、`--profile {metal4,m3}` 和 `--require-clean`。`--app` 与 `--profile` 必须同时提供。它调用 [build_identity.py](../scripts/build_identity.py) 的真实 `verify_identity`，核对**最终 App 内嵌的模块、运行表和 shader 字节**，而不仅检查清单本身。未指定时 `identity.status=not_checked`；指定后核验失败时为 `invalid`，不能推断任意其他 App 通过。

## 协议与边界

每条响应是单行 JSON，顶层固定使用 `schema: game2mobile.operator.v1`、`command`、`code`、`ok`、`exit_code`、`scope: local-read-only`。成功的 `capabilities` 返回当前支持的操作；`status` 具有 `observation`、`identity` 和固定的 `playability: unverified`；`next` 返回一次启动对应的 `next_action`；`diagnose` 包含现有完整启动分析报告（仍为本地、脱敏后才能分享）。输出不包含所传日志/App 路径，也不回显底层文件读错时可能包含私有路径的异常。

退出码与 `boot_diagnostics.py` 对齐：`0` 表示当次启动首帧观测证据有效、无结构化错误（或 `capabilities` 查询成功），**绝不代表游戏可玩**；`1` 表示启动证据不足或运行错误；`2` 表示输入/证据异常或显式 App 的身份校验失败；`3` 表示操作尚未实现。已实现的稳定错误码包含 `FIRST_PRESENT_OBSERVED`、`AWAITING_GPU_SUBMIT`、`AWAITING_FIRST_PRESENT`、`NO_BOOT_EVIDENCE`、`BOOT_EVIDENCE_INVALID`、`BUILD_IDENTITY_INVALID`、`BAD_ARGUMENT`、`NOT_SUPPORTED`。无需依赖任何中文提示文字分支。

`python3 scripts/g2mctl.py build` 会**明确失败**，返回 `NOT_SUPPORTED`，不会默默调用现有 M1 构建流程。当前无 HTTP 端点，因此没有打开的端口、令牌管理或远程写入能力。未来把 GUI、AI 与构建任务接到同一个执行器之前，需要实现原子 JobRequest/JobEvent 状态、取消/中断、权限边界和显式凭据/签名操作授权；这属于 S2-08/09 的后续阶段，**尚未交付**。

本接口的测试随仓库现有 `python3 -m unittest discover -s scripts/tests -v` 自动运行。它们只用合成测试记录，不能作为 D2R 真机首帧、帧率或存档验收凭据。更多数据定义见 [启动诊断手册](STARTUP_DIAGNOSTICS.zh-CN.md)、[S2Arm 整合计划](S2ARM_INTEGRATION_PLAN.zh-CN.md)。
