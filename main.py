# -*- coding: utf-8 -*-
import os
os.environ.setdefault("KIVY_NO_ARGS", "1")

import socket
import errno
import threading
import json
import time
import re
import traceback
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.lang import Builder
from kivy.metrics import dp, sp
from kivy.core.clipboard import Clipboard
from kivy.clock import Clock, mainthread
from kivy.uix.popup import Popup
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.scrollview import ScrollView
from kivy.uix.image import Image
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.utils import escape_markup, platform

import qrcode
from pygments import lex
from pygments.lexers import PythonLexer, TextLexer, get_lexer_for_filename
from pygments.token import Comment, Error, Keyword, Name, Number, Operator, String, Token

try:
    from plyer import filechooser as plyer_filechooser
except Exception:
    plyer_filechooser = None

# ===================== 网络配置常量 =====================
BROADCAST_PORT = 18888
TCP_PORT = 18889
BROADCAST_INTERVAL = 2  # 设备广播间隔(秒)
PEER_TIMEOUT = 10       # 设备离线超时(秒)
BUFFER_SIZE = 4096
ENCODING = "utf-8"
MAX_PAYLOAD_BYTES = 10 * 1024 * 1024  # 单次分享最大10MB，避免误传超大内容
MAX_HISTORY_ITEMS = 50
QR_FILENAME = "pair_qr.png"
APP_VERSION = "v20260625-ipv6-ui"
ANDROID_FILE_PICK_REQUEST = 18890
TOKEN_COLORS = {
    Keyword: "8cc8ff",
    Name.Function: "9cdcfe",
    Name.Class: "4ec9b0",
    Name.Builtin: "c586c0",
    String: "ce9178",
    Number: "b5cea8",
    Comment: "6a9955",
    Operator: "d4d4d4",
    Error: "ff6b6b",
    Token: "d4d4d4",
}

# ===================== 中文字体兼容处理 =====================
def register_chinese_font():
    """优先加载同目录CJK字体，失败则尝试系统字体，保证中文正常显示"""
    font_paths = [
        "assets/CJK.ttf",
        "assets/CJK.ttc",
        "CJK.ttf",
        "CJK.ttc",
        "C:/Windows/Fonts/msyh.ttc",  # Windows 微软雅黑
        "/System/Library/Fonts/PingFang.ttc",  # macOS 苹方
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"  # Linux 文泉驿
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                LabelBase.register(name="CJK", fn_regular=path)
                return True
            except:
                continue
    return False

register_chinese_font()

# ===================== 界面KV定义 =====================

# Android compatibility helpers
def request_android_permissions():
    if platform != "android":
        return
    try:
        from android.permissions import Permission, request_permissions
        names = [
            "INTERNET", "ACCESS_NETWORK_STATE", "ACCESS_WIFI_STATE",
            "CHANGE_WIFI_MULTICAST_STATE", "READ_EXTERNAL_STORAGE",
            "WRITE_EXTERNAL_STORAGE", "READ_MEDIA_IMAGES", "READ_MEDIA_VIDEO",
            "READ_MEDIA_AUDIO",
        ]
        permissions = [getattr(Permission, name) for name in names if hasattr(Permission, name)]
        request_permissions(permissions)
    except Exception:
        pass


def writable_directory(path):
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        try:
            os.remove(probe)
        except OSError:
            pass
        return True
    except Exception:
        return False


def app_private_dir():
    app = App.get_running_app()
    if app:
        try:
            if app.user_data_dir:
                return app.user_data_dir
        except Exception:
            pass
    return os.getcwd()


def default_save_dir():
    if platform == "android":
        candidates = []
        try:
            from android.storage import primary_external_storage_path, app_storage_path
            root = primary_external_storage_path()
            candidates.append(os.path.join(root, "Download", "LanCodeShare"))
            candidates.append(os.path.join(root, "Documents", "LanCodeShare"))
            candidates.append(os.path.join(app_storage_path(), "received_codes"))
        except Exception:
            pass
        candidates.append(os.path.join(app_private_dir(), "received_codes"))
        for candidate in candidates:
            if candidate and writable_directory(candidate):
                return candidate
    path = os.path.join(os.getcwd(), "received_codes")
    os.makedirs(path, exist_ok=True)
    return path


def android_scan_file(path):
    if platform != "android":
        return False
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        MediaScannerConnection = autoclass("android.media.MediaScannerConnection")
        MediaScannerConnection.scanFile(PythonActivity.mActivity, [str(path)], None, None)
        return True
    except Exception:
        return False


def get_android_wifi_ip():
    if platform != "android":
        return None
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Context = autoclass("android.content.Context")
        Formatter = autoclass("android.text.format.Formatter")
        activity = PythonActivity.mActivity
        wifi = activity.getApplicationContext().getSystemService(Context.WIFI_SERVICE)
        if wifi:
            ip = Formatter.formatIpAddress(wifi.getConnectionInfo().getIpAddress())
            if ip and not ip.startswith("127.") and ip != "0.0.0.0":
                return str(ip)
    except Exception:
        return None
    return None

def get_android_interface_ips():
    """Return IPv4 addresses from Android network interfaces."""
    if platform != "android":
        return []
    ips = []
    try:
        from jnius import autoclass
        NetworkInterface = autoclass("java.net.NetworkInterface")
        Collections = autoclass("java.util.Collections")
        interfaces = Collections.list(NetworkInterface.getNetworkInterfaces())
        for iface in interfaces:
            try:
                if not iface.isUp() or iface.isLoopback():
                    continue
                addresses = Collections.list(iface.getInetAddresses())
                for addr in addresses:
                    host = str(addr.getHostAddress())
                    if host and ":" not in host and not host.startswith("127.") and host != "0.0.0.0":
                        if host not in ips:
                            ips.append(host)
            except Exception:
                continue
    except Exception:
        pass
    return ips


def _strip_ipv6_scope(ip):
    return (ip or "").split("%", 1)[0]


def is_valid_ipv6(ip):
    """Return True when ip is a valid IPv6 literal, including scoped link-local input."""
    try:
        socket.inet_pton(socket.AF_INET6, _strip_ipv6_scope(ip))
        return True
    except OSError:
        return False


def is_loopback_ip(ip):
    clean = _strip_ipv6_scope(ip)
    return clean.startswith("127.") or clean in ("::1", "0:0:0:0:0:0:0:1")


def normalize_ipv6_host(host):
    value = (host or "").strip()
    if value.startswith("[") and "]" in value:
        value = value[1:value.index("]")]
    return value


def get_android_interface_ipv6s():
    """Return usable IPv6 addresses from Android network interfaces."""
    if platform != "android":
        return []
    ips = []
    try:
        from jnius import autoclass
        NetworkInterface = autoclass("java.net.NetworkInterface")
        Collections = autoclass("java.util.Collections")
        interfaces = Collections.list(NetworkInterface.getNetworkInterfaces())
        for iface in interfaces:
            try:
                if not iface.isUp() or iface.isLoopback():
                    continue
                iface_name = str(iface.getName())
                addresses = Collections.list(iface.getInetAddresses())
                for addr in addresses:
                    host = str(addr.getHostAddress())
                    if not host or ":" not in host:
                        continue
                    base = _strip_ipv6_scope(host)
                    if not is_valid_ipv6(base) or is_loopback_ip(base):
                        continue
                    if host.startswith("fe80:") and "%" not in host and iface_name:
                        host = f"{base}%{iface_name}"
                    if host not in ips:
                        ips.append(host)
            except Exception:
                continue
    except Exception:
        pass
    return ips


def get_local_ipv6_candidates():
    """Collect local IPv6 candidates for display, discovery and self-address checks."""
    ips = []
    for ip in get_android_interface_ipv6s():
        if ip not in ips:
            ips.append(ip)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET6):
            ip = info[4][0]
            if ip and is_valid_ipv6(ip) and not is_loopback_ip(ip) and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    return ips


