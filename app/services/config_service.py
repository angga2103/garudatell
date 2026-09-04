from app.core.config_manager import config

class ConfigService:

    @staticmethod
    def get(key,default=""):
        return config.get(key,default)

    @staticmethod
    def set(key,value):
        return config.set(key,value)

    @staticmethod
    def exists(key):
        return config.exists(key)

    @staticmethod
    def all():
        return config.as_dict()
