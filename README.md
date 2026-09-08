# Marvis GUID + svid 同步工具 v2.1（菜单更新版）

**工具版本：2.1.0-experimental · 适配 Marvis：1.60.2500.191 · 日期：2026-09-08**

## v2.1 菜单变化

```text
1. 只读查看 GUID/svid 一致性
2. 生成新 GUID 并同步 svid
3. 自定义 GUID 并同步 svid
4. 恢复最近一次事务（含 svid）
5. 查看完整 GUID
6. 关闭 Marvis（指定六种进程）
7. 只读检查今天的登录日志
0. 退出脚本
```

- **每个选项成功、取消、报错或输入无效后，都返回主菜单。只有选择 0 才正常退出。** 终端被外部关闭或输入流结束时，会结束程序，避免无限循环。
- 修改/恢复操作每次完成后立即恢复原本运行中的后台服务并释放锁，不再等到退出菜单。
- `run.cmd` 在选择 0 后直接结束，不再多出一次“按任意键继续”；启动异常时仍保留错误信息。

### 菜单 6 的关闭范围

只处理 Marvis 安装目录中的以下六种进程（同名多个实例也会处理）：

```text
MarvisKnowledgebase.exe
MarvisDlSvr.exe
MarvisAgent.exe
MarvisHost.exe
MarvisMCP.exe
Marvis.exe
```

**先保存工作，再输入 YES 确认。** 工具先尝试正常关闭窗口并给出约 5 秒的共同等待期，再结束仍未退出的目标进程。必要的强制结束可能丢失未保存内容。

不使用全进程树结束，不按模糊名称匹配，不处理安装目录外的同名程序，不主动结束 `MarvisSvr` 或其他未列出的进程。关闭结果会列出已关闭、剩余和错误信息；如果仍有其他组件阻止 GUID 修改，修改选项会明确报告，不会自动扩大关闭范围。

### 更新文件

菜单在 Python 中实现，因此 `run.cmd` 和 `marvis_device_id.py` **需要一起更新**。其他机器请使用新的 v2.1 ZIP；原目录中的 `backups` 必须保留，不要删除或用别的机器的备份替换。

新 ZIP 不包含任何个人设备标识或备份。旧 `.rar`、v2 ZIP 和历史验证记录均没有被改成 v2.1，不要混用。

## 当前状态：脚本已更新，实际登录待你验证

本轮只修改工具并测试模拟环境，没有再次改变本机 GUID、实际注册表值、登录凭据，也没有退出或重启本机 Marvis。

不要沿用 v1 的“本地检查通过就代表登录正常”结论。v2 的 `status: applied` 只代表**本地三处标识一致性和 SDK 返回值检查通过**；输出始终明确包含：

```json
"login_stability_verified": false
```

用户已反馈 v2 在本机测试可行。本次 v2.1 只更新菜单、关闭进程和每项操作的收尾流程；没有再次实际应用设备标识修改，也没有代替用户做完整登录测试。

## 为什么升级

本机历史证据显示：v1 改完 Beacon GUID 后，前台使用新值，而 LocalSystem 下的 `MarvisSvr` 仍使用原 `svid`；后续 `checkLogin` 返回 HTTP 200、业务 `-101 / redis: nil` 后登出。恢复原 GUID 后检查返回 `code: 0`。

这是同步修正的依据，但不是服务端唯一根因的证明。不能把 `redis: nil` 解释成已经完全恢复了服务器内部会话规则。

## 修改范围

v2 仅修改：

1. 当前 Windows 用户的 `Tencent\beacon\beacon_marvis.db` 内的应用 `guid`；使用原有 DPAPI 保护方式。
2. **64 位注册表视图** `HKLM\SOFTWARE\Tencent\Marvis\Env` 的 **`svid`**。
3. **64 位注册表视图** `HKCU\SOFTWARE\Tencent\Marvis\Env` 的 **`svid`**。

两处 `svid` 必须已经存在、类型为 `REG_SZ`、值是 32 位十六进制。**工具不会创建缺失的键或值，不会自动扩展到其他路径。**