def get_local_ip_candidates():
    """Collect local IP candidates for self-address detection."""
    ips = []
    for ip in get_android_interface_ips():
        if ip not in ips:
            ips.append(ip)
    for ip in get_local_ipv6_candidates():
        if ip not in ips:
            ips.append(ip)
    try:
        host_ips = socket.gethostbyname_ex(socket.gethostname())[2]
        for ip in host_ips:
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    last_ip = globals().get("_LAST_LOCAL_IP", "")
    if last_ip and not last_ip.startswith("127.") and last_ip not in ips:
        ips.append(last_ip)
    return ips

def acquire_android_multicast_lock():
    """Keep Wi-Fi broadcast discovery alive on Android when the system is saving power."""
    if platform != "android":
        return None
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Context = autoclass("android.content.Context")
        activity = PythonActivity.mActivity
        wifi = activity.getApplicationContext().getSystemService(Context.WIFI_SERVICE)
        if not wifi:
            return None
        lock = wifi.createMulticastLock("LanCodeShareDiscovery")
        lock.setReferenceCounted(True)
        lock.acquire()
        return lock
    except Exception:
        return None

class ReadOnlyTextInput(TextInput):
    """Display-only text area that does not open the selection/copy bubble."""
    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self.collide_point(*touch.pos):
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if self.collide_point(*touch.pos):
            return True
        return super().on_touch_up(touch)

KV_STRING = '''
#:import dp kivy.metrics.dp
#:import sp kivy.metrics.sp

<Label>:
    font_name: "CJK"

<Button>:
    font_name: "CJK"
    background_normal: ""
    background_down: ""

<ToggleButton>:
    font_name: "CJK"
    background_normal: ""
    background_down: ""

<TextInput>:
    font_name: "CJK"

<ReadOnlyTextInput>:
    font_name: "CJK"

<RootWidget>:
    orientation: "vertical"
    padding: dp(10)
    spacing: dp(8)
    canvas.before:
        Color:
            rgba: 0.055, 0.075, 0.115, 1
        Rectangle:
            pos: self.pos
            size: self.size

    # 顶栏
    BoxLayout:
        id: top_bar
        size_hint_y: None
        height: dp(50)
        padding: [dp(10), 0]
        spacing: dp(8)
        canvas.before:
            Color:
                rgba: 0.09, 0.16, 0.27, 1
            RoundedRectangle:
                pos: self.pos
                size: self.size
                radius: [dp(10)]
        Label:
            id: title_label
            text: "局域网代码分享"
            font_size: sp(18)
            bold: True
            halign: "left"
            valign: "middle"
            text_size: self.size
            color: 0.92, 0.95, 1, 1
            size_hint_x: 1
        Label:
            id: user_label
            text: "用户：加载中…"
            font_size: sp(12)
            color: 0.55, 0.85, 1, 1
            halign: "center"
            valign: "middle"
            text_size: self.size
            size_hint_x: None
            width: dp(125)
        Label:
            id: status_label
            text: "未连接"
            font_size: sp(12)
            color: 1, 0.45, 0.45, 1
            halign: "center"
            valign: "middle"
            text_size: self.size
            size_hint_x: None
            width: dp(70)
        Button:
            id: pair_button
            text: "配对码"
            size_hint_x: None
            width: dp(70)
            font_size: sp(11)
            background_color: 0.12, 0.16, 0.24, 1
            color: 1, 1, 1, 1
            on_release: root.show_pair_qr()
        Button:
            id: settings_button
            text: "设置"
            size_hint_x: None
            width: dp(60)
            background_color: 0.12, 0.16, 0.24, 1
            color: 1, 1, 1, 1
            on_release: root.open_settings()

    # 保存目录提示
    Label:
        id: save_dir_label
        text: "保存到：…"
        size_hint_y: None
        height: dp(26)
        font_size: sp(11)
        color: 0.65, 0.72, 0.82, 1
        halign: "left"
        valign: "middle"
        text_size: self.size
        padding_x: dp(4)

    # 中部主区域
    BoxLayout:
        id: main_area
        spacing: dp(8)
        size_hint_y: 1

        # 左侧：发送区
        BoxLayout:
            id: send_panel
            orientation: "vertical"
            spacing: dp(6)
            padding: dp(8)
            size_hint_x: 0.45
            canvas.before:
                Color:
                    rgba: 0.085, 0.115, 0.18, 1
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(10)]

            BoxLayout:
                size_hint_y: None
                height: dp(30)
                spacing: dp(4)
                Label:
                    text: "发送"
                    bold: True
                    font_size: sp(15)
                    halign: "left"
                    valign: "middle"
                    text_size: self.size
                    color: 0.92, 0.95, 1, 1
                    size_hint_x: None
                    width: dp(80)
                Widget:
                    size_hint_x: 1
                Label:
                    id: char_count
                    text: "0 字符"
                    font_size: sp(11)
                    color: 0.6, 0.65, 0.75, 1
                    size_hint_x: None
                    width: dp(60)
                    halign: "right"
                    valign: "middle"
                    text_size: self.size

            BoxLayout:
                size_hint_y: None
                height: dp(34)
                spacing: dp(6)
                Label:
                    text: "文件名:"
                    font_size: sp(12)
                    color: 0.7, 0.75, 0.85, 1
                    size_hint_x: None
                    width: dp(60)
                    valign: "middle"
                TextInput:
                    id: filename_input
                    text: "hello.py"
                    multiline: False
                    font_size: sp(12)
                    background_color: 0.05, 0.07, 0.10, 1
                    foreground_color: 0.9, 0.95, 1, 1
                    padding: [dp(8), dp(6), dp(8), dp(6)]

            TextInput:
                id: code_input
                hint_text: "在这里粘贴或输入 Python 代码…"
                font_size: sp(12)
                size_hint_y: 1
                background_color: 0.05, 0.07, 0.10, 1
                foreground_color: 0.9, 0.95, 1, 1
                hint_text_color: 0.55, 0.6, 0.7, 1
                padding: [dp(8), dp(8), dp(8), dp(8)]
                on_text: root.update_char_count()

            BoxLayout:
                size_hint_y: None
                height: dp(38)
                spacing: dp(6)
                Button:
                    text: "打开文件"
                    background_color: 0.12, 0.16, 0.24, 1
                    color: 1, 1, 1, 1
                    on_release: root.open_file_chooser()
                Button:
                    text: "粘贴"
                    background_color: 0.12, 0.16, 0.24, 1
                    color: 1, 1, 1, 1
                    on_release: root.paste_from_clipboard()
                Button:
                    text: "预览"
                    background_color: 0.12, 0.16, 0.24, 1
                    color: 1, 1, 1, 1
                    on_release: root.preview_send_code()
                Button:
                    text: "发送"
                    background_color: 0.10, 0.48, 0.96, 1
                    color: 1, 1, 1, 1
                    bold: True
                    on_release: root.send_code()

        # 中间：在线成员
        BoxLayout:
            id: peer_panel
            orientation: "vertical"
            spacing: dp(6)
            padding: dp(8)
            size_hint_x: 0.25
            canvas.before:
                Color:
                    rgba: 0.085, 0.115, 0.18, 1
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(10)]

            BoxLayout:
                size_hint_y: None
                height: dp(30)
                spacing: dp(4)
                Label:
                    text: "在线成员"
                    bold: True
                    font_size: sp(15)
                    halign: "left"
                    valign: "middle"
                    text_size: self.size
                    color: 0.92, 0.95, 1, 1
                    size_hint_x: None
                    width: dp(100)
                Widget:
                    size_hint_x: 1
                Label:
                    id: peer_count_label
                    text: "在线 0 人"
                    font_size: sp(11)
                    color: 0.55, 0.85, 1, 1
                    size_hint_x: None
                    width: dp(70)
                    halign: "right"
                    valign: "middle"
                    text_size: self.size

            Label:
                id: selected_peer_label
                text: "（未选择）"
                size_hint_y: None
                height: dp(26)
                font_size: sp(11)
                color: 0.6, 0.65, 0.75, 1
                halign: "left"
                valign: "middle"
                text_size: self.size
                padding_x: dp(4)

            BoxLayout:
                size_hint_y: None
                height: dp(34)
                spacing: dp(6)
                TextInput:
                    id: manual_ip_input
                    hint_text: "IP / [IPv6]:端口"
                    multiline: False
                    font_size: sp(11)
                    background_color: 0.05, 0.07, 0.10, 1
                    foreground_color: 0.9, 0.95, 1, 1
                    hint_text_color: 0.55, 0.6, 0.7, 1
                    padding: [dp(8), dp(6), dp(8), dp(6)]
                Button:
                    text: "直连"
                    size_hint_x: None
                    width: dp(56)
                    font_size: sp(11)
                    background_color: 0.12, 0.16, 0.24, 1
                    color: 1, 1, 1, 1
                    on_release: root.add_manual_peer()

            ScrollView:
                size_hint_y: 1
                do_scroll_x: False
                bar_width: dp(4)
                BoxLayout:
                    id: peer_list_box
                    orientation: "vertical"
                    size_hint_y: None
                    height: max(self.minimum_height, self.parent.height)
                    spacing: dp(4)
                    padding: [0, dp(2), 0, dp(2)]

        # 右侧：接收区
        BoxLayout:
            id: receive_panel
            orientation: "vertical"
            spacing: dp(6)
            padding: dp(8)
            size_hint_x: 0.30
            canvas.before:
                Color:
                    rgba: 0.085, 0.115, 0.18, 1
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(10)]

            BoxLayout:
                size_hint_y: None
                height: dp(30)
                spacing: dp(4)
                Label:
                    text: "最近接收"
                    bold: True
                    font_size: sp(15)
                    halign: "left"
                    valign: "middle"
                    text_size: self.size
                    color: 0.92, 0.95, 1, 1
                    size_hint_x: None
                    width: dp(100)
                Widget:
                    size_hint_x: 1
                Button:
                    text: "历史"
                    size_hint_x: None
                    width: dp(56)
                    font_size: sp(11)
                    background_color: 0.12, 0.16, 0.24, 1
                    color: 1, 1, 1, 1
                    on_release: root.show_history()
                Button:
                    text: "清空"
                    size_hint_x: None
                    width: dp(56)
                    font_size: sp(11)
                    background_color: 0.12, 0.16, 0.24, 1
                    color: 1, 1, 1, 1
                    on_release: root.clear_received()

            Label:
                id: recv_filename
                text: "—"
                size_hint_y: None
                height: dp(22)
                font_size: sp(12)
                color: 0.55, 0.85, 1, 1
                halign: "left"
                valign: "middle"
                text_size: self.size
            Label:
                id: recv_meta
                text: "等待代码…"
                size_hint_y: None
                height: dp(22)
                font_size: sp(10)
                color: 0.6, 0.65, 0.75, 1
                halign: "left"
                valign: "middle"
                text_size: self.size

            ReadOnlyTextInput:
                id: recv_view
                text: ""
                readonly: True
                font_size: sp(12)
                background_color: 0.05, 0.07, 0.10, 1
                foreground_color: 0.9, 0.95, 1, 1
                padding: [dp(8), dp(8), dp(8), dp(8)]

            Button:
                text: "复制到剪贴板"
                size_hint_y: None
                height: dp(36)
                background_color: 0.10, 0.48, 0.96, 1
                color: 1, 1, 1, 1
                bold: True
                on_release: root.copy_to_clipboard()

            Button:
                text: "高亮预览"
                size_hint_y: None
                height: dp(34)
                background_color: 0.12, 0.16, 0.24, 1
                color: 1, 1, 1, 1
                on_release: root.preview_received_code()

    # 底部状态日志
    BoxLayout:
        id: log_panel
        size_hint_y: 0.20
        orientation: "vertical"
        padding: dp(6)
        spacing: dp(4)
        canvas.before:
            Color:
                rgba: 0.075, 0.10, 0.155, 1
            RoundedRectangle:
                pos: self.pos
                size: self.size
                radius: [dp(10)]
        BoxLayout:
            size_hint_y: None
            height: dp(24)
            spacing: dp(4)
            Label:
                text: "状态日志"
                bold: True
                font_size: sp(12)
                halign: "left"
                valign: "middle"
                text_size: self.size
                color: 0.92, 0.95, 1, 1
                size_hint_x: None
                width: dp(80)
            Widget:
                size_hint_x: 1
            Button:
                text: "清空"
                size_hint_x: None
                width: dp(56)
                font_size: sp(10)
                background_color: 0.12, 0.16, 0.24, 1
                color: 1, 1, 1, 1
                on_release: root.clear_log()
        ReadOnlyTextInput:
            id: log_view
            readonly: True
            font_size: sp(10)
            background_color: 0.04, 0.05, 0.08, 1
            foreground_color: 0.65, 0.78, 0.85, 1
            padding: [dp(6), dp(6), dp(6), dp(6)]
'''

