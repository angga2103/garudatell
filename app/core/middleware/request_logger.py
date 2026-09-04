from flask import request
from app.core.logger import logger

def request_logger():

    logger.info(
        f"{request.method} "
        f"{request.path} "
        f"{request.remote_addr}"
    )
