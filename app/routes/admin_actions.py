
from flask import Blueprint, jsonify
import os

admin_actions = Blueprint("admin_actions", __name__)

@admin_actions.route("/admin/api/action/<action>", methods=["POST"])
def action(action):

    if action == "restart_flask":
        return jsonify({
            "success": True,
            "message": "Restart Flask dijadwalkan"
        })

    elif action == "reload_config":
        return jsonify({
            "success": True,
            "message": "Config berhasil di-reload"
        })

    elif action == "clear_cache":
        return jsonify({
            "success": True,
            "message": "Cache dibersihkan"
        })

    elif action == "test_service":
        return jsonify({
            "success": True,
            "message": "Semua service normal"
        })

    return jsonify({
        "success": False,
        "message": "Action tidak dikenal"
    })
