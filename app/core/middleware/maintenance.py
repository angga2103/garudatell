from flask import jsonify
from app.core.config_manager import config

def maintenance_mode():

    if config.get("MAINTENANCE_MODE","0") == "1":

        return jsonify({
            "status":False,
            "message":"Server sedang maintenance."
        }),503
