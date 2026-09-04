

from app.models.provider import Provider
from flask import jsonify

runtime = RuntimeProviderEngine()

from flask import Blueprint, render_template
from app.models.provider import Provider

admin_provider_bp = Blueprint(
    "admin_provider",
    __name__
)

@admin_provider_bp.route("/providers")
def providers():

    providers = Provider.query.order_by(
        Provider.provider_type,
        Provider.name
    ).all()

    return render_template(
        "admin/providers.html",
        providers=providers
    )


@admin_provider_bp.route("/providers/<int:pid>/toggle", methods=["POST"])
def toggle_provider(pid):
    provider = Provider.query.get_or_404(pid)

    new_state = runtime.toggle(pid)

    return jsonify({
        "status": True,
        "provider_id": pid,
        "enabled": new_state
    })
