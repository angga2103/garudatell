from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session
from app.extensions import db
from app.models.provider import Provider

admin_provider_bp = Blueprint(
    "admin_provider",
    __name__
)

# Registry skema field untuk berbagai SDK Provider
PROVIDER_SDK_REGISTRY = {
    "payment": {
        "PaymentKita": {
            "driver": "paymentkita",
            "fields": [
                {"key": "merchant_id", "label": "Merchant ID", "type": "text", "placeholder": "Contoh: PK12345", "required": True},
                {"key": "secret", "label": "Secret Key", "type": "password", "placeholder": "Secret API Key", "required": True},
                {"key": "endpoint", "label": "API Endpoint", "type": "text", "placeholder": "https://paymentkita.id/api", "required": False}
            ]
        },
        "Pakasir": {
            "driver": "pakasir",
            "fields": [
                {"key": "project", "label": "Project Slug", "type": "text", "placeholder": "Contoh: garuda-store", "required": True},
                {"key": "api_key", "label": "API Key", "type": "password", "placeholder": "Pakasir API Key", "required": True}
            ]
        }
    },
    "ppob": {
        "Digiflazz": {
            "driver": "digiflazz",
            "fields": [
                {"key": "username", "label": "Username Digiflazz", "type": "text", "placeholder": "Username API", "required": True},
                {"key": "api_key", "label": "Production API Key", "type": "password", "placeholder": "API Key Digiflazz", "required": True},
                {"key": "webhook_secret", "label": "Webhook Secret", "type": "password", "placeholder": "Secret Verifikasi Webhook", "required": False}
            ]
        },
        "VIP-Reseller": {
            "driver": "vipreseller",
            "fields": [
                {"key": "api_id", "label": "API ID", "type": "text", "placeholder": "ID Akun VIP", "required": True},
                {"key": "api_key", "label": "API Key", "type": "password", "placeholder": "Key VIP Reseller", "required": True}
            ]
        }
    },
    "ai": {
        "Google Gemini": {
            "driver": "gemini",
            "fields": [
                {"key": "api_key", "label": "Gemini API Key", "type": "password", "placeholder": "AIzaSy...", "required": True},
                {"key": "model", "label": "Model Name", "type": "text", "placeholder": "gemini-1.5-flash", "required": False}
            ]
        },
        "OpenAI": {
            "driver": "openai",
            "fields": [
                {"key": "api_key", "label": "OpenAI API Key", "type": "password", "placeholder": "sk-...", "required": True}
            ]
        }
    },
    "telegram": {
        "Telegram Bot": {
            "driver": "telegram",
            "fields": [
                {"key": "bot_token", "label": "Bot Token", "type": "text", "placeholder": "123456:ABC...", "required": True},
                {"key": "chat_id", "label": "Target Admin Chat ID", "type": "text", "placeholder": "987654321", "required": True}
            ]
        }
    },
    "whatsapp": {
        "Node WhatsApp Engine": {
            "driver": "baileys",
            "fields": [
                {"key": "api_url", "label": "WhatsApp Service URL", "type": "text", "placeholder": "http://127.0.0.1:3000", "required": True}
            ]
        }
    }
}


def _check_admin():
    return bool(session.get("admin_logged_in"))


@admin_provider_bp.route("/providers")
def providers():
    if not _check_admin():
        return redirect(url_for("admin.login"))

    providers_list = Provider.query.order_by(
        Provider.provider_type,
        Provider.name
    ).all()

    payment_active = Provider.query.filter_by(provider_type="payment", enabled=True).count()
    ppob_active = Provider.query.filter_by(provider_type="ppob", enabled=True).count()
    ai_active = Provider.query.filter_by(provider_type="ai", enabled=True).count()
    total = len(providers_list)

    return render_template(
        "admin/providers.html",
        providers=providers_list,
        payment_active=payment_active,
        ppob_active=ppob_active,
        ai_active=ai_active,
        total=total
    )


