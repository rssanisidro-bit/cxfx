# -*- coding: utf-8 -*-
import socket
import threading
import json
import time
import os
import re
from pathlib import Path
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.lang import Builder
from kivy.metrics import dp, sp
from kivy.core.clipboard import Clipboard
from kivy.clock import Clock
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

os.environ.setdefault("KIVY_NO_ARGS", "1")

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
KV_STRING = '''
#:import dp kivy.metrics.dp
#:import sp kivy.metrics.sp

<Label>:
    font_name: "CJK"

<Button>:
    font_name: "CJK"

<ToggleButton>:
    font_name: "CJK"

<TextInput>:
    font_name: "CJK"

<RootWidget>:
    orientation: "vertical"
    padding: dp(10)
    spacing: dp(8)
    canvas.before:
        Color:
            rgba: 0.07, 0.09, 0.13, 1
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
                rgba: 0.13, 0.17, 0.24, 1
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
            text: "配对码"
            size_hint_x: None
            width: dp(70)
            font_size: sp(11)
            background_color: 0.20, 0.24, 0.32, 1
            color: 1, 1, 1, 1
            on_release: root.show_pair_qr()
        Button:
            text: "设置"
            size_hint_x: None
            width: dp(60)
            background_color: 0.20, 0.24, 0.32, 1
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
                    rgba: 0.11, 0.14, 0.20, 1
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
                    background_color: 0.20, 0.24, 0.32, 1
                    color: 1, 1, 1, 1
                    on_release: root.open_file_chooser()
                Button:
                    text: "粘贴"
                    background_color: 0.20, 0.24, 0.32, 1
                    color: 1, 1, 1, 1
                    on_release: root.paste_from_clipboard()
                Button:
                    text: "预览"
                    background_color: 0.20, 0.24, 0.32, 1
                    color: 1, 1, 1, 1
                    on_release: root.preview_send_code()
                Button:
                    text: "发送"
                    background_color: 0.31, 0.55, 1, 1
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
                    rgba: 0.11, 0.14, 0.20, 1
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
                    hint_text: "输入对方IP"
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
                    background_color: 0.20, 0.24, 0.32, 1
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
                    rgba: 0.11, 0.14, 0.20, 1
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
                    background_color: 0.20, 0.24, 0.32, 1
                    color: 1, 1, 1, 1
                    on_release: root.show_history()
                Button:
                    text: "清空"
                    size_hint_x: None
                    width: dp(56)
                    font_size: sp(11)
                    background_color: 0.20, 0.24, 0.32, 1
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

            TextInput:
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
                background_color: 0.31, 0.55, 1, 1
                color: 1, 1, 1, 1
                bold: True
                on_release: root.copy_to_clipboard()

            Button:
                text: "高亮预览"
                size_hint_y: None
                height: dp(34)
                background_color: 0.20, 0.24, 0.32, 1
                color: 1, 1, 1, 1
                on_release: root.preview_received_code()

    # 底部状态日志
    BoxLayout:
        size_hint_y: 0.20
        orientation: "vertical"
        padding: dp(6)
        spacing: dp(4)
        canvas.before:
            Color:
                rgba: 0.09, 0.11, 0.16, 1
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
                background_color: 0.18, 0.22, 0.30, 1
                color: 1, 1, 1, 1
                on_release: root.clear_log()
        TextInput:
            id: log_view
            readonly: True
            font_size: sp(10)
            background_color: 0.04, 0.05, 0.08, 1
            foreground_color: 0.65, 0.78, 0.85, 1
            padding: [dp(6), dp(6), dp(6), dp(6)]
'''

