# Game2Mobile · 启动诊断与构建身份

本手册用于回答两个问题：**当前 App 是否对应本次构建输入，以及本次启动实际观察到了哪一步。** 构建身份一致、宿主返回、首次 GPU 提交、首次上屏和游戏可玩是不同的验收结果。

> 当前状态：已实现结构化观测、只读分析和构建身份核验；本轮尚无真实游戏的真机运行结果。本文的日志片段、运行 ID 和结果示例均为合成示例，不是设备测试记录。完整私有构建与设备验收仍按 [M1 私有资源构建流程](M1_PRIVATE_BUILD.zh-CN.md) 执行。

## 1. 分析已经取得的日志

在仓库根目录运行；分析器仅依赖 Python 标准库，不运行游戏，不连接设备，不改写输入日志：

```bash
# 常规 run.sh 拉回的 boot 日志默认位于此处。
# 如果本机 local.env 使用其他 DM_ROOT，请换成实际日志路径。
python3 scripts/boot_diagnostics.py \
  "${DM_ROOT:-$HOME/dm-work}/run/ios/out/boot.txt"

# 输出机器可读 JSON。
python3 scripts/boot_diagnostics.py \
  "${DM_ROOT:-$HOME/dm-work}/run/ios/out/boot.txt" --json

# 显式选择某次启动。此 ID 仅为合成示例，请替换为实际记录中的值。
python3 scripts/boot_diagnostics.py \
  "${DM_ROOT:-$HOME/dm-work}/run/ios/out/boot.txt" \
  --run-id 0123456789abcdef0123456789abcdef --json
```

默认选择日志中**最后新出现的 `run_id`**。已出现的旧运行即使稍后才写出回调，也不会让默认选择退回旧运行。指定 `--run-id` 时，只分析该运行；找不到指定 ID 会明确失败。各运行的事件始终分开，不会用旧运行的首帧补齐新运行。

通过 `dm/ios/run.sh <mode>` 启动时，脚本生成的本次启动回执会传入 App；原生 logger 使用合法的 `DM_RUN_RECEIPT` 作为 `run_id`。没有合法回执时，logger 生成进程级关联 ID。它用于关联日志，不是设备号、账号标识或可信签名。

### 保留历史证据

现有普通日志、`RUN_RECEIPT`、`DONE`、失败行和性能采样信息继续保留；新增 `G2M_BOOT` 行提供补充观测。分析器不删除或改写这些内容。旧版本日志没有结构化记录时，结果为“未知”，不推断其成功或失败。

`run.sh` 会重新取得当前模式的本地输出，因此需要对比历史运行时，应在下一次启动前把原日志复制到仓库外的私有证据目录，按运行 ID、源码提交和构建配置分别保存。保留对应的构建身份清单和分析结果，不要把多个启动手工裁剪拼成一次启动。原始日志可能含本机路径、设备或签名信息，不要直接上传到公开 Issue；分享诊断摘要前也应检查内容。

## 2. `G2M_BOOT` 协议

每条记录独占一行，以 `G2M_BOOT ` 开头，后接 JSON。下面仅是**合成格式示例**：

```text
G2M_BOOT {"schema":1,"run_id":"0123456789abcdef0123456789abcdef","seq":1,"elapsed_ms":0.000,"stage":"host_start","status":"begin","code":""}
```

| 字段 | 含义与约束 |
|---|---|
| `schema` | 当前版本为整数 `1`；未知版本不能作为有效证据 |
| `run_id` | 32 位小写十六进制，区分运行 |
| `seq` | 同一运行从 `1` 开始的连续正整数；跨线程分配受同一日志锁保护 |
| `elapsed_ms` | 相对本次 logger 初始化的单调时钟毫秒，非负、不回退；它表示记录时刻，不是进程墙钟时间或 GPU 执行时间 |
| `stage` | 下表中的固定阶段名 |
| `status` | `begin`、`ok` 或 `error`；`ok` 只说明对应观测点已经到达 |
| `code` | 空字符串或最多 63 字符的小写字母、数字、下划线稳定码；不放路径和自由文本 |
| `module` | 可选，1–15 个英文字母、数字或下划线，用于模块事件 |

logger 会隔离普通日志的未完成半行；分析器严格识别物理行首的标记，不从任意诊断文本中截取看似有效的 JSON。额外 JSON 字段不进入报告。

### 阶段的真实含义

