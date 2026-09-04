import logging
import os

os.makedirs("storage/logs",exist_ok=True)

logging.basicConfig(
filename="storage/logs/garudatel.log",
level=logging.INFO,
format="%(asctime)s %(levelname)s %(message)s"
)

logger=logging.getLogger("GarudaTel")
