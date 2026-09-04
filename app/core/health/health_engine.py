import os
import shutil
import psutil
from datetime import datetime


class HealthEngine:

    def status(self):

        disk = shutil.disk_usage("/")

        return {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cpu": round(psutil.cpu_percent(interval=1), 1),
            "ram": round(psutil.virtual_memory().percent, 1),
            "disk": round((disk.used / disk.total) * 100, 1),
            "uptime": round((datetime.now().timestamp() - psutil.boot_time()) / 3600, 2),
            "database": os.path.exists("app/garudatel.db"),
            "env": os.path.exists(".env"),
        }