| 阶段 | 记录位置与可以得出的结论 |
|---|---|
| `host_start` | `begin` 位于宿主预装载入口；`ok` 表示模块装载、重定位和相关宿主准备调用已完成。后台预取等异步工作可能仍在进行 |
| `module_load` | 按模块分两对记录：`code=layout` 包围布局读取，`code=image` 包围映像映射、动态信息解析和 gate 注册。可通过 `module` 区分 `main`、`sdk` 等模块；最后未完成项因此能指向当时实际处理的模块 |
| `relocation` | 聚合记录重定位及强制接管检查的开始和完成；不表示所有游戏服务语义都已实现 |
| `sdk_init` | 包围宿主调用的 SDK/libc 初始化序列；`ok` 表示这段初始化调用返回 |
| `module_init` | 包围各模块的 `DT_INIT` 调用；同时有聚合事件和带 `module` 的模块事件 |
| `guest_entry` | `begin` 标记准备转交控制给 `nnMain` 的位置；不证明已经进入主菜单或可操作场景。`ok` 且 `code=returned` 仅表示入口返回。正常持续运行的游戏可能始终没有对应 `ok` |
| `gpu_submit` | 记录首次真实 guest 命令缓冲提交调用完成；不等于 GPU 执行完成，也不保证执行没有错误 |
| `first_present` | 仅在真实 drawable 的 `addPresentedHandler` 回调给出 `presentedTime > 0` 时记录。请求呈现、排队、被丢弃的帧和缺少该回调的模拟器路径都不生成此证据 |
| `host_return` | 宿主前端运行调用返回后的生命周期记录；`ok/returned` 不等于游戏已出图或已完成游玩验收 |

`gpu_submit` 和 `first_present` 各只记录首次观察。`first_present.elapsed_ms` 是上屏回调被记录的时间，不能直接当成精确显示延迟。

**观测日志的先后不等于 GPU 因果执行顺序。** 提交线程和上屏回调可以并发，SDK 或模块初始化也可能触发图形工作。分析器在同一次运行的日志收集结束时核对宿主就绪、游戏入口、GPU 提交和上屏的必要证据集合，不要求所有图形事件严格排在初始化之后；序号和记录时间仍须自洽。

## 3. 结果与退出码

下面的 `0/1/2` 是 **`boot_diagnostics.py` 的退出码**，不要与 `run.sh` 的命令完成状态混用。

| 退出码 | 含义 | 后续动作 |
|---|---|---|
| `0` | 同一运行存在有效首帧证据，且该运行没有被记录的结构化错误 | 继续做真实画面、操作、音频、存档恢复和持续运行验收 |
| `1` | 尚无足够首帧证据，或本次运行报告了结构化错误 | 根据最后事件、未完成阶段和错误码定位；补充同次运行的日志或线程现场 |
| `2` | 参数、读取或日志证据异常，包括格式、schema、字段、序号、时间、依赖或资源上限问题 | 先修复采集或协议问题；这份记录不能作为有效首帧证明 |

错误优先于首帧成功。若首帧之后记录了 `error`，整体结果为 `runtime_error`、退出码为 `1`；JSON 仍保留已经观察到首帧的事实。若证据存在格式或顺序异常，整体退出码为 `2`。

人读输出包含运行 ID、GPU 提交、首帧、最后事件、最后未完成阶段、异常及下一步建议。JSON 的版本与核心字段如下；这是**节选结构，不是实际测试结果**：

```json
{
  "schema": "game2mobile.boot-diagnostics.v1",
  "scope": "startup-observation-only",
  "playability": "unverified",
  "result": "awaiting_first_present",
  "exit_code": 1,
  "first_present": {"observed": false, "valid": false, "elapsed_ms": null},
  "gpu_submit": {"observed": true, "elapsed_ms": 123.0}
}
```

完整输出还包括 `run_id`、`selection`、`observed_runs`、`last_stage`、`last_incomplete_stage`、`pending_stages`、`runtime_errors`、`issues`、`issue_count`、`timeline`、`timeline_truncated` 和 `next_action`。自动化应读取 `result`、`exit_code` 等稳定字段，不匹配中文说明文字。

常见结果的判断边界：

- `no_boot_evidence`：没有结构化记录，状态未知。普通 `DONE` 无法补足证据。
- `startup_incomplete`：尚未观察到游戏入口；最后 `begin` 提供排查起点，不等于确认卡死。
- `awaiting_gpu_submit`：已到入口观测点，尚无 GPU 提交记录。
- `awaiting_first_present`：有提交记录，尚无有效上屏记录。日志过早结束、回调缺失、等待或其他原因都可能造成缺证据，不能仅据此宣称黑屏根因。
- `host_returned_before_first_present`：宿主返回但没有首帧证据。
- `first_present_observed`：首帧证据成立，画面正确性、主菜单、操作和持续运行仍未验收。

结构化错误并未覆盖所有原生退出和崩溃路径。没有 `error` 行不能证明程序无错误；仍需结合保留的原生日志和设备现场。

## 4. 完整性与多线程边界

每次有效运行必须从 `host_start/begin`、`seq=1` 开始。缺行、重复序号、序号倒退、时间倒退、未知 schema、非法字段或重复 JSON 键都会使证据无效。模块的开始和完成可以交错，不以一个全局阶段栈推断死锁。

首帧需要同次运行最终收集到必要依赖。分析器不会从另一次运行借用缺失事件，也不会因为尾部截断而回退到旧运行的成功结果。可以归属某个运行的坏记录只影响该运行；无法归属的尾部坏记录会保守影响最新运行及最后活动运行。一个全新、从序号 `1` 开始的运行可与更早的无归属损坏记录分开。

