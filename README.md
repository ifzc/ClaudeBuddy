# Desktop Timezone · 飞书 / 微信独立时区

让 Windows 桌面版飞书和微信分别使用指定时区，保留电脑原来的系统时区。

这是基于进程内时区覆盖的实验工具，不是飞书或腾讯官方插件。已经在 Windows 11 x64、飞书 **8.2.0.73** 和微信 **4.1.7.59** 上验证聊天时间显示。

## 功能与范围

| 应用 | 已验证范围 | 覆盖的进程 |
| --- | --- | --- |
| 飞书 | 聊天列表时间、日历 GMT+8 显示 | 主进程、界面 renderer |
| 微信 4.x（`Weixin.exe`） | 聊天列表时间 | 聊天主进程 |

- 两个应用可以选择不同的时区，分别启动和恢复普通模式。
- 可选北京、东京、亚利桑那、纽约、洛杉矶、伦敦、UTC；按 Windows 时区规则处理夏令时。
- 配置自动保存；不修改系统时区、注册表或应用安装文件，不改变 UTC 时间戳。
- 不开放网络调试端口，不收集或上传聊天内容、登录凭据。

微信小程序、内置网页、OCR、音视频和辅助进程，以及飞书后台、GPU、utility 进程不在覆盖范围。旧版 `WeChat.exe` 暂不支持。实际消息发送、日程创建、提醒与音视频行为未全面验证，应用升级后也需要重新验证。

## 运行

### 独立可执行文件

可以自行构建，也可以在 [Actions](https://github.com/ifzc/desktop-timezone/actions) 中打开成功的 Windows 构建，下载 `DesktopTimezone-windows-x64` artifact 并完整解压。GitHub 下载 Actions artifact 可能要求登录。程序未做代码签名。

1. 运行 `DesktopTimezone.exe`，选择“飞书”或“微信”标签页。
2. 保存该应用的草稿、结束通话，并从系统托盘完全退出该应用。
3. 选择时区，点击“应用时区并启动”。如出现登录界面，请自行完成登录。
4. 使用期间保持工具窗口打开。
5. 更换时区或停止使用时，点击对应的“恢复普通启动”。确认后会退出并重新打开该应用，以清除进程内时区缓存。

关闭工具会询问是否恢复它管理的应用。如果工具意外退出，请从托盘完全退出受影响的应用，再通过原快捷方式启动。

### 从源码运行

需要 **Windows x64、Python 3.12 或更新版本**。以下命令在仓库根目录执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,build]"
.\.venv\Scripts\python.exe -m desktop_timezone
```

也可运行虚拟环境中的 `desktop-timezone.exe`。加 `--weixin` 可默认显示微信标签页。

## 配置

源码运行时，`config.json` 保存在当前工作目录；独立 EXE 运行时保存在 EXE 旁边。首次运行使用北京时间，不需要先复制示例。

```json
{
  "apps": {
    "feishu": { "timeZone": "Asia/Shanghai" },
    "weixin": { "timeZone": "America/Phoenix" }
  }
}
```

默认查找常见安装位置。自定义路径可在对应应用项中添加 `"executable": "D:\\Applications\\Weixin\\Weixin.exe"`。配置示例在 [examples/config.json](examples/config.json)；用户运行配置被 Git 忽略。

## 测试与构建

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe tests/integration/selftest.py
.\scripts\build.ps1 -Python .\.venv\Scripts\python.exe
```

默认构建输出位于 `dist/`。原生测试只创建并操作自己的 Python 测试进程，不启动或重启已安装的飞书、微信。它验证真实 Windows API 的时区转换、冬夏令时、UTC 不变、释放后恢复及双控制器隔离。GitHub Actions 在 Windows 上执行检查、测试和构建。

## 结构

```text
src/desktop_timezone/
  app.py                 界面与应用生命周期
  configuration.py       配置校验和保存
  profiles.py            应用范围、路径和时区映射
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
