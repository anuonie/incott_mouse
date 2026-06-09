"""
鼠标控件主窗口
明亮主题悬浮窗，显示鼠标电量、连接状态
"""

import sys
import os
import ctypes
import ctypes.wintypes

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSystemTrayIcon,
    QMenu, QAction, QGraphicsDropShadowEffect
)
from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF, pyqtSignal, QPropertyAnimation, QEasingCurve, pyqtProperty, QObject
from PyQt5.QtGui import (
    QPainter, QColor, QFont, QPen, QLinearGradient,
    QConicalGradient, QRadialGradient, QBrush, QPainterPath, QIcon
)
import math


class _MouseHook(QObject):
    """全局鼠标钩子，监控左右键和滚轮动作"""
    left_pressed = pyqtSignal(bool)
    right_pressed = pyqtSignal(bool)
    scroll_event = pyqtSignal()

    WH_MOUSE_LL = 14
    WM_LBUTTONDOWN = 0x0201
    WM_LBUTTONUP   = 0x0202
    WM_RBUTTONDOWN = 0x0204
    WM_RBUTTONUP   = 0x0205
    WM_MOUSEWHEEL  = 0x020A

    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("pt", ctypes.wintypes.POINT),
            ("mouseData", ctypes.wintypes.DWORD),
            ("flags", ctypes.wintypes.DWORD),
            ("time", ctypes.wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    HOOKPROC = ctypes.WINFUNCTYPE(
        ctypes.c_long,
        ctypes.c_int,
        ctypes.wintypes.WPARAM,
        ctypes.wintypes.LPARAM,
    )

    def __init__(self):
        super().__init__()
        self._hook_id = None
        self._proc = self.HOOKPROC(self._hook_handler)
        self._install()

    def _install(self):
        try:
            # 正确设置 CallNextHookEx 参数类型（兼容64位）
            user32 = ctypes.windll.user32
            user32.CallNextHookEx.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.wintypes.WPARAM,
                ctypes.wintypes.LPARAM,
            ]
            user32.CallNextHookEx.restype = ctypes.c_long
            self._hook_id = user32.SetWindowsHookExW(
                self.WH_MOUSE_LL, self._proc, None, 0
            )
        except Exception:
            pass

    def uninstall(self):
        if self._hook_id:
            try:
                ctypes.windll.user32.UnhookWindowsHookEx(self._hook_id)
            except Exception:
                pass
            self._hook_id = None

    def _hook_handler(self, nCode, wParam, lParam):
        if nCode >= 0:
            if wParam == self.WM_LBUTTONDOWN:
                self.left_pressed.emit(True)
            elif wParam == self.WM_LBUTTONUP:
                self.left_pressed.emit(False)
            elif wParam == self.WM_RBUTTONDOWN:
                self.right_pressed.emit(True)
            elif wParam == self.WM_RBUTTONUP:
                self.right_pressed.emit(False)
            elif wParam == self.WM_MOUSEWHEEL:
                self.scroll_event.emit()
        return ctypes.windll.user32.CallNextHookEx(self._hook_id, nCode, wParam, lParam)


class _ToggleSwitch(QWidget):
    """自定义滑块开关：pill轨道 + 圆圈左右滑动"""
    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(42, 24)
        self._checked = False
        self._knob_x = 2.0  # 圆圈x偏移

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        self._checked = checked
        self._knob_x = 18.0 if checked else 2.0
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._checked = not self._checked
            # 动画
            self._anim = QPropertyAnimation(self, b'knob_x', self)
            self._anim.setDuration(120)
            self._anim.setStartValue(self._knob_x)
            self._anim.setEndValue(18.0 if self._checked else 2.0)
            self._anim.setEasingCurve(QEasingCurve.InOutQuad)
            self._anim.start()
            self.toggled.emit(self._checked)

    def get_knob_x(self):
        return self._knob_x

    def set_knob_x(self, v):
        self._knob_x = v
        self.update()

    knob_x = pyqtProperty(float, get_knob_x, set_knob_x)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2
        # 轨道
        track_color = QColor(0, 184, 120) if self._checked else QColor(208, 208, 218)
        p.setPen(Qt.NoPen)
        p.setBrush(track_color)
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)
        # 圆圈
        knob_r = 9
        p.setBrush(Qt.white)
        p.drawEllipse(QPointF(self._knob_x + knob_r, h / 2), knob_r, knob_r)
        p.end()


