import os
import shutil
from datetime import datetime
from dotenv import load_dotenv, set_key

class ConfigManager:

    def __init__(self, env_path=".env"):
        self.env_path = env_path
        self.reload()

    def reload(self):
        load_dotenv(self.env_path, override=True)

    def get(self, key, default=""):
        return os.getenv(key, default)

    def exists(self, key):
        return os.getenv(key) is not None

    def backup(self):
        os.makedirs("backups/env", exist_ok=True)

        if os.path.exists(self.env_path):
            dst = f"backups/env/.env.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy2(self.env_path, dst)
            return dst

        return None

    def validate(self, key, value):

        value = str(value).strip()

        if value == "":
            raise ValueError(f"{key} tidak boleh kosong")

        if "TOKEN" in key and len(value) < 20:
            raise ValueError(f"{key} tidak valid")

        if "SECRET" in key and len(value) < 20:
            raise ValueError(f"{key} tidak valid")

        return True

    def set(self, key, value):

        self.validate(key, value)

        self.backup()

        set_key(self.env_path, key, str(value))

        self.reload()

        return True

    def set_many(self, data: dict):

        self.backup()

        for k, v in data.items():

            self.validate(k, v)

            set_key(self.env_path, k, str(v))

        self.reload()

    def as_dict(self):

        self.reload()

        result = {}

        with open(self.env_path) as f:

            for line in f:

                line=line.strip()

                if "=" in line and not line.startswith("#"):

                    k,v=line.split("=",1)

                    result[k]=v

        return result


config = ConfigManager()