不修改 Windows `MachineGuid`、QIMEI、`Androws` 项、登录 Token、安全存储、EXE/DLL、登录检查或登出分支。

**注意：HKLM 是机器级的 Marvis 应用配置，同一台机器上其他 Windows 用户运行 Marvis 时也可能受到影响。不要在其他用户正使用 Marvis 的机器上做该测试。**

## 新版包与旧文件

- 请使用新包 **`marvis-device-id-tool-v2.1.zip`**，或者本目录已更新的源码。
- 如果原目录还存在 `marvis-device-id-tool.rar`，它是此前的旧包，**没有被更新，不要用它分发 v2**。
- 原 `verification.json` 是 v1 的历史记录，不代表 v2 验证结果。
- v2.1 的 52 项测试、模拟进程关闭结果及本机目标未修改证明见 `verification-v2.1.json`。`verification-v2.json` 保留为上一版记录。
- 分发 ZIP 不包含任何机器的 `backups`、设备 ID 或历史日志。

## 环境要求

- 64 位 Windows，64 位 Python **3.10+**；本轮使用 Python 3.13 测试。
- 不需要 pip 安装第三方依赖；使用 Python 标准库、Windows DPAPI 和本机 Marvis SDK。
- 当前只允许上述精确构建；四个核心二进制的 SHA-256 不匹配会拒绝运行。
- 修改/恢复时需要访问 HKLM 的权限，通常需管理员运行。**仍然必须是同一个 Windows 用户，不能换一个管理员账户代跑 DPAPI 解密。**

## 建议验证步骤

### 1. 先只读确认基线

运行 `run.cmd`，确认标题包含 **v2**。选择 **1**。

应看到：

```json
"local_identity_consistent": true
```

如果为 false 或报 `Baseline GUID/svid mismatch`，先使用对应的旧备份恢复原状态，再测试 v2。新版不会在不一致基线上猜测哪个值正确，也不会直接替你“修复”未知来源的值。

### 2. 正常退出 Marvis 及其组件

先保存工作，再从应用正常退出；也可使用新增菜单 6 并确认关闭。新版检查整个 Tencent\Marvis 安装树，包括旧工具漏掉的 `MarvisHost`、`MarvisAgent`、知识库等子组件。

如果输出 `Close Marvis and its foreground components first`，说明仍有组件在运行；**此时没有进行标识写入**。先正常退出这些组件，不要反复执行修改。

工具只会在明确选择修改/恢复时，临时停止精确版本路径下的 `MarvisSvr` 后台服务及其崩溃报告器；操作后恢复原先运行中的服务。修改/恢复选项本身不会强制终止前台，也不会自动登录；新增菜单 6 经确认后可以强制结束指定进程。

### 3. 执行一次受控修改

同一 Windows 用户下，以管理员身份运行 `run.cmd`：

- 选 **2**：生成新的稳定 GUID，同时同步两处 `svid`。
- 或选 **3**：输入一个 32 位十六进制 GUID，不能全零，不能带连字符。
- 输入 `YES` 确认修改范围。

先只执行一次，不要反复生成新值。保存输出中的新 **`backup_id`**。

正常本地结果应包含：

```json
{
  "status": "applied",
  "tool_version": "2.1.0-experimental",
  "local_identity_consistent": true,
  "svid_hklm_synced": true,
  "svid_hkcu_synced": true,
  "registry_changed": true,
  "windows_machine_guid_changed": false,
  "login_stability_verified": false
}
```

`registry_changed: true` 指的是两处 **Marvis Env/svid**，不是系统 MachineGuid。

### 4. 手动启动并重新登录，检查后续会话

1. 记录测试开始时间。
2. 手动启动 Marvis 并正常登录。
3. 观察至少 10 分钟并实际使用，再正常退出、重新启动验证一次；不要把 10 分钟作为长期稳定性的保证。
4. 菜单 **7** 可以只读查看当天的登录事件与检查结果；它不会输出令牌或原始日志内容。
5. 更精确时用 `check-login --since` 只查看本次测试之后的记录。