# ===================== 工具函数 =====================
def get_local_ip():
    """获取本机局域网IP地址"""
    try:
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        test_socket.connect(("8.8.8.8", 80))
        local_ip = test_socket.getsockname()[0]
        test_socket.close()
        if not local_ip.startswith("127."):
            return local_ip
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127."):
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
        # 基础配置
        self.username = f"用户_{os.getpid()}"
        self.local_ip = get_local_ip()
        self.save_dir = default_save_dir()

        # 在线成员管理
        self.peers = {}
        self.peers_lock = threading.Lock()
        self.selected_peer_ip = None
        self.running = True
        self.layout_mode = None
        self.history = []

        # 初始化UI
        self.ids.user_label.text = f"用户：{self.username}"
        self.ids.save_dir_label.text = f"保存到：{self.save_dir}"
        self.update_char_count()
        self._update_responsive_layout(Window.width)
        Window.bind(size=lambda window, size: self._update_responsive_layout(size[0]))

        # 启动网络线程
        threading.Thread(target=self._udp_broadcast_sender, daemon=True).start()
        threading.Thread(target=self._udp_broadcast_receiver, daemon=True).start()
        threading.Thread(target=self._tcp_server, daemon=True).start()

        # 定时检查离线设备
        Clock.schedule_interval(self._check_peer_timeout, 1)

        self.add_log(f"程序启动，本机IP：{self.local_ip}")
        self.add_log("正在搜索局域网内的在线设备…")
        self.add_log("若列表没有出现对方，可让对方查看本机IP后手动直连")

    # ---------- 基础工具方法 ----------
    def add_log(self, message):
        """添加状态日志，自动滚动到底部"""
        Clock.schedule_once(lambda dt: self._append_log(message), 0)

    def _append_log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.ids.log_view.text += f"[{timestamp}] {message}\n"
        lines = self.ids.log_view.text.splitlines()
        if lines:
            self.ids.log_view.cursor = (len(lines[-1]), len(lines) - 1)

    def update_char_count(self):
        """更新输入框字符计数"""
        self.ids.char_count.text = f"{len(self.ids.code_input.text)} 字符"

    def _update_responsive_layout(self, width):
        """根据窗口宽度在桌面三栏和手机上下布局之间切换"""
        mode = "mobile" if width < dp(720) else "desktop"
        if mode == self.layout_mode:
            return

        self.layout_mode = mode
        main_area = self.ids.main_area
        send_panel = self.ids.send_panel
        peer_panel = self.ids.peer_panel
        receive_panel = self.ids.receive_panel

        if mode == "mobile":
            main_area.orientation = "vertical"
            send_panel.size_hint = (1, 0.50)
            peer_panel.size_hint = (1, 0.22)
            receive_panel.size_hint = (1, 0.28)
            self.ids.title_label.font_size = sp(14)
            self.ids.user_label.width = dp(88)
            self.ids.status_label.width = dp(56)
        else:
            main_area.orientation = "horizontal"
            send_panel.size_hint = (0.45, 1)
            peer_panel.size_hint = (0.25, 1)
            receive_panel.size_hint = (0.30, 1)
            self.ids.title_label.font_size = sp(18)
            self.ids.user_label.width = dp(125)
            self.ids.status_label.width = dp(70)

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
            "name": self.username,
            "ip": self.local_ip,
            "port": TCP_PORT
        }
        pair_text = json.dumps(pair_info, ensure_ascii=False)
        qr_path = os.path.join(app_private_dir(), QR_FILENAME)
        img = qrcode.make(pair_text)
        img.save(qr_path)

        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(12))
        content.add_widget(Image(source=qr_path, allow_stretch=True, keep_ratio=True))
        ip_label = Label(
            text=f"IP：{self.local_ip}    端口：{TCP_PORT}",
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
        """????????????????Android ?? SAF??? content:// ???????"""
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
                self.add_log(f"???????{e}")

        if plyer_filechooser:
            plyer_filechooser.open_file(
                on_selection=_on_file_selected,
                filters=["*.py", "*.txt", "*.kv", "*.json", "*.md", "*.java", "*.c", "*.cpp", "*.h", "*.js"]
            )
        else:
            self._open_kivy_file_chooser(_on_file_selected)

    def _apply_loaded_file(self, filename, content):
        if len(content.encode(ENCODING)) > MAX_PAYLOAD_BYTES:
            self.add_log("????10MB????????")
            return
        filename = sanitize_filename(filename)
        self.ids.code_input.text = content
        self.ids.filename_input.text = filename
        self.add_log(f"??????{filename}")

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
            self.add_log("??????????")
            return True
        except Exception as exc:
            self.add_log(f"???????????????????{exc}")
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
                self.add_log("???????")
                return
            NativeTextBridge = autoclass("org.tju.challenge.lancodeshare.NativeTextBridge")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            uri = str(NativeTextBridge.extractResultUri(intent))
            filename = str(NativeTextBridge.getDisplayNameForUri(PythonActivity.mActivity, uri))
            threading.Thread(target=self._load_android_uri_thread, args=(uri, filename), daemon=True).start()
        except Exception as exc:
            self.add_log(f"???????{exc}")

    def _load_android_uri_thread(self, uri, filename):
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            NativeTextBridge = autoclass("org.tju.challenge.lancodeshare.NativeTextBridge")
            content = str(NativeTextBridge.readUriAsText(PythonActivity.mActivity, uri, ENCODING, MAX_PAYLOAD_BYTES))
            Clock.schedule_once(lambda dt: self._apply_loaded_file(filename, content), 0)
        except Exception as exc:
            self.add_log(f"???????{exc}")

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

    def _refresh_peer_list_ui(self):
        """刷新在线成员列表界面"""
        peer_list = self.ids.peer_list_box
        peer_list.clear_widgets()
        with self.peers_lock:
            peers_snapshot = list(self.peers.items())

        if not peers_snapshot:
            empty_label = Label(
                text="暂无在线成员",
                color=(0.5, 0.55, 0.65, 1),
                font_size=sp(11),
                size_hint_y=None,
                height=dp(28),
                halign="center",
                valign="middle"
            )
            peer_list.add_widget(empty_label)
        else:
            for ip, info in peers_snapshot:
                display_name = f"{info['name']}\n{ip}"
                btn = ToggleButton(
                    text=display_name,
                    size_hint_y=None,
                    height=dp(42),
                    background_color=(0.15, 0.2, 0.3, 1),
                    background_down=(0.31, 0.55, 1, 1),
                    color=(0.9, 0.95, 1, 1),
                    font_size=sp(11),
                    group="peer_group"
                )
                if ip == self.selected_peer_ip:
                    btn.state = "down"
                btn.bind(on_release=lambda b, ip=ip, name=info["name"]: self._select_peer(ip, name))
                peer_list.add_widget(btn)

        self.ids.peer_count_label.text = f"在线 {len(peers_snapshot)} 人"

    def _select_peer(self, ip, name):
        """选中接收方设备"""
        self.selected_peer_ip = ip
        self.ids.selected_peer_label.text = f"已选择：{name}"
        self.add_log(f"选中接收方：{name} ({ip})")

    def add_manual_peer(self):
        """手动添加接收方IP，作为UDP发现失败时的备用连接方式"""
        ip = self.ids.manual_ip_input.text.strip()
        if not is_valid_ipv4(ip):
            self.add_log("请输入正确的IPv4地址，例如 192.168.1.23")
            return
        if ip == self.local_ip:
            self.add_log("不能把本机IP添加为接收方")
            return

        name = f"手动设备 {ip}"
        with self.peers_lock:
            self.peers[ip] = {
                "name": name,
                "port": TCP_PORT,
                "last_seen": time.time(),
                "manual": True
            }

        self.selected_peer_ip = ip
        self.ids.selected_peer_label.text = f"已选择：{name}"
        self._refresh_peer_list_ui()
        self.add_log(f"已手动添加接收方：{ip}")

    # ---------- UDP设备发现 ----------
    def _udp_broadcast_sender(self):
        """UDP广播发送线程：定时广播本机信息"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while self.running:
            try:
                data = json.dumps({
                    "name": self.username,
                    "ip": self.local_ip,
                    "port": TCP_PORT
                }).encode(ENCODING)
                sock.sendto(data, ("255.255.255.255", BROADCAST_PORT))
            except Exception:
                pass
            time.sleep(BROADCAST_INTERVAL)
        sock.close()

    def _udp_broadcast_receiver(self):
        """UDP广播接收线程：发现其他在线设备"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", BROADCAST_PORT))
            sock.settimeout(1)
        except Exception as e:
            self.add_log(f"设备发现服务启动失败：{e}")
            sock.close()
            return

        while self.running:
            try:
                data, addr = sock.recvfrom(BUFFER_SIZE)
                peer_info = json.loads(data.decode(ENCODING))
                peer_ip = peer_info.get("ip") or addr[0]
                if peer_ip == self.local_ip:
                    continue

                with self.peers_lock:
                    old_info = self.peers.get(peer_ip)
                    is_new = old_info is None
                    name_changed = old_info and old_info.get("name") != peer_info.get("name")
                    self.peers[peer_ip] = {
                        "name": peer_info.get("name", f"设备 {peer_ip}"),
                        "port": int(peer_info.get("port", TCP_PORT)),
                        "last_seen": time.time(),
                        "manual": False
                    }

                if is_new:
                    self.add_log(f"发现新设备：{peer_info.get('name', peer_ip)} ({peer_ip})")
                if is_new or name_changed:
                    Clock.schedule_once(lambda dt: self._refresh_peer_list_ui(), 0)
            except socket.timeout:
                continue
            except Exception:
                continue
        sock.close()

    # ---------- TCP服务端：接收代码 ----------
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
        """发送代码子线程，避免阻塞UI"""
        with self.peers_lock:
            peer_info = self.peers.get(target_ip)
        if not peer_info:
            self.add_log("接收方已离线")
            return

        target_port = peer_info["port"]
        self.add_log(f"正在向 {peer_info['name']} 发送…")

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(8)
                sock.connect((target_ip, target_port))

                payload = json.dumps({
                    "filename": filename,
                    "content": content,
                    "sender": self.username
                }).encode(ENCODING)

                # 先发送数据长度，再发送实际内容
                sock.sendall(len(payload).to_bytes(4, 'big'))
                sock.sendall(payload)
            self.add_log(f"发送成功：{filename}")
            Clock.schedule_once(
                lambda dt: self._add_history("sent", filename, content, f"{peer_info['name']} ({target_ip})"),
                0
            )

        except Exception as e:
            self.add_log(f"发送失败：{str(e)}")

    # ---------- 清空功能 ----------
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
        """程序退出时停止所有线程"""
        self.running = False

# ===================== 应用入口 =====================
class CodeShareApp(App):
    def build(self):
        Builder.load_string(KV_STRING)
        self.title = "局域网代码分享"
        return RootWidget()

    def on_stop(self):
        if hasattr(self.root, 'on_stop'):
            self.root.on_stop()

if __name__ == "__main__":
    CodeShareApp().run()