默认限制为单行 16 KiB、输入 128 MiB、结构化候选记录 100,000 条和运行 ID 1,024 个。过长物理行按有限块读取；协议行超限或整体输入超限会报告异常。时间线最多展示 256 条，异常细节也有显示上限，计数和截断标记保留。不要通过删去异常行来“修好”验收结果，应重新取得完整证据。

这些检查验证日志内部一致性，不提供加密真实性证明。手工伪造一份完整协议日志并不能成为真机证据。

## 5. 构建身份：确认分析的是哪一份 App

[`scripts/build_identity.py`](../scripts/build_identity.py) 已接入 [`dm/ios/run.sh build`](../dm/ios/run.sh)。构建流程先对已暂存的资源执行 `create`，生成 `dm/ios/Gen/dm/build_identity.json`；清单随资源进入 App 的 `dm/build_identity.json`。Xcode 构建和签名验证后，流程对最终 App 执行 `verify`，不一致会停止构建成功报告。

清单版本为 `game2mobile.build-identity.v1`，包含：

| 内容 | 作用 |
|---|---|
| `source` | 源码提交与 `dirty` 状态，包含已修改文件和未被忽略的未跟踪文件 |
| `product`、`profile` | `dm/PRODUCT` 版本及 `metal4` / `m3` 配置 |
| `rewriter_sha256`、`shader_chain` | 重写器与 shader 翻译链身份 |
| `modules` | `main/sdk` 的游戏 build ID、映像长度与摘要，以及最终嵌入 section 的预期长度和摘要 |
| `runtime_files` | 模块 fixups/gates/cuts、shader 映射、PSO 清单、C1 表，以及存在时的启动清单等摘要 |
| `shader_cache` | 当前链下缓存文件内容的汇总摘要与数量 |
| `fingerprint` | 上述清单内容的统一摘要，用于比对和记录 |

`create` 核对模块生成完成标记与重写器身份、模块布局、游戏 build ID、暂存表与输入一致性，并将 shader 表绑定到当前源码。`verify` 重新读取最终 `DmIOS` Mach-O，核对 `main/sdk` 的嵌入 section 长度与实际字节摘要，并按 x0、W、x1 的逻辑顺序重新计算完整映像摘要、核对原长度和末页零填充；同时核对 App 内运行表及 shader 缓存的实际字节。只存在文件名、旧缓存目录或一份旧清单不足以通过核验。shader 摘要仅排除 Xcode 复制时会删除的 Finder `.DS_Store` 元数据，其他缓存文件及可选变体仍纳入核对。

通常由 `run.sh build` 自动调用即可。下列命令仅说明接口；路径必须替换为同一次真实构建的实际目录：

```bash
# create 写入暂存区；不会替你构建、链接、签名或安装 App。
python3 scripts/build_identity.py create --profile metal4 \
  --modules /private/current-module-product \
  --stage dm/ios/Gen

# verify 读取最终 App 和当前源码；M1 要求 --require-clean。
python3 scripts/build_identity.py verify --profile metal4 \
  --app /private/current-build/DmIOS.app --require-clean
```

旧接口构建使用 `--profile m3`，需要与实际构建配置一致。`create` 和 `verify` 的成功结果是 JSON；它们的退出码规则独立于启动日志分析器。

普通开发构建可以记录 `dirty=true`，**M1 验证要求干净源码**。干净状态包含已修改文件和未被忽略的未跟踪文件，因为 Xcode 也会编译 `Sources` 中新增的源码；被 Git 忽略的私有资源和正常生成物不纳入该源码状态。它不是所有私有输入的完整清单，也不为脏工作区提供精确源码快照。不要把修改过但尚未确认版本的构建当作某个干净提交的验收结果。M1 的独立证据目录、资源生成、签名与干净源码流程详见 [M1 手册](M1_PRIVATE_BUILD.zh-CN.md)。

构建身份清单不包含原始游戏字节、本机绝对路径、设备 ID 或签名身份。它用于版本与字节一致性核对，不是签名认证、完整 RomFS 清单、游戏逻辑等价证明或真机可玩性证明。`DM_GEN_ONLY=1` 只生成暂存资源和清单，不能替代最终 App 的 `verify`。

## 6. 一次验收需要保留什么

把同次运行的日志和 `run_id`，与对应 App 的身份清单、源码提交、构建配置及设备测试记录一起保存在私有证据目录。当前日志协议不会自动证明某个 `run_id` 对应哪份身份清单；需要沿用同次构建、签名、安装和启动的证据链，不能靠相同文件名推断。

构建身份核验、有效首帧与完整游戏验收分别记录。进入主菜单、实际操作、画面与音频、存档恢复和持续运行需要各自的真实观察。参见 [M1 私有资源构建流程](M1_PRIVATE_BUILD.zh-CN.md)、[构建与发布验收清单](BUILD_AND_RELEASE.zh-CN.md) 和 [S2Arm 借鉴实施计划](S2ARM_INTEGRATION_PLAN.zh-CN.md)。