# ===================== 工具函数 =====================
def get_local_ip():
    """Get local LAN IPv4 address."""
    android_ip = get_android_wifi_ip()
    if android_ip:
        globals()["_LAST_LOCAL_IP"] = android_ip
        return android_ip

    for ip in get_android_interface_ips():
        globals()["_LAST_LOCAL_IP"] = ip
        return ip

    try:
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        test_socket.connect(("8.8.8.8", 80))
        local_ip = test_socket.getsockname()[0]
        test_socket.close()
        if not local_ip.startswith("127."):
            globals()["_LAST_LOCAL_IP"] = local_ip
            return local_ip
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127."):
                globals()["_LAST_LOCAL_IP"] = ip
                return ip
    except Exception:
        pass

    return "127.0.0.1"

def is_valid_ipv4(ip):
    """检查是否是合法IPv4地址"""
    try:
        socket.inet_aton(ip)
        return ip.count(".") == 3
    except OSError:
        return False


def is_valid_host_ip(ip):
    return is_valid_ipv4(ip) or is_valid_ipv6(ip)


def format_peer_address(ip, port=TCP_PORT):
    if is_valid_ipv6(ip):
        wrapped = f"[{ip}]"
        return f"{wrapped}:{port}" if int(port or TCP_PORT) != TCP_PORT else wrapped
    return f"{ip}:{port}" if int(port or TCP_PORT) != TCP_PORT else ip


def parse_peer_address(raw):
    """Parse manual peer input as IPv4/IPv6 with optional port. Returns (ip, port) or None."""
    value = (raw or "").strip().replace(" ", "").replace("\uff1a", ":")
    value = re.sub(r"^https?://", "", value, flags=re.IGNORECASE)
    if value.startswith("["):
        end = value.find("]")
        if end <= 0:
            return None
        host = value[1:end]
        rest = value[end + 1:]
        value = host
        port_text = None
        if rest.startswith(":"):
            port_text = rest[1:].split("/", 1)[0]
        elif rest.startswith("/"):
            port_text = None
        elif rest:
            return None
    else:
        value = value.split("/", 1)[0]
        port_text = None
    if not value:
        return None

    port = TCP_PORT
    ip = value
    if port_text is not None:
        if not port_text.isdigit():
            return None
        port = int(port_text)
        if port < 1 or port > 65535:
            return None
    elif value.count(":") == 1:
        ip, port_text = value.rsplit(":", 1)
        if not port_text.isdigit():
            return None
        port = int(port_text)
        if port < 1 or port > 65535:
            return None
    elif value.count(":") > 1 and not is_valid_ipv6(value):
        ip_part, maybe_port = value.rsplit(":", 1)
        if maybe_port.isdigit() and is_valid_ipv6(ip_part):
            ip = ip_part
            port = int(maybe_port)
            if port < 1 or port > 65535:
                return None

    ip = normalize_ipv6_host(ip)
    if not is_valid_host_ip(ip):
        return None
    return ip, port


