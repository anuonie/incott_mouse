"""
鼠标控件 - 主入口
显示因科特 G23 v2 无线鼠标的电量和连接状态的桌面小组件

用法:
  python main.py              正常启动，显示窗口
  python main.py --autostart  最小化启动（仅托盘图标，开机自启用）
  python main.py --install    注册开机自启动
  python main.py --uninstall  取消开机自启动
"""

import sys
import os
import ctypes

# 设置工作目录为脚本所在目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 单实例检查：防止重复启动导致多个托盘图标
_mutex = ctypes.windll.kernel32.CreateMutexW(None, True, "MouseWidget_SingleInstance")
if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
    print("已有实例在运行，退出")
    sys.exit(0)

# Windows 任务栏图标：设置 AppUserModelID，使任务栏显示自定义图标而非 Python 图标
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('MouseWidget.App')
except Exception:
    pass

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QPainter, QColor, QPen, QIcon, QPixmap, QLinearGradient, QBrush, QFont
from battery_monitor import BatteryMonitor
from mouse_widget import MouseWidget


def _make_app_icon():
    """生成鼠标形状应用图标（多尺寸）"""
    icon = QIcon()
    for size in [16, 32, 48, 64, 128]:
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        s = size / 32
        body_rect = QRectF(8*s, 4*s, 16*s, 24*s)
        grad = QLinearGradient(8*s, 4*s, 8*s, 28*s)
        grad.setColorAt(0, QColor(0, 200, 150))
        grad.setColorAt(1, QColor(0, 160, 120))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(body_rect, 8*s, 8*s)
        p.setPen(QPen(QColor(255, 255, 255, 180), 1.2*s))
        p.drawLine(QPointF(16*s, 6*s), QPointF(16*s, 15*s))
        wheel_rect = QRectF(14*s, 9*s, 4*s, 6*s)
        p.setBrush(QColor(255, 255, 255, 200))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(wheel_rect, 2*s, 2*s)
        p.end()
        icon.addPixmap(pix)
    return icon


# ──── 开机自启动管理 (Windows 注册表) ────

REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "MouseWidget"


def get_exe_path():
    """获取当前脚本的启动命令（用 pythonw 避免弹出命令行窗口）"""
    pythonw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    script = os.path.abspath(__file__)
    return f'"{pythonw}" "{script}" --autostart'


def install_autostart():
    """注册开机自启动"""
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_WRITE)
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, get_exe_path())
        winreg.CloseKey(key)
        print(f"✓ 已注册开机自启动")
        print(f"  命令: {get_exe_path()}")
    except Exception as e:
        print(f"✗ 注册失败: {e}")


def uninstall_autostart():
    """取消开机自启动"""
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_WRITE)
        winreg.DeleteValue(key, APP_NAME)
        winreg.CloseKey(key)
        print("✓ 已取消开机自启动")
    except FileNotFoundError:
        print("  未找到自启动项，无需操作")
    except Exception as e:
        print(f"✗ 取消失败: {e}")


def check_autostart():
    """检查是否已注册自启动"""
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return val
    except Exception:
        return None


# ──── 主程序 ────

def main():
    # 处理命令行参数
    args = [a.lower() for a in sys.argv[1:]]

    if '--install' in args:
        install_autostart()
        return
    if '--uninstall' in args:
        uninstall_autostart()
        return

    autostart_mode = '--autostart' in args

    # 高 DPI 支持
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # 关闭窗口不退出（托盘模式）
    app.setApplicationName("鼠标控件")
    app.setFont(QFont("Microsoft YaHei", 9))
    app.setStyleSheet("QWidget { font-family: 'Microsoft YaHei'; }")
    app.setWindowIcon(_make_app_icon())

    # 初始化电池监控
    monitor = BatteryMonitor()

    # 创建控件
    widget = MouseWidget(monitor)

    # 默认出现在屏幕右下角
    screen = app.primaryScreen().geometry()
    x = screen.width() - widget.width() - 60
    y = screen.height() - widget.height() - 100
    widget.move(x, y)

    if autostart_mode:
        # 开机自启：最小化到托盘，不显示窗口
        widget.hide()
        widget.tray.showMessage(
            "鼠标控件", "已在后台启动，双击托盘图标打开",
            1, 2000
        )
    else:
        widget.show()
        widget.setWindowIcon(_make_app_icon())  # 显示后再次设置确保任务栏图标生效

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