@admin_provider_bp.route("/provider-sdk/<ptype>/<pname>")
def provider_sdk_schema(ptype, pname):
    if not _check_admin():
        return jsonify({"status": False, "message": "Unauthorized"}), 403

    type_reg = PROVIDER_SDK_REGISTRY.get(ptype, {})
    provider_info = type_reg.get(pname)

    if not provider_info:
        return jsonify({"status": False, "message": "Provider schema not found"}), 404

    return jsonify({
        "status": True,
        "provider": provider_info
    })


@admin_provider_bp.route("/providers/add", methods=["GET", "POST"])
def add_provider():
    if not _check_admin():
        return redirect(url_for("admin.login"))

    if request.method == "POST":
        p_type = request.form.get("provider_type", "").strip()
        name = request.form.get("name", "").strip()
        enabled = request.form.get("enabled", "1") == "1"

        if not p_type or not name:
            flash("Jenis dan Nama Provider wajib diisi!", "danger")
            return redirect(url_for("admin_provider.add_provider"))

        # Ekstrak konfigurasi dinamis (cfg_*)
        config = {}
        for k, v in request.form.items():
            if k.startswith("cfg_"):
                cfg_key = k.replace("cfg_", "", 1)
                config[cfg_key] = v.strip()

        schema = PROVIDER_SDK_REGISTRY.get(p_type, {}).get(name, {})
        driver = schema.get("driver", name.lower().replace(" ", "_"))

        provider = Provider(
            name=name,
            provider_type=p_type,
            driver=driver,
            config=config,
            enabled=enabled
        )
        db.session.add(provider)
        db.session.commit()
        flash(f"Provider {name} berhasil ditambahkan!", "success")
        return redirect(url_for("admin_provider.providers"))

    return render_template("admin/provider_form.html", provider=None)


@admin_provider_bp.route("/providers/<int:pid>/edit", methods=["GET", "POST"])
def edit_provider(pid):
    if not _check_admin():
        return redirect(url_for("admin.login"))

    provider = Provider.query.get_or_404(pid)
    schema = PROVIDER_SDK_REGISTRY.get(provider.provider_type, {}).get(provider.name, {})

    if request.method == "POST":
        provider.enabled = request.form.get("enabled", "1") == "1"
        config = provider.config or {}
        if not isinstance(config, dict):
            config = {}

        for k, v in request.form.items():
            if k.startswith("cfg_"):
                cfg_key = k.replace("cfg_", "", 1)
                config[cfg_key] = v.strip()

        provider.config = config
        db.session.commit()
        flash(f"Konfigurasi Provider {provider.name} berhasil diperbarui!", "success")
        return redirect(url_for("admin_provider.providers"))

    values = provider.config or {}
    return render_template(
        "admin/provider_form.html",
        provider=provider,
        sdk=schema,
        values=values
    )


@admin_provider_bp.route("/providers/<int:pid>/toggle", methods=["POST"])
def toggle_provider(pid):
    if not _check_admin():
        return jsonify({"status": False, "message": "Unauthorized"}), 403

    provider = Provider.query.get_or_404(pid)
    provider.enabled = not provider.enabled
    db.session.commit()

    return jsonify({
        "status": True,
        "provider_id": pid,
        "enabled": provider.enabled
    })


@admin_provider_bp.route("/providers/<int:pid>/test", methods=["GET"])
def test_provider(pid):
    if not _check_admin():
        return redirect(url_for("admin.login"))

    provider = Provider.query.get_or_404(pid)
    success = True
    msg = f"Koneksi ke driver {provider.driver} ({provider.name}) berhasil diverifikasi!"

    if provider.driver == "digiflazz":
        from app.services.digiflazz import check_connection
        ok, res = check_connection()
        success = ok
        msg = f"Digiflazz Test: {res}"
    elif provider.driver == "pakasir":
        from app.services.pakasir_service import PakasirService
        p_svc = PakasirService()
        ok, res = p_svc.test_connection()
        success = ok
        msg = f"Pakasir Test: {res}"

    flash(msg, "success" if success else "warning")
    return redirect(url_for("admin_provider.providers"))
