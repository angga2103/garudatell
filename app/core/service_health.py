
import sqlite3
import os

class ServiceHealth:

    @staticmethod
    def check_database():

        try:
            db = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "garudatel.db"
            )

            conn = sqlite3.connect(db)
            conn.execute("select 1")
            conn.close()

            return {
                "status":"ONLINE",
                "color":"badge-online"
            }

        except Exception:

            return {
                "status":"OFFLINE",
                "color":"badge-offline"
            }

    @staticmethod
    def check_scheduler():

        return {
            "status":"RUNNING",
            "color":"badge-online"
        }

    @staticmethod
    def check_plugins():

        return {
            "status":"ACTIVE",
            "color":"badge-online"
        }

    @staticmethod
    def check_digiflazz():

        return {
            "status":"READY",
            "color":"badge-warning"
        }

    @staticmethod
    def check_payment():

        return {
            "status":"READY",
            "color":"badge-warning"
        }

    @staticmethod
    def check_bot():

        return {
            "status":"READY",
            "color":"badge-warning"
        }

    @classmethod
    def get_all(cls):

        return {

            "database":cls.check_database(),

            "scheduler":cls.check_scheduler(),

            "plugins":cls.check_plugins(),

            "digiflazz":cls.check_digiflazz(),

            "payment":cls.check_payment(),

            "telegram":cls.check_bot()

        }
