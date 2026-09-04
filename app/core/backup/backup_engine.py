import os
import shutil
from datetime import datetime

from app.core.logger import logger


class BackupEngine:

    def __init__(self):

        self.base = "backups"

        os.makedirs(self.base, exist_ok=True)

    def _timestamp(self):
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def backup_database(self):

        src = "app/garudatel.db"

        if not os.path.exists(src):
            return None

        dst = f"{self.base}/database/db_{self._timestamp()}.db"

        os.makedirs(os.path.dirname(dst), exist_ok=True)

        shutil.copy2(src, dst)

        logger.info(f"DATABASE BACKUP : {dst}")

        return dst

    def backup_env(self):

        src = ".env"

        if not os.path.exists(src):
            return None

        dst = f"{self.base}/env/.env_{self._timestamp()}"

        os.makedirs(os.path.dirname(dst), exist_ok=True)

        shutil.copy2(src, dst)

        logger.info(f"ENV BACKUP : {dst}")

        return dst

    def backup_source(self):

        os.makedirs(f"{self.base}/source", exist_ok=True)

        filename = f"{self.base}/source/source_{self._timestamp()}"

        archive = shutil.make_archive(
            filename,
            "zip",
            "."
        )

        logger.info(f"SOURCE BACKUP : {archive}")

        return archive

