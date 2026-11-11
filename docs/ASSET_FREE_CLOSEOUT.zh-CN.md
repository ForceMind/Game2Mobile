# Game2Mobile：无游戏资源工程交付与接续边界

日期：2026-11-10（America/Los_Angeles）。开发起点：`6e6c83730e1ec4fc4587a4e7e33b81fdb375094c`。实现与逐提交 CI 证据集中在 [PR #20](https://github.com/ForceMind/Game2Mobile/pull/20)。本记录不代替 M1 私有构建与设备验收。

## 本次实际实现

| 工作 | 代码与测试 | 验证边界 |
|---|---|---|
| Loader 边界 | `dm/host/loader_validate.h` 接入真实 `loader.c`；布局字段、缺项/重复、键页索引、MOD0、动态段终止、符号名和重定位表/目的地址、门参数范围 | 合成模块反例与 5,000 次变异，ASan/UBSan；没有真实 D2R 模块语义验收 |
| 未支持重定位 | 明确拒绝未知类型，不再按 ABS64 写入；不猜测忽略 TLS 类 | 遇到真实模块拒绝时保存错误码，按实际类型做最小补丁；不是新增通用重定位支持 |
| 内存保护失败 | 检查 `mprotect` 返回值；失败池持续保守判脏；解除保护失败不无限重试；溢出/空范围拒绝 | 注入失败及真实 macOS mprotect、原有并发测试；未核对 GPU 像素 |
| 构建过程 | 共用原 M1 执行器，独占仓库锁、有限超时、进程组清理、取消/异常终态、私有原子快照 | Linux/Darwin 无害子进程与隔离夹具；不会启动用户设备或取得资源 |
| AI 操作入口 | 只读状态/诊断/计划，显式本机构建，摘要包导出及检查 | CLI，不是图形启动器或远程 HTTP 控制服务 |
| 验收工具 | 真实 App 字节、同次日志哈希、构建/系统身份、声明时长、七项检查与附件哈希 | 记录完整性，不是图像质量识别或签名设备证明 |
| 可重现源代码 | CI 输出仅含已跟踪公共 Git 对象的 source.bundle、commit/tree 与 SHA-256 | 不包含 .git/config、local.env、忽略的资源、工作区日志、签名或游戏文件 |

新校验器为头文件，生产宿主编译单元仍是 92 个。公开无资源预期为 **89/92 + 3 个真实资源阻塞**，不是完整游戏链接。所有新的源代码与合成测试采用项目已有许可证；没有搬入 S2Arm 实现或商业资源。

## 直接可执行的开发验证

```bash
python3 -m unittest discover -s scripts/tests -v
python3 dm/host/tests/test_boot_trace.py
cc -std=c11 -O1 -g -fsanitize=address,undefined \
  dm/host/tests/t_loader_validate.c -o /tmp/g2m-loader-check
/tmp/g2m-loader-check
python3 scripts/g2mctl.py capabilities
python3 scripts/g2mctl.py build-plan
```

Apple CI 还运行两个真实系统的内存保护、并发、进程清理与证据工具测试；已有 iOS 26/18 生产源码、17 文件前端、四种 XcodeGen 项目与独立诊断 App 检查全部保留。每次修改以对应提交的 CI 为准，不能用上一提交结果替代。

## 接续顺序与不可混淆的剩余项

1. **M1：受控 Apple Silicon Mac + 合法版本匹配的 ExeFS/RomFS + 本地签名。** 运行原 `m1_local_pipeline.py all` 或显式 `g2mctl build --execute-local`。保留全新证据目录，生成真实表头并达到 92/92，实际链接和签名。此会话没有这些私有输入，不能填入通过。
2. **设备：指定 iPhone/iPad 的实际启动、画面、输入、声音、存档与 30 分钟运行。** 用当前日志、App、模板和附件核对记录；人工验收，不能用合成测试、`DONE`、首呈现回调或自填 JSON 冒充。
3. **S2-06/07：真实场景的 Metal 3/4 对照和完整单帧采集/离线回放。** 需要先取得目标场景及合法私有帧，确定资源覆盖和同步语义。本次没有实现或验证新的完整帧录放器；现有命令回放不是完整帧持久化能力。
4. **图形启动器、D2R 适配包完整抽离、第二款游戏及多平台库（S2-08 后续与 S2-11/12）。** 仍是未交付产品能力，不因为 CLI 存在就标完成；按原计划在首款游戏与实际第二款输入可验证后推进。

上述第 4 类并非全部由环境阻塞，而是后续尚未实施的产品范围。本次完成的是可独立验收的运行时防护和本机构建/诊断/验收工具，不宣称整个长期计划已经完成。

## 重要兼容性说明

Loader 防护针对可复现的越界与错误解释行为：合法的现有编码规则保持不变，拒绝项产生稳定启动错误码。真实游戏可能暴露此前被静默接受的特殊布局或重定位；应在本机留存事件、匹配的 Build ID、布局信息和合法输入，先补合成反例，再决定语义修复。不要把防护关闭后“能继续运行”当作正确性证明，也不要为了过 CI 伪造私有生成头文件。

详见 [操作入口](AI_OPERATOR_CLI.zh-CN.md)、[M1 私有流程](M1_PRIVATE_BUILD.zh-CN.md)、[启动诊断](STARTUP_DIAGNOSTICS.zh-CN.md) 和 [整合计划](S2ARM_INTEGRATION_PLAN.zh-CN.md)。

## 合并后验证补充

PR #20 的最终分支 12 项检查均通过，但主线再次执行时发现 Darwin 的退出竞态：仅剩僵尸进程的组也可能让 `killpg` 返回 `EPERM`。PR #21 增加限定本次进程组的只读退出核查；只有确认无活进程才保留原超时/取消结论，仍有活进程、读取失败或结果不明时返回 `stage_cleanup_failed`，不会忽略真正的权限失败。回归包含实际不响应 TERM 的后代进程，确保父进程退出后仍完成该组的强制清理。

同时精确忽略 `t_dirty_init` / `t_dirty_failures` 及其 `.dSYM`，避免测试输出污染 M1 干净源码检查；对应 `.c` 仍可跟踪。没有放宽源码门槛，也没有增加提权或任意进程扫描/终止。Darwin 行为核对来源为 Apple XNU `bsd/kern/kern_sig.c` 的 `killpg1`（过滤 SZOMB 后以接收者数量判断 EPERM）；代码不复制上游实现。最终验证以 PR #21 和对应主线 CI 为准。