需要关注最新一次登录后是否出现多次 `checkLogin_result` 且 `code: 0`，以及是否出现 `logout`、`checkLogin_logout` 或 `server_checkLogin_error`。

`login_stability_verified` 不会被脚本自动改成 true：成功的几次日志观测不是长期登录稳定性的证明。

### 5. 再次掉线时立即恢复本次 v2 事务

先正常退出 Marvis，再选择菜单 **4**。这会选择最近一个未完成恢复的事务。

若存在多次修改，使用输出中的确切新 `backup_id` 恢复，不能照搬其他机器或之前示例的编号。

**v2 必须使用 v2 工具恢复，不能用旧版脚本恢复 v2 事务。** 旧版只能恢复文件，会漏掉 svid，重新造成不一致。

如果同步三处后仍退出，先恢复，不要继续扩大修改到 QIMEI、Token 或禁用登录检查。

## PowerShell 命令

本机脚本完整路径：

```powershell
$tool = 'C:\Users\Administrator\Documents\Codex\2026-09-08\c-program-files-tencent-marvis-application\outputs\marvis-device-id-tool\marvis_device_id.py'
```

在其他机器上，把 `$tool` 改成**那台机器实际的完整路径**。

只读状态：

```powershell
python -B $tool status
```

随机修改并同步（先退出所有 Marvis 组件）：

```powershell
python -B $tool change --stop-background
```

自定义建议使用菜单 3。CLI 参数为 `change --new-id`，后面填写 32 位十六进制值，同时带 `--stop-background`。

恢复最近一个活动事务：

```powershell
python -B $tool restore --stop-background
```

要指定备份，在上述命令添加 `--backup-id` 及**本机此次修改输出的编号**。

测试开始时记录时间：

```powershell
$since = Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'
```

登录测试后，在同一 PowerShell 窗口查看之后的结果：

```powershell
python -B $tool check-login --since $since
```

## 备份、事务与失败处理

每次 v2 修改都会创建三个文件：

- `original.dpapi.ini`：原 Beacon 加密文件。
- `registry.before.dpapi`：包含原 HKLM/HKCU svid 的 **DPAPI 加密快照**。
- `manifest.json`：事务状态、格式版本、校验哈希、脱敏字段信息。

备份必须与工具一起保留在原机器、原 Windows 用户环境下。ZIP 中没有备份；不要把其他机器的备份拿来替代。

文件与注册表无法做到一个原子写操作。新版采用预检查、事前备份、每步读回校验、补偿回滚，并记录中间阶段：

- 一处写入失败或 SDK 返回值不符：尝试恢复原文件和两处 svid。
- 任一恢复失败，或发现并发写入了不属于本次事务的其他标识：明确报恢复不完整，不覆盖陌生值，并暂停自动重启后台服务。保留备份和错误输出再处理。
- 文件/注册表恢复成功后，服务启动失败：输出会说明本地操作已完成和服务恢复失败，不能误当作标识已经自动回滚。
- 检测到当前标识属于另一次不相关事务时拒绝覆盖。
- 发现备份之后硬件字段变化时拒绝整段替换，避免丢失其他数据。
- 断电或直接结束工具进程仍可能留下中间状态，必须保留日志和备份，使用对应 v2 事务恢复；不存在跨存储完全原子的保证。

## 旧版备份兼容

旧备份没有注册表快照。v2 仅在 HKLM/HKCU `svid` **已经等于旧备份的原 GUID** 时，允许用 v1 备份恢复 Beacon 文件；不会从缺失快照中猜测注册表原值。

否则应使用对应 v2 事务恢复，或先人工分析当前状态，不应强行覆盖。

## 测试边界

- 自动测试全部使用临时加密文件与模拟注册表/进程，不写实际注册表，不调用业务接口。
- 测试覆盖权限不足、部分写入失败、失败恢复、备份损坏、并发变化、旧备份兼容和脱敏日志解析。
- 本机只执行了 `status` 与 `check-login` 只读命令，确认恢复后的旧 GUID 和两处 svid 一致。
- **新版真实修改、LocalSystem 运行时采用新值，以及登录长期保持，需要你执行上述测试验证。**
