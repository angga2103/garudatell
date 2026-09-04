
import socket
import sqlite3
import os

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
DB_FILE = os.path.join(BASE_DIR, "garudatel.db")


class HealthChecker:

    @staticmethod
    def tcp(host, port, timeout=1):
        try:
            s = socket.socket()
            s.settimeout(timeout)
            s.connect((host, port))
            s.close()
            return True
        except:
            return False

    @staticmethod
    def database():
        try:
            conn = sqlite3.connect(DB_FILE)
            conn.execute("SELECT 1")
            conn.close()
            return True
        except:
            return False

    @staticmethod
    def flask():
        return True

    @staticmethod
    def scheduler():
        try:
            from app.core.scheduler import scheduler
            return scheduler is not None
        except:
            return False

    @staticmethod
    def digiflazz():
        return True

    @staticmethod
    def telegram():
        return True

    @staticmethod
    def payment():
        return True

    @classmethod
    def status(cls):
        return {
            "flask": cls.flask(),
            "database": cls.database(),
            "scheduler": cls.scheduler(),
            "digiflazz": cls.digiflazz(),
            "telegram": cls.telegram(),
            "payment": cls.payment()
        }
