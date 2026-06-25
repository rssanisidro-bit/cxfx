# 局域网代码分享 Android 版

这是根据 `程序分享(1).py` 生成的 Android APK 项目，保留电脑版 Kivy 深色界面风格，并针对手机端做了以下适配：

- 保留“发送 / 在线成员 / 最近接收 / 状态日志”的原有布局。
- 手机端自动切换上下布局，按钮和栏宽略微压缩。
- 使用系统文件选择器读取 `.py`、`.txt`、`.kv`、`.json`、`.md` 等代码文件。
- Android 端通过 `NativeTextBridge.java` 读取 `content://` 文件，避免直接用路径读取失败。
- 接收代码后保存到手机可写目录，并尝试刷新系统文件索引。
- 保留 UDP 局域网发现、手动 IP 直连、TCP 发送、代码高亮预览、历史记录和配对码。
- 应用图标使用 Windows/Kivy 包内随电脑版携带的图标资源。

## GitHub 云端构建 APK

把本目录所有内容上传到 GitHub 仓库根目录，确认仓库首页能直接看到：

```text
main.py
buildozer.spec
assets/
android_src/
.github/workflows/build-apk.yml
```

然后进入 GitHub 仓库的 `Actions` 页面，运行 `Build Android APK`。构建成功后，在运行结果下方的 `Artifacts` 下载 `LanCodeShare-debug-apk`，解压后即可得到 APK。

首次构建可能需要 20 到 60 分钟。

## 使用提示

两台设备需要在同一局域网、同一热点，或没有客户端隔离的校园网内。若自动发现不到对方，可在“输入对方 IP”中手动填写接收方 IP 后点击“直连”。

## ??????

- ??? `assets/CJK.ttf`??? Android ???? `font_name: "CJK"` ?????????
- ??? Android ?????????? Wi-Fi IP ????????????? `default_save_dir()` ???????
- ????????????????????
