# Game2Mobile · M1 私有资源构建与验收

> 状态：**已接入本地完整构建流程，但尚未完成真实游戏的全量链接和真机测试。** 本文不提供游戏镜像、解密密钥、商业资源或可玩的 IPA。不得将这些数据、生成的头文件、构建产物或原始日志上传到公开 GitHub。

## 目的与现状

公开 Apple Silicon CI 已在 iOS 26/Metal 4 和 iOS 18/M3 两种目标上，分别从真实 Makefile 编译成功 **88/91** 个宿主编译单元。剩余三个文件的头文件必须从用户合法持有、版本匹配的 Nintendo Switch 游戏 RomFS 中生成：

| 生成文件（仅保存在 `dm/host/`） | 对应编译单元 | 生成脚本 |
|---|---|---|
| `dm_hud_exp.h` | `host/diag.c` | `dm/ios/tools/gen_hud_exp.py` |
| `dm_bright_levels.inc` | `host/dm_bright.c` | `dm/tools/gen_bright_levels.py` |
| `dm_vault_tab.h` | `host/dm_vault_ui.c` | `dm/ios/tools/gen_vault_table.py` |

本阶段新增的私有构建模式 **不会伪造这些头文件**。它会在 Mac 上使用本机真实游戏数据生成、验证、临时复制，然后使用 Apple Clang 验证 91/91，最后尝试原有 `DmIOS` 完整构建。

## 准备环境

- **Apple Silicon Mac**，使用对应 iOS 目标版本的 Xcode、XcodeGen、Metal Toolchain、.NET、spirv-cross 和 Python。
- 已合法获得并导出的《暗黑破坏神 II：狱火重生》Switch 更新版本 `3.3.94012` 的 `ExeFS/main`、`ExeFS/sdk`、`ExeFS/subsdk0` 与 `RomFS/data`（包括资料片）。
- `DM_ROOT` 默认 `~/dm-work`，游戏目录与之前 `setup.sh` 的路径规则一致。
- 需要构建真实 iOS App 时，在本机的 `dm/ios/local.env` 里配置自己的 Apple 开发团队、Bundle ID 和签名。配置文件受 Git 忽略规则保护。

## 使用

在仓库根目录执行：

```bash
# 完全无副作用，只说明将执行的步骤；Linux 上也可执行
python3 scripts/m1_local_pipeline.py plan

# 本地私有端到端：检查工具/游戏版本、准备模块与着色器、
# 从用户自己的 RomFS 生成三个头文件、严格编译 91/91、
# 最后构建并验证签名的 DmIOS.app（不自动安装或上传）
python3 scripts/m1_local_pipeline.py all --profile metal4

# 旧图形接口版本（iOS 18 / M3）；请确认所用 Xcode/SDK 支持
python3 scripts/m1_local_pipeline.py all --profile m3
```

如果环境已准备好，可以单独执行 `preflight`、`prepare`、`headers`、`verify`、`build` 阶段。例如：

```bash
python3 scripts/m1_local_pipeline.py headers --profile metal4
python3 scripts/m1_local_pipeline.py verify --profile metal4
```

编译器也支持直接使用这三个私有头文件，不会把它们提交进 Git：

```bash
# 注意：--report 路径必须位于 Git 仓库之外。
python3 scripts/ci_production_compile.py \
  --profiles metal4 --strict \
  --private-derived-headers dm/host \
  --report "${DM_ROOT:-$HOME/dm-work}/m1-private-codegen.json"
```

## 验收与安全边界

私有日志、逐文件编译结果和安全的汇总 JSON 保存到 `DM_ROOT/m1-private-evidence/<commit>/<profile>/`。目录不在 Git 工作树内，脚本不执行任何 `git add`、GitHub API 上传或远程发布操作。

- 若三个文件缺失、为空、包含明显的 CI 占位标记、是符号链接，脚本立即失败；**不会伪造游戏数据以凑齐 91/91**。
- 必须严格编译 **91/91** 且无其他错误，才算该编译阶段通过。若失败，保留本机日志供定位；对外可分享的 JSON 不包含头文件原文、密钥、设备标识或原始编译报错。
- 在 `all` 模式中，最后调用原有 `dm/ios/run.sh build`，再核对 `DmIOS.app` 的名称、ARM64 可执行文件与本机 Apple 签名。
- **即使上述所有步骤通过，也只能称为本地真实游戏 App 已构建/签名，不能自动宣称画面、声音、存档、运行性能或真机安装已验证。** 这些需单独记录实机冒烟测试。
- 项目公开 CI 仍只使用受版本控制的源文件，不会取得这三个私有头文件；因此公开检查持续保持 **88/91 + 3 个受控资源阻塞**，这是符合设计的结果。

参见 [完整编译覆盖率报告](PRODUCTION_COMPILE_COVERAGE.md) 和 [M1 Issue #1](https://github.com/ForceMind/Game2Mobile/issues/1)。

## English summary

Run `python3 scripts/m1_local_pipeline.py plan` for a safe preview. On an Apple Silicon Mac with your legally obtained, version-matched game files and Apple signing configured locally, run `python3 scripts/m1_local_pipeline.py all --profile metal4`. This regenerates the three **private** RomFS-derived headers, verifies the real 91-source ARM64 compile with no synthetic substitutes, and attempts a locally signed real `DmIOS.app` build. No commercial game files, keys, logs or App bundles are uploaded to GitHub. A successful signed build is **not** proof of game launch or real-device playability.
