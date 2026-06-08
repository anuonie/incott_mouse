"""
因科特 G23 v2 鼠标电池监控模块
通过逆向工程 incott.net 网页驱动的 WebHID 协议实现

协议 (已验证):
  VID: 0x093A  PID: 0x522C (无线) / 0x622C (充电中)
  接口: Usage Page 0xFF05, Col02 (第二个 Collection)
  Report ID: 0x09
  读取状态命令: send_feature_report([0x09, 0x89, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
  读取响应: get_feature_report(0x09, 64)
  响应格式 (已验证):
    buf[0] = 0x09 (Report ID)
    buf[1] = 0x89 (命令回显)
    buf[2] = 电量百分比 (>100 时减去128表示正在充电)
    buf[3] = 配置组/档位号
    buf[4] = 回报率索引 (0=1000Hz, 1=500, 2=250, 3=125, 4=8K, 5=4K, 6=2K)
    buf[5] = DPI索引 (0=400, 1=800, 2=1600, 3=2400, 4=3200, 5=6400)
"""

import hid
import time
import threading

# 设备标识
VID = 0x093A
PIDS = [0x522C, 0x622C]

# DPI 预设值
DPI_PRESETS = [400, 800, 1600, 2400, 3200, 6400]

# 回报率预设值 (Hz)
HZ_PRESETS = [1000, 500, 250, 125, 8000, 4000, 2000]

# 连接类型描述
CONN_MAP = {
    0x522C: '2.4G 无线',
    0x622C: '有线充电',
}


class BatteryMonitor:
    """因科特 G23 v2 鼠标电池监控器"""

    def __init__(self):
        self._cached_data = None
        self._last_check = 0
        self._check_interval = 3600
        self._lock = threading.Lock()
        self._device_path = None
        self._all_paths = []
        self._find_device()

    def _find_device(self):
        """查找所有 FF05 接口，按 Col 排序（优先 Col02）"""
        self._all_paths = []
        devices = hid.enumerate(VID, 0)

        for d in devices:
            if d['vendor_id'] != VID or d['product_id'] not in PIDS:
                continue
            up = d.get('usage_page', 0)
            if up == 0xFF05:
                self._all_paths.append(d['path'])

        # 优先尝试列表中的第二个 (Col02)
        if len(self._all_paths) >= 2:
            self._device_path = self._all_paths[1]  # Col02
            print(f"[BatteryMonitor] 使用 Col02 接口")
        elif self._all_paths:
            self._device_path = self._all_paths[0]
            print(f"[BatteryMonitor] 使用 Col01 接口 (备用)")
        else:
            print("[BatteryMonitor] 未找到因科特 G23 v2 设备")

    def get_device_info(self):
        """获取鼠标设备信息和电池状态"""
        with self._lock:
            now = time.time()
            if self._cached_data and (now - self._last_check) < self._check_interval:
                return self._cached_data

            info = self._read_status()
            if info:
                self._cached_data = info
                self._last_check = now
            return self._cached_data

    def _read_status(self):
        """通过 HID Feature Report 读取鼠标电量和状态"""
        if not self._device_path:
            self._find_device()
            if not self._device_path:
                return None

        # 尝试所有 FF05 接口
        paths_to_try = [self._device_path] + [p for p in self._all_paths if p != self._device_path]

        for path in paths_to_try:
            h = None
            try:
                h = hid.device()
                h.open_path(path)

                cmd = [0x09, 0x89] + [0x00] * 7

                # 第一次读取（基准值）
                h.send_feature_report(cmd)
                first = None
                for attempt in range(5):
                    time.sleep(0.06)
                    try:
                        response = h.get_feature_report(0x09, 64)
                    except Exception:
                        continue
                    if not response or len(response) < 4:
                        continue
                    if response[0] != 0x09 or response[1] != 0x89:
                        continue
                    first = response
                    break

                if not first:
                    continue

                # 等待固件更新 HID 报告，再读两次
                time.sleep(1.0)
                later_reads = []
                for read_round in range(2):
                    h.send_feature_report(cmd)
                    for attempt in range(5):
                        time.sleep(0.06)
                        try:
                            response = h.get_feature_report(0x09, 64)
                        except Exception:
                            continue
                        if not response or len(response) < 4:
                            continue
                        if response[0] != 0x09 or response[1] != 0x89:
                            continue
                        later_reads.append(response)
                        break
                    if read_round == 0:
                        time.sleep(0.5)

                # 合并所有读取
                all_reads = [first] + later_reads
                batteries = []
                last_dpi, last_hz, last_charging = 0, 0, False
                for resp in all_reads:
                    raw = resp[2]
                    chg = raw > 100
                    bat = raw - 128 if chg else raw
                    bat = max(0, min(100, bat))
                    batteries.append(bat)
                    dpi_idx = resp[5]
                    hz_idx = resp[4]
                    last_dpi = DPI_PRESETS[dpi_idx] if dpi_idx < len(DPI_PRESETS) else 0
                    last_hz = HZ_PRESETS[hz_idx] if hz_idx < len(HZ_PRESETS) else 0
                    last_charging = chg

                best = {
                    'battery': min(batteries),
                    'charging': last_charging,
                    'dpi': last_dpi,
                    'polling_rate': last_hz,
                }
                self._device_path = path

                # 连接类型根据 PID 判断
                current_pid = self._get_current_pid()
                connection = CONN_MAP.get(current_pid, '2.4G 无线')

                result = {
                    'name': '因科特 G23 v2',
                    'battery': best['battery'],
                    'charging': best['charging'],
                    'connected': True,
                    'connection': connection,
                    'dpi': best['dpi'],
                    'polling_rate': best['polling_rate'],
                    'is_real': True,
                }
                print(f"[BatteryMonitor] 电量:{best['battery']}% "
                      f"DPI:{best['dpi']} Hz:{best['polling_rate']}")
                return result

            except Exception as e:
                print(f"[BatteryMonitor] 接口 {path[-30:]} 失败: {e}")
            finally:
                if h:
                    try:
                        h.close()
                    except Exception:
                        pass

        return None

    def _get_current_pid(self):
        """获取当前连接设备的 PID"""
        devices = hid.enumerate(VID, 0)
        for d in devices:
            if d['vendor_id'] == VID and d['product_id'] in PIDS:
                up = d.get('usage_page', 0)
                if up >= 0xFF00:
                    return d['product_id']
        return 0x522C

    def force_refresh(self):
        """强制刷新数据"""
        with self._lock:
            self._last_check = 0
            self._cached_data = None
        return self.get_device_info()

    @property
    def is_available(self):
        return self._device_path is not None
