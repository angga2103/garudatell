"""
GarudaTel Enterprise
System Monitor Core
"""

import os
import time
import platform
import socket

try:
    import psutil
except ImportError:
    psutil = None


class SystemMonitor:

    @staticmethod
    def get_status():

        if psutil:
            cpu = psutil.cpu_percent(interval=0.2)
            ram = psutil.virtual_memory().percent
            disk = psutil.disk_usage("/").percent
            uptime = int(time.time() - psutil.boot_time())
        else:
            cpu = 0
            ram = 0
            disk = 0
            uptime = 0

        days = uptime // 86400
        hours = (uptime % 86400) // 3600
        minutes = (uptime % 3600) // 60

        if days:
            uptime_text = f"{days} Hari {hours} Jam"
        elif hours:
            uptime_text = f"{hours} Jam {minutes} Menit"
        else:
            uptime_text = f"{minutes} Menit"

        return {
            "cpu": round(cpu,1),
            "ram": round(ram,1),
            "disk": round(disk,1),
            "uptime": uptime_text,
            "hostname": socket.gethostname(),
            "os": platform.platform(),
            "python": platform.python_version(),
            "processor": platform.processor()
        }