class MouseWidget(QWidget):
    """鼠标控件主窗口"""

    def __init__(self, battery_monitor):
        super().__init__()
        self.monitor = battery_monitor

        # 窗口状态
        self._dragging = False
        self._drag_pos = None
        self._battery_pct = 0
        self._target_pct = 0
        self._warned_low = False
        self._glow_phase = 0.0
        self._left_pressed = False
        self._right_pressed = False
        self._scroll_alpha = 0  # 滚轮发光效果

        # 明亮主题颜色
        self.C_BG = QColor(255, 255, 255)
        self.C_CARD = QColor(248, 248, 252)
        self.C_BORDER = QColor(225, 225, 235)
        self.C_TEXT = QColor(40, 40, 60)
        self.C_TEXT2 = QColor(130, 130, 155)
        self.C_ACCENT = QColor(0, 180, 135)
        self.C_GREEN = QColor(0, 190, 120)
        self.C_YELLOW = QColor(230, 170, 20)
        self.C_RED = QColor(230, 60, 60)
        self.C_MOUSE = QColor(210, 210, 220)
        self.C_MOUSE_BTN = QColor(225, 225, 235)

        self._init_window()
        self._build_ui()
        self._init_timers()
        self._init_tray()
        self._init_mouse_hook()

    # ───────── 窗口初始化 ─────────

    def _init_window(self):
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Window
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(330, 540)
        self.setWindowIcon(self._make_mouse_icon())

    # ───────── UI 构建 ─────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(0)

        container = QWidget()
        container.setStyleSheet(
            "background:rgba(255,255,255,250);border-radius:18px;"
        )
        lay = QVBoxLayout(container)
        lay.setContentsMargins(18, 14, 18, 18)
        lay.setSpacing(12)

        # 标题栏
        lay.addLayout(self._build_title_bar())
        # 鼠标绘制区 (自定义绘制)
        self.mouse_area = _MouseArea(self)
        self.mouse_area.setFixedHeight(210)
        lay.addWidget(self.mouse_area)
        # 电量条
        lay.addLayout(self._build_battery_bar())
        # 连接状态卡片
        lay.addLayout(self._build_conn_card())
        # DPI / 回报率卡片
        lay.addLayout(self._build_dpi_card())
        # 设备信息卡片
        lay.addLayout(self._build_info_card())
        # 开机自启动开关
        lay.addLayout(self._build_autostart_row())
        lay.addStretch()
        # 低电量警告
        self.warn_lbl = QLabel("⚠  电量不足，请尽快充电！")
        self.warn_lbl.setAlignment(Qt.AlignCenter)
        self.warn_lbl.setStyleSheet(
            "color:#e03c3c;background:rgba(230,60,60,18);"
            "border-radius:8px;padding:7px;font-size:12px;font-weight:bold;"
        )
        self.warn_lbl.hide()
        lay.addWidget(self.warn_lbl)

        root.addWidget(container)

    def _build_title_bar(self):
        h = QHBoxLayout()
        t = QLabel("🖱  鼠标控件")
        t.setStyleSheet("color:#2a2a3c;font-size:15px;font-weight:bold;border:none;")
        h.addWidget(t)
        h.addStretch()
        # 关闭（最小化到托盘）
        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(28, 28)
        self.btn_close.setStyleSheet(self._circle_btn_style())
        self.btn_close.clicked.connect(self._on_close)
        h.addWidget(self.btn_close)
        return h

    def _build_battery_bar(self):
        h = QHBoxLayout()
        h.setSpacing(8)
        self.batt_icon_lbl = QLabel("🔋")
        self.batt_icon_lbl.setStyleSheet("font-size:16px;border:none;")
        h.addWidget(self.batt_icon_lbl)
        self.batt_pct_lbl = QLabel("--%")
        self.batt_pct_lbl.setStyleSheet(
            "color:#00b878;font-size:14px;font-weight:bold;border:none;"
        )
        h.addWidget(self.batt_pct_lbl)
        self.batt_status_lbl = QLabel("")
        self.batt_status_lbl.setStyleSheet(
            "color:#8282a0;font-size:11px;border:none;background:transparent;"
        )
        h.addWidget(self.batt_status_lbl)
        h.addStretch()
        # 刷新按钮（文字，与电量左右对称）
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setFixedSize(56, 28)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                color: #00b878; background: rgba(0,180,135,18);
                border: none; border-radius: 6px;
                font-size: 12px; font-weight: bold;
            }
            QPushButton:hover { background: rgba(0,180,135,35); }
            QPushButton:pressed { background: rgba(0,180,135,55); }
            QPushButton:disabled { color: #aaa; background: rgba(0,0,0,8); }
        """)
        self.btn_refresh.clicked.connect(self._do_refresh)
        h.addWidget(self.btn_refresh)
        return h

    def _build_conn_card(self):
        card = QWidget()
        card.setStyleSheet(self._card_style())
        h = QHBoxLayout(card)
        h.setContentsMargins(14, 10, 14, 10)
        left = QVBoxLayout()
        left.setSpacing(3)
        lbl = QLabel("连接状态")
        lbl.setStyleSheet("color:#8282a0;font-size:10px;")
        left.addWidget(lbl)
        self.conn_val = QLabel("检测中...")
        self.conn_val.setStyleSheet("color:#2a2a3c;font-size:13px;font-weight:bold;")
        left.addWidget(self.conn_val)
        h.addLayout(left)
        h.addStretch()
        self.conn_dot = QLabel("●")
        self.conn_dot.setStyleSheet("color:#ccc;font-size:20px;")
        h.addWidget(self.conn_dot)
        return self._wrap(card)

    def _build_dpi_card(self):
        card = QWidget()
        card.setStyleSheet(self._card_style())
        h = QHBoxLayout(card)
        h.setContentsMargins(14, 10, 14, 10)
        # DPI
        dpi_col = QVBoxLayout()
        dpi_col.setSpacing(3)
        lbl1 = QLabel("DPI")
        lbl1.setStyleSheet("color:#8282a0;font-size:10px;")
        dpi_col.addWidget(lbl1)
        self.dpi_val = QLabel("--")
        self.dpi_val.setStyleSheet("color:#00b878;font-size:15px;font-weight:bold;")
        dpi_col.addWidget(self.dpi_val)
        h.addLayout(dpi_col)
        h.addStretch()
        # 回报率
        hz_col = QVBoxLayout()
        hz_col.setSpacing(3)
        lbl2 = QLabel("回报率")
        lbl2.setStyleSheet("color:#8282a0;font-size:10px;")
        hz_col.addWidget(lbl2)
        self.hz_val = QLabel("--")
        self.hz_val.setStyleSheet("color:#00b878;font-size:15px;font-weight:bold;")
        hz_col.addWidget(self.hz_val)
        h.addLayout(hz_col)
        return self._wrap(card)

    def _build_info_card(self):
        card = QWidget()
        card.setStyleSheet(self._card_style())
        h = QHBoxLayout(card)
        h.setContentsMargins(14, 10, 14, 10)
        self.dev_name_lbl = QLabel("检测中...")
        self.dev_name_lbl.setStyleSheet("color:#2a2a3c;font-size:13px;font-weight:bold;")
        h.addWidget(self.dev_name_lbl)
        h.addStretch()
        self.conn_type_lbl = QLabel("")
        self.conn_type_lbl.setStyleSheet(
            "color:#8282a0;font-size:11px;background:rgba(0,0,0,8);"
            "border-radius:4px;padding:3px 7px;"
        )
        h.addWidget(self.conn_type_lbl)
        return self._wrap(card)

    def _build_autostart_row(self):
        h = QHBoxLayout()
        h.setContentsMargins(4, 2, 4, 2)
        lbl = QLabel("开机自启动")
        lbl.setStyleSheet("color:#8282a0;font-size:12px;")
        h.addWidget(lbl)
        h.addStretch()
        self.autostart_chk = _ToggleSwitch()
        self.autostart_chk.setChecked(self._is_autostart())
        self.autostart_chk.toggled.connect(self._toggle_autostart)
        h.addWidget(self.autostart_chk)
        return h

    # ───────── 样式工具 ─────────

    def _card_style(self):
        return (
            "background:rgba(248,248,252,255);border-radius:12px;"
        )

    def _wrap(self, widget):
        """把 widget 包进 QHBoxLayout，并加淡阴影"""
        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 25))
        widget.setGraphicsEffect(shadow)
        h = QHBoxLayout()
        h.addWidget(widget)
        return h

    def _circle_btn_style(self, close=False):
        if close:
            return """
                QPushButton {
                    background: transparent; color: #999;
                    border-radius: 14px; font-size: 13px;
                    border: none; font-weight: bold;
                }
                QPushButton:hover {
                    background: #ff5555; color: white;
                }
                QPushButton:pressed {
                    background: #dd3333; color: white;
                }
            """
        else:
            return """
                QPushButton {
                    background: transparent; color: #888;
                    border-radius: 14px; font-size: 13px;
                    border: none; font-weight: bold;
                }
                QPushButton:hover {
                    background: rgba(0,0,0,15); color: #333;
                }
                QPushButton:pressed {
                    background: rgba(0,0,0,25);
                }
            """

    # ───────── 系统托盘 ─────────

    def _init_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self._make_tray_icon())
        self.tray.setToolTip("鼠标控件")

        menu = QMenu()
        show_action = QAction("显示", menu)
        show_action.triggered.connect(self._show_from_tray)
        menu.addAction(show_action)

        # 开机自启动开关
        menu.addSeparator()
        self.autostart_action = QAction("开机自启动", menu)
        self.autostart_action.setCheckable(True)
        self.autostart_action.setChecked(self._is_autostart())
        self.autostart_action.triggered.connect(self._toggle_autostart)
        menu.addAction(self.autostart_action)

        menu.addSeparator()
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self._quit_app)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _make_refresh_icon(self, angle=0):
        """绘制刷新图标，支持旋转角度"""
        from PyQt5.QtGui import QPixmap, QIcon, QPainterPath
        from PyQt5.QtCore import QPoint
        pix = QPixmap(28, 28)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(14, 14)
        p.rotate(angle)
        p.translate(-14, -14)
        p.setPen(QPen(QColor(130, 130, 155), 1.8, Qt.SolidLine, Qt.RoundCap))
        rect = QRectF(7, 7, 14, 14)
        p.drawArc(rect, 30 * 16, 270 * 16)
        p.setBrush(QColor(130, 130, 155))
        p.setPen(Qt.NoPen)
        arrow = QPainterPath()
        arrow.moveTo(20, 7)
        arrow.lineTo(23, 11)
        arrow.lineTo(17, 11)
        arrow.closeSubpath()
        p.drawPath(arrow)
        p.end()
        return QIcon(pix)

    def _start_refresh_anim(self):
        self.btn_refresh.setText("读取中")
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                color: #888; background: rgba(0,0,0,12);
                border: none; border-radius: 6px;
                font-size: 12px; font-weight: bold;
            }
        """)

    def _stop_refresh_anim(self):
        self.btn_refresh.setText("刷新")
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                color: #00b878; background: rgba(0,180,135,18);
                border: none; border-radius: 6px;
                font-size: 12px; font-weight: bold;
            }
            QPushButton:hover { background: rgba(0,180,135,35); }
            QPushButton:pressed { background: rgba(0,180,135,55); }
            QPushButton:disabled { color: #aaa; background: rgba(0,0,0,8); }
        """)

    def _do_refresh(self):
        """手动刷新数据"""
        self.btn_refresh.setEnabled(False)
        self._start_refresh_anim()
        from PyQt5.QtCore import QThread, pyqtSignal

        class _RefreshWorker(QThread):
            done = pyqtSignal(dict)
            failed = pyqtSignal()

            def __init__(self, monitor):
                super().__init__()
                self.monitor = monitor

            def run(self):
                info = self.monitor.force_refresh()
                if info:
                    self.done.emit(info)
                else:
                    self.failed.emit()

        self._worker = _RefreshWorker(self.monitor)
        self._worker.done.connect(self._on_refresh_done)
        self._worker.failed.connect(self._on_refresh_failed)
        self._worker.start()

    def _on_refresh_done(self, info):
        self._target_pct = info['battery']
        self._refresh_data()
        self._stop_refresh_anim()
        self.btn_refresh.setEnabled(True)

    def _on_refresh_failed(self):
        self._stop_refresh_anim()
        self.btn_refresh.setEnabled(True)

    def _make_mouse_icon(self, size=128):
        """生成鼠标形状图标"""
        from PyQt5.QtGui import QPixmap, QIcon
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        s = size / 32  # 缩放因子
        # 鼠标身体
        body_rect = QRectF(8*s, 4*s, 16*s, 24*s)
        grad = QLinearGradient(8*s, 4*s, 8*s, 28*s)
        grad.setColorAt(0, QColor(0, 200, 150))
        grad.setColorAt(1, QColor(0, 160, 120))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(body_rect, 8*s, 8*s)
        # 分割线
        p.setPen(QPen(QColor(255, 255, 255, 180), 1.2*s))
        p.drawLine(QPointF(16*s, 6*s), QPointF(16*s, 15*s))
        # 滚轮
        wheel_rect = QRectF(14*s, 9*s, 4*s, 6*s)
        p.setBrush(QColor(255, 255, 255, 200))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(wheel_rect, 2*s, 2*s)
        p.end()
        return QIcon(pix)

    def _make_tray_icon(self, pct=None):
        """生成托盘图标（鼠标形状）"""
        return self._make_mouse_icon(128)


    def _show_from_tray(self):
        self.showNormal()
        self.activateWindow()

    def _is_autostart(self):
        import winreg
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
            winreg.QueryValueEx(key, "MouseWidget")
            winreg.CloseKey(key)
            return True
        except Exception:
            return False

    def _toggle_autostart(self, checked):
        import winreg
        reg_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_WRITE)
            if checked:
                main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'main.py')
                cmd = f'"{ sys.executable}" "{main_py}" --autostart'
                winreg.SetValueEx(key, "MouseWidget", 0, winreg.REG_SZ, cmd)
            else:
                winreg.DeleteValue(key, "MouseWidget")
            winreg.CloseKey(key)
            # 同步两端状态
            self.autostart_chk.blockSignals(True)
            self.autostart_chk.setChecked(checked)
            self.autostart_chk.blockSignals(False)
            self.autostart_action.blockSignals(True)
            self.autostart_action.setChecked(checked)
            self.autostart_action.blockSignals(False)
        except Exception:
            # 失败时恢复两端状态
            revert = not checked
            self.autostart_chk.blockSignals(True)
            self.autostart_chk.setChecked(revert)
            self.autostart_chk.blockSignals(False)
            self.autostart_action.blockSignals(True)
            self.autostart_action.setChecked(revert)
            self.autostart_action.blockSignals(False)

    def _quit_app(self):
        self._mouse_hook.uninstall()
        self.tray.hide()
        from PyQt5.QtWidgets import QApplication
        QApplication.quit()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_from_tray()

    def _on_close(self):
        """最小化到托盘"""
        self.hide()

    # ───────── 全局鼠标钩子（仅光标在界面内时激活） ─────────

    def _init_mouse_hook(self):
        self._cursor_inside = False
        self._mouse_hook = _MouseHook()
        self._mouse_hook.left_pressed.connect(self._on_hook_left)
        self._mouse_hook.right_pressed.connect(self._on_hook_right)
        self._mouse_hook.scroll_event.connect(self._on_hook_scroll)

    def enterEvent(self, e):
        self._cursor_inside = True

    def leaveEvent(self, e):
        self._cursor_inside = False
        # 离开时清除所有按压状态
        if self._left_pressed or self._right_pressed or self._scroll_alpha > 0:
            self._left_pressed = False
            self._right_pressed = False
            self._scroll_alpha = 0
            if hasattr(self, 'mouse_area'):
                self.mouse_area.update()

    def _on_hook_left(self, pressed):
        if not self._cursor_inside:
            return
        self._left_pressed = pressed
        if hasattr(self, 'mouse_area'):
            self.mouse_area.update()

    def _on_hook_right(self, pressed):
        if not self._cursor_inside:
            return
        self._right_pressed = pressed
        if hasattr(self, 'mouse_area'):
            self.mouse_area.update()

    def _on_hook_scroll(self):
        if not self._cursor_inside:
            return
        self._scroll_alpha = 200
        if hasattr(self, 'mouse_area'):
            self.mouse_area.update()

    # ───────── 定时器 ─────────

    def _init_timers(self):
        self.data_timer = QTimer(self)
        self.data_timer.timeout.connect(self._refresh_data)
        self.data_timer.start(60000)

        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._animate)
        self.anim_timer.start(30)

        QTimer.singleShot(500, self._refresh_data)

    def _refresh_data(self):
        info = self.monitor.get_device_info()
        if not info:
            return

        self._target_pct = info['battery']
        self._connected = info['connected']

        name = info['name']
        if len(name) > 22:
            name = name[:20] + '...'
        self.dev_name_lbl.setText(name)

        dpi = info.get('dpi', 0)
        if dpi:
            self.dpi_val.setText(f"{dpi}")
        hz = info.get('polling_rate', 0)
        if hz:
            if hz >= 1000:
                self.hz_val.setText(f"{hz // 1000}K Hz")
            else:
                self.hz_val.setText(f"{hz} Hz")

        conn_text = info.get('connection', '')
        self.conn_type_lbl.setText(conn_text)

        if info['connected']:
            self.conn_val.setText("已连接")
            self.conn_val.setStyleSheet("color:#00b878;font-size:13px;font-weight:bold;")
            self.conn_dot.setStyleSheet("color:#00b878;font-size:20px;")
        else:
            self.conn_val.setText("未连接")
            self.conn_val.setStyleSheet("color:#e03c3c;font-size:13px;font-weight:bold;")
            self.conn_dot.setStyleSheet("color:#ccc;font-size:20px;")

        if info.get('charging'):
            self.batt_status_lbl.setText("⚡ 充电中")
        else:
            self.batt_status_lbl.setText("")

        self._check_low_battery(info['battery'])

    def _check_low_battery(self, pct):
        if pct <= 20 and not self._warned_low:
            self._warned_low = True
            self.warn_lbl.show()
            self.tray.showMessage(
                "⚠ 鼠标电量低",
                f"当前电量仅剩 {pct}%，请尽快充电！",
                QSystemTrayIcon.Warning, 5000
            )
        elif pct > 25:
            self._warned_low = False
            self.warn_lbl.hide()

    def _animate(self):
        if abs(self._battery_pct - self._target_pct) > 0.5:
            self._battery_pct += (self._target_pct - self._battery_pct) * 0.08
            self._update_battery_display()
            self.mouse_area.update()

        if self._warned_low:
            self._glow_phase += 0.06
            alpha = int(128 + 80 * math.sin(self._glow_phase))
            self.warn_lbl.setStyleSheet(
                f"color:#e03c3c;background:rgba(230,60,60,{alpha // 8});"
                f"border-radius:8px;padding:7px;font-size:12px;font-weight:bold;"
            )

        if self._scroll_alpha > 0:
            self._scroll_alpha = max(0, self._scroll_alpha - 15)
            self.mouse_area.update()

    def _update_battery_display(self):
        pct = round(self._battery_pct)
        color = self._battery_color(pct)
        self.batt_pct_lbl.setText(f"{pct}%")
        self.batt_pct_lbl.setStyleSheet(
            f"color:{color.name()};font-size:16px;font-weight:bold;border:none;"
        )
        if pct > 60:
            self.batt_icon_lbl.setText("🔋")
        elif pct > 20:
            self.batt_icon_lbl.setText("🪫")
        else:
            self.batt_icon_lbl.setText("⚠️")

    def _battery_color(self, pct):
        if pct > 60:
            return self.C_GREEN
        elif pct > 25:
            return self.C_YELLOW
        return self.C_RED

    # ───────── 鼠标拖动 ─────────

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_pos = e.globalPos() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._dragging and e.buttons() == Qt.LeftButton:
            self.move(e.globalPos() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._dragging = False

    def paintEvent(self, event):
        """绘制窗口阴影"""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for i in range(4, 0, -1):
            alpha = int(3 * (4 - i))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, alpha))
            rect = QRectF(
                10 - i, 10 - i,
                self.width() - 20 + 2 * i,
                self.height() - 20 + 2 * i
            )
            p.drawRoundedRect(rect, 18 + i, 18 + i)
        p.end()

    @property
    def battery_pct(self):
        return self._battery_pct


class _MouseArea(QWidget):
    """自定义绘制区域：鼠标图形 + 电量环"""

    def __init__(self, parent: MouseWidget):
        super().__init__(parent)
        self.parent = parent

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2

        mouse_w, mouse_h = 88, 134
        mx, my = cx - mouse_w / 2, cy - mouse_h / 2 - 5

        # 鼠标主体 - 浅色渐变
        body_path = QPainterPath()
        body_path.addRoundedRect(
            QRectF(mx, my, mouse_w, mouse_h), 36, 36
        )
        grad = QLinearGradient(mx, my, mx, my + mouse_h)
        grad.setColorAt(0, QColor(230, 230, 240))
        grad.setColorAt(1, QColor(205, 205, 218))
        p.fillPath(body_path, QBrush(grad))

        # 鼠标边框
        p.setPen(QPen(QColor(195, 195, 210), 1.5))
        p.drawPath(body_path)

        # 左右键高亮
        btn_bottom = my + mouse_h * 0.42
        if self.parent._left_pressed:
            left_btn = QPainterPath()
            left_btn.addRect(QRectF(mx, my, mouse_w / 2, btn_bottom - my))
            p.fillPath(left_btn.intersected(body_path), QColor(0, 180, 135, 60))
        if self.parent._right_pressed:
            right_btn = QPainterPath()
            right_btn.addRect(QRectF(cx, my, mouse_w / 2, btn_bottom - my))
            p.fillPath(right_btn.intersected(body_path), QColor(0, 180, 135, 60))

        # 左右键分割线
        p.setPen(QPen(QColor(210, 210, 222), 1.2))
        p.drawLine(QPointF(cx, my + 4), QPointF(cx, btn_bottom))

        # 滚轮
        scroll_alpha = self.parent._scroll_alpha
        wheel_color = QColor(220, 220, 232) if scroll_alpha == 0 else QColor(
            220 + int((0 - 220) * scroll_alpha / 200),
            220 + int((180 - 220) * scroll_alpha / 200),
            232 + int((135 - 232) * scroll_alpha / 200)
        )
        wheel_rect = QRectF(cx - 7, my + 22, 14, 26)
        p.setBrush(wheel_color)
        p.setPen(QPen(QColor(190, 190, 205), 1))
        p.drawRoundedRect(wheel_rect, 6, 6)
        p.setPen(QPen(QColor(200, 200, 215), 0.8))
        for i in range(3):
            y = wheel_rect.top() + 7 + i * 6
            p.drawLine(QPointF(cx - 3.5, y), QPointF(cx + 3.5, y))

        # 鼠标底部灯光效果
        glow = QRadialGradient(cx, my + mouse_h - 10, 42)
        glow.setColorAt(0, QColor(0, 180, 135, 25))
        glow.setColorAt(1, QColor(0, 180, 135, 0))
        p.fillRect(QRectF(mx - 10, my + mouse_h - 50, mouse_w + 20, 60), QBrush(glow))

        # 电量环形指示器 - 100段分段显示
        pct = self.parent.battery_pct
        color = self.parent._battery_color(round(pct))
        filled = round(pct)

        radius = 68
        arc_rect = QRectF(cx - radius, cy - radius + 5, radius * 2, radius * 2)
        start_angle = 150 * 16
        full_span = 240 * 16  # 3840 (1/16度)
        gap = 4                # 段间隙 (1/16度)
        seg_span = (full_span - gap * 100) // 100  # 每段弧长 (1/16度)

        p.setPen(QPen(QColor(225, 225, 235), 5, Qt.SolidLine, Qt.FlatCap))
        for i in range(100):
            angle = start_angle + (full_span * i) // 100
            if i < filled:
                p.setPen(QPen(color, 5, Qt.SolidLine, Qt.FlatCap))
            else:
                p.setPen(QPen(QColor(225, 225, 235), 5, Qt.SolidLine, Qt.FlatCap))
            p.drawArc(arc_rect, angle, seg_span)

        # 鼠标中心小圆点
        p.setBrush(QColor(color.red(), color.green(), color.blue(), 50))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy + 10), 5, 5)

        p.end()
