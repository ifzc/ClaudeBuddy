# ClaudeBuddy · 飞书 / 微信 / 任务栏独立时区

<img src="src/desktop_timezone/assets/claudebuddy.png" alt="ClaudeBuddy 橙色像素小螃蟹" width="80" height="80">

ClaudeBuddy 让 Windows 桌面版飞书、微信和主屏任务栏时钟分别显示指定时区，保留电脑原来的系统时区。

使用 Claude Code 风格的橙色像素小螃蟹图标，覆盖程序文件、窗口、任务栏和系统托盘。图标源文件位于 `src/desktop_timezone/assets/`，可用 `python scripts/generate_icon.py` 重新生成。

这是基于进程内时区覆盖的实验工具，不是飞书或腾讯官方插件。已经在 Windows 11 x64、飞书 **8.2.0.73** 和微信 **4.1.7.59** 上验证聊天时间显示。

## 功能与范围

| 应用 | 已验证范围 | 覆盖的进程 |
| --- | --- | --- |
| 飞书 | 聊天列表时间、日历 GMT+8 显示 | 主进程、界面 renderer |
| 微信 4.x（`Weixin.exe`） | 聊天列表时间 | 聊天主进程 |
| Windows 11 主屏任务栏时钟 | 时间与日期、实时切换时区、鼠标点击穿透 | 工具自己的显示窗口，未注入 Explorer |

- 飞书、微信、任务栏时钟可以选择不同的时区，分别启用和关闭。
- 可选北京、东京、亚利桑那、纽约、洛杉矶、伦敦、UTC；按 Windows 时区规则处理夏令时。
- 配置自动保存；不修改系统时区、注册表或应用安装文件，不改变 UTC 时间戳。
- 不开放网络调试端口，不收集或上传聊天内容、登录凭据。

微信小程序、内置网页、OCR、音视频和辅助进程，以及飞书后台、GPU、utility 进程不在覆盖范围。旧版 `WeChat.exe` 暂不支持。实际消息发送、日程创建、提醒与音视频行为未全面验证，应用升级后也需要重新验证。

## 运行

### 独立可执行文件

可以自行构建，也可以在 [Actions](https://github.com/ifzc/ClaudeBuddy/actions) 中打开成功的 Windows 构建，下载 `ClaudeBuddy-windows-x64` artifact 并完整解压。GitHub 下载 Actions artifact 可能要求登录。程序未做代码签名。

1. 运行 `ClaudeBuddy.exe`，选择“飞书”或“微信”标签页。
2. 保存该应用的草稿、结束通话，并从系统托盘完全退出该应用。
3. 选择时区，点击“应用时区并启动”。如出现登录界面，请自行完成登录。
4. 可以点击 × 关闭设置窗口，工具会收起到系统托盘继续维护时区，不会重启应用或自动恢复时区。点击托盘图标可重新打开设置。
5. 更换时区或停止使用时，点击对应的“恢复普通启动”。确认后会退出并重新打开该应用，以清除进程内时区缓存。

没有管理中的应用时，关闭窗口会直接退出工具。维护时区期间，关闭窗口只收起到托盘；若系统托盘不可用，则最小化到任务栏。需要结束后台运行时，先手动恢复对应应用，再关闭工具。意外终止后台进程后，请完全退出受影响的应用并通过原快捷方式启动。

### 任务栏时钟（v0.2.0）

1. 选择“任务栏时钟”标签页，选择时区，点击“应用任务栏时区”。默认是北京时间。
2. 主屏右下角原时钟位置显示该时区的 24 小时时间和月/日；选择另一时区后再次应用即可更新，无需重启 Explorer。
3. 关闭设置窗口后继续在托盘运行。点击“关闭独立时钟”会立即露出原来的 Windows 时钟。
4. 启用状态会保存，再次打开工具时自动恢复。此功能不会添加 Windows 开机启动项。
5. v0.2.1 新增“显示日期”开关：取消勾选后只显示居中的时间，重新勾选显示时间和日期。切换立即生效并自动保存。
6. v0.2.2 在时钟显示区域上下各留 2 个物理像素，避免背景覆盖任务栏边线。

这是覆盖在原时钟上方的独立显示窗口，鼠标点击会穿透到原时钟。展开的 Windows 日历、通知、文件时间和系统时区保持原样。当前仅支持能识别的 Windows 11 主屏任务栏布局，已验证 Windows 11 26H2（26300.9711）；其他布局识别失败时显示错误，不猜测覆盖位置。多屏的副屏时钟暂不覆盖。全屏窗口覆盖时钟区域时隐藏显示层，任务栏再次可见后继续显示。外观使用简单的深色或浅色背景，不复制任务栏的透明材质。

### 从源码运行

需要 **Windows x64、Python 3.12 或更新版本**。以下命令在仓库根目录执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,build]"
.\.venv\Scripts\python.exe -m desktop_timezone
```

也可运行虚拟环境中的 `claudebuddy.exe`。加 `--weixin` 或 `--taskbar` 可默认显示对应标签页。旧的 `desktop-timezone` 命令保留为兼容入口。

## 配置

源码运行时，`config.json` 保存在当前工作目录；独立 EXE 运行时保存在 EXE 旁边。首次运行使用北京时间，不需要先复制示例。

```json
{
  "apps": {
    "feishu": { "timeZone": "Asia/Shanghai" },
    "weixin": { "timeZone": "America/Phoenix" }
  },
  "taskbar": { "timeZone": "Asia/Shanghai", "enabled": false, "showDate": true }
}
```

默认查找常见安装位置。自定义路径可在对应应用项中添加 `"executable": "D:\\Applications\\Weixin\\Weixin.exe"`。配置示例在 [examples/config.json](examples/config.json)；用户运行配置被 Git 忽略。

## 测试与构建

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe tests/integration/selftest.py
.\.venv\Scripts\python.exe tests/integration/window_lifecycle.py
.\scripts\build.ps1 -Python .\.venv\Scripts\python.exe
```

默认构建输出位于 `dist/`。原生测试只创建并操作自己的 Python 测试进程，不启动或重启已安装的飞书、微信。它验证真实 Windows API 的时区转换、冬夏令时、UTC 不变、释放后恢复及双控制器隔离。GitHub Actions 在 Windows 上执行检查、测试和构建。

任务栏实际显示测试需在有可见 Windows 11 主屏任务栏的桌面手动运行 `python tests/integration/taskbar_lifecycle.py`，会短暂覆盖任务栏时钟并自动移除，验证点击穿透、收起到托盘、实时切换和关闭。此项不在无交互桌面的 CI 中运行；跨日及夏令时转换由普通单元测试覆盖。

## 结构

```text
src/desktop_timezone/
  app.py                 界面与应用生命周期
  configuration.py       配置校验和保存
  profiles.py            应用范围、路径和时区映射
  tray.py                Windows 系统托盘与设置窗口恢复
  taskbar_clock.py        主屏时钟定位、独立时间转换和点击穿透显示层
  native_timezone.py     原生进程控制与 Frida 会话
  agent.js               Windows / ICU 时区接口覆盖
tests/                   配置和进程范围测试
tests/integration/       真实 Windows API 测试
scripts/                 独立 EXE 构建入口
docs/                    实现原理与验证边界
```

更多说明见 [实现原理](docs/architecture.md) 和 [验证记录](docs/validation.md)。

## 许可证

本项目代码使用 [MIT License](LICENSE)。Frida 等依赖保留各自许可证，详见 [第三方声明](THIRD_PARTY_NOTICES.md)。本项目不包含飞书或微信程序，也不与其厂商关联。