def connect_tcp(host, port, timeout=8):
    """Open a TCP connection to an IPv4 or IPv6 literal."""
    family = socket.AF_INET6 if is_valid_ipv6(host) else socket.AF_INET
    last_error = None
    try:
        addr_infos = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
    except Exception:
        addr_infos = [(family, socket.SOCK_STREAM, 0, "", (host, port, 0, 0) if family == socket.AF_INET6 else (host, port))]
    for af, socktype, proto, _canon, sockaddr in addr_infos:
        sock = socket.socket(af, socktype, proto)
        try:
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
    if last_error:
        raise last_error
    raise OSError("connect failed")


def get_broadcast_targets(ip):
    """Return global and subnet broadcast targets for more reliable discovery."""
    targets = ["255.255.255.255"]
    if is_valid_ipv4(ip):
        parts = ip.split(".")
        subnet_target = ".".join(parts[:3] + ["255"])
        if subnet_target not in targets:
            targets.append(subnet_target)
    return targets

def sanitize_filename(filename):
    """把收到的文件名限制为安全的普通文件名"""
    filename = os.path.basename((filename or "code.py").strip())
    filename = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", filename)
    filename = filename.strip(" .")
    return filename or "code.py"

def make_unique_path(directory, filename):
    """同名文件已存在时自动加时间戳，避免覆盖历史接收内容"""
    filename = sanitize_filename(filename)
    path = os.path.join(directory, filename)
    if not os.path.exists(path):
        return path

    name, ext = os.path.splitext(filename)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(directory, f"{name}_{timestamp}{ext}")

def recv_exact(sock, size):
    """从TCP连接中精确读取指定字节数"""
    chunks = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(min(BUFFER_SIZE, remaining))
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)

def get_lexer_for_code(filename):
    """根据文件名选择语法高亮规则"""
    try:
        return get_lexer_for_filename(filename)
    except Exception:
        if filename.lower().endswith(".py"):
            return PythonLexer()
        return TextLexer()

def token_color(token_type):
    """把Pygments token映射为Kivy markup颜色"""
    current = token_type
    while current is not Token:
        if current in TOKEN_COLORS:
            return TOKEN_COLORS[current]
        current = current.parent
    return TOKEN_COLORS[Token]

def code_to_markup(code, filename="code.py"):
    """把代码转成Kivy可显示的彩色markup文本"""
    lexer = get_lexer_for_code(filename)
    lines = []
    for line_no, line in enumerate(code.splitlines() or [""], 1):
        highlighted = []
        for token_type, value in lex(line, lexer):
            escaped = escape_markup(value)
            highlighted.append(f"[color={token_color(token_type)}]{escaped}[/color]")
        lines.append(f"[color=5f7a95]{line_no:>3}[/color]  {''.join(highlighted)}")
    return "\n".join(lines)

