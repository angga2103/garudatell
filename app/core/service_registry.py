
from app.core.health_checker import HealthChecker


class ServiceRegistry:

    @staticmethod
    def get_status():
        h = HealthChecker.status()

        return {
            "Digiflazz": {
                "status": "ONLINE" if h["digiflazz"] else "OFFLINE",
                "color": "green" if h["digiflazz"] else "red"
            },

            "Payment Gateway": {
                "status": "ONLINE" if h["payment"] else "OFFLINE",
                "color": "green" if h["payment"] else "red"
            },

            "Telegram Bot": {
                "status": "ONLINE" if h["telegram"] else "OFFLINE",
                "color": "green" if h["telegram"] else "red"
            },

            "Database": {
                "status": "ONLINE" if h["database"] else "OFFLINE",
                "color": "green" if h["database"] else "red"
            },

            "Flask": {
                "status": "ONLINE" if h["flask"] else "OFFLINE",
                "color": "green" if h["flask"] else "red"
            },

            "Scheduler": {
                "status": "ONLINE" if h["scheduler"] else "OFFLINE",
                "color": "green" if h["scheduler"] else "red"
            }

        }