# ===================== 主界面逻辑 =====================
class RootWidget(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.username = f"\u8bbe\u5907_{os.getpid()}"
        self.local_ip = "127.0.0.1"
        self.local_ipv6 = []
        self.save_dir = app_private_dir()
        self.multicast_lock = None
        self.network_started = False

        self.peers = {}
        self.peers_lock = threading.Lock()
        self.selected_peer_ip = None
        self.running = True
        self.layout_mode = None
        self.history = []

        self.ids.save_dir_label.text = self._save_status_text()
        self.update_char_count()
        self._update_responsive_layout(Window.width)
        Window.bind(size=lambda window, size: self._update_responsive_layout(size[0]))
        Clock.schedule_once(self._post_startup, 0.2)

    def _save_status_text(self):
        ipv6_count = len(getattr(self, "local_ipv6", []) or [])
        return f"{APP_VERSION}  \u672c\u673aIPv4\uff1a{self.local_ip}  IPv6\uff1a{ipv6_count}\u4e2a  \u4fdd\u5b58\u5230\uff1a{self.save_dir}"

    def _post_startup(self, dt):
        try:
            request_android_permissions()
        except Exception as e:
            self.add_log(f"权限请求跳过：{e}")

        try:
            self.local_ip = get_local_ip()
            self.local_ipv6 = get_local_ipv6_candidates()
        except Exception as e:
            self.local_ip = "127.0.0.1"
            self.add_log(f"获取本机IP失败：{e}")

        try:
            self.save_dir = default_save_dir()
            self.ids.save_dir_label.text = self._save_status_text()
        except Exception as e:
            self.add_log(f"保存目录初始化失败：{e}")

        try:
            self.multicast_lock = acquire_android_multicast_lock()
        except Exception:
            self.multicast_lock = None

        if not self.network_started:
            self.network_started = True
            for target in (self._udp_broadcast_sender, self._udp_broadcast_receiver, self._tcp_server, self._tcp_server_ipv6):
                try:
                    threading.Thread(target=target, daemon=True).start()
                except Exception as e:
                    self.add_log(f"网络线程启动失败：{e}")
            Clock.schedule_interval(self._check_peer_timeout, 1)

        self._refresh_header_labels()
        self.add_log(f"程序启动，本机IP：{self.local_ip}")
        self.add_log("正在搜索局域网内的在线设备…")
        self.add_log("若列表没有出现对方，请确认两台设备在同一Wi-Fi/热点，或手动输入对方IP直连")

    def add_log(self, message):
        """添加状态日志，自动滚动到底部"""
        Clock.schedule_once(lambda dt: self._append_log(message), 0)

    def _append_log(self, message):
        try:
            timestamp = time.strftime("%H:%M:%S")
            self.ids.log_view.text += f"[{timestamp}] {message}\n"
            lines = self.ids.log_view.text.splitlines()
            if lines and hasattr(self.ids.log_view, "cursor"):
                self.ids.log_view.cursor = (len(lines[-1]), len(lines) - 1)
        except Exception:
            pass

    def update_char_count(self):
        """更新输入框字符计数"""
        self.ids.char_count.text = f"{len(self.ids.code_input.text)} 字符"

    def _refresh_header_labels(self):
        """Keep the header readable on both desktop and phone widths."""
        if getattr(self, "layout_mode", None) == "mobile":
            self.ids.title_label.text = "\u7a0b\u5e8f\u5206\u4eab"
            self.ids.user_label.text = f"\u8bbe\u5907\n{self.username}"
        else:
            self.ids.title_label.text = f"\u5c40\u57df\u7f51\u7a0b\u5e8f\u5206\u4eab {APP_VERSION}"
            self.ids.user_label.text = f"\u7528\u6237\uff1a{self.username}"

    def _update_responsive_layout(self, width):
        """Switch between desktop columns and a phone-friendly stacked layout."""
        mode = "mobile" if width < dp(720) else "desktop"
        if mode == self.layout_mode:
            return

        self.layout_mode = mode
        main_area = self.ids.main_area
        send_panel = self.ids.send_panel
        peer_panel = self.ids.peer_panel
        receive_panel = self.ids.receive_panel
        top_bar = self.ids.top_bar
        log_panel = self.ids.log_panel

        if mode == "mobile":
            main_area.orientation = "vertical"
            main_area.spacing = dp(10)
            top_bar.height = dp(64)
            top_bar.padding = [dp(12), 0]
            top_bar.spacing = dp(6)
            send_panel.size_hint = (1, 0.37)
            peer_panel.size_hint = (1, 0.32)
            receive_panel.size_hint = (1, 0.31)
            log_panel.size_hint_y = 0.13
            self.ids.title_label.size_hint_x = None
            self.ids.title_label.font_size = sp(17)
            self.ids.title_label.width = dp(96)
            self.ids.user_label.width = dp(94)
            self.ids.user_label.font_size = sp(10)
            self.ids.status_label.width = dp(54)
            self.ids.status_label.font_size = sp(10)
            self.ids.pair_button.width = dp(58)
            self.ids.pair_button.font_size = sp(10)
            self.ids.settings_button.width = dp(54)
            self.ids.settings_button.font_size = sp(10)
            send_panel.padding = [dp(12), dp(12), dp(12), dp(12)]
            peer_panel.padding = [dp(12), dp(12), dp(12), dp(12)]
            receive_panel.padding = [dp(12), dp(12), dp(12), dp(12)]
            self.ids.save_dir_label.height = dp(34)
            self.ids.save_dir_label.font_size = sp(10)
        else:
            main_area.orientation = "horizontal"
            main_area.spacing = dp(8)
            top_bar.height = dp(50)
            top_bar.padding = [dp(10), 0]
            top_bar.spacing = dp(8)
            send_panel.size_hint = (0.45, 1)
            peer_panel.size_hint = (0.25, 1)
            receive_panel.size_hint = (0.30, 1)
            log_panel.size_hint_y = 0.20
            self.ids.title_label.size_hint_x = 1
            self.ids.title_label.font_size = sp(18)
            self.ids.user_label.width = dp(125)
            self.ids.user_label.font_size = sp(12)
            self.ids.status_label.width = dp(70)
            self.ids.status_label.font_size = sp(12)
            self.ids.pair_button.width = dp(70)
            self.ids.pair_button.font_size = sp(11)
            self.ids.settings_button.width = dp(60)
            self.ids.settings_button.font_size = sp(11)
            send_panel.padding = [dp(8), dp(8), dp(8), dp(8)]
            peer_panel.padding = [dp(8), dp(8), dp(8), dp(8)]
            receive_panel.padding = [dp(8), dp(8), dp(8), dp(8)]
            self.ids.save_dir_label.height = dp(26)
            self.ids.save_dir_label.font_size = sp(11)
        self._refresh_header_labels()

    def _add_history(self, direction, filename, content, peer):
        """记录最近发送/接收的代码"""
        item = {
            "direction": direction,
            "filename": sanitize_filename(filename),
            "content": content,
            "peer": peer,
            "time": time.strftime("%H:%M:%S")
        }
        self.history.insert(0, item)
        del self.history[MAX_HISTORY_ITEMS:]

    def _build_code_preview(self, filename, content):
        preview = Label(
            text=code_to_markup(content, filename),
            markup=True,
            font_name="CJK",
            font_size=sp(12),
            color=(0.86, 0.9, 0.96, 1),
            size_hint=(None, None),
            halign="left",
            valign="top",
            padding=(dp(10), dp(10))
        )
        def _resize_preview(widget, size):
            widget.size = (max(size[0], dp(720)), size[1])

        preview.bind(texture_size=_resize_preview)
        scroll = ScrollView(do_scroll_x=True, do_scroll_y=True)
        scroll.add_widget(preview)
        return scroll

    def show_code_preview(self, filename, content, title="代码预览"):
        """弹出语法高亮预览窗口"""
        if not content.strip():
            self.add_log("暂无代码可预览")
            return
        popup = Popup(
            title=f"{title} - {filename}",
            content=self._build_code_preview(filename, content),
            size_hint=(0.88, 0.88)
        )
        popup.open()

    def preview_send_code(self):
        filename = sanitize_filename(self.ids.filename_input.text)
        self.show_code_preview(filename, self.ids.code_input.text, "发送预览")

    def preview_received_code(self):
        filename = sanitize_filename(self.ids.recv_filename.text)
        self.show_code_preview(filename, self.ids.recv_view.text, "接收预览")

    def show_pair_qr(self):
        """显示本机配对二维码，扫码后可看到IP和端口"""
        pair_info = {
            "app": "lan-code-share",
            "version": 3,
            "name": self.username,
            "ip": self.local_ip,
            "ipv6": self.local_ipv6[:4],
            "port": TCP_PORT
        }
        pair_text = json.dumps(pair_info, ensure_ascii=False)
        qr_path = os.path.join(app_private_dir(), QR_FILENAME)
        img = qrcode.make(pair_text)
        img.save(qr_path)

        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(12))
        content.add_widget(Image(source=qr_path, allow_stretch=True, keep_ratio=True))
        ip_label = Label(
            text=f"IP: {self.local_ip}    IPv6: {len(self.local_ipv6)}    Port: {TCP_PORT}",
            size_hint_y=None,
            height=dp(28),
            font_size=sp(13),
            color=(0.92, 0.95, 1, 1)
        )
        copy_btn = Button(text="复制IP", size_hint_y=None, height=dp(38))
        content.add_widget(ip_label)
        content.add_widget(copy_btn)

        popup = Popup(title="本机配对码", content=content, size_hint=(0.6, 0.8))

        def _copy_ip(_):
            Clipboard.copy(self.local_ip)
            self.add_log("已复制本机IP")

        copy_btn.bind(on_release=_copy_ip)
        popup.open()

    def show_history(self):
        """显示发送/接收历史"""
        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        scroll = ScrollView(do_scroll_x=False)
        list_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        list_box.bind(minimum_height=list_box.setter("height"))
        scroll.add_widget(list_box)
        content.add_widget(scroll)

        popup = Popup(title="传输历史", content=content, size_hint=(0.82, 0.82))

        if not self.history:
            list_box.add_widget(Label(
                text="暂无历史记录",
                size_hint_y=None,
                height=dp(40),
                color=(0.65, 0.72, 0.82, 1)
            ))
        else:
            for index, item in enumerate(self.history):
                direction = "发送" if item["direction"] == "sent" else "接收"
                btn = Button(
                    text=f"{item['time']}  {direction}  {item['filename']}  {item['peer']}",
                    size_hint_y=None,
                    height=dp(42),
                    font_size=sp(11),
                    halign="left",
                    background_color=(0.16, 0.20, 0.28, 1),
                    color=(0.92, 0.95, 1, 1)
                )
                btn.bind(on_release=lambda _, i=index: self.open_history_item(i, popup))
                list_box.add_widget(btn)

        popup.open()

    def open_history_item(self, index, parent_popup=None):
        """打开单条历史，可复制、预览、回填到发送区"""
        if index >= len(self.history):
            return
        item = self.history[index]
        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        meta = Label(
            text=f"{item['time']}  {item['filename']}  {item['peer']}",
            size_hint_y=None,
            height=dp(28),
            font_size=sp(12),
            color=(0.65, 0.85, 1, 1)
        )
        content.add_widget(meta)
        content.add_widget(self._build_code_preview(item["filename"], item["content"]))

        button_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        copy_btn = Button(text="复制")
        load_btn = Button(text="放入发送区")
        close_btn = Button(text="关闭")
        button_row.add_widget(copy_btn)
        button_row.add_widget(load_btn)
        button_row.add_widget(close_btn)
        content.add_widget(button_row)

        popup = Popup(title="历史详情", content=content, size_hint=(0.88, 0.88))

        def _copy(_):
            Clipboard.copy(item["content"])
            self.add_log(f"已复制历史内容：{item['filename']}")

        def _load(_):
            self.ids.filename_input.text = item["filename"]
            self.ids.code_input.text = item["content"]
            self.add_log(f"已载入历史到发送区：{item['filename']}")
            if parent_popup:
                parent_popup.dismiss()
            popup.dismiss()

        copy_btn.bind(on_release=_copy)
        load_btn.bind(on_release=_load)
        close_btn.bind(on_release=lambda _: popup.dismiss())
        popup.open()

    # ---------- 剪贴板功能 ----------
    def paste_from_clipboard(self):
        """从剪贴板粘贴内容"""
        content = Clipboard.paste()
        if content:
            self.ids.code_input.text = content
            self.add_log("已从剪贴板粘贴内容")
        else:
            self.add_log("剪贴板为空")

    def copy_to_clipboard(self):
        """复制接收内容到剪贴板"""
        content = self.ids.recv_view.text
        if content:
            Clipboard.copy(content)
            self.add_log("已复制接收内容到剪贴板")
        else:
            self.add_log("暂无内容可复制")

    # ---------- 文件选择功能 ----------
    def open_file_chooser(self):
        """Open a code file. On Android, use SAF so content:// files can be read safely."""
        if platform == "android" and self._open_android_file_picker():
            return

        def _on_file_selected(selection):
            if not selection:
                return
            file_path = selection[0]
            try:
                with open(file_path, "r", encoding=ENCODING) as f:
                    content = f.read()
                self._apply_loaded_file(os.path.basename(file_path), content)
            except Exception as e:
                self.add_log(f"File read failed: {e}")

        if plyer_filechooser:
            plyer_filechooser.open_file(
                on_selection=_on_file_selected,
                filters=["*.py", "*.txt", "*.kv", "*.json", "*.md", "*.java", "*.c", "*.cpp", "*.h", "*.js"]
            )
        else:
            self._open_kivy_file_chooser(_on_file_selected)

    def _apply_loaded_file(self, filename, content):
        if len(content.encode(ENCODING)) > MAX_PAYLOAD_BYTES:
            self.add_log("File is larger than 10MB")
            return
        filename = sanitize_filename(filename)
        self.ids.code_input.text = content
        self.ids.filename_input.text = filename
        self.add_log(f"Loaded file: {filename}")

    def _open_android_file_picker(self):
        try:
            from android import activity as android_activity
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            NativeTextBridge = autoclass("org.tju.challenge.lancodeshare.NativeTextBridge")
            try:
                android_activity.unbind(on_activity_result=self.on_android_file_result)
            except Exception:
                pass
            android_activity.bind(on_activity_result=self.on_android_file_result)
            PythonActivity.mActivity.startActivityForResult(
                NativeTextBridge.createOpenDocumentIntent(),
                ANDROID_FILE_PICK_REQUEST,
            )
            self.add_log("File operation canceled")
            return True
        except Exception as exc:
            self.add_log(f"File operation failed: {exc}")
            return False

    def on_android_file_result(self, request_code, result_code, intent):
        if request_code != ANDROID_FILE_PICK_REQUEST:
            return
        try:
            from android import activity as android_activity
            from jnius import autoclass
            try:
                android_activity.unbind(on_activity_result=self.on_android_file_result)
            except Exception:
                pass
            Activity = autoclass("android.app.Activity")
            if result_code != Activity.RESULT_OK or intent is None:
                self.add_log("File operation canceled")
                return
            NativeTextBridge = autoclass("org.tju.challenge.lancodeshare.NativeTextBridge")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            uri = str(NativeTextBridge.extractResultUri(intent))
            filename = str(NativeTextBridge.getDisplayNameForUri(PythonActivity.mActivity, uri))
            threading.Thread(target=self._load_android_uri_thread, args=(uri, filename), daemon=True).start()
        except Exception as exc:
            self.add_log(f"File operation failed: {exc}")

    def _load_android_uri_thread(self, uri, filename):
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            NativeTextBridge = autoclass("org.tju.challenge.lancodeshare.NativeTextBridge")
            content = str(NativeTextBridge.readUriAsText(PythonActivity.mActivity, uri, ENCODING, MAX_PAYLOAD_BYTES))
            Clock.schedule_once(lambda dt: self._apply_loaded_file(filename, content), 0)
        except Exception as exc:
            self.add_log(f"File operation failed: {exc}")

    def _open_kivy_file_chooser(self, on_selection):
        """plyer不可用时使用Kivy内置文件选择器"""
        chooser = FileChooserListView(
            path=os.getcwd(),
            filters=["*.py", "*.txt", "*.kv"],
            size_hint_y=1
        )
        open_btn = Button(text="打开", size_hint_y=None, height=dp(40))
        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        content.add_widget(chooser)
        content.add_widget(open_btn)
        popup = Popup(title="选择代码文件", content=content, size_hint=(0.9, 0.9))

        def _confirm(_):
            on_selection(chooser.selection)
            popup.dismiss()

        open_btn.bind(on_release=_confirm)
        popup.open()

    # ---------- 设置功能 ----------
    def open_settings(self):
        """修改用户名设置弹窗"""
        content = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(15), size_hint_y=None, height=dp(120))
        name_input = TextInput(text=self.username, multiline=False, hint_text="输入你的用户名")
        confirm_btn = Button(text="确认", size_hint_y=None, height=dp(40))

        content.add_widget(Label(text="修改用户名", size_hint_y=None, height=dp(30)))
        content.add_widget(name_input)
        content.add_widget(confirm_btn)
        popup = Popup(title="设置", content=content, size_hint=(0.6, None), height=dp(200))

        def on_confirm(_):
            new_name = name_input.text.strip()
            if new_name:
                self.username = new_name
                self.ids.user_label.text = f"用户：{self.username}"
                self.add_log(f"用户名已修改为：{self.username}")
            popup.dismiss()

        confirm_btn.bind(on_release=on_confirm)
        popup.open()

    # ---------- 在线成员管理 ----------
    def _check_peer_timeout(self, dt):
        """定时检查并移除超时离线的设备"""
        now = time.time()
        with self.peers_lock:
            timeout_ips = [
                ip for ip, info in self.peers.items()
                if not info.get("manual") and now - info["last_seen"] > PEER_TIMEOUT
            ]
        for ip in timeout_ips:
            with self.peers_lock:
                info = self.peers.pop(ip, None)
            if not info:
                continue
            name = info["name"]
            if ip == self.selected_peer_ip:
                self.selected_peer_ip = None
                self.ids.selected_peer_label.text = "（未选择）"
            self.add_log(f"设备离线：{name}")
        if timeout_ips:
            self._refresh_peer_list_ui()

    @mainthread
    def _refresh_peer_list_ui(self):
        """Refresh peer list using clear device cards for Android stability."""
        peer_list = self.ids.peer_list_box
        peer_list.clear_widgets()
        with self.peers_lock:
            peers_snapshot = sorted(
                self.peers.items(),
                key=lambda item: (item[1].get("manual", False), item[1].get("name", ""), item[0])
            )

        selected_name = None
        for ip, info in peers_snapshot:
            if ip == self.selected_peer_ip:
                selected_name = info.get("name", f"\u8bbe\u5907 {ip}")
                break
        if selected_name:
            self.ids.selected_peer_label.text = f"\u5df2\u9009\u62e9\uff1a{selected_name}"
        elif not self.selected_peer_ip:
            self.ids.selected_peer_label.text = "\uff08\u672a\u9009\u62e9\uff09"

        if not peers_snapshot:
            empty_label = Label(
                text="\u6682\u65e0\u5728\u7ebf\u6210\u5458\n\u53ef\u7b49\u5f85\u81ea\u52a8\u53d1\u73b0\uff0c\u6216\u4f7f\u7528 IP \u76f4\u8fde",
                color=(0.55, 0.62, 0.72, 1),
                font_size=sp(11),
                size_hint_y=None,
                height=dp(52),
                halign="center",
                valign="middle"
            )
            empty_label.bind(size=lambda widget, size: setattr(widget, "text_size", size))
            peer_list.add_widget(empty_label)
        else:
            for ip, info in peers_snapshot:
                name = info.get("name", f"\u8bbe\u5907 {ip}")
                port = int(info.get("port", TCP_PORT) or TCP_PORT)
                address = format_peer_address(ip, port)
                tag = "\u624b\u52a8" if info.get("manual") else "\u5728\u7ebf"
                family = info.get("family") or ("IPv6" if is_valid_ipv6(ip) else "IPv4")
                display_name = f"{name} \u00b7 {tag} \u00b7 {family}\n{address}"
                selected = ip == self.selected_peer_ip
                btn = Button(
                    text=display_name,
                    size_hint_y=None,
                    height=dp(60),
                    background_normal="",
                    background_color=(0.10, 0.46, 0.92, 1) if selected else (0.10, 0.15, 0.23, 1),
                    color=(1, 1, 1, 1) if selected else (0.86, 0.92, 1, 1),
                    font_size=sp(11),
                    halign="left",
                    valign="middle"
                )
                btn.bind(size=lambda widget, size: setattr(widget, "text_size", (size[0] - dp(16), None)))
                btn.bind(on_release=lambda _btn, ip=ip, name=name: self._select_peer(ip, name))
                peer_list.add_widget(btn)

        device_keys = set()
        for ip, info in peers_snapshot:
            device_keys.add(info.get("name") or ip)
        self.ids.peer_count_label.text = f"\u5728\u7ebf {len(device_keys)} \u4eba"

    @mainthread
    def _select_peer(self, ip, name):
        """Select a receiver device."""
        self.selected_peer_ip = ip
        self.ids.selected_peer_label.text = f"\u5df2\u9009\u62e9\uff1a{name}"
        self._refresh_peer_list_ui()
        with self.peers_lock:
            port = int(self.peers.get(ip, {}).get("port", TCP_PORT) or TCP_PORT)
        self.add_log(f"\u9009\u4e2d\u63a5\u6536\u65b9\uff1a{name} ({format_peer_address(ip, port)})")

    def _remember_peer(self, ip, name, port=TCP_PORT, manual=False, family=None):
        ip = normalize_ipv6_host(ip)
        if not is_valid_host_ip(ip) or is_loopback_ip(ip):
            return False, False
        try:
            peer_port = int(port or TCP_PORT)
        except Exception:
            peer_port = TCP_PORT
        if peer_port < 1 or peer_port > 65535:
            peer_port = TCP_PORT

        local_candidates = set(get_local_ip_candidates() + [self.local_ip, "127.0.0.1", "::1"])
        if ip in local_candidates:
            return False, False

        peer_name = name or f"\u8bbe\u5907 {ip}"
        peer_family = family or ("IPv6" if is_valid_ipv6(ip) else "IPv4")
        refresh_needed = False
        is_new = False
        with self.peers_lock:
            old_info = self.peers.get(ip)
            is_new = old_info is None
            name_changed = bool(old_info and old_info.get("name") != peer_name)
            port_changed = bool(old_info and int(old_info.get("port", TCP_PORT) or TCP_PORT) != peer_port)
            family_changed = bool(old_info and old_info.get("family") != peer_family)
            self.peers[ip] = {
                "name": peer_name,
                "port": peer_port,
                "last_seen": time.time(),
                "manual": manual,
                "family": peer_family
            }
            if not self.selected_peer_ip:
                self.selected_peer_ip = ip
                refresh_needed = True
        return is_new, (is_new or name_changed or port_changed or family_changed or refresh_needed)

    def add_manual_peer(self):
        """Add a manual receiver as fallback when discovery is unavailable."""
        parsed = parse_peer_address(self.ids.manual_ip_input.text)
        if not parsed:
            self.add_log("\u8bf7\u8f93\u5165\u6b63\u786e\u7684\u5730\u5740\uff0c\u4f8b\u5982 192.168.1.23\u3001192.168.1.23:18889 \u6216 [IPv6]:18889")
            return

        ip, port = parsed
        try:
            self.local_ip = get_local_ip()
            self.local_ipv6 = get_local_ipv6_candidates()
        except Exception:
            pass
        local_candidates = set(get_local_ip_candidates() + [self.local_ip, "127.0.0.1", "::1"])
        if ip in local_candidates:
            self.add_log(f"\u4e0d\u80fd\u628a\u672c\u673a\u5730\u5740 {ip} \u6dfb\u52a0\u4e3a\u63a5\u6536\u65b9\u3002\u8bf7\u5728\u53e6\u4e00\u53f0\u8bbe\u5907\u4e0a\u67e5\u770b\u5e76\u8f93\u5165\u5bf9\u65b9IP\u3002")
            return

        old = self.peers.get(ip, {})
        peer_name = old.get("name") or f"\u624b\u52a8\u8bbe\u5907 {ip}"
        self._remember_peer(ip, peer_name, port, manual=True)

        self.selected_peer_ip = ip
        self.ids.manual_ip_input.text = format_peer_address(ip, port)
        self.ids.selected_peer_label.text = f"\u5df2\u9009\u62e9\uff1a{peer_name}"
        self._refresh_peer_list_ui()
        self.add_log(f"\u5df2\u6dfb\u52a0\u5907\u7528\u63a5\u6536\u65b9\uff1a{format_peer_address(ip, port)}")

    def _udp_broadcast_sender(self):
        """Broadcast local device info to both global and subnet broadcast addresses."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass

        while self.running:
            try:
                current_ip = get_local_ip()
                if is_valid_ipv4(current_ip) and not current_ip.startswith("127."):
                    self.local_ip = current_ip
                self.local_ipv6 = get_local_ipv6_candidates()

                payload = json.dumps({
                    "app": "lan-code-share",
                    "version": 3,
                    "kind": "announce",
                    "name": self.username,
                    "ip": self.local_ip,
                    "ipv6": self.local_ipv6[:4],
                    "port": TCP_PORT
                }).encode(ENCODING)

                for target in get_broadcast_targets(self.local_ip):
                    try:
                        sock.sendto(payload, (target, BROADCAST_PORT))
                    except Exception:
                        continue
            except Exception:
                pass
            time.sleep(max(1, BROADCAST_INTERVAL))
        sock.close()

    def _udp_broadcast_receiver(self):
        """Receive broadcast announcements and keep nearby devices updated."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", BROADCAST_PORT))
            sock.settimeout(1)
        except Exception as e:
            self.add_log(f"\u8bbe\u5907\u53d1\u73b0\u670d\u52a1\u542f\u52a8\u5931\u8d25\uff1a{e}")
            sock.close()
            return

        while self.running:
            try:
                data, addr = sock.recvfrom(BUFFER_SIZE)
                peer_info = json.loads(data.decode(ENCODING))
                app_name = peer_info.get("app")
                if app_name not in (None, "lan-code-share"):
                    continue

                peer_ip = peer_info.get("ip") or addr[0]
                if (not is_valid_ipv4(peer_ip)) or peer_ip.startswith("127."):
                    peer_ip = addr[0]

                try:
                    peer_port = int(peer_info.get("port", TCP_PORT))
                except Exception:
                    peer_port = TCP_PORT
                if peer_port < 1 or peer_port > 65535:
                    peer_port = TCP_PORT

                peer_name = peer_info.get("name") or f"\u8bbe\u5907 {peer_ip}"
                changed = False
                discovered = []

                is_new, need_refresh = self._remember_peer(peer_ip, peer_name, peer_port, manual=False, family="IPv4")
                if is_new:
                    discovered.append(peer_ip)
                changed = changed or need_refresh

                for ipv6 in peer_info.get("ipv6", []) or []:
                    ipv6 = normalize_ipv6_host(str(ipv6))
                    if not is_valid_ipv6(ipv6) or is_loopback_ip(ipv6):
                        continue
                    is_new_v6, need_refresh_v6 = self._remember_peer(ipv6, peer_name, peer_port, manual=False, family="IPv6")
                    if is_new_v6:
                        discovered.append(ipv6)
                    changed = changed or need_refresh_v6

                for found_ip in discovered:
                    self.add_log(f"\u53d1\u73b0\u8bbe\u5907\uff1a{peer_name} ({found_ip})")
                if changed:
                    Clock.schedule_once(lambda dt: self._refresh_peer_list_ui(), 0)
            except socket.timeout:
                continue
            except Exception:
                continue
        sock.close()

    def _tcp_server(self):
        """TCP服务端线程：监听并接收代码"""
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            server_sock.bind(("", TCP_PORT))
            server_sock.listen(5)
            server_sock.settimeout(1)
            Clock.schedule_once(lambda dt: setattr(self.ids.status_label, 'text', "已就绪"), 0)
            Clock.schedule_once(lambda dt: setattr(self.ids.status_label, 'color', (0.4, 0.9, 0.5, 1)), 0)
        except Exception as e:
            self.add_log(f"端口占用，服务启动失败：{e}")
            return

        while self.running:
            try:
                client_sock, addr = server_sock.accept()
                threading.Thread(target=self._handle_tcp_client, args=(client_sock, addr), daemon=True).start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.add_log(f"连接异常：{e}")
        server_sock.close()

    def _tcp_server_ipv6(self):
        """Best-effort IPv6 TCP listener. IPv4 remains the primary fallback."""
        try:
            server_sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        except OSError:
            return
        try:
            server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "IPV6_V6ONLY"):
                server_sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        except Exception:
            pass

        try:
            server_sock.bind(("::", TCP_PORT))
            server_sock.listen(5)
            server_sock.settimeout(1)
            self.add_log("IPv6 接收接口已启用")
        except Exception as e:
            self.add_log(f"IPv6 接收接口未启用：{e}")
            server_sock.close()
            return

        while self.running:
            try:
                client_sock, addr = server_sock.accept()
                threading.Thread(target=self._handle_tcp_client, args=(client_sock, addr), daemon=True).start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.add_log(f"IPv6 连接异常：{e}")
        server_sock.close()

    def _handle_tcp_client(self, sock, addr):
        """处理单个TCP连接，接收完整代码数据"""
        try:
            # 先读取4字节数据长度，解决TCP粘包问题
            length_bytes = recv_exact(sock, 4)
            if not length_bytes:
                return
            data_length = int.from_bytes(length_bytes, 'big')
            if data_length <= 0 or data_length > MAX_PAYLOAD_BYTES:
                raise ValueError("数据大小异常，已拒绝接收")

            received_data = recv_exact(sock, data_length)
            if received_data is None:
                raise ConnectionError("连接中断，数据未接收完整")

            payload = json.loads(received_data.decode(ENCODING))
            filename = sanitize_filename(payload.get("filename", "unknown.py"))
            code_content = payload.get("content", "")
            sender = payload.get("sender", "未知用户")

            # 切回主线程更新界面
            Clock.schedule_once(lambda dt: self._update_receive_ui(filename, code_content, sender, addr[0]), 0)

            # 自动保存到本地
            save_path = make_unique_path(self.save_dir, filename)
            with open(save_path, "w", encoding=ENCODING) as f:
                f.write(code_content)
                f.flush()
                os.fsync(f.fileno())
            android_scan_file(save_path)
            try:
                sock.sendall(b"OK")
            except Exception:
                pass
            saved_name = os.path.basename(save_path)
            self.add_log(f"接收完成：{filename}，已保存为 {saved_name}")

        except Exception as e:
            self.add_log(f"接收失败：{str(e)}")
        finally:
            sock.close()

    def _update_receive_ui(self, filename, content, sender, ip):
        """更新接收区界面"""
        self.ids.recv_filename.text = filename
        self.ids.recv_meta.text = f"来自：{sender} ({ip})"
        self.ids.recv_view.text = content
        self._add_history("received", filename, content, f"{sender} ({ip})")

    # ---------- TCP客户端：发送代码 ----------
    def send_code(self):
        """发送代码按钮触发"""
        if not self.selected_peer_ip:
            self.add_log("请先在中间列表选择接收方")
            return
        filename = sanitize_filename(self.ids.filename_input.text)
        self.ids.filename_input.text = filename
        code_content = self.ids.code_input.text
        if not code_content.strip():
            self.add_log("发送内容不能为空")
            return
        if len(code_content.encode(ENCODING)) > MAX_PAYLOAD_BYTES:
            self.add_log("发送内容超过10MB，请拆分后再发送")
            return

        threading.Thread(
            target=self._send_code_thread,
            args=(self.selected_peer_ip, filename, code_content),
            daemon=True
        ).start()

    def _send_code_thread(self, target_ip, filename, content):
        """Send code in a worker thread."""
        with self.peers_lock:
            peer_info = self.peers.get(target_ip)
        if not peer_info:
            self.add_log("接收方已离线")
            return

        try:
            self.local_ip = get_local_ip()
            self.local_ipv6 = get_local_ipv6_candidates()
        except Exception:
            pass
        local_candidates = set(get_local_ip_candidates() + [self.local_ip, "127.0.0.1", "::1"])
        if target_ip in local_candidates:
            self.add_log(f"发送失败：{target_ip} 是本机地址。请在另一台设备上查看接收方IP，或等待自动发现后选择对方设备。")
            return

        target_port = int(peer_info.get("port", TCP_PORT) or TCP_PORT)
        target_address = format_peer_address(target_ip, target_port)
        self.add_log(f"正在向 {peer_info['name']} ({target_address}) 发送…")

        try:
            with connect_tcp(target_ip, target_port, timeout=8) as sock:
                payload = json.dumps({
                    "filename": filename,
                    "content": content,
                    "sender": self.username
                }).encode(ENCODING)
                sock.sendall(len(payload).to_bytes(4, 'big'))
                sock.sendall(payload)
                try:
                    sock.settimeout(3)
                    ack = sock.recv(2)
                except socket.timeout:
                    ack = b""
                if ack != b"OK":
                    self.add_log("发送完成，但未收到对方确认；请查看接收方记录")
                    return
            self.add_log(f"发送成功：{filename}")
            Clock.schedule_once(
                lambda dt: self._add_history("sent", filename, content, f"{peer_info['name']} ({target_ip})"),
                0
            )
        except OSError as e:
            unreachable = {getattr(errno, "EHOSTUNREACH", 113), getattr(errno, "ENETUNREACH", 101), 113, 101}
            if getattr(e, "errno", None) in unreachable:
                self.add_log("发送失败：无法到达对方设备。请确认两台设备连接同一Wi-Fi/热点，关闭VPN/移动数据切换；校园网可能开启客户端隔离，需换热点或使用中继模式。")
            elif getattr(e, "errno", None) in {getattr(errno, "ECONNREFUSED", 111), 111, 10061}:
                self.add_log("发送失败：对方未启动接收服务，或端口被系统/防火墙拦截。请让对方重新打开应用并等待显示已就绪。")
            else:
                self.add_log(f"发送失败：{str(e)}")
        except Exception as e:
            self.add_log(f"发送失败：{str(e)}")

    def clear_received(self):
        """清空接收区"""
        self.ids.recv_filename.text = "—"
        self.ids.recv_meta.text = "等待代码…"
        self.ids.recv_view.text = ""
        self.add_log("已清空接收区")

    def clear_log(self):
        """清空日志"""
        self.ids.log_view.text = ""

    def on_stop(self):
        """Stop worker threads and release Android network locks."""
        self.running = False
        lock = getattr(self, "multicast_lock", None)
        if lock:
            try:
                if lock.isHeld():
                    lock.release()
            except Exception:
                pass

# ===================== 应用入口 =====================
class CodeShareApp(App):
    def build(self):
        self.title = f"\u5c40\u57df\u7f51\u7a0b\u5e8f\u5206\u4eab {APP_VERSION}"
        self.icon = "assets/icon.png"
        try:
            Builder.load_string(KV_STRING)
            return RootWidget()
        except Exception:
            err = traceback.format_exc()
            try:
                crash_path = os.path.join(os.getcwd(), "startup_crash.log")
                with open(crash_path, "w", encoding="utf-8") as f:
                    f.write(err)
            except Exception:
                pass
            box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
            box.add_widget(Label(text="启动失败，错误信息如下：", size_hint_y=None, height=dp(36)))
            box.add_widget(Label(text=err, font_size=sp(10), halign="left", valign="top"))
            return box

    def on_stop(self):
        if hasattr(self.root, 'on_stop'):
            self.root.on_stop()

if __name__ == "__main__":
    CodeShareApp().run()
