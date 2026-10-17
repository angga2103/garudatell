from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from app.models.admin import Admin
from app.models.product import Product
from app.models.margin import MarginTier
from app.models.user import User
from app.models.transaction import Transaction
from app.models.banner import Banner
from app.models.broadcast import BroadcastLog
from app.models.deposit_ticket import DigiDepositTicket
from app.services.digiflazz import sync_products, check_balance, request_deposit
from app.extensions import db, limiter, cache, csrf
import os
import requests
import hashlib
import time
from datetime import datetime, timedelta
from dotenv import set_key, load_dotenv

admin_bp = Blueprint('admin', __name__)
BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
ENV_FILE = os.path.join(BASE_DIR, '.env')

# Fungsi Pembersih Karakter Gaib
def clean_str(val):
    if not val: return ''
    return str(val).replace("'", "").replace('"', '').strip(" \t\n\r")

@admin_bp.before_request
def restrict_admin():
    if request.endpoint not in ['admin.login', 'static'] and 'admin_logged_in' not in session:
        return redirect(url_for('admin.login'))

@admin_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        admin = Admin.query.filter_by(username=username).first()
        
        if admin and admin.check_password(password):
            session['admin_logged_in'] = True
            return redirect(url_for('admin.dashboard'))
            
        flash('Username atau Password salah!', 'danger')
    return render_template('admin/login.html')

@admin_bp.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    flash('Anda telah berhasil keluar dari panel admin.', 'info')
    return redirect(url_for('admin.login'))

@admin_bp.route('/')
@admin_bp.route('/dashboard')
def dashboard():
    load_dotenv(ENV_FILE, override=True)
    env_data = {
        'digi_user': clean_str(os.getenv('DIGI_USER')),
        'digi_key': clean_str(os.getenv('DIGI_KEY')),
        'digi_url': clean_str(os.getenv('DIGI_URL', 'https://api.digiflazz.com/v1')),
        'pk_merchant': clean_str(os.getenv('PAYMENTKITA_MERCHANT_ID')),
        'pk_secret': clean_str(os.getenv('PAYMENTKITA_SECRET')),
        'pakasir_project': clean_str(os.getenv('PAKASIR_PROJECT')),
        'pakasir_key': clean_str(os.getenv('PAKASIR_API_KEY')),
        'active_pg': clean_str(os.getenv('ACTIVE_PAYMENT_GATEWAY', 'paymentkita')).lower(),
        'bot_cs_token': clean_str(os.getenv('BOT_CS_TOKEN')),
        'bot_cs_chat': clean_str(os.getenv('BOT_CS_CHAT_ID')),
        'bot_notif_token': clean_str(os.getenv('BOT_NOTIF_TOKEN')),
        'bot_notif_chat': clean_str(os.getenv('BOT_NOTIF_CHAT_ID')),
        'bot_admin_token': clean_str(os.getenv('BOT_ADMIN_TOKEN')),
        'bot_admin_chat': clean_str(os.getenv('BOT_ADMIN_CHAT_ID')),
        'vip_api_id': clean_str(os.getenv('VIP_API_ID')),
        'vip_api_key': clean_str(os.getenv('VIP_API_KEY')),
        'digi_webhook_secret': clean_str(os.getenv('DIGI_WEBHOOK_SECRET')),
        'telegram_api_url': clean_str(os.getenv('TELEGRAM_API_BASE_URL') or os.getenv('TELEGRAM_API_URL', ''))
    }

    # Metrik Riil dari Database
    total_users = User.query.count()
    total_balance = db.session.query(db.func.sum(User.balance)).scalar() or 0.0
    
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    trx_today_count = Transaction.query.filter(Transaction.created_at >= today_start).count()
    total_trx = Transaction.query.count()

    # Deteksi IP Public VPS untuk Whitelist & Callback URL Dinamis (dengan Caching 1 Jam)
    server_public_ip = clean_str(os.getenv('SERVER_PUBLIC_IP'))
    if not server_public_ip:
        server_public_ip = cache.get('server_public_ip')
        if not server_public_ip:
            try:
                server_public_ip = requests.get('https://api.ipify.org', timeout=1.5).text.strip()
                if server_public_ip:
                    cache.set('server_public_ip', server_public_ip, timeout=3600)
            except Exception:
                server_public_ip = '203.194.115.182'

    f_proto = request.headers.get('X-Forwarded-Proto') or request.scheme
    f_host = request.headers.get('X-Forwarded-Host') or request.host
    vip_callback_url = f"{f_proto}://{f_host}/api/callback/vipreseller"
    digi_callback_url = f"{f_proto}://{f_host}/api/callback/digiflazz"

    env_data['server_public_ip'] = server_public_ip
    env_data['vip_callback_url'] = vip_callback_url
    from app.services.setting_service import is_vip_reseller_enabled, get_manual_deposit_settings
    vip_reseller_enabled = is_vip_reseller_enabled()
    manual_depo = get_manual_deposit_settings()

    return render_template('admin/dashboard.html',
                           total_users=total_users,
                           total_balance=total_balance,
                           trx_today_count=trx_today_count,
                           total_trx=total_trx,
                           vip_reseller_enabled=vip_reseller_enabled,
                           manual_depo=manual_depo,
                           **env_data)

@admin_bp.route('/save_config', methods=['POST'])
def save_config():
    if not os.path.exists(ENV_FILE): open(ENV_FILE, 'a').close()
    
    form_type = request.form.get('form_type')
    if form_type == 'manual_deposit':
        from app.services.setting_service import save_manual_deposit_settings
        save_manual_deposit_settings(request.form)
        flash('✅ Informasi rekening & atas nama deposit transfer manual berhasil disimpan!', 'success')
        return_url = request.form.get('return_url')
        if return_url and 'store_settings' in return_url:
            return redirect(url_for('admin.store_settings'))
        return redirect(url_for('admin.dashboard'))
    elif form_type == 'switch_gateway':
        target_gw = clean_str(request.form.get('active_payment_gateway', 'paymentkita')).lower()
        if target_gw in ['paymentkita', 'pakasir']:
            set_key(ENV_FILE, 'ACTIVE_PAYMENT_GATEWAY', target_gw)
            gw_name = "PAKASIR" if target_gw == 'pakasir' else "PAYMENTKITA"
            flash(f"✅ Payment Gateway utama berhasil dialihkan ke {gw_name}!", 'success')
        else:
            flash("Pilihan payment gateway tidak valid!", 'danger')
        return redirect(url_for('admin.dashboard'))
    elif form_type == 'digiflazz':
        set_key(ENV_FILE, 'DIGI_USER', clean_str(request.form.get('digi_user')))
        set_key(ENV_FILE, 'DIGI_URL', clean_str(request.form.get('digi_url')))
        if request.form.get('digi_key'): set_key(ENV_FILE, 'DIGI_KEY', clean_str(request.form.get('digi_key')))
        if request.form.get('digi_webhook_secret') is not None:
            set_key(ENV_FILE, 'DIGI_WEBHOOK_SECRET', clean_str(request.form.get('digi_webhook_secret')))
        load_dotenv(ENV_FILE, override=True)
        flash('✅ Pengaturan Digiflazz & Webhook berhasil disimpan!', 'success')
        return redirect(url_for('admin.dashboard'))
    elif form_type == 'paymentkita':
        set_key(ENV_FILE, 'PAYMENTKITA_MERCHANT_ID', clean_str(request.form.get('pk_merchant')))
        if request.form.get('pk_secret'): set_key(ENV_FILE, 'PAYMENTKITA_SECRET', clean_str(request.form.get('pk_secret')))
        if request.form.get('set_active') == '1':
            set_key(ENV_FILE, 'ACTIVE_PAYMENT_GATEWAY', 'paymentkita')
            flash('Kredensial PaymentKita disimpan & dijadikan Payment Gateway Aktif!', 'success')
            return redirect(url_for('admin.dashboard'))
    elif form_type == 'pakasir':
        set_key(ENV_FILE, 'PAKASIR_PROJECT', clean_str(request.form.get('pakasir_project')))
        if request.form.get('pakasir_key'): set_key(ENV_FILE, 'PAKASIR_API_KEY', clean_str(request.form.get('pakasir_key')))
        if request.form.get('set_active') == '1':
            set_key(ENV_FILE, 'ACTIVE_PAYMENT_GATEWAY', 'pakasir')
            flash('Kredensial Pakasir disimpan & dijadikan Payment Gateway Aktif!', 'success')
            return redirect(url_for('admin.dashboard'))
    elif form_type == 'bot_cs':
        set_key(ENV_FILE, 'BOT_CS_CHAT_ID', clean_str(request.form.get('bot_cs_chat')))
        if request.form.get('bot_cs_token'): set_key(ENV_FILE, 'BOT_CS_TOKEN', clean_str(request.form.get('bot_cs_token')))
    elif form_type == 'bot_notif':
        set_key(ENV_FILE, 'BOT_NOTIF_CHAT_ID', clean_str(request.form.get('bot_notif_chat')))
        if request.form.get('bot_notif_token'): set_key(ENV_FILE, 'BOT_NOTIF_TOKEN', clean_str(request.form.get('bot_notif_token')))
    elif form_type == 'vipreseller':
        set_key(ENV_FILE, 'VIP_API_ID', clean_str(request.form.get('vip_api_id')))
        if request.form.get('vip_api_key'): set_key(ENV_FILE, 'VIP_API_KEY', clean_str(request.form.get('vip_api_key')))
    elif form_type == 'bot_admin':
        set_key(ENV_FILE, 'BOT_ADMIN_CHAT_ID', clean_str(request.form.get('bot_admin_chat')))
        if request.form.get('bot_admin_token'): set_key(ENV_FILE, 'BOT_ADMIN_TOKEN', clean_str(request.form.get('bot_admin_token')))
        if request.form.get('telegram_api_url') is not None:
            set_key(ENV_FILE, 'TELEGRAM_API_BASE_URL', clean_str(request.form.get('telegram_api_url')))
        
    load_dotenv(ENV_FILE, override=True)
    flash('Konfigurasi berhasil disimpan!', 'success')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/test_connection/<tipe>')
def test_connection(tipe):
    load_dotenv(ENV_FILE, override=True)
    if tipe == 'digiflazz':
        user = clean_str(os.getenv('DIGI_USER'))
        key = clean_str(os.getenv('DIGI_KEY'))
        url = clean_str(os.getenv('DIGI_URL', 'https://api.digiflazz.com/v1')) + '/cek-saldo'
        
        if not user or not key:
            flash('Kredensial Digiflazz belum diisi!', 'danger')
            return redirect(url_for('admin.dashboard'))
        
        is_dev_key = key.lower().startswith('dev-')
        sign = hashlib.md5(f"{user}{key}depo".encode()).hexdigest()
        try:
            r = requests.post(url, json={"cmd": "deposit", "username": user, "sign": sign}, headers={'Content-Type': 'application/json'}, timeout=12)
            res = r.json()
            data = res.get('data', {}) if isinstance(res, dict) else {}
            rc = data.get('rc')
            
            # Periksa Response Code dari Digiflazz
            if rc and rc != '00':
                err_msg = data.get('message', 'Ditolak server Digiflazz')
                hint = ""
                if rc == '45':
                    hint = " (Pastikan IP VPS Anda sudah didaftarkan pada Whitelist IP di Panel Digiflazz)"
                elif rc == '42':
                    hint = " (Username API Buyer tidak cocok atau tidak terdaftar)"
                elif rc == '41':
                    hint = " (Signature atau API Key tidak valid)"
                flash(f"❌ Digiflazz Menolak (RC {rc}): {err_msg}{hint}", 'danger')
            elif r.status_code != 200:
                err_msg = data.get('message', f'HTTP Error {r.status_code}')
                flash(f"❌ Digiflazz Gagal: {err_msg}", 'danger')
            elif 'deposit' in data:
                saldo = float(data['deposit'])
                if is_dev_key:
                    flash(f"⚠️ Terhubung dalam Mode DEVELOPMENT (Sandbox). Saldo: Rp {saldo:,.0f}. Catatan: API Key dev selalu bernilai Rp 0 dan tiket deposit tidak tercatat di akun riil Digiflazz. Gunakan Production Key untuk transaksi nyata.", 'warning')
                else:
                    flash(f"✅ Koneksi Digiflazz Sukses! Saldo Anda: Rp {saldo:,.0f}", 'success')
            else:
                err_msg = data.get('message', 'Format respon tidak dikenali')
                flash(f"❌ Respons tidak sesuai: {err_msg}", 'danger')
        except Exception as e:
            flash(f"❌ Error Sistem: {str(e)}", 'danger')

    elif tipe == 'vipreseller':
        from app.services.vip_reseller import VIPReseller
        vip = VIPReseller()
        if not vip.api_id or not vip.api_key:
            flash('❌ API ID atau API Key VIP-Reseller belum diisi!', 'danger')
            return redirect(url_for('admin.dashboard'))
        try:
            res = vip.get_profile()
            if res and res.get('result'):
                p_data = res.get('data', {})
                name = p_data.get('name') or p_data.get('username') or '-'
                balance = float(p_data.get('balance', 0))
                flash(f"✅ Koneksi VIP-Reseller Sukses! Akun: {name}, Saldo: Rp {balance:,.0f}", 'success')
            else:
                msg = res.get('message', 'Ditolak oleh server VIP-Reseller') if res else 'Respon kosong dari VIP-Reseller'
                hint = ""
                if 'whitelist' in str(msg).lower() or 'ip' in str(msg).lower():
                    hint = " (Pastikan IP VPS Anda didaftarkan di Whitelist IP Panel VIP-Reseller)"
                flash(f"❌ VIP-Reseller Menolak: {msg}{hint}", 'danger')
        except Exception as e:
            flash(f"❌ Error VIP-Reseller: {str(e)}", 'danger')

    elif tipe == 'paymentkita':
        from app.services.paymentkita_service import PaymentKitaService
        pk_config = {
            'merchant_id': clean_str(os.getenv('PAYMENTKITA_MERCHANT_ID')),
            'secret': clean_str(os.getenv('PAYMENTKITA_SECRET'))
        }
        if not pk_config['merchant_id'] or not pk_config['secret']:
            flash('❌ Merchant ID atau Secret Key PaymentKita belum lengkap!', 'danger')
            return redirect(url_for('admin.dashboard'))
        try:
            pk = PaymentKitaService(pk_config)
            res = pk.balance()
            if res and res.get('status'):
                bal = res.get('data', {}).get('balance', 0)
                flash(f"✅ Koneksi PaymentKita Sukses! Saldo Merchant: Rp {bal:,.0f}", 'success')
            else:
                err = res.get('error') or res.get('message') or 'Ditolak oleh PaymentKita'
                flash(f"❌ PaymentKita: {err}", 'danger')
        except Exception as e:
            flash(f"❌ Error PaymentKita: {str(e)}", 'danger')

    elif tipe == 'pakasir':
        from app.services.pakasir_service import PakasirService
        pakasir = PakasirService()
        ok, msg = pakasir.test_connection()
        if ok:
            flash(f"✅ {msg}", 'success')
        else:
            flash(f"❌ {msg}", 'danger')

    elif tipe.startswith('bot_'):
        token = clean_str(os.getenv(f'{tipe.upper()}_TOKEN'))
        chat_id = clean_str(os.getenv(f'{tipe.upper()}_CHAT_ID'))
        if not token or not chat_id:
            flash('❌ Token atau Chat ID Bot belum lengkap!', 'danger')
            return redirect(url_for('admin.dashboard'))
        try:
            from app.services.telegram_service import call_telegram_api, get_admin_inline_keyboard
            target_chat = chat_id.split(',')[0].strip()
            payload = {
                "chat_id": target_chat,
                "text": "✅ <b>Tes koneksi dari Panel Admin GarudaTel berhasil!</b>\nBot siap digunakan.",
                "parse_mode": "HTML"
            }
            if tipe == 'bot_admin':
                payload["text"] = (
                    "🦅 <b>BOT 3 : PANEL & FITUR ADMIN GARUDATEL</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "✅ Tes koneksi berhasil! Silakan pilih fitur admin di bawah ini:"
                )
                payload["reply_markup"] = get_admin_inline_keyboard()
            
            resp = call_telegram_api('post', f"bot{token}/sendMessage", json=payload, timeout=(15, 30))
            res = resp.json()
            if res.get('ok'):
                flash('✅ Tes koneksi sukses! Pesan menu berhasil dikirim ke Telegram Anda.', 'success')
            else:
                flash(f"❌ Gagal kirim pesan: {res.get('description')}", 'danger')
        except Exception as e:
            err_text = str(e)
            hint = ""
            if "timeout" in err_text.lower() or "timed out" in err_text.lower():
                hint = " (Penyebab: VPS mengalami kendala koneksi ke Telegram API karena prioritas IPv6 atau blokir ISP hosting. Solusi: Gunakan menu [4] -> [5] di CLI 'garudatell' untuk optimasi IPv4 atau masukkan Proxy Telegram di konfigurasi)."
            flash(f"❌ Error Telegram: {err_text}{hint}", 'danger')
            
    else:
        flash(f'✅ Konfigurasi {tipe} telah tersimpan.', 'success')

    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/sync_digiflazz', methods=['POST'])
def sync_digiflazz():
    force = request.args.get('force') == '1' or request.form.get('force') == '1'
    success, message = sync_products(force=force)
    if success:
        flash(message, 'success')
    else:
        category = 'warning' if 'Cooldown' in message else 'danger'
        flash(message, category)
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/api/cron/sync-products', methods=['GET', 'POST'])
@csrf.exempt
def cron_sync_products():
    """
    Endpoint otomatis untuk Cron Job VPS Linux (disarankan setiap 30 menit).
    Proteksi token keamanan: Header 'X-Cron-Key' atau parameter '?key=...'.
    Contoh command crontab Linux:
    */30 * * * * curl -s -X POST "https://ipay.my.id/api/cron/sync-products?key=CRON_SECRET" > /dev/null 2>&1
    """
    cron_secret = (os.getenv('CRON_SECRET_KEY') or '').strip()
    if not cron_secret:
        return jsonify({
            'status': 'error',
            'message': 'CRON_SECRET_KEY belum dikonfigurasi di environment server'
        }), 500

    provided_key = request.headers.get('X-Cron-Key') or request.args.get('key') or request.form.get('key') or ''

    import secrets
    if not provided_key or not secrets.compare_digest(provided_key, cron_secret):
        return jsonify({
            'status': 'error',
            'message': 'Unauthorized: Token keamanan cron job tidak valid'
        }), 403

    force = request.args.get('force') == '1'
    ok, msg = sync_products(force=force, notify_admin_bot=True)
    status_str = 'success' if ok else ('cooldown' if 'Cooldown' in msg else 'error')

    # Pemindaian berkala saldo minim pengguna setelah sync produk sukses
    scan_res = None
    if ok:
        try:
            from app.services.balance_notification_service import scan_and_notify_all_low_balance_users
            scan_res = scan_and_notify_all_low_balance_users(force_all=False)
        except Exception as e_scan:
            print(f"[CRON SCAN LOW BAL ERROR] {e_scan}")

    return jsonify({
        'status': status_str,
        'message': msg,
        'low_balance_scan': scan_res,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }), (200 if ok or 'Cooldown' in msg else 500)

@admin_bp.route('/api/cron/check-low-balance', methods=['GET', 'POST'])
@csrf.exempt
def cron_check_low_balance():
    """
    Endpoint otomatis untuk Cron Job VPS Linux untuk memindai saldo minim (< Rp 100.000) dan mengirim notifikasi WhatsApp.
    Contoh command crontab Linux:
    0 * * * * curl -s -X POST "https://ipay.my.id/api/cron/check-low-balance?key=CRON_SECRET" > /dev/null 2>&1
    """
    cron_secret = (os.getenv('CRON_SECRET_KEY') or '').strip()
    if not cron_secret:
        return jsonify({
            'status': 'error',
            'message': 'CRON_SECRET_KEY belum dikonfigurasi di environment server'
        }), 500

    provided_key = request.headers.get('X-Cron-Key') or request.args.get('key') or request.form.get('key') or ''

    import secrets
    if not provided_key or not secrets.compare_digest(provided_key, cron_secret):
        return jsonify({
            'status': 'error',
            'message': 'Unauthorized: Token keamanan cron job tidak valid'
        }), 403

    force = request.args.get('force') == '1' or request.form.get('force') == '1'
    from app.services.balance_notification_service import scan_and_notify_all_low_balance_users
    res = scan_and_notify_all_low_balance_users(force_all=force)

    return jsonify({
        'status': 'success',
        'data': res,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

@admin_bp.route('/change-password', methods=['POST'])
def change_password():
    new_password = request.form['new_password']
    admin = Admin.query.first()
    if not admin:
        admin = Admin(username='admin')
        db.session.add(admin)
    admin.set_password(new_password)
    db.session.commit()
    flash('✅ Password berhasil diperbarui!', 'success')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/produk')
def produk():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))
        
    page = request.args.get('page', 1, type=int)
    search_q = request.args.get('q', '').strip()
    category_filter = request.args.get('category', '').strip()
    seller_filter = request.args.get('seller', '').strip()

    query = Product.query
    if search_q:
        search_pattern = f"%{search_q}%"
        query = query.filter(
            db.or_(
                Product.name.ilike(search_pattern),
                Product.sku_code.ilike(search_pattern),
                Product.brand.ilike(search_pattern),
                Product.seller_name.ilike(search_pattern)
            )
        )
    if category_filter:
        query = query.filter(Product.category == category_filter)
    if seller_filter:
        query = query.filter(Product.seller_name == seller_filter)

    total_products_count = Product.query.count()
    filtered_count = query.count()
    
    pagination = query.order_by(Product.id.asc()).paginate(page=page, per_page=50, error_out=False)
    products = pagination.items

    # Dapatkan semua kategori unik untuk filter dropdown
    raw_cats = db.session.query(Product.category).distinct().order_by(Product.category).all()
    categories = [c[0] for c in raw_cats if c[0]]

    # Dapatkan semua seller unik untuk filter dropdown
    raw_sellers = db.session.query(Product.seller_name).filter(
        Product.seller_name != None,
        Product.seller_name != ''
    ).distinct().order_by(Product.seller_name).all()
    sellers = [s[0] for s in raw_sellers if s[0]]

    return render_template('admin/produk.html',
                           products=products,
                           pagination=pagination,
                           search_q=search_q,
                           category_filter=category_filter,
                           seller_filter=seller_filter,
                           categories=categories,
                           sellers=sellers,
                           total_products_count=total_products_count,
                           filtered_count=filtered_count)

@admin_bp.route('/transactions')
def transactions():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    page = request.args.get('page', 1, type=int)
    search_q = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()
    payment_filter = request.args.get('payment_status', '').strip()
    source_filter = request.args.get('source', '').strip().lower()
    store_id_raw = request.args.get('store_id', '').strip()
    seller_filter = request.args.get('seller', '').strip()
    date_preset = request.args.get('date_preset', '').strip().lower()
    start_date_raw = request.args.get('start_date', '').strip()
    end_date_raw = request.args.get('end_date', '').strip()
    date_raw = request.args.get('date', '').strip()

    # Hitung batas tanggal UTC berdasarkan waktu lokal WIB (UTC+7)
    from datetime import datetime, timedelta

    now_utc = datetime.utcnow()
    now_wib = now_utc + timedelta(hours=7)
    today_wib = now_wib.date()

    if date_preset == 'today':
        start_date_raw = today_wib.strftime('%Y-%m-%d')
        end_date_raw = today_wib.strftime('%Y-%m-%d')
    elif date_preset == 'yesterday':
        yest_wib = today_wib - timedelta(days=1)
        start_date_raw = yest_wib.strftime('%Y-%m-%d')
        end_date_raw = yest_wib.strftime('%Y-%m-%d')
    elif date_preset == '7d':
        start_date_raw = (today_wib - timedelta(days=6)).strftime('%Y-%m-%d')
        end_date_raw = today_wib.strftime('%Y-%m-%d')
    elif date_preset == '30d':
        start_date_raw = (today_wib - timedelta(days=29)).strftime('%Y-%m-%d')
        end_date_raw = today_wib.strftime('%Y-%m-%d')
    elif date_preset == 'this_month':
        start_date_raw = today_wib.replace(day=1).strftime('%Y-%m-%d')
        end_date_raw = today_wib.strftime('%Y-%m-%d')
    elif date_raw and not start_date_raw and not end_date_raw:
        start_date_raw = date_raw
        end_date_raw = date_raw

    start_utc = None
    end_utc = None

    if start_date_raw:
        try:
            sd = datetime.strptime(start_date_raw, '%Y-%m-%d')
            start_utc = sd - timedelta(hours=7)
        except ValueError:
            pass

    if end_date_raw:
        try:
            ed = datetime.strptime(end_date_raw, '%Y-%m-%d')
            end_utc = ed.replace(hour=23, minute=59, second=59, microsecond=999999) - timedelta(hours=7)
        except ValueError:
            pass

    if start_utc and not end_utc:
        end_utc = (start_utc + timedelta(days=1)) - timedelta(microseconds=1)
        end_date_raw = start_date_raw

    query = Transaction.query.outerjoin(User, Transaction.user_id == User.id)

    if search_q:
        search_pattern = f"%{search_q}%"
        query = query.filter(
            db.or_(
                Transaction.ref_id.ilike(search_pattern),
                Transaction.target_number.ilike(search_pattern),
                Transaction.product_name.ilike(search_pattern),
                Transaction.sku_code.ilike(search_pattern),
                Transaction.device_name.ilike(search_pattern),
                Transaction.seller_name.ilike(search_pattern),
                User.name.ilike(search_pattern),
                User.phone.ilike(search_pattern)
            )
        )

    # Filter khusus Toko / User
    selected_store = None
    store_total = 0
    store_success = 0
    store_failed = 0
    store_revenue = 0.0

    if store_id_raw:
        try:
            store_id = int(store_id_raw)
            query = query.filter(Transaction.user_id == store_id)
            selected_store = User.query.get(store_id)
            if selected_store:
                store_total = Transaction.query.filter_by(user_id=store_id).count()
                store_success = Transaction.query.filter_by(user_id=store_id, status='SUCCESS').count()
                store_failed = Transaction.query.filter(
                    Transaction.user_id == store_id,
                    Transaction.status.in_(['FAILED', 'GAGAL', 'CANCELLED', 'BATAL'])
                ).count()
                store_revenue = db.session.query(db.func.sum(Transaction.amount)).filter(
                    Transaction.user_id == store_id,
                    Transaction.status == 'SUCCESS'
                ).scalar() or 0.0
        except (ValueError, TypeError):
            pass

    # Filter Tanggal (WIB dikonversi ke UTC)
    if start_utc:
        query = query.filter(Transaction.created_at >= start_utc)
    if end_utc:
        query = query.filter(Transaction.created_at <= end_utc)

    # Filter Status Provider (Mendukung FAILED/GAGAL, PENDING/PROCESSING, SUCCESS/SUKSES)
    if status_filter:
        st_up = status_filter.upper()
        if st_up in ['FAILED', 'GAGAL']:
            query = query.filter(Transaction.status.in_(['FAILED', 'GAGAL', 'CANCELLED', 'BATAL']))
        elif st_up in ['PENDING', 'PROCESSING', 'PROSES']:
            query = query.filter(Transaction.status.in_(['PENDING', 'PROCESSING', 'PROSES']))
        elif st_up in ['SUCCESS', 'SUKSES']:
            query = query.filter(Transaction.status.in_(['SUCCESS', 'SUKSES']))
        else:
            query = query.filter(Transaction.status == st_up)

    if payment_filter:
        query = query.filter(Transaction.payment_status == payment_filter.upper())

    if source_filter == 'cabang':
        query = query.filter(Transaction.device_id != None)
    elif source_filter == 'web':
        query = query.filter(Transaction.device_id == None)

    # Filter Seller Digiflazz (Case-insensitive & Partial Matching)
    if seller_filter:
        s_clean = seller_filter.strip()
        seller_skus = [
            r[0] for r in db.session.query(Product.sku_code).filter(
                db.func.upper(Product.seller_name).like(f"%{s_clean.upper()}%")
            ).all()
            if r[0]
        ]
        if seller_skus:
            query = query.filter(
                db.or_(
                    db.func.upper(Transaction.seller_name).like(f"%{s_clean.upper()}%"),
                    Transaction.sku_code.in_(seller_skus)
                )
            )
        else:
            query = query.filter(
                db.func.upper(Transaction.seller_name).like(f"%{s_clean.upper()}%")
            )

    # Auto-sync pasif: cek hingga 5 transaksi PROCESSING terbaru ke provider secara otomatis
    try:
        from app.routes.transaction import sync_single_transaction
        quick_pending = Transaction.query.filter(
            Transaction.status.in_(['PROCESSING', 'PENDING', 'PROSES']),
            Transaction.payment_status == 'PAID'
        ).order_by(Transaction.id.desc()).limit(5).all()
        for qp in quick_pending:
            sync_single_transaction(qp)
    except Exception as e_qsync:
        pass

    total_count = Transaction.query.count()
    success_count = Transaction.query.filter_by(status='SUCCESS').count()
    total_revenue = db.session.query(db.func.sum(Transaction.amount)).filter(Transaction.status == 'SUCCESS').scalar() or 0.0

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = Transaction.query.filter(Transaction.created_at >= today_start).count()

    all_stores = User.query.order_by(User.name.asc()).all()

    # Dapatkan daftar Seller unik dari Product & Transaction
    prod_sellers = [
        r[0] for r in db.session.query(Product.seller_name).filter(Product.seller_name != None, Product.seller_name != '').distinct().all()
        if r[0]
    ]
    trx_sellers = [
        r[0] for r in db.session.query(Transaction.seller_name).filter(Transaction.seller_name != None, Transaction.seller_name != '').distinct().all()
        if r[0]
    ]
    all_sellers = sorted(set(prod_sellers + trx_sellers))

    pagination = query.order_by(Transaction.id.desc()).paginate(page=page, per_page=25, error_out=False)
    trxs = pagination.items

    return render_template('admin/transactions.html',
                           transactions=trxs,
                           pagination=pagination,
                           search_q=search_q,
                           status_filter=status_filter,
                           payment_filter=payment_filter,
                           source_filter=source_filter,
                           seller_filter=seller_filter,
                           start_date=start_date_raw,
                           end_date=end_date_raw,
                           date_preset=date_preset,
                           all_sellers=all_sellers,
                           store_id=store_id_raw,
                           selected_store=selected_store,
                           store_total=store_total,
                           store_success=store_success,
                           store_failed=store_failed,
                           store_revenue=store_revenue,
                           all_stores=all_stores,
                           total_count=total_count,
                           success_count=success_count,
                           total_revenue=total_revenue,
                           today_count=today_count)

@admin_bp.route('/user/adjust_balance', methods=['POST'])
def adjust_user_balance_route():
    """Endpoint penambahan (+) atau pemotongan (-) saldo manual oleh Admin di web."""
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    user_id = request.form.get('user_id')
    amount_raw = request.form.get('amount', '0')
    action = request.form.get('action', 'add').strip().lower()
    note = request.form.get('note', '').strip()
    redirect_to = request.form.get('redirect_to', 'users')

    from app.services.balance_service import adjust_user_balance_manual
    ok, new_bal, msg, trx = adjust_user_balance_manual(
        user_id=user_id,
        amount=amount_raw,
        action=action,
        note=note,
        admin_source='Web Admin'
    )

    if ok:
        flash(f"✅ {msg}", 'success')
    else:
        flash(f"❌ {msg}", 'danger')

    if redirect_to == 'transactions':
        return redirect(url_for('admin.transactions', store_id=user_id))
    return redirect(url_for('admin.users'))

@admin_bp.route('/transactions/update_status/<int:id>', methods=['POST'])
def update_transaction_status(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    trx = Transaction.query.get_or_404(id)
    new_status = request.form.get('status')
    new_payment_status = request.form.get('payment_status')
    sn = request.form.get('sn')
    do_refund = request.form.get('do_refund') == '1'

    old_status = trx.status
    old_payment_status = trx.payment_status

    if new_status:
        trx.status = new_status.upper()
    if new_payment_status:
        trx.payment_status = new_payment_status.upper()
    if sn is not None and sn.strip():
        trx.sn = sn.strip()

    refund_success = False
    refund_msg = ""

    # KASUS 1: Admin meng-approve transaksi deposit menjadi SUCCESS
    if trx.status == 'SUCCESS' and old_status != 'SUCCESS':
        if trx.sku_code in ['DEPOSIT_SALDO', 'DEPOSIT_MANUAL']:
            user = User.query.filter_by(id=trx.user_id).with_for_update().first()
            if user:
                old_bal = float(user.balance or 0.0)
                user.balance += trx.amount
                trx.payment_status = 'PAID'
                print(f"[ADMIN DEPOSIT APPROVE] User {user.id} balance +Rp {trx.amount} for trx {trx.ref_id}")
                try:
                    from app.services.balance_notification_service import check_and_notify_low_balance
                    check_and_notify_low_balance(user.id, old_bal, user.balance)
                except Exception:
                    pass

    # KASUS 2: Admin mengubah status ke FAILED dengan opsi REFUND SALDO
    elif trx.status == 'FAILED' and do_refund:
        # Validasi 1: Pastikan bukan transaksi tiket deposit atau penyesuaian manual
        if trx.sku_code in ['DEPOSIT_SALDO', 'DEPOSIT_MANUAL', 'MANUAL_DEDUCTION']:
            flash(f"Peringatan: Transaksi tiket deposit / penyesuaian saldo tidak dapat di-refund pembelian.", "warning")
        # Validasi 2: Pastikan pembayaran sudah PAID (Lunas)
        elif trx.payment_status != 'PAID':
            flash(f"Peringatan: Refund dibatalkan karena status pembayaran transaksi {trx.ref_id} belum lunas (UNPAID).", "warning")
        else:
            refund_amount = float(trx.amount or 0.0)
            if refund_amount > 0:
                # A. Jika transaksi dari Kasir Cabang (device_id ada)
                if trx.device_id:
                    from app.models.trusted_device import TrustedDevice
                    from app.models.branch_mutation import BranchMutation
                    b_dev = db.session.query(TrustedDevice).filter_by(id=trx.device_id).with_for_update().first()
                    if b_dev:
                        # Cek proteksi double refund jika status sebelumnya sudah FAILED
                        existing_mut = BranchMutation.query.filter(
                            BranchMutation.device_id == b_dev.id,
                            BranchMutation.type == 'REFUND',
                            BranchMutation.description.like(f"%{trx.ref_id}%")
                        ).first()
                        if existing_mut and old_status == 'FAILED':
                            flash(f"Peringatan: Transaksi {trx.ref_id} sudah pernah di-refund ke cabang {b_dev.device_name} pada {existing_mut.created_at_wib}. Saldo tidak di-refund ganda.", "warning")
                        else:
                            b_before = float(b_dev.branch_balance or 0.0)
                            b_dev.branch_balance = b_before + refund_amount
                            mut_rf = BranchMutation(
                                device_id=b_dev.id,
                                user_id=trx.user_id,
                                type='REFUND',
                                amount=refund_amount,
                                balance_before=b_before,
                                balance_after=b_dev.branch_balance,
                                description=f"Refund transaksi gagal ({trx.ref_id}) oleh Admin",
                                shift_name="Admin Web",
                                created_at=datetime.utcnow()
                            )
                            db.session.add(mut_rf)
                            refund_success = True
                            refund_msg = f" serta saldo Rp {refund_amount:,.0f} berhasil dikembalikan ke cabang {b_dev.device_name}"
                            print(f"[ADMIN MANUAL REFUND KASIR] Branch #{b_dev.id} ({b_dev.device_name}) +Rp {refund_amount:,.0f} for trx {trx.ref_id}")
                # B. Transaksi dari Pengguna Reguler
                else:
                    user = User.query.filter_by(id=trx.user_id).with_for_update().first()
                    if user:
                        old_bal = float(user.balance or 0.0)
                        user.balance = old_bal + refund_amount
                        refund_success = True
                        refund_msg = f" serta saldo Rp {refund_amount:,.0f} berhasil dikembalikan ke akun {user.name}"
                        print(f"[ADMIN MANUAL REFUND USER] User #{user.id} ({user.name}) +Rp {refund_amount:,.0f} for trx {trx.ref_id}")

                        try:
                            from app.services.balance_notification_service import (
                                notify_admin_balance_adjustment,
                                check_and_notify_low_balance
                            )
                            notify_admin_balance_adjustment(
                                user_id=user.id,
                                old_balance=old_bal,
                                amount=refund_amount,
                                new_balance=user.balance,
                                action='add',
                                note=f"Refund pesanan {trx.product_name} ({trx.ref_id})",
                                admin_source='Admin Web Refund',
                                ref_id=trx.ref_id
                            )
                            check_and_notify_low_balance(user.id, old_bal, user.balance)
                        except Exception as e_wa:
                            print(f"[REFUND NOTIF WA ERR]: {e_wa}")

    trx.updated_at = datetime.utcnow()
    db.session.commit()

    from app.services.telegram_service import async_send_trx_notification
    notif_title = f"ADMIN MANUAL REFUND: {trx.status}" if refund_success else f"ADMIN UPDATE: {trx.status}"
    async_send_trx_notification(trx, title=notif_title)

    flash(f"Status transaksi {trx.ref_id} berhasil diperbarui{refund_msg}!", 'success')
    return redirect(request.referrer or url_for('admin.transactions'))


@admin_bp.route('/transactions/sync/<int:id>', methods=['POST'])
@csrf.exempt
def sync_transaction_admin(id):
    """Menyinkronkan status 1 transaksi tertentu langsung ke provider (Digiflazz/VIP)."""
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    trx = Transaction.query.get_or_404(id)
    from app.routes.transaction import sync_single_transaction
    from app.services.digiflazz import build_seller_complaint_info
    old_status = trx.status
    changed = sync_single_transaction(trx)
    comp_info = build_seller_complaint_info(trx)

    return jsonify({
        'status': 'success',
        'changed': changed,
        'trx_id': trx.id,
        'ref_id': trx.ref_id,
        'old_status': old_status,
        'new_status': trx.status,
        'sn': trx.sn or '-',
        'seller_name': comp_info.get('seller_name') or '-',
        'seller_tele': comp_info.get('seller_tele') or '',
        'seller_wa': comp_info.get('seller_wa') or '',
        'complaint_info': comp_info,
        'message': f"Transaksi {trx.ref_id}: Status {trx.status} (SN: {trx.sn or '-'}) | Seller: {comp_info.get('seller_name') or '-'}"
    })


@admin_bp.route('/transactions/complain_seller/<int:id>', methods=['POST'])
@csrf.exempt
def complain_seller_admin(id):
    """
    Endpoint Smart Auto-Complaint ke Seller Digiflazz dari Panel Admin:
    - action='sync_info': Menarik data terbaru dari Digiflazz (kontak Tele & WA seller + SN) lalu mengembalikan info format komplain.
    - action='send_wa': Mengirim otomatis pesan komplain berformat standar Digiflazz ke WhatsApp Seller via Bot Baileys.
    """
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    trx = Transaction.query.get_or_404(id)
    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    action = str(payload.get('action', 'sync_info')).strip().lower()
    mode = payload.get('mode')

    from app.routes.transaction import sync_single_transaction
    from app.services.digiflazz import build_seller_complaint_info

    # Jika diminta sync_info atau kontak seller belum lengkap, tarik dari Digiflazz
    if action == 'sync_info' or not (trx.seller_tele or trx.seller_wa):
        try:
            sync_single_transaction(trx)
        except Exception as e_sync:
            print(f"[COMPLAIN SELLER SYNC ERR] {e_sync}")

    comp_info = build_seller_complaint_info(trx, mode=mode)

    if action == 'send_wa':
        seller_wa = comp_info.get('seller_wa_clean') or comp_info.get('seller_wa') or ''
        complaint_text = (payload.get('complaint_text') or comp_info.get('complaint_text') or '').strip()

        if not seller_wa:
            return jsonify({
                'status': 'error',
                'message': f"Seller ({comp_info.get('seller_name')}) tidak mencantumkan nomor WhatsApp CS di response API Digiflazz. Gunakan tombol Telegram Seller atau Copy format komplain manual.",
                'complaint_info': comp_info
            }), 400

        try:
            from app.wa_helper import kirim_wa
            ok = kirim_wa(seller_wa, complaint_text)
            if ok:
                return jsonify({
                    'status': 'success',
                    'message': f"✅ Komplain standar Digiflazz berhasil dikirim otomatis via WA Baileys ke CS Seller ({comp_info.get('seller_name')} - {seller_wa})!",
                    'complaint_info': comp_info
                })
            else:
                return jsonify({
                    'status': 'error',
                    'message': "Gagal kirim via WA Baileys: Pastikan Bot WA Baileys di port 3000 aktif & terhubung.",
                    'complaint_info': comp_info
                }), 500
        except Exception as e_wa:
            return jsonify({
                'status': 'error',
                'message': f"Error WA Baileys: {e_wa}",
                'complaint_info': comp_info
            }), 500

    return jsonify({
        'status': 'success',
        'message': f"Data kontak Seller ({comp_info.get('seller_name')}) & format komplain berhasil disinkronkan.",
        'complaint_info': comp_info
    })


@admin_bp.route('/transactions/sync_all_pending', methods=['POST'])
@csrf.exempt
def sync_all_pending_admin():
    """Menyinkronkan seluruh transaksi berstatus PROCESSING/PENDING dalam 48 jam terakhir."""
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    from app.routes.transaction import sync_all_pending_transactions
    res = sync_all_pending_transactions(limit=30, max_hours=48)

    msg = f"Selesai memeriksa {res['total_checked']} transaksi. {res['updated_count']} transaksi berhasil disinkronkan ke provider."
    return jsonify({
        'status': 'success',
        'message': msg,
        'data': res
    })

@admin_bp.route('/margin', methods=['GET', 'POST'])
def margin():
    if MarginTier.query.count() == 0:
        defaults = [
            MarginTier(level=1, min_price=0, max_price=10000, margin=200),
            MarginTier(level=2, min_price=10001, max_price=50000, margin=500),
            MarginTier(level=3, min_price=50001, max_price=100000, margin=1000),
            MarginTier(level=4, min_price=100001, max_price=500000, margin=2500),
            MarginTier(level=5, min_price=500001, max_price=99999999, margin=5000)
        ]
        db.session.bulk_save_objects(defaults)
        db.session.commit()
    if request.method == 'POST':
        for i in range(1, 6):
            tier = MarginTier.query.filter_by(level=i).first()
            if tier:
                tier.min_price = float(request.form.get(f'min_price_{i}', tier.min_price))
                tier.max_price = float(request.form.get(f'max_price_{i}', tier.max_price))
                tier.margin = float(request.form.get(f'margin_{i}', tier.margin))
        db.session.commit()
        flash('Rumus Auto-Tier berhasil diperbarui!', 'success')
        return redirect(url_for('admin.margin'))
    tiers = MarginTier.query.order_by(MarginTier.level).all()
    return render_template('admin/margin.html', tiers=tiers)

@admin_bp.route('/apply_auto_tier', methods=['POST'])
def apply_auto_tier():
    tiers = MarginTier.query.order_by(MarginTier.level).all()
    products = Product.query.filter_by(is_manual_margin=False).all()
    update_count = 0
    for p in products:
        for t in tiers:
            if t.min_price <= p.base_price <= t.max_price:
                p.sell_price = p.base_price + t.margin
                update_count += 1
                break
    db.session.commit()
    flash(f'SUKSES: {update_count} produk diupdate!', 'success')
    return redirect(url_for('admin.produk'))

@admin_bp.route('/edit_margin/<int:id>', methods=['POST'])
def edit_margin(id):
    product = Product.query.get_or_404(id)
    new_price = request.form.get('sell_price')
    if new_price and new_price.isdigit():
        product.sell_price = float(new_price)
        product.is_manual_margin = True
        db.session.commit()
        flash(f'Harga {product.name} berhasil diubah!', 'success')
    return redirect(url_for('admin.produk'))

@admin_bp.route('/reset_margin/<int:id>', methods=['POST'])
def reset_margin(id):
    product = Product.query.get_or_404(id)
    product.is_manual_margin = False
    db.session.commit()
    flash(f'Harga {product.name} dikembalikan ke Auto Tier.', 'success')
    return redirect(url_for('admin.produk'))

@admin_bp.route('/product/edit/<int:id>', methods=['POST'])
def edit_product(id):
    product = Product.query.get_or_404(id)
    
    # 1. Update Harga Jual (jika ada input valid)
    new_price = request.form.get('sell_price')
    if new_price and new_price.strip():
        try:
            val_p = float(new_price.strip().replace('.', '').replace(',', ''))
            product.sell_price = val_p
            product.is_manual_margin = True
        except ValueError:
            pass

    # 2. Update Deskripsi Produk
    new_desc = request.form.get('description', '').strip()
    is_lock_desc = request.form.get('is_manual_desc') in ['1', 'on', 'true', 'True']
    
    product.description = new_desc if new_desc else None
    # Jika admin mengisi deskripsi atau mencentang kunci, tandai sebagai manual
    if new_desc or is_lock_desc:
        product.is_manual_desc = True
    else:
        product.is_manual_desc = False

    db.session.commit()
    flash(f'Produk {product.name} ({product.sku_code}) berhasil diperbarui!', 'success')
    return redirect(url_for('admin.produk'))

@admin_bp.route('/product/reset_desc/<int:id>', methods=['POST'])
def reset_product_desc(id):
    product = Product.query.get_or_404(id)
    product.is_manual_desc = False
    db.session.commit()
    flash(f'Kunci deskripsi {product.name} telah dibuka. Deskripsi akan otomatis disinkronkan dari Digiflazz pada sinkronisasi berikutnya.', 'info')
    return redirect(url_for('admin.produk'))

@admin_bp.route('/users')
def users():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))
    
    sort_by = request.args.get('sort', 'id_desc').strip()
    search_q = request.args.get('q', '').strip()
    role_filter = request.args.get('role', '').strip().lower()
    status_filter = request.args.get('status', '').strip().lower()
    balance_filter = request.args.get('balance', '').strip().lower()

    # Statistik Keseluruhan (Database-wide)
    total_user_count = User.query.count()
    count_member = User.query.filter_by(role='user').count()
    count_reseller = User.query.filter_by(role='reseller').count()
    count_vip = User.query.filter_by(role='vip').count()
    count_blocked = User.query.filter_by(is_active=False).count()

    total_user_balance = db.session.query(db.func.sum(User.balance)).scalar() or 0.0
    total_commission_balance = db.session.query(db.func.sum(User.commission_balance)).scalar() or 0.0
    total_user_points = db.session.query(db.func.sum(User.points)).scalar() or 0

    # Query Terfilter
    query = User.query

    if search_q:
        search_pattern = f"%{search_q}%"
        or_clauses = [
            User.name.ilike(search_pattern),
            User.phone.ilike(search_pattern),
            User.email.ilike(search_pattern)
        ]
        if search_q.isdigit():
            or_clauses.append(User.id == int(search_q))
        query = query.filter(db.or_(*or_clauses))

    if role_filter in ['user', 'reseller', 'vip']:
        query = query.filter(User.role == role_filter)

    if status_filter == 'active':
        query = query.filter(User.is_active == True)
    elif status_filter == 'blocked':
        query = query.filter(User.is_active == False)

    if balance_filter == 'low':
        query = query.filter(db.func.coalesce(User.balance, 0.0) < 100000)
    elif balance_filter == 'zero':
        query = query.filter(db.func.coalesce(User.balance, 0.0) <= 0)
    elif balance_filter == 'positive':
        query = query.filter(db.func.coalesce(User.balance, 0.0) > 0)

    # Sorting
    if sort_by == 'saldo_desc':
        query = query.order_by(db.func.coalesce(User.balance, 0.0).desc(), User.id.desc())
    elif sort_by == 'saldo_asc':
        query = query.order_by(db.func.coalesce(User.balance, 0.0).asc(), User.id.desc())
    elif sort_by == 'name_asc':
        query = query.order_by(User.name.asc())
    elif sort_by == 'name_desc':
        query = query.order_by(User.name.desc())
    elif sort_by == 'points_desc':
        query = query.order_by(db.func.coalesce(User.points, 0).desc(), User.id.desc())
    elif sort_by == 'commission_desc':
        query = query.order_by(db.func.coalesce(User.commission_balance, 0.0).desc(), User.id.desc())
    elif sort_by == 'id_asc':
        query = query.order_by(User.id.asc())
    else:
        sort_by = 'id_desc'
        query = query.order_by(User.id.desc())

    all_users = query.all()

    # Hitung statistik untuk daftar user yang sedang ditampilkan
    displayed_balance = sum(float(u.balance or 0.0) for u in all_users)
    displayed_commission = sum(float(u.commission_balance or 0.0) for u in all_users)
    displayed_points = sum(int(u.points or 0) for u in all_users)

    # Hitung total saldo cabang
    overall_branch_balance = sum(float(u.total_branch_balance or 0.0) for u in all_users)
    overall_asset_balance = total_user_balance + overall_branch_balance

    return render_template(
        'admin/users.html',
        users=all_users,
        sort_by=sort_by,
        search_q=search_q,
        role_filter=role_filter,
        status_filter=status_filter,
        balance_filter=balance_filter,
        total_user_count=total_user_count,
        count_member=count_member,
        count_reseller=count_reseller,
        count_vip=count_vip,
        count_blocked=count_blocked,
        total_user_balance=total_user_balance,
        total_commission_balance=total_commission_balance,
        total_user_points=total_user_points,
        displayed_balance=displayed_balance,
        displayed_commission=displayed_commission,
        displayed_points=displayed_points,
        overall_branch_balance=overall_branch_balance,
        overall_asset_balance=overall_asset_balance
    )

@admin_bp.route('/users/scan_low_balance', methods=['POST'])
def scan_low_balance():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    force = request.form.get('force') == '1'
    from app.services.balance_notification_service import scan_and_notify_all_low_balance_users
    res = scan_and_notify_all_low_balance_users(force_all=force)

    total_low = res.get('total_low', 0)
    notified_users = res.get('notified_users', 0)
    notified_uplines = res.get('notified_uplines', 0)

    if notified_users > 0 or notified_uplines > 0:
        flash(f"✅ Pemindaian selesai! Berhasil mengirim notifikasi WhatsApp saldo minim ke {notified_users} user dan {notified_uplines} upline.", "success")
    elif total_low > 0:
        flash(f"ℹ️ Ditemukan {total_low} user dengan saldo < Rp 100.000, tetapi mereka sudah dinotifikasi sebelumnya (< 12 jam). Centang 'Paksa Kirim Ulang' jika ingin mengirim ulang sekarang.", "warning")
    else:
        flash("🎉 Seluruh akun toko saat ini memiliki saldo aman di atas Rp 100.000!", "info")

    return redirect(url_for('admin.users'))

@admin_bp.route('/users/<int:user_id>/kickout', methods=['POST'])
def user_kickout(user_id):
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Akses ditolak. Silakan login kembali.'}), 403

    from app.models.user import User
    from app.services.session_service import revoke_user_session
    user = User.query.get_or_404(user_id)
    admin_user = session.get('admin_username', 'Admin')

    ok, msg = revoke_user_session(user, reason='ADMIN_KICKOUT', actor_name=f"Admin ({admin_user})")
    if ok:
        return jsonify({'status': 'success', 'message': f'Sesi login akun {user.name} berhasil diputus (Kick Out). Akun kini bebas login.'})
    return jsonify({'status': 'error', 'message': msg}), 400

@admin_bp.route('/users/<int:user_id>/sync_commission', methods=['POST'])
@csrf.exempt
def sync_user_commission(user_id):
    if not session.get('admin_logged_in'):
        if request.is_json:
            return jsonify({'success': False, 'message': 'Sesi telah berakhir'}), 401
        return redirect(url_for('admin.login'))

    from app.services.commission_service import sync_user_commission_balance
    ok, msg, report = sync_user_commission_balance(user_id)

    if request.is_json:
        return jsonify({'success': ok, 'message': msg, 'report': report})

    if ok:
        flash(f"✅ {msg}", "success")
    else:
        flash(f"❌ {msg}", "danger")

    return redirect(url_for('admin.users'))

@admin_bp.route('/device-logs')
def device_logs():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    from app.models.device_session_log import DeviceSessionLog
    from app.models.user import User

    page = request.args.get('page', 1, type=int)
    per_page = 30
    event_filter = request.args.get('event', '').strip()
    search_q = request.args.get('q', '').strip()

    query = DeviceSessionLog.query.order_by(DeviceSessionLog.id.desc())

    if event_filter:
        query = query.filter(DeviceSessionLog.event_type == event_filter)

    if search_q:
        q_clean = f"%{search_q}%"
        query = query.join(User).filter(
            db.or_(
                User.name.ilike(q_clean),
                DeviceSessionLog.phone.ilike(q_clean),
                DeviceSessionLog.device_name.ilike(q_clean),
                DeviceSessionLog.ip_address.ilike(q_clean),
                DeviceSessionLog.details.ilike(q_clean)
            )
        )

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    logs = pagination.items

    return render_template(
        'admin/device_logs.html',
        logs=logs,
        pagination=pagination,
        event_filter=event_filter,
        search_q=search_q
    )

@admin_bp.route('/user/update_action', methods=['POST'])
def update_user_action():
    from flask import request, flash, redirect, url_for
    
    try:
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin.login'))
        
        # Mengambil ID dari form body
        user_id = request.form.get('user_id')
        user = User.query.get(user_id)
        
        if not user:
            flash('Pengguna tidak ditemukan!', 'error')
            return redirect(url_for('admin.users'))
            
        # Memperbarui Nama
        name = request.form.get('name', '').strip()
        if name:
            user.name = name

        # Memperbarui Nomor WhatsApp
        phone = request.form.get('phone', '').strip()
        if phone:
            dup_phone = User.query.filter(User.phone == phone, User.id != user.id).first()
            if dup_phone:
                flash(f'Gagal: Nomor WhatsApp {phone} sudah digunakan oleh {dup_phone.name}!', 'error')
                return redirect(url_for('admin.users'))
            user.phone = phone

        # Memperbarui Email (Sanitasi nilai kosong/None dan cek duplikasi)
        email_raw = request.form.get('email')
        if email_raw:
            cleaned_email = email_raw.strip()
            if cleaned_email in ('', "''", '""', 'None', 'none', 'null'):
                user.email = None
            else:
                dup_email = User.query.filter(User.email == cleaned_email, User.id != user.id).first()
                if dup_email:
                    flash(f'Gagal: Email {cleaned_email} sudah digunakan oleh {dup_email.name}!', 'error')
                    return redirect(url_for('admin.users'))
                user.email = cleaned_email
        else:
            user.email = None
        
        # Memperbarui Saldo secara transparan dengan pencatatan Transaksi & Mutasi
        balance_raw = request.form.get('balance')
        if balance_raw is not None and balance_raw != '':
            try:
                new_bal = float(balance_raw)
                old_bal = float(user.balance or 0.0)
                diff = round(new_bal - old_bal, 2)
                if abs(diff) >= 1.0:
                    from app.services.balance_service import adjust_user_balance_manual
                    b_action = 'add' if diff > 0 else 'deduct'
                    b_amt = abs(diff)
                    b_note = request.form.get('balance_note', '').strip() or 'Sinkronisasi/Edit Data Toko oleh Admin'
                    adjust_user_balance_manual(user.id, b_amt, action=b_action, note=b_note, admin_source='Web Admin (Edit Pengguna)')
                else:
                    user.balance = new_bal
            except ValueError:
                pass
            
        # Memperbarui Poin Member
        points_raw = request.form.get('points')
        if points_raw is not None and points_raw != '':
            try:
                new_points = max(0, int(points_raw))
                old_points = int(user.points or 0)
                if new_points != old_points:
                    from app.models.point_log import PointLog
                    diff = new_points - old_points
                    log = PointLog(
                        user_id=user.id,
                        type='ADMIN_ADJUST',
                        points=diff,
                        balance_added=0.0,
                        description=f'Penyesuaian oleh Admin (dari {old_points} ke {new_points} Pts)'
                    )
                    db.session.add(log)
                    user.points = new_points
            except ValueError:
                pass

        # Memperbarui Password
        new_password = request.form.get('password')
        if new_password and new_password.strip():
            user.set_password(new_password.strip())
            
        # Memperbarui Role, Masa Aktif, Komisi, dan Upline
        from app.services.tier_service import get_wib_now, ensure_user_referral_code
        now = get_wib_now()

        new_role = request.form.get('role', 'user')
        user.role = new_role

        status_val = request.form.get('status')
        user.is_active = True if str(status_val) in ('1', 'true', 'True') else False

        # Saldo Komisi Downline
        comm_balance_raw = request.form.get('commission_balance')
        if comm_balance_raw is not None and comm_balance_raw != '':
            try:
                user.commission_balance = max(0.0, float(comm_balance_raw))
            except ValueError:
                pass

        # Masa Aktif Langganan
        expires_date_raw = request.form.get('role_expires_at', '').strip()
        add_days_raw = request.form.get('add_days', '').strip()

        if new_role == 'user':
            user.role_expires_at = None
        elif new_role in ('reseller', 'vip'):
            if new_role == 'vip':
                ensure_user_referral_code(user)

            if expires_date_raw:
                try:
                    if 'T' in expires_date_raw:
                        user.role_expires_at = datetime.strptime(expires_date_raw, '%Y-%m-%dT%H:%M')
                    elif len(expires_date_raw) == 10:
                        user.role_expires_at = datetime.strptime(expires_date_raw, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
                    else:
                        user.role_expires_at = datetime.strptime(expires_date_raw, '%Y-%m-%d %H:%M:%S')
                except Exception:
                    pass
            elif add_days_raw:
                try:
                    days = int(add_days_raw)
                    if days > 0:
                        base_date = user.role_expires_at if (user.role_expires_at and user.role_expires_at > now) else now
                        user.role_expires_at = base_date + timedelta(days=days)
                except Exception:
                    pass
            elif not user.role_expires_at or user.role_expires_at <= now:
                # Default 30 hari jika role baru di-upgrade admin tanpa memilih hari
                user.role_expires_at = now + timedelta(days=30)

        # Upline Assignment / Reset
        upline_raw = request.form.get('upline_input', '').strip()
        if upline_raw:
            if upline_raw in ('0', '-', 'none', 'null', 'hapus'):
                user.upline_id = None
            else:
                up_user = User.query.filter(
                    (User.referral_code == upline_raw) | 
                    (User.phone == upline_raw) | 
                    (User.name == upline_raw) |
                    (User.id == (int(upline_raw) if upline_raw.isdigit() else -1))
                ).first()
                if up_user and up_user.id != user.id:
                    user.upline_id = up_user.id

        # Tambahan: Manual Downline Assignment via Form Submit
        from app.services.tier_service import assign_downline_by_phone
        new_downline_phone = request.form.get('new_downline_phone', '').strip()
        downline_msg = ""
        if new_downline_phone:
            ok_down, msg_down, _ = assign_downline_by_phone(user, new_downline_phone)
            if not ok_down:
                flash(f'Peringatan Downline: {msg_down}', 'warning')
            else:
                downline_msg = f" & {msg_down}"
        
        db.session.commit()
        status_text = "diaktifkan" if user.is_active else "diblokir"
        flash(f'Data pengguna {user.name} berhasil diperbarui (Status: {status_text}){downline_msg}!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Terjadi kesalahan sistem: {str(e)}', 'error')
        
    return redirect(url_for('admin.users'))


@admin_bp.route('/user/reset_points/<int:user_id>', methods=['POST'])
def reset_user_points_action(user_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))
    try:
        user = User.query.get(user_id)
        if user:
            old_pts = int(user.points or 0)
            user.points = 0
            from app.models.point_log import PointLog
            plog = PointLog(
                user_id=user.id,
                type='RESET',
                points=-old_pts,
                balance_added=0.0,
                description=f'Reset poin menjadi 0 oleh Admin'
            )
            db.session.add(plog)
            db.session.commit()
            flash(f'Poin pengguna {user.name} berhasil direset menjadi 0.', 'success')
        else:
            flash('Pengguna tidak ditemukan!', 'error')
    except Exception as e:
        db.session.rollback()
        flash(f'Gagal mereset poin: {str(e)}', 'error')
    return redirect(url_for('admin.users'))


@admin_bp.route('/user/<int:user_id>/downlines', methods=['GET'])
def get_user_downlines(user_id):
    """Mengambil daftar seluruh downline aktif dari seorang pengguna."""
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    from app.services.tier_service import get_user_downlines_list
    user = User.query.get(user_id)
    if not user:
        return jsonify({'status': 'error', 'message': 'Pengguna tidak ditemukan'}), 404

    downlines = get_user_downlines_list(user_id)
    return jsonify({
        'status': 'success',
        'upline': {
            'id': user.id,
            'name': user.name,
            'phone': user.phone,
            'role': user.get_effective_role() if hasattr(user, 'get_effective_role') else user.role,
            'referral_code': user.referral_code or '-'
        },
        'count': len(downlines),
        'downlines': downlines
    })


@admin_bp.route('/user/<int:user_id>/add_downline', methods=['POST'])
@csrf.exempt
def add_user_downline(user_id):
    """Menambahkan downline secara manual ke seorang pengguna melalui nomor WhatsApp."""
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    from app.services.tier_service import assign_downline_by_phone
    user = User.query.get(user_id)
    if not user:
        return jsonify({'status': 'error', 'message': 'Pengguna upline tidak ditemukan'}), 404

    data = request.get_json(silent=True) or request.form
    phone = data.get('phone') or data.get('downline_phone') or data.get('new_downline_phone')

    ok, msg, downline = assign_downline_by_phone(user, phone)
    if not ok:
        return jsonify({'status': 'error', 'message': msg}), 400

    return jsonify({
        'status': 'success',
        'message': msg,
        'downline': {
            'id': downline.id,
            'name': downline.name,
            'phone': downline.phone,
            'email': downline.email or '-',
            'role': downline.get_effective_role() if hasattr(downline, 'get_effective_role') else downline.role,
            'balance': float(downline.balance or 0.0),
            'points': int(downline.points or 0)
        }
    })


@admin_bp.route('/user/<int:user_id>/remove_downline/<int:downline_id>', methods=['POST'])
@csrf.exempt
def remove_user_downline(user_id, downline_id):
    """Melepaskan relasi downline dari seorang pengguna."""
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    from app.services.tier_service import remove_downline
    user = User.query.get(user_id)
    if not user:
        return jsonify({'status': 'error', 'message': 'Pengguna upline tidak ditemukan'}), 404

    ok, msg = remove_downline(user, downline_id)
    if not ok:
        return jsonify({'status': 'error', 'message': msg}), 400

    return jsonify({
        'status': 'success',
        'message': msg
    })



@admin_bp.route('/user/<int:user_id>/audit_saldo')
def user_audit_saldo(user_id):
    """
    Halaman Rekonsiliasi & Audit Alur Saldo VIP beserta seluruh Kasir Cabang.
    Menampilkan perputaran deposit, transfer antar cabang, penjualan kasir, dan penarikan.
    """
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    user = User.query.get_or_404(user_id)
    from app.models.trusted_device import TrustedDevice
    from app.models.branch_mutation import BranchMutation
    from app.models.transaction import Transaction

    branches = TrustedDevice.query.filter_by(user_id=user.id).order_by(TrustedDevice.created_at.asc()).all()

    # Ringkasan Saldo
    saldo_utama = float(user.balance or 0.0)
    total_saldo_cabang = sum(float(b.branch_balance or 0.0) for b in branches if b.status == 'approved')
    total_aset = saldo_utama + total_saldo_cabang

    # Statistik Penjualan per Cabang
    for b in branches:
        b.sales_count = Transaction.query.filter_by(device_id=b.id, status='SUCCESS').count()
        b.sales_volume = db.session.query(db.func.sum(Transaction.amount)).filter_by(device_id=b.id, status='SUCCESS').scalar() or 0.0

    # Total Finansial Akun
    total_deposit_sukses = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.user_id == user.id,
        Transaction.sku_code.in_(['DEPOSIT_SALDO', 'DEPOSIT_MANUAL']),
        Transaction.status == 'SUCCESS'
    ).scalar() or 0.0

    total_belanja_cabang = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.user_id == user.id,
        Transaction.device_id != None,
        Transaction.status == 'SUCCESS'
    ).scalar() or 0.0

    total_belanja_web = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.user_id == user.id,
        Transaction.device_id == None,
        ~Transaction.sku_code.in_(['DEPOSIT_SALDO', 'DEPOSIT_MANUAL']),
        Transaction.status == 'SUCCESS'
    ).scalar() or 0.0

    total_belanja_all = total_belanja_cabang + total_belanja_web

    # Timeline Perputaran Saldo Terpadu
    timeline = []

    # 1. Deposit Masuk
    deposits = Transaction.query.filter(
        Transaction.user_id == user.id,
        Transaction.sku_code.in_(['DEPOSIT_SALDO', 'DEPOSIT_MANUAL'])
    ).all()
    for d in deposits:
        timeline.append({
            'timestamp': d.created_at,
            'category': 'deposit',
            'badge_text': 'DEPOSIT MASUK',
            'badge_bg': '#ecfdf5',
            'badge_color': '#059669',
            'icon': 'fas fa-arrow-down',
            'icon_color': '#059669',
            'entity': 'Saldo Utama Owner',
            'title': f"Deposit {d.payment_method.upper()}",
            'description': f"Isi Saldo ({d.product_name})",
            'target': d.target_number or user.phone,
            'ref_id': d.ref_id,
            'amount': float(d.amount),
            'amount_prefix': '+',
            'amount_color': '#059669',
            'status': d.status,
            'balance_impact': 'Menambah Saldo Utama'
        })

    # 2. Mutasi Saldo Cabang
    b_muts = BranchMutation.query.filter_by(user_id=user.id).all()
    for m in b_muts:
        dev_name = m.device.device_name if m.device else f"Cabang #{m.device_id}"
        if m.type == 'TOPUP_FROM_OWNER':
            timeline.append({
                'timestamp': m.created_at,
                'category': 'transfer',
                'badge_text': 'TRANSFER KE CABANG',
                'badge_bg': '#e0f2fe',
                'badge_color': '#0284c7',
                'icon': 'fas fa-share-square',
                'icon_color': '#0284c7',
                'entity': f"Saldo Utama ➔ {dev_name}",
                'title': f"Alokasi Saldo ke {dev_name}",
                'description': m.description or f"Pengiriman modal kasir (Shift: {m.shift_name or 'Kasir'})",
                'target': dev_name,
                'ref_id': f"MUT-{m.id}",
                'amount': float(m.amount),
                'amount_prefix': '⇄',
                'amount_color': '#0284c7',
                'status': 'SUCCESS',
                'balance_impact': f"Saldo Utama -Rp {m.amount:,.0f} | Saldo Cabang Menjadi Rp {m.balance_after:,.0f}"
            })
        elif m.type == 'WITHDRAW_TO_OWNER':
            timeline.append({
                'timestamp': m.created_at,
                'category': 'withdraw',
                'badge_text': 'TARIK DARI CABANG',
                'badge_bg': '#fef3c7',
                'badge_color': '#b45309',
                'icon': 'fas fa-reply',
                'icon_color': '#b45309',
                'entity': f"{dev_name} ➔ Saldo Utama",
                'title': f"Tarik Saldo dari {dev_name}",
                'description': m.description or "Penarikan modal cabang kembali ke Saldo Utama Owner",
                'target': dev_name,
                'ref_id': f"MUT-{m.id}",
                'amount': float(m.amount),
                'amount_prefix': '⇄',
                'amount_color': '#b45309',
                'status': 'SUCCESS',
                'balance_impact': f"Saldo Cabang -Rp {m.amount:,.0f} (Sisa: Rp {m.balance_after:,.0f}) | Saldo Utama bertambah"
            })
        elif m.type == 'SALE':
            timeline.append({
                'timestamp': m.created_at,
                'category': 'sale_cabang',
                'badge_text': 'TRANSAKSI KASIR CABANG',
                'badge_bg': '#fef2f2',
                'badge_color': '#dc2626',
                'icon': 'fas fa-cash-register',
                'icon_color': '#dc2626',
                'entity': dev_name,
                'title': f"Penjualan di {dev_name}",
                'description': m.description or f"Transaksi POS kasir (Shift: {m.shift_name or 'Kasir'})",
                'target': dev_name,
                'ref_id': f"MUT-{m.id}",
                'amount': float(m.amount),
                'amount_prefix': '-',
                'amount_color': '#dc2626',
                'status': 'SUCCESS',
                'balance_impact': f"Potong Saldo Cabang (Sisa Saldo Cabang: Rp {m.balance_after:,.0f})"
            })
        elif m.type == 'REFUND':
            timeline.append({
                'timestamp': m.created_at,
                'category': 'refund',
                'badge_text': 'REFUND CABANG',
                'badge_bg': '#f0fdf4',
                'badge_color': '#10b981',
                'icon': 'fas fa-undo-alt',
                'icon_color': '#10b981',
                'entity': dev_name,
                'title': f"Pengembalian Dana ke {dev_name}",
                'description': m.description or "Refund otomatis untuk transaksi cabang yang gagal/dibatalkan",
                'target': dev_name,
                'ref_id': f"MUT-{m.id}",
                'amount': float(m.amount),
                'amount_prefix': '+',
                'amount_color': '#10b981',
                'status': 'SUCCESS',
                'balance_impact': f"Saldo Cabang Dipulihkan Menjadi Rp {m.balance_after:,.0f}"
            })

    # 3. Transaksi Web Utama milik Owner (jika ada pembelian via web)
    web_sales = Transaction.query.filter(
        Transaction.user_id == user.id,
        Transaction.device_id == None,
        ~Transaction.sku_code.in_(['DEPOSIT_SALDO', 'DEPOSIT_MANUAL']),
        Transaction.payment_method == 'SALDO'
    ).all()
    for ws in web_sales:
        timeline.append({
            'timestamp': ws.created_at,
            'category': 'sale_web',
            'badge_text': 'TRANSAKSI WEB UTAMA',
            'badge_bg': '#eef2ff',
            'badge_color': '#6366f1',
            'icon': 'fas fa-globe',
            'icon_color': '#6366f1',
            'entity': 'Saldo Utama Owner',
            'title': f"Order Web: {ws.product_name}",
            'description': f"Tujuan: {ws.target_number} (SKU: {ws.sku_code})",
            'target': ws.target_number,
            'ref_id': ws.ref_id,
            'amount': float(ws.amount),
            'amount_prefix': '-',
            'amount_color': '#6366f1',
            'status': ws.status,
            'balance_impact': 'Memotong Saldo Utama Owner'
        })

    # Urutkan kronologi dari terbaru ke terlama
    timeline.sort(key=lambda x: x['timestamp'] or datetime.min, reverse=True)

    # Tambahkan format waktu WIB
    for item in timeline:
        if item['timestamp']:
            wib = item['timestamp'] + timedelta(hours=7)
            item['date_str'] = wib.strftime('%d-%m-%Y')
            item['time_str'] = wib.strftime('%H:%M WIB')
        else:
            item['date_str'] = '-'
            item['time_str'] = '-'

    # Filter kategori jika diminta oleh admin
    cat_filter = request.args.get('cat', 'all').strip().lower()
    if cat_filter != 'all':
        timeline = [item for item in timeline if item['category'] == cat_filter]

    return render_template('admin/user_audit_saldo.html',
                           user=user,
                           branches=branches,
                           saldo_utama=saldo_utama,
                           total_saldo_cabang=total_saldo_cabang,
                           total_aset=total_aset,
                           total_deposit_sukses=total_deposit_sukses,
                           total_belanja_cabang=total_belanja_cabang,
                           total_belanja_web=total_belanja_web,
                           total_belanja_all=total_belanja_all,
                           timeline=timeline,
                           cat_filter=cat_filter)

@admin_bp.route('/sync_vipreseller', methods=['POST'])
def sync_vipreseller():
    from app.services.vip_reseller import VIPReseller
    from app.models.product import Product
    from app.models.margin import MarginTier
    from app import db
    vip = VIPReseller()
    
    # Menarik Data dari KEDUA Endpoint secara serentak
    res_prepaid = vip.get_services()
    res_games = vip.get_game_services()
    
    products_data = []
    
    # Gabungkan Data Prepaid
    if res_prepaid and res_prepaid.get('result'):
        for p in res_prepaid.get('data', []):
            p['_is_game'] = False
            products_data.append(p)
            
    # Gabungkan Data Games Premium (Genshin, Roblox, Valorant, dll)
    if res_games and res_games.get('result'):
        for p in res_games.get('data', []):
            p['_is_game'] = True
            products_data.append(p)
            
    if not products_data:
        err_msgs = []
        if res_prepaid and not res_prepaid.get('result'):
            err_msgs.append(f"Prepaid: {res_prepaid.get('message', 'Error')}")
        if res_games and not res_games.get('result'):
            err_msgs.append(f"Games: {res_games.get('message', 'Error')}")
        detail_msg = " | ".join(err_msgs) if err_msgs else "Respon data kosong dari server VIP-Reseller."
        hint = ""
        if 'whitelist' in detail_msg.lower() or 'ip' in detail_msg.lower():
            hint = " (Pastikan IP VPS Anda sudah didaftarkan pada Whitelist IP di Panel VIP-Reseller)"
        flash(f"❌ Gagal menarik data dari VIP-Reseller: {detail_msg}{hint}", 'danger')
        return redirect(url_for('admin.dashboard'))
        
    tiers = MarginTier.query.all()
    def get_margin(base_price):
        for t in tiers:
            if t.min_price <= base_price <= t.max_price:
                return t.margin
        return 0
        
    new_count, update_count = 0, 0
    
    for p in products_data:
        sku = p.get('code')
        if not sku: continue
        
        # Ekstrak Harga
        if isinstance(p.get('price'), dict):
            base_price = float(p.get('price', {}).get('basic', 0))
        else:
            base_price = float(p.get('price', 0))
            
        sell_price = base_price + get_margin(base_price)
        status_str = str(p.get('status', '')).lower()
        is_active = 1 if status_str in ['available', 'normal', '1'] else 0
        
        # Logika Kategori & Brand Cerdas
        if p.get('_is_game'):
            raw_brand = str(p.get('game', 'Lainnya'))
            category_name = 'Games' # Memaksa semua API Game masuk kategori Games
        else:
            raw_brand = str(p.get('brand', 'Lainnya'))
            category_name = str(p.get('category', 'Lainnya'))
            
        brand_vip = 'VIP-' + raw_brand
        raw_name = str(p.get('name', 'Tanpa Nama')).replace('[VIP] ', '')
        name_vip = f"[VIP] {raw_name}"
        
        existing = Product.query.filter_by(sku_code=sku).first()
        if existing:
            if not existing.is_manual_margin:
                existing.sell_price = sell_price
            existing.base_price = base_price
            existing.is_active = is_active
            existing.name = name_vip
            existing.brand = brand_vip
            existing.category = category_name
            update_count += 1
        else:
            new_prod = Product(
                sku_code=sku,
                name=name_vip,
                category=category_name,
                brand=brand_vip,
                base_price=base_price,
                sell_price=sell_price,
                is_active=is_active
            )
            db.session.add(new_prod)
            new_count += 1
            
    db.session.commit()
    flash(f"Sinkronisasi VIP-Reseller Sukses! {new_count} Game Baru, {update_count} Diperbarui.", 'success')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/toggle_vip_reseller', methods=['POST'])
def toggle_vip_reseller():
    """
    Mengaktifkan atau Menonaktifkan seluruh provider VIP-Reseller secara instan.
    Ketika OFF, seluruh produk VIP-Reseller (Game, Voucher, dll) disembunyikan
    dari website pengguna dan kasir POS, sehingga hanya produk Digiflazz yang tampil.
    """
    from app.services.setting_service import is_vip_reseller_enabled, set_vip_reseller_status
    current_status = is_vip_reseller_enabled()
    new_status = not current_status
    set_vip_reseller_status(new_status)
    
    try:
        from app.extensions import cache
        cache.clear()
    except Exception:
        pass
        
    if new_status:
        flash("✅ Provider VIP-Reseller BERHASIL DIAKTIFKAN (ON). Seluruh katalog game & voucher VIP kini tampil di website dan kasir.", "success")
    else:
        flash("⚠️ Provider VIP-Reseller BERHASIL DINONAKTIFKAN (OFF). Seluruh produk VIP-Reseller kini disembunyikan. Hanya produk Digiflazz yang tampil.", "warning")
        
    return redirect(url_for('admin.dashboard'))


# =====================================================================
# =====================================================================
# API BOT WHATSAPP PAIRING (REAL NODE.JS CONNECTION) & AUTO-RECOVERY
# =====================================================================
def _find_executable(name):
    """
    Mencari binary executable (node, pm2, npm) secara komprehensif di PATH,
    direktori standar Linux, nvm (/root/.nvm, /home/*/.nvm), dan snap.
    """
    import shutil, glob, os, subprocess

    # 1. Cek standard PATH
    p = shutil.which(name)
    if p and os.path.isfile(p):
        return p

    # 2. Cek lokasi standar Linux
    candidates = [
        f"/usr/local/bin/{name}",
        f"/usr/bin/{name}",
        f"/bin/{name}",
        f"/snap/bin/{name}",
        f"/root/.npm-global/bin/{name}",
    ]
    for loc in candidates:
        if os.path.isfile(loc) and (os.access(loc, os.X_OK) or os.name == 'nt'):
            return loc

    # 3. Cek pola NVM di /root dan /home
    nvm_patterns = [
        f"/root/.nvm/versions/node/*/bin/{name}",
        f"/home/*/.nvm/versions/node/*/bin/{name}",
        f"/home/*/.npm-global/bin/{name}",
        f"/var/www/.nvm/versions/node/*/bin/{name}",
    ]
    for pat in nvm_patterns:
        matches = glob.glob(pat)
        if matches:
            for m in sorted(matches, reverse=True):
                if os.path.isfile(m) and (os.access(m, os.X_OK) or os.name == 'nt'):
                    return m

    # 4. Coba temukan via login shell bash (evaluasi .bashrc / .profile)
    if os.name != 'nt':
        try:
            out = subprocess.run(
                ['bash', '-l', '-c', f'which {name}'],
                capture_output=True, text=True, timeout=3
            )
            if out.returncode == 0:
                cand = out.stdout.strip()
                if cand and os.path.isfile(cand):
                    return cand
        except Exception:
            pass

    return None


def _ensure_wa_bot_running():
    """
    Mengecek apakah Mesin Baileys di port 3000 aktif.
    Jika tidak aktif, mencoba menyalakan via PM2 (di Linux) atau background node.
    """
    import requests, subprocess, sys, os, time
    from flask import current_app

    # 1. Cek dulu apakah port 3000 sudah merespons (coba 127.0.0.1 dan localhost)
    for host in ['127.0.0.1', 'localhost']:
        try:
            r = requests.get(f'http://{host}:3000/api/status', timeout=2)
            if r.status_code == 200:
                return True, "Mesin Node.js sudah aktif di port 3000."
        except Exception:
            pass

    # 2. Persiapkan direktori & file log
    base_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    wa_bot_dir = os.path.join(base_dir, 'wa_bot')
    server_js = os.path.join(wa_bot_dir, 'server_bot.js')
    log_dir = os.path.join(base_dir, 'storage', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'wa_bot.log')

    if not os.path.exists(server_js):
        return False, f"File server_bot.js tidak ditemukan di {wa_bot_dir}."

    node_bin = _find_executable('node')
    npm_bin = _find_executable('npm')
    pm2_bin = _find_executable('pm2')

    if not node_bin and not pm2_bin:
        return False, (
            "Node.js belum terinstall di server VPS Anda. "
            "Silakan buka terminal VPS dan jalankan: bash wa_bot/setup_pm2.sh"
        )

    # 3. Cek dependensi node_modules
    baileys_pkg = os.path.join(wa_bot_dir, 'node_modules', '@whiskeysockets', 'baileys')
    express_pkg = os.path.join(wa_bot_dir, 'node_modules', 'express')
    if not (os.path.exists(baileys_pkg) and os.path.exists(express_pkg)):
        if npm_bin:
            try:
                current_app.logger.info("Menginstall dependencies wa_bot via npm...")
                subprocess.run([npm_bin, 'install', '--omit=dev'], cwd=wa_bot_dir, capture_output=True, text=True, timeout=180)
            except Exception as e:
                current_app.logger.warning(f"npm install warning: {e}")

    # 4. Coba nyalakan mesin bot
    start_method = "direct node"
    pm2_error_msg = ""
    if pm2_bin:
        try:
            # Set PATH agar PM2 menemukan binary node
            pm2_env = os.environ.copy()
            if node_bin:
                node_dir = os.path.dirname(node_bin)
                pm2_env['PATH'] = node_dir + os.pathsep + pm2_env.get('PATH', '')

            res = subprocess.run([pm2_bin, 'restart', 'garudatel-wa-bot'], cwd=wa_bot_dir, capture_output=True, text=True, env=pm2_env, timeout=12)
            if res.returncode != 0:
                res = subprocess.run([pm2_bin, 'start', 'server_bot.js', '--name', 'garudatel-wa-bot', '--restart-delay=3000'], cwd=wa_bot_dir, capture_output=True, text=True, env=pm2_env, timeout=12)
                if res.returncode == 0:
                    subprocess.run([pm2_bin, 'save'], cwd=wa_bot_dir, capture_output=True, text=True, env=pm2_env, timeout=5)
                    start_method = "pm2"
                else:
                    pm2_error_msg = (res.stderr or res.stdout or "").strip()
            else:
                start_method = "pm2"
        except Exception as e:
            pm2_error_msg = str(e)
            current_app.logger.warning(f"PM2 auto-start failed: {e}")

    if start_method != "pm2" and node_bin:
        # Fallback jalankan proses node di latar belakang
        try:
            with open(log_file, 'a', encoding='utf-8') as out_f:
                if sys.platform == 'win32':
                    subprocess.Popen([node_bin, 'server_bot.js'], cwd=wa_bot_dir, stdout=out_f, stderr=out_f, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS)
                else:
                    subprocess.Popen([node_bin, 'server_bot.js'], cwd=wa_bot_dir, stdout=out_f, stderr=out_f, start_new_session=True)
            start_method = "direct node"
        except Exception as e:
            current_app.logger.warning(f"Direct node start failed: {e}")

    # 5. Tunggu hingga socket siap mendengarkan (hingga 8 detik)
    for _ in range(8):
        time.sleep(1)
        for host in ['127.0.0.1', 'localhost']:
            try:
                r = requests.get(f'http://{host}:3000/api/status', timeout=2)
                if r.status_code == 200:
                    return True, f"Mesin Node.js berhasil dihidupkan ({start_method}) dan siap di port 3000!"
            except Exception:
                pass

    # Ambil catatan log terakhir untuk diagnostik
    last_log = ""
    if os.path.exists(log_file):
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as lf:
                lines = lf.readlines()
                last_log = "".join(lines[-4:]).strip()
        except Exception:
            pass

    diag = []
    diag.append(f"Node: {'OK' if node_bin else 'Tidak Ditemukan'}")
    diag.append(f"PM2: {'OK' if pm2_bin else 'Tidak Ditemukan'}")
    if pm2_error_msg:
        diag.append(f"PM2 Err: {pm2_error_msg[:60]}")
    if last_log:
        diag.append(f"Log: {last_log[:80]}")

    detail = " | ".join(diag)
    return False, f"Mesin belum merespons di port 3000 ({detail}). Silakan jalankan 'bash wa_bot/setup_pm2.sh' di terminal VPS."


@admin_bp.route('/wa_pairing', methods=['POST'])
def wa_pairing():
    from flask import request, jsonify
    import requests
    
    try:
        data = request.get_json() or {}
        bot_number = data.get('number')
        if not bot_number:
            return jsonify({'status': 'error', 'message': 'Nomor WhatsApp tidak boleh kosong'})
            
        from app.wa_helper import _get_wa_headers
        wa_headers = _get_wa_headers()

        # Mengirim sinyal ke Mesin Baileys Node.js
        try:
            response = requests.post('http://127.0.0.1:3000/api/pair', json={'number': bot_number}, headers=wa_headers, timeout=30)
            return jsonify(response.json())
        except requests.exceptions.RequestException:
            # Jika port 3000 belum menyala, coba auto-recovery
            ok, msg = _ensure_wa_bot_running()
            if ok:
                try:
                    response = requests.post('http://127.0.0.1:3000/api/pair', json={'number': bot_number}, headers=wa_headers, timeout=30)
                    return jsonify(response.json())
                except Exception as ex:
                    return jsonify({'status': 'error', 'message': f'Mesin dinyalakan namun pairing gagal: {ex}'})
            else:
                return jsonify({
                    'status': 'error',
                    'message': f'Gagal menghubungi Mesin Node.js: {msg}'
                })
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@admin_bp.route('/wa_restart', methods=['POST'])
def wa_restart():
    from flask import jsonify
    ok, msg = _ensure_wa_bot_running()
    return jsonify({'status': 'success' if ok else 'error', 'message': msg})


@admin_bp.route('/wa_reset_session', methods=['POST'])
def wa_reset_session():
    from flask import jsonify
    import requests
    import os, shutil
    from app.wa_helper import _get_wa_headers
    
    try:
        r = requests.post('http://127.0.0.1:3000/api/reset', headers=_get_wa_headers(), timeout=5)
        if r.status_code == 200:
            return jsonify(r.json())
    except Exception:
        pass
        
    # Manual reset: hapus auth_info_baileys dari disk dan restart mesin
    base_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    auth_dir = os.path.join(base_dir, 'wa_bot', 'auth_info_baileys')
    if os.path.exists(auth_dir):
        try:
            shutil.rmtree(auth_dir)
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Gagal menghapus folder sesi: {e}'})
            
    _ensure_wa_bot_running()
    return jsonify({
        'status': 'success',
        'message': 'Sesi WhatsApp berhasil dibersihkan & mesin direstart. Silakan masukkan nomor dan minta kode pairing baru.'
    })


@admin_bp.route('/wa_diagnostics', methods=['GET'])
def wa_diagnostics():
    from flask import jsonify
    import os, requests, subprocess
    
    base_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    wa_bot_dir = os.path.join(base_dir, 'wa_bot')
    log_file = os.path.join(base_dir, 'storage', 'logs', 'wa_bot.log')
    
    node_bin = _find_executable('node')
    npm_bin = _find_executable('npm')
    pm2_bin = _find_executable('pm2')
    
    node_ver = None
    if node_bin:
        try:
            node_ver = subprocess.run([node_bin, '-v'], capture_output=True, text=True, timeout=3).stdout.strip()
        except Exception:
            pass
            
    pm2_ver = None
    if pm2_bin:
        try:
            pm2_ver = subprocess.run([pm2_bin, '-v'], capture_output=True, text=True, timeout=3).stdout.strip()
        except Exception:
            pass

    port_status = False
    port_resp = None
    for host in ['127.0.0.1', 'localhost']:
        try:
            r = requests.get(f'http://{host}:3000/api/status', timeout=2)
            if r.status_code == 200:
                port_status = True
                port_resp = r.json()
                break
        except Exception as e:
            port_resp = {'error': str(e)}

    node_modules_ok = os.path.exists(os.path.join(wa_bot_dir, 'node_modules', '@whiskeysockets', 'baileys'))
    
    log_tail = ""
    if os.path.exists(log_file):
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                log_tail = "".join(lines[-10:])
        except Exception:
            pass

    return jsonify({
        'status': 'success',
        'diagnostics': {
            'node_path': node_bin,
            'node_version': node_ver,
            'npm_path': npm_bin,
            'pm2_path': pm2_bin,
            'pm2_version': pm2_ver,
            'node_modules_installed': node_modules_ok,
            'port_3000_listening': port_status,
            'port_3000_data': port_resp,
            'log_tail': log_tail
        }
    })


# =====================================================================
# API GENERATE OTP MANUAL DARURAT (10 MENIT & NOTIFIKASI TELEGRAM CS)
# =====================================================================
@admin_bp.route('/generate_otp_manual', methods=['POST'])
@csrf.exempt
def generate_otp_manual():
    from flask import request, jsonify
    import urllib.parse
    
    try:
        data = request.get_json() or {}
        target_number = data.get('number', '').strip()
        user_name = data.get('name', '').strip() or None
        send_tele = data.get('send_telegram', True)
        
        if not target_number:
            return jsonify({'status': 'error', 'message': 'Nomor WhatsApp wajib diisi'})
            
        from app.services.otp_service import create_otp
        from app.services.telegram_service import send_emergency_otp_request
        
        # Simpan OTP ke tabel database OtpCode dengan masa berlaku 10 menit (600 detik)
        expiry_seconds = 10 * 60
        otp_code = create_otp(target_number, action='manual', username=user_name, expiry_seconds=expiry_seconds)
        
        # Bersihkan format nomor untuk direct WhatsApp
        clean_num = ''.join(filter(str.isdigit, str(target_number)))
        if clean_num.startswith('0'):
            clean_num = '62' + clean_num[1:]

        from app.services.setting_service import get_store_name
        current_store = get_store_name()
        
        # Susun pesan WhatsApp untuk user
        display_name = user_name or 'Pengguna / Calon Member'
        wa_message = (
            f"Halo kak {display_name}!\n\n"
            f"Berikut adalah *Kode OTP Darurat* Anda untuk akun {current_store}:\n\n"
            f"👉 *{otp_code}*\n\n"
            f"⚠️ *PENTING:* Kode OTP ini bersifat rahasia dan *HANYA BERLAKU 10 MENIT* "
            f"khusus untuk nomor ini ({clean_num}).\n\n"
            f"Silakan masukkan kode pada formulir verifikasi Anda di website {current_store}. Terima kasih!"
        )
        wa_link = f"https://wa.me/{clean_num}?text={urllib.parse.quote(wa_message)}"
        
        # Kirim notifikasi ke Bot Telegram CS
        tele_sent = False
        tele_msg = ""
        if send_tele:
            tele_sent, tele_msg, _ = send_emergency_otp_request(
                phone=clean_num,
                otp_code=otp_code,
                user_name=user_name,
                action_type='Admin Generate Manual',
                expiry_minutes=10
            )
        
        return jsonify({
            'status': 'success',
            'otp': otp_code,
            'expiry_minutes': 10,
            'phone': clean_num,
            'wa_link': wa_link,
            'telegram_sent': tele_sent,
            'telegram_message': tele_msg,
            'message': 'Kode OTP Darurat (10 Menit) berhasil diciptakan & notifikasi dikirim ke CS!'
        })
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


# =====================================================================
# PUSAT PERSETUJUAN BANTUAN OTP MANUAL (ADMIN PANEL)
# =====================================================================
@admin_bp.context_processor
def inject_pending_otp():
    try:
        from app.models.otp_manual import OtpManualRequest
        count = OtpManualRequest.query.filter_by(status='PENDING').count()
        return dict(pending_otp_count=count)
    except Exception:
        return dict(pending_otp_count=0)

@admin_bp.route('/otp_manual')
def otp_manual():
    from app.models.otp_manual import OtpManualRequest
    requests_list = OtpManualRequest.query.order_by(OtpManualRequest.id.desc()).limit(100).all()
    count_pending = OtpManualRequest.query.filter_by(status='PENDING').count()
    count_approved = OtpManualRequest.query.filter_by(status='APPROVED').count()
    count_rejected = OtpManualRequest.query.filter_by(status='REJECTED').count()
    return render_template(
        'admin/otp_manual.html',
        requests_list=requests_list,
        count_pending=count_pending,
        count_approved=count_approved,
        count_rejected=count_rejected,
        page_title='Pusat Bantuan OTP Manual'
    )

@admin_bp.route('/otp_manual/approve', methods=['POST'])
@csrf.exempt
def otp_manual_approve():
    from app.models.otp_manual import OtpManualRequest
    from flask import request, jsonify
    import urllib.parse
    import random
    
    try:
        data = request.get_json() or {}
        req_id = data.get('request_id')
        manual_req = OtpManualRequest.query.get(req_id)
        if not manual_req:
            return jsonify({'status': 'error', 'message': 'Data permohonan tidak ditemukan.'})
            
        otp_code = str(random.randint(100000, 999999))
        manual_req.otp_code = otp_code
        manual_req.status = 'APPROVED'
        manual_req.approved_at = datetime.utcnow()
        manual_req.expires_at = time.time() + 600 # 10 menit
        manual_req.attempts = 0
        db.session.commit()
        
        clean_num = ''.join(filter(str.isdigit, str(manual_req.phone)))
        if clean_num.startswith('0'):
            clean_num = '62' + clean_num[1:]
            
        from app.services.setting_service import get_store_name
        current_store = get_store_name()
        
        wa_message = (
            f"Halo kak {manual_req.name or 'Pelanggan'}!\n\n"
            f"Permintaan bantuan OTP Anda telah *DISETUJUI* oleh Admin {current_store}.\n"
            f"Berikut adalah Kode OTP Anda:\n\n"
            f"👉 *{otp_code}*\n\n"
            f"⚠️ *PENTING:* Kode ini berlaku selama *10 MENIT* khusus untuk nomor {clean_num}. "
            f"Silakan masukkan pada form verifikasi Anda di website {current_store}."
        )
        wa_link = f"https://wa.me/{clean_num}?text={urllib.parse.quote(wa_message)}"
        
        return jsonify({
            'status': 'success',
            'message': 'Permintaan OTP berhasil disetujui!',
            'otp_code': otp_code,
            'phone': clean_num,
            'wa_link': wa_link
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)})

@admin_bp.route('/otp_manual/reject', methods=['POST'])
@csrf.exempt
def otp_manual_reject():
    from app.models.otp_manual import OtpManualRequest
    from flask import request, jsonify
    
    try:
        data = request.get_json() or {}
        req_id = data.get('request_id')
        reason = data.get('reason', '').strip() or 'Permintaan ditolak oleh Administrator'
        
        manual_req = OtpManualRequest.query.get(req_id)
        if not manual_req:
            return jsonify({'status': 'error', 'message': 'Data permohonan tidak ditemukan.'})
            
        manual_req.status = 'REJECTED'
        manual_req.rejection_reason = reason
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': f'Permintaan OTP berhasil ditolak dengan alasan: {reason}'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)})

@admin_bp.route('/otp_manual/unblock', methods=['POST'])
@csrf.exempt
def otp_manual_unblock():
    from app.models.otp_manual import OtpManualRequest
    from flask import request, jsonify
    
    try:
        data = request.get_json() or {}
        req_id = data.get('request_id')
        phone = data.get('phone', '').strip()
        
        # Reset status penolakan untuk request ini atau semua request nomor ini
        if req_id:
            req = OtpManualRequest.query.get(req_id)
            if req:
                req.status = 'UNBLOCKED'
                phone = req.phone
        
        if phone:
            clean_num = ''.join(filter(str.isdigit, str(phone)))
            from app.services.otp_service import get_phone_variants
            variants = get_phone_variants(clean_num)
            rejected_records = OtpManualRequest.query.filter(
                OtpManualRequest.phone.in_(variants),
                OtpManualRequest.status == 'REJECTED'
            ).all()
            for r in rejected_records:
                r.status = 'UNBLOCKED'
                
        db.session.commit()
        return jsonify({
            'status': 'success',
            'message': 'Blokir nomor berhasil dibuka! Pengguna kini dapat mengajukan OTP kembali.'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)})


# =====================================================================
# API CEK STATUS WA (BYPASS FIREWALL)
# =====================================================================
@admin_bp.route('/wa_status', methods=['GET'])
def wa_status():
    from flask import jsonify
    import requests
    try:
        r = requests.get('http://127.0.0.1:3000/api/status', timeout=5)
        return jsonify(r.json())
    except:
        return jsonify({'connected': False})

# =====================================================================
# API TEST KIRIM PESAN WA
# =====================================================================
@admin_bp.route('/wa_test_message', methods=['POST'])
def wa_test_message():
    from flask import request, jsonify
    import requests
    from app.wa_helper import _get_wa_headers
    try:
        data = request.get_json()
        r = requests.post('http://127.0.0.1:3000/api/send', json=data, headers=_get_wa_headers(), timeout=10)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({'status': 'error', 'message': 'Gagal menghubungi Mesin Node.js'})


# =====================================================================
# BANNER CENTER
# =====================================================================
@admin_bp.route('/banner')
def banner():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))
    banners = Banner.query.order_by(Banner.id.desc()).all()
    total_banners = len(banners)
    active_banners = sum(1 for b in banners if b.is_active)
    return render_template('admin/banner.html', banners=banners, total_banners=total_banners, active_banners=active_banners)

@admin_bp.route('/banner/add', methods=['POST'])
def add_banner():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))
    title = request.form.get('title', '').strip()
    image_url = request.form.get('image_url', '').strip()
    link_url = request.form.get('link_url', '').strip()
    is_active = True if request.form.get('is_active') == '1' else False
    
    if not title or not image_url:
        flash('Judul dan URL gambar banner wajib diisi!', 'danger')
        return redirect(url_for('admin.banner'))
        
    b = Banner(title=title, image_url=image_url, link_url=link_url, is_active=is_active)
    db.session.add(b)
    db.session.commit()
    flash('Banner berhasil ditambahkan!', 'success')
    return redirect(url_for('admin.banner'))

@admin_bp.route('/banner/toggle/<int:id>', methods=['POST'])
def toggle_banner(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))
    b = Banner.query.get_or_404(id)
    b.is_active = not b.is_active
    db.session.commit()
    status_str = "diaktifkan" if b.is_active else "dinonaktifkan"
    flash(f"Banner '{b.title}' berhasil {status_str}!", 'success')
    return redirect(url_for('admin.banner'))

@admin_bp.route('/banner/delete/<int:id>', methods=['POST'])
def delete_banner(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))
    b = Banner.query.get_or_404(id)
    db.session.delete(b)
    db.session.commit()
    flash('Banner berhasil dihapus!', 'success')
    return redirect(url_for('admin.banner'))


# =====================================================================
# BROADCAST CENTER
# =====================================================================
@admin_bp.route('/broadcast')
def broadcast():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))
    logs = BroadcastLog.query.order_by(BroadcastLog.id.desc()).limit(20).all()
    total_broadcasts = BroadcastLog.query.count()
    active_users_count = User.query.filter_by(is_active=True).count()
    total_messages_sent = db.session.query(db.func.sum(BroadcastLog.success_count)).scalar() or 0
    return render_template('admin/broadcast.html', 
                           logs=logs, 
                           total_broadcasts=total_broadcasts,
                           active_users_count=active_users_count,
                           total_messages_sent=total_messages_sent)

@admin_bp.route('/broadcast/send', methods=['POST'])
def send_broadcast():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))
    target_type = request.form.get('target_type', 'all')
    raw_custom = request.form.get('custom_numbers', '').strip()
    msg_template = request.form.get('message', '').strip()

    if not msg_template:
        flash('Pesan broadcast tidak boleh kosong!', 'danger')
        return redirect(url_for('admin.broadcast'))

    from app.wa_helper import kirim_wa
    
    recipients = []
    if target_type == 'all':
        users = User.query.filter_by(is_active=True).all()
        recipients = [(u.phone, u.name) for u in users if u.phone]
    else:
        for num in raw_custom.replace('\r', '').split('\n'):
            cleaned = num.strip()
            if cleaned:
                recipients.append((cleaned, 'Pelanggan'))

    if not recipients:
        flash('Tidak ada target penerima broadcast yang valid!', 'danger')
        return redirect(url_for('admin.broadcast'))

    success_c = 0
    failed_c = 0
    for phone, name in recipients:
        text_to_send = msg_template.replace('{name}', name)
        try:
            res = kirim_wa(phone, text_to_send)
            if res:
                success_c += 1
            else:
                failed_c += 1
        except Exception:
            failed_c += 1

    b_log = BroadcastLog(
        target_type=target_type,
        recipient_count=len(recipients),
        success_count=success_c,
        failed_count=failed_c,
        message=msg_template[:500]
    )
    db.session.add(b_log)
    db.session.commit()

    flash(f"Broadcast selesai: {success_c} pesan sukses terkirim, {failed_c} gagal.", 'success')
    return redirect(url_for('admin.broadcast'))


# =====================================================================
# SALDO & DEPOSIT DIGIFLAZZ CENTER
# =====================================================================
@admin_bp.route('/saldo')
def saldo():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    load_dotenv(ENV_FILE, override=True)
    # Cek Saldo dari Cache atau Real-Time API Digiflazz (TTL 60 detik)
    cached_data = cache.get('digi_balance_info')
    if cached_data is not None:
        is_connected, digi_balance, digi_msg = cached_data
    else:
        is_connected, digi_balance, digi_msg = check_balance()
        if is_connected:
            cache.set('digi_balance_info', (is_connected, digi_balance, digi_msg), timeout=60)
    
    # Riwayat Tiket Deposit Digiflazz
    tickets = DigiDepositTicket.query.order_by(DigiDepositTicket.id.desc()).limit(20).all()
    latest_ticket = DigiDepositTicket.query.filter_by(status='PENDING').order_by(DigiDepositTicket.id.desc()).first()
    
    digi_user = os.getenv('DIGI_USER', '')
    digi_key = os.getenv('DIGI_KEY', '')
    digi_url = os.getenv('DIGI_URL', 'https://api.digiflazz.com/v1')
    is_dev_key = digi_key.lower().startswith('dev-')

    return render_template('admin/saldo.html',
                           digi_balance=digi_balance,
                           digi_status=digi_msg,
                           is_connected=is_connected,
                           digi_user=digi_user,
                           digi_url=digi_url,
                           is_dev_key=is_dev_key,
                           tickets=tickets,
                           latest_ticket=latest_ticket)

@admin_bp.route('/saldo/cek', methods=['POST'])
def cek_saldo_digiflazz():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    load_dotenv(ENV_FILE, override=True)
    # Invalidasi cache lama dan perbarui dengan saldo terbaru
    cache.delete('digi_balance_info')
    is_connected, digi_balance, digi_msg = check_balance()
    if is_connected:
        cache.set('digi_balance_info', (is_connected, digi_balance, digi_msg), timeout=60)
        
        # Deteksi otomatis saldo masuk terhadap tiket PENDING
        pending_tickets = DigiDepositTicket.query.filter_by(status='PENDING').order_by(DigiDepositTicket.id.asc()).all()
        prev_balance = cache.get('prev_recorded_digi_balance')
        auto_success_count = 0
        
        if prev_balance is not None and digi_balance > prev_balance:
            balance_diff = digi_balance - prev_balance
            for pt in pending_tickets:
                if abs(pt.amount_transfer - balance_diff) <= 500 or (balance_diff >= pt.amount_requested):
                    pt.status = 'SUCCESS'
                    auto_success_count += 1
                    balance_diff -= pt.amount_transfer
            if auto_success_count > 0:
                db.session.commit()
                flash(f"🎉 Terdeteksi saldo bertambah! {auto_success_count} tiket deposit otomatis diubah statusnya menjadi SUKSES.", 'success')

        cache.set('prev_recorded_digi_balance', digi_balance, timeout=86400 * 7)

        digi_key = os.getenv('DIGI_KEY', '')
        if digi_key.lower().startswith('dev-'):
            flash(f"⚠️ Saldo Digiflazz saat ini: Rp {digi_balance:,.0f} (Mode DEVELOPMENT / Sandbox). Gunakan Production Key untuk melihat saldo riil.", 'warning')
        else:
            flash(f"Saldo Digiflazz saat ini: Rp {digi_balance:,.0f}", 'success')
    else:
        flash(f"Gagal cek saldo Digiflazz: {digi_msg}", 'danger')

    return redirect(url_for('admin.saldo'))

@admin_bp.route('/saldo/tiket', methods=['POST'])
def minta_tiket_deposit():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    load_dotenv(ENV_FILE, override=True)
    try:
        amount = int(request.form.get('amount', 0))
    except (ValueError, TypeError):
        amount = 0

    bank = request.form.get('bank', 'BCA').strip()
    owner_name = request.form.get('owner_name', '').strip()

    if amount < 100000:
        flash('Minimal deposit tiket Digiflazz adalah Rp 100.000!', 'danger')
        return redirect(url_for('admin.saldo'))

    if not owner_name:
        flash('Nama pemilik rekening pengirim wajib diisi!', 'danger')
        return redirect(url_for('admin.saldo'))

    success, data, message = request_deposit(amount, bank, owner_name)

    if success:
        amount_transfer = float(data.get('amount', amount))
        acc_no = data.get('account_no', '') or data.get('account_number', '') or data.get('notes', '')
        acc_name = data.get('account_name', 'PT DIGIFLAZZ INTERKONEKSI INDONESIA')
        notes = data.get('notes', '')
        bank_res = data.get('bank', bank)

        # Simpan ke tabel DigiDepositTicket
        ticket = DigiDepositTicket(
            amount_requested=float(amount),
            amount_transfer=amount_transfer,
            bank=bank_res,
            owner_name=owner_name,
            account_number=acc_no,
            account_name=acc_name,
            notes=notes,
            rc=data.get('rc', '00'),
            status='PENDING'
        )
        db.session.add(ticket)
        db.session.commit()

        digi_key = os.getenv('DIGI_KEY', '')
        if digi_key.lower().startswith('dev-'):
            flash(f"⚠️ Tiket Deposit (SIMULASI DEV) Dibuat! Harap dicatat: Mode Development tidak mencatat tiket pada dashboard member riil Digiflazz.", 'warning')
        else:
            flash(f"✅ Tiket Deposit Berhasil Dibuat! Harap transfer TEPAT Rp {amount_transfer:,.0f} ke rekening {bank_res} ({acc_no}) agar saldo masuk otomatis.", 'success')
    else:
        flash(f"🚨 Gagal membuat tiket deposit: {message}", 'danger')

    return redirect(url_for('admin.saldo'))

@admin_bp.route('/saldo/tiket/batal/<int:id>', methods=['POST'])
def batal_tiket_deposit(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    ticket = DigiDepositTicket.query.get_or_404(id)
    ticket.status = 'CANCELLED'
    db.session.commit()
    flash(f"Tiket deposit #{ticket.id} telah dibatalkan.", 'success')
    return redirect(url_for('admin.saldo'))

@admin_bp.route('/saldo/tiket/sukses/<int:id>', methods=['POST'])
def sukses_tiket_deposit(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    ticket = DigiDepositTicket.query.get_or_404(id)
    ticket.status = 'SUCCESS'
    db.session.commit()
    flash(f"Tiket deposit #{ticket.id} berhasil ditandai sebagai SUKSES.", 'success')
    return redirect(url_for('admin.saldo'))

@admin_bp.route('/saldo/tiket/hapus/<int:id>', methods=['POST'])
def hapus_tiket_deposit(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    ticket = DigiDepositTicket.query.get_or_404(id)
    t_id = ticket.id
    db.session.delete(ticket)
    db.session.commit()
    flash(f"Riwayat tiket deposit #{t_id} berhasil dihapus permanen.", 'success')
    return redirect(url_for('admin.saldo'))

@admin_bp.route('/saldo/tiket/bersihkan', methods=['POST'])
def bersihkan_tiket_deposit():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    deleted_count = DigiDepositTicket.query.filter(DigiDepositTicket.status.in_(['CANCELLED', 'EXPIRED'])).delete(synchronize_session=False)
    db.session.commit()
    flash(f"Berhasil membersihkan {deleted_count} riwayat tiket deposit yang dibatalkan.", 'success')
    return redirect(url_for('admin.saldo'))


# =====================================================================
# =====================================================================
# LAPORAN & REKAPITULASI KEUANGAN (EXECUTIVE P&L / LABA RUGI)
# =====================================================================
@admin_bp.route('/reports')
def reports():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    from app.models.commission import CommissionLog
    from app.models.point_log import PointLog
    from app.services.setting_service import get_report_financial_settings

    time_range = request.args.get('range', '30days').strip().lower()
    start_date_raw = request.args.get('start_date', '').strip()
    end_date_raw = request.args.get('end_date', '').strip()

    # Hitung batas tanggal UTC berdasarkan waktu lokal WIB (UTC+7)
    now_utc = datetime.utcnow()
    now_wib = now_utc + timedelta(hours=7)
    today_wib = now_wib.date()

    start_wib_date = None
    end_wib_date = None

    if time_range == 'today':
        start_wib_date = today_wib
        end_wib_date = today_wib
        range_label = f"Hari Ini ({today_wib.strftime('%d %b %Y')})"
    elif time_range == 'yesterday':
        yest_wib = today_wib - timedelta(days=1)
        start_wib_date = yest_wib
        end_wib_date = yest_wib
        range_label = f"Kemarin ({yest_wib.strftime('%d %b %Y')})"
    elif time_range == '7days':
        start_wib_date = today_wib - timedelta(days=6)
        end_wib_date = today_wib
        range_label = f"7 Hari Terakhir ({start_wib_date.strftime('%d %b')} - {end_wib_date.strftime('%d %b %Y')})"
    elif time_range == 'this_month':
        start_wib_date = today_wib.replace(day=1)
        end_wib_date = today_wib
        range_label = f"Bulan Ini ({start_wib_date.strftime('%d %b')} - {end_wib_date.strftime('%d %b %Y')})"
    elif time_range == 'last_month':
        first_of_this_month = today_wib.replace(day=1)
        last_day_prev = first_of_this_month - timedelta(days=1)
        start_wib_date = last_day_prev.replace(day=1)
        end_wib_date = last_day_prev
        range_label = f"Bulan Lalu ({start_wib_date.strftime('%d %b')} - {end_wib_date.strftime('%d %b %Y')})"
    elif time_range == 'this_year':
        start_wib_date = today_wib.replace(month=1, day=1)
        end_wib_date = today_wib
        range_label = f"Tahun Ini {today_wib.year} (01 Jan - {today_wib.strftime('%d %b %Y')})"
    elif time_range == 'all':
        start_wib_date = None
        end_wib_date = None
        range_label = "Semua Waktu (Sepanjang Masa)"
    elif time_range == 'custom' and (start_date_raw or end_date_raw):
        try:
            start_wib_date = datetime.strptime(start_date_raw, '%Y-%m-%d').date() if start_date_raw else None
        except ValueError:
            start_wib_date = None
        try:
            end_wib_date = datetime.strptime(end_date_raw, '%Y-%m-%d').date() if end_date_raw else today_wib
        except ValueError:
            end_wib_date = today_wib
        
        s_lbl = start_wib_date.strftime('%d %b %Y') if start_wib_date else 'Awal Transaksi'
        e_lbl = end_wib_date.strftime('%d %b %Y') if end_wib_date else 'Hari Ini'
        range_label = f"Periode Kustom: {s_lbl} s/d {e_lbl}"
    else:  # Default '30days'
        time_range = '30days'
        start_wib_date = today_wib - timedelta(days=29)
        end_wib_date = today_wib
        range_label = f"30 Hari Terakhir ({start_wib_date.strftime('%d %b')} - {end_wib_date.strftime('%d %b %Y')})"

    start_utc = None
    end_utc = None
    start_wib_dt = None
    end_wib_dt = None

    if start_wib_date:
        start_wib_dt = datetime.combine(start_wib_date, datetime.min.time())
        start_utc = start_wib_dt - timedelta(hours=7)
    if end_wib_date:
        end_wib_dt = datetime.combine(end_wib_date, datetime.max.time().replace(microsecond=999999))
        end_utc = end_wib_dt - timedelta(hours=7)

    # 1. TRANSAKSI PRODUK DIGITAL (PENJUALAN OMSET & MODAL HPP)
    NON_PRODUCT_SKUS = ['DEPOSIT_SALDO', 'DEPOSIT_MANUAL', 'ADMIN_BALANCE', 'MANUAL_DEDUCTION', 'COMMISSION_PAYOUT']

    prod_trx_base = Transaction.query.filter(~Transaction.sku_code.in_(NON_PRODUCT_SKUS))
    if start_utc:
        prod_trx_base = prod_trx_base.filter(Transaction.created_at >= start_utc)
    if end_utc:
        prod_trx_base = prod_trx_base.filter(Transaction.created_at <= end_utc)

    total_trx = prod_trx_base.count()
    success_trx = prod_trx_base.filter(Transaction.status == 'SUCCESS').count()
    pending_trx = prod_trx_base.filter(Transaction.status == 'PENDING').count()
    failed_trx = prod_trx_base.filter(Transaction.status.in_(['FAILED', 'CANCELLED'])).count()
    success_rate = round((success_trx / total_trx * 100), 1) if total_trx > 0 else 0.0

    # Ambil seluruh transaksi produk sukses untuk agregasi omset & modal provider
    successful_trxs = prod_trx_base.filter(Transaction.status == 'SUCCESS').all()

    # Pre-fetch katalog produk untuk mapping harga modal (HPP) fallback
    product_base_map = {p.sku_code: float(p.base_price or 0.0) for p in Product.query.with_entities(Product.sku_code, Product.base_price).all()}

    total_omset = 0.0
    total_cogs = 0.0
    for t in successful_trxs:
        t_amt = float(t.amount or 0.0)
        t_base = float(t.base_price or 0.0)
        if t_base <= 0:
            t_base = product_base_map.get(t.sku_code, 0.0)
        total_omset += t_amt
        total_cogs += t_base

    # Laba Kotor (Gross Profit)
    gross_profit = total_omset - total_cogs
    gross_margin_percent = round((gross_profit / total_omset * 100), 2) if total_omset > 0 else 0.0

    # 2. DEPOSIT MASUK (ARUS KAS TOP-UP SALDO)
    depo_query = Transaction.query.filter(
        Transaction.sku_code.in_(['DEPOSIT_SALDO', 'DEPOSIT_MANUAL']),
        Transaction.status == 'SUCCESS'
    )
    if start_utc:
        depo_query = depo_query.filter(Transaction.created_at >= start_utc)
    if end_utc:
        depo_query = depo_query.filter(Transaction.created_at <= end_utc)
    total_deposit_in = sum(float(d.amount or 0.0) for d in depo_query.all())
    deposit_count = depo_query.count()

    # 3. BEBAN KOMISI VIP & UPLINE DOWNLINE
    comm_query = CommissionLog.query.filter(CommissionLog.status != 'cancelled')
    if start_wib_dt:
        comm_query = comm_query.filter(CommissionLog.created_at >= start_wib_dt)
    if end_wib_dt:
        comm_query = comm_query.filter(CommissionLog.created_at <= end_wib_dt)

    total_vip_commission = db.session.query(db.func.sum(CommissionLog.commission_amount)).filter(
        CommissionLog.status != 'cancelled',
        (CommissionLog.created_at >= start_wib_dt) if start_wib_dt else True,
        (CommissionLog.created_at <= end_wib_dt) if end_wib_dt else True
    ).scalar() or 0.0
    vip_commission_count = comm_query.count()

    # 4. BEBAN POIN MEMBER (PENCAIRAN POIN KE SALDO RUPIAH)
    point_claim_query = PointLog.query.filter(PointLog.type == 'CLAIM_TO_SALDO')
    if start_utc:
        point_claim_query = point_claim_query.filter(PointLog.created_at >= start_utc)
    if end_utc:
        point_claim_query = point_claim_query.filter(PointLog.created_at <= end_utc)

    total_point_expense = db.session.query(db.func.sum(PointLog.balance_added)).filter(
        PointLog.type == 'CLAIM_TO_SALDO',
        (PointLog.created_at >= start_utc) if start_utc else True,
        (PointLog.created_at <= end_utc) if end_utc else True
    ).scalar() or 0.0
    points_claimed_count = point_claim_query.count()

    # Info poin reward terbit
    earn_query = PointLog.query.filter(PointLog.type == 'EARN_TRX')
    if start_utc:
        earn_query = earn_query.filter(PointLog.created_at >= start_utc)
    if end_utc:
        earn_query = earn_query.filter(PointLog.created_at <= end_utc)
    points_rewarded_total = db.session.query(db.func.sum(PointLog.points)).filter(
        PointLog.type == 'EARN_TRX',
        (PointLog.created_at >= start_utc) if start_utc else True,
        (PointLog.created_at <= end_utc) if end_utc else True
    ).scalar() or 0

    # 5. BEBAN SERVER POKOK & OPERASIONAL LAINNYA (DINAMIS & CUSTOM)
    default_fin_settings = get_report_financial_settings()

    # Periksa override parameter dari GET request
    server_cost_raw = request.args.get('server_cost')
    if server_cost_raw is not None and server_cost_raw.strip() != '':
        try:
            active_server_cost = float(server_cost_raw)
        except ValueError:
            active_server_cost = default_fin_settings['server_cost']
    else:
        active_server_cost = default_fin_settings['server_cost']

    other_cost_raw = request.args.get('other_cost')
    if other_cost_raw is not None and other_cost_raw.strip() != '':
        try:
            active_other_cost = float(other_cost_raw)
        except ValueError:
            active_other_cost = default_fin_settings['other_server_cost']
    else:
        active_other_cost = default_fin_settings['other_server_cost']

    active_other_notes = request.args.get('other_notes', default_fin_settings['other_server_notes']).strip() or default_fin_settings['other_server_notes']
    active_tax_mode = request.args.get('tax_mode', default_fin_settings['tax_mode']).strip().lower()
    if active_tax_mode not in ['percent_omset', 'percent_profit', 'fixed', 'exempt']:
        active_tax_mode = default_fin_settings['tax_mode']

    tax_rate_raw = request.args.get('tax_rate')
    if tax_rate_raw is not None and tax_rate_raw.strip() != '':
        try:
            active_tax_rate = float(tax_rate_raw)
        except ValueError:
            active_tax_rate = default_fin_settings['tax_rate']
    else:
        active_tax_rate = default_fin_settings['tax_rate']

    total_server_costs = active_server_cost + active_other_cost
    total_opex = total_vip_commission + total_point_expense + total_server_costs

    # Laba Operasional Sebelum Pajak (EBT)
    operating_profit = gross_profit - total_opex

    # 6. BEBAN PAJAK PENGHASILAN DINAMIS
    if active_tax_mode == 'percent_omset':
        tax_expense = round(total_omset * (active_tax_rate / 100.0), 2)
        tax_label = f"PPh Final UMKM ({active_tax_rate}% dari Omset)"
    elif active_tax_mode == 'percent_profit':
        taxable_profit = max(0.0, operating_profit)
        tax_expense = round(taxable_profit * (active_tax_rate / 100.0), 2)
        tax_label = f"Pajak Penghasilan ({active_tax_rate}% Laba Operasional)"
    elif active_tax_mode == 'fixed':
        tax_expense = round(active_tax_rate, 2)
        tax_label = f"Pajak Nominal Tetap (Rp {tax_expense:,.0f})"
    else:  # exempt
        tax_expense = 0.0
        tax_label = "Bebas Pajak (0%)"

    # 7. LABA BERSIH AKHIR (NET PROFIT)
    net_profit = operating_profit - tax_expense
    net_margin_percent = round((net_profit / total_omset * 100), 2) if total_omset > 0 else 0.0

    # 8. TOP 5 PRODUK TERLARIS
    top_products_raw = db.session.query(
        Transaction.product_name,
        db.func.count(Transaction.id).label('sales_count'),
        db.func.sum(Transaction.amount).label('subtotal')
    ).filter(
        Transaction.status == 'SUCCESS',
        ~Transaction.sku_code.in_(NON_PRODUCT_SKUS),
        (Transaction.created_at >= start_utc) if start_utc else True,
        (Transaction.created_at <= end_utc) if end_utc else True
    ).group_by(Transaction.product_name).order_by(db.desc('sales_count')).limit(5).all()

    top_products = [
        {'name': p[0], 'sales': p[1], 'revenue': float(p[2] or 0.0)}
        for p in top_products_raw
    ]

    # 9. METODE PEMBAYARAN
    methods_raw = db.session.query(
        Transaction.payment_method,
        db.func.count(Transaction.id).label('trx_count'),
        db.func.sum(Transaction.amount).label('volume')
    ).filter(
        Transaction.status == 'SUCCESS',
        ~Transaction.sku_code.in_(NON_PRODUCT_SKUS),
        (Transaction.created_at >= start_utc) if start_utc else True,
        (Transaction.created_at <= end_utc) if end_utc else True
    ).group_by(Transaction.payment_method).all()

    payment_methods = [
        {'method': m[0] or 'N/A', 'count': m[1], 'volume': float(m[2] or 0.0)}
        for m in methods_raw
    ]

    # Rasio Persentase Pos terhadap Omset untuk Income Statement
    def get_ratio(nom):
        if total_omset <= 0: return 0.0
        return round((nom / total_omset) * 100, 2)

    ratios = {
        'omset': 100.0 if total_omset > 0 else 0.0,
        'cogs': get_ratio(total_cogs),
        'gross_profit': gross_margin_percent,
        'vip_commission': get_ratio(total_vip_commission),
        'point_expense': get_ratio(total_point_expense),
        'server_cost': get_ratio(active_server_cost),
        'other_server_cost': get_ratio(active_other_cost),
        'total_opex': get_ratio(total_opex),
        'operating_profit': get_ratio(operating_profit),
        'tax_expense': get_ratio(tax_expense),
        'net_profit': net_margin_percent
    }

    return render_template('admin/reports.html',
                           time_range=time_range,
                           start_date_str=start_wib_date.strftime('%Y-%m-%d') if start_wib_date else '',
                           end_date_str=end_wib_date.strftime('%Y-%m-%d') if end_wib_date else '',
                           range_label=range_label,
                           total_trx=total_trx,
                           success_trx=success_trx,
                           pending_trx=pending_trx,
                           failed_trx=failed_trx,
                           success_rate=success_rate,
                           total_omset=total_omset,
                           total_cogs=total_cogs,
                           gross_profit=gross_profit,
                           gross_margin_percent=gross_margin_percent,
                           total_deposit_in=total_deposit_in,
                           deposit_count=deposit_count,
                           total_vip_commission=total_vip_commission,
                           vip_commission_count=vip_commission_count,
                           total_point_expense=total_point_expense,
                           points_claimed_count=points_claimed_count,
                           points_rewarded_total=points_rewarded_total,
                           server_cost=active_server_cost,
                           other_server_cost=active_other_cost,
                           other_server_notes=active_other_notes,
                           total_server_costs=total_server_costs,
                           tax_mode=active_tax_mode,
                           tax_rate=active_tax_rate,
                           tax_expense=tax_expense,
                           tax_label=tax_label,
                           total_opex=total_opex,
                           operating_profit=operating_profit,
                           net_profit=net_profit,
                           net_margin_percent=net_margin_percent,
                           ratios=ratios,
                           top_products=top_products,
                           payment_methods=payment_methods,
                           default_fin_settings=default_fin_settings)


@admin_bp.route('/reports/save_settings', methods=['POST'])
@csrf.exempt
def save_reports_settings():
    if not session.get('admin_logged_in'):
        if request.is_json:
            return jsonify({'success': False, 'message': 'Sesi telah berakhir, silakan login kembali'}), 401
        return redirect(url_for('admin.login'))

    from app.services.setting_service import save_report_financial_settings

    if request.is_json:
        data = request.get_json() or {}
    else:
        data = request.form.to_dict()

    try:
        save_report_financial_settings(data)
        if request.is_json:
            return jsonify({
                'success': True,
                'message': 'Konfigurasi default beban server dan skema pajak berhasil disimpan!'
            })
        flash('✅ Pengaturan default beban server & skema pajak berhasil disimpan permanen!', 'success')
        return redirect(url_for('admin.reports', range=request.form.get('range', '30days')))
    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'message': f'Gagal menyimpan: {str(e)}'}), 500
        flash(f'Gagal menyimpan pengaturan: {str(e)}', 'danger')
        return redirect(url_for('admin.reports'))



# ==========================================
# PUSAT PENGATURAN POIN MEMBER (ADMIN)
# ==========================================
@admin_bp.route('/point_settings', methods=['GET', 'POST'])
def point_settings():
    """Halaman konfigurasi skema, nilai tukar, dan aturan dinamis poin member."""
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    from app.models.setting import Setting
    from app.models.point_log import PointLog
    from app.models.user import User

    keys = [
        'point_rate',
        'point_reward_per_trx',
        'point_claim_start_day',
        'point_claim_end_day',
        'point_claim_force_open',
        'point_rules_content'
    ]

    if request.method == 'POST':
        try:
            for k in keys:
                val = request.form.get(k, '')
                if k != 'point_rules_content':
                    val = val.strip()
                s = Setting.query.filter_by(key=k).first()
                if not s:
                    s = Setting(key=k, value=val)
                    db.session.add(s)
                else:
                    s.value = val
            db.session.commit()
            from app.services.setting_service import invalidate_setting_cache
            invalidate_setting_cache()
            flash('Pengaturan & Aturan Poin Member berhasil disimpan!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Gagal menyimpan pengaturan: {str(e)}', 'error')
        return redirect(url_for('admin.point_settings'))

    # GET Request
    settings_dict = {}
    for k in keys:
        s = Setting.query.filter_by(key=k).first()
        settings_dict[k] = s.value if s and s.value else ''

    total_points_circulating = db.session.query(db.func.sum(User.points)).scalar() or 0
    total_balance_disbursed = db.session.query(db.func.sum(PointLog.balance_added)).filter(PointLog.type == 'CLAIM_TO_SALDO').scalar() or 0.0

    return render_template('admin/point_settings.html',
                           settings=settings_dict,
                           total_points_circulating=total_points_circulating,
                           total_balance_disbursed=total_balance_disbursed)


# ==========================================
# RUTE MANAJEMEN NOTIFIKASI ADMIN
# ==========================================
@admin_bp.route('/notifikasi', methods=['GET', 'POST'])
def notifications():
    """Halaman Pengelolaan & Pengiriman Notifikasi Broadcast Admin"""
    from app.models.notification import Notification
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        message = request.form.get('message', '').strip()
        n_type = request.form.get('type', 'info').strip()
        link = request.form.get('link', '').strip() or None
        target = request.form.get('target', 'all').strip()

        target_user_id = None
        if target != 'all' and target.isdigit():
            target_user_id = int(target)

        if not title or not message:
            flash('Judul dan isi pesan notifikasi wajib diisi!', 'danger')
        else:
            notif = Notification(
                title=title,
                message=message,
                type=n_type,
                link=link,
                target_user_id=target_user_id,
                is_broadcast=(target_user_id is None)
            )
            db.session.add(notif)
            db.session.commit()
            target_label = "seluruh pengguna" if target_user_id is None else f"user ID #{target_user_id}"
            flash(f'✅ Notifikasi berhasil dikirimkan ke {target_label}!', 'success')
        return redirect(url_for('admin.notifications'))

    all_notifs = Notification.query.order_by(Notification.created_at.desc()).limit(100).all()
    all_users = User.query.order_by(User.name.asc()).all()
    return render_template('admin/notifikasi.html',
                           notifications=all_notifs,
                           users=all_users)


@admin_bp.route('/notifikasi/delete/<int:id>', methods=['POST'])
def delete_notification(id):
    """Menghapus pesan notifikasi."""
    from app.models.notification import Notification
    notif = Notification.query.get_or_404(id)
    db.session.delete(notif)
    db.session.commit()
    flash('✅ Notifikasi telah berhasil dihapus.', 'success')
    return redirect(url_for('admin.notifications'))


# ==========================================
# RUTE MONITORING TIKET CS (BOT 1 CS) ADMIN
# ==========================================
@admin_bp.route('/tickets')
def tickets():
    """Daftar Tiket Keluhan Pengguna Masuk (CS Center)"""
    from app.models.support_ticket import SupportTicket
    filter_status = request.args.get('status', 'ACTIVE').upper()
    query = SupportTicket.query

    if filter_status == 'ACTIVE':
        # Default: hanya tampilkan tiket aktif (OPEN & PROCESS) agar tidak menumpuk ke bawah
        query = query.filter(SupportTicket.status.in_(['OPEN', 'PROCESS']))
    elif filter_status in ['OPEN', 'PROCESS', 'RESOLVED', 'CLOSED']:
        query = query.filter_by(status=filter_status)
    # Jika 'ALL', tampilkan seluruh tiket tanpa filter status

    all_tickets = query.order_by(SupportTicket.created_at.desc()).limit(150).all()
    
    # Statistik tiket
    total_open = SupportTicket.query.filter_by(status='OPEN').count()
    total_process = SupportTicket.query.filter_by(status='PROCESS').count()
    total_resolved = SupportTicket.query.filter_by(status='RESOLVED').count()
    total_closed = SupportTicket.query.filter_by(status='CLOSED').count()
    total_all = SupportTicket.query.count()
    total_active = total_open + total_process

    return render_template('admin/tickets.html',
                           tickets=all_tickets,
                           current_filter=filter_status,
                           total_open=total_open,
                           total_process=total_process,
                           total_resolved=total_resolved,
                           total_closed=total_closed,
                           total_all=total_all,
                           total_active=total_active)


@admin_bp.route('/tickets/<int:id>/status', methods=['POST'])
def update_ticket_status(id):
    """Memperbarui status tiket bantuan CS (mendukung AJAX & standard form submit)."""
    from app.models.support_ticket import SupportTicket
    ticket = SupportTicket.query.get_or_404(id)

    # Support form data or JSON
    new_status = None
    admin_reply_text = None

    if request.is_json:
        json_data = request.get_json(silent=True) or {}
        new_status = json_data.get('status')
        admin_reply_text = json_data.get('admin_reply')

    if not new_status:
        new_status = request.form.get('status')
    if not admin_reply_text:
        admin_reply_text = request.form.get('admin_reply')

    new_status = (new_status or 'RESOLVED').strip().upper()
    admin_reply_text = (admin_reply_text or '').strip()

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json

    if new_status in ['OPEN', 'PROCESS', 'RESOLVED', 'CLOSED']:
        ticket.status = new_status
        if admin_reply_text:
            ticket.admin_reply = admin_reply_text
            ticket.admin_replied_at = datetime.utcnow()
            ticket.admin_name = 'Admin CS'
        db.session.commit()

        msg = f'Status tiket #{ticket.ticket_number} berhasil diperbarui menjadi {new_status}.'
        if is_ajax:
            return jsonify({
                'success': True,
                'message': msg,
                'ticket_id': ticket.id,
                'ticket_number': ticket.ticket_number,
                'new_status': new_status
            })
        flash(f'✅ {msg}', 'success')
    else:
        msg = 'Status tidak valid!'
        if is_ajax:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, 'danger')

    redirect_url = request.referrer or url_for('admin.tickets')
    return redirect(redirect_url)


# =====================================================================
# RUTE PENGATURAN PROFIL TOKO & UPLOAD LOGO STRUK THERMAL
# =====================================================================
@admin_bp.route('/store_settings', methods=['GET', 'POST'])
def store_settings():
    """Halaman Pengaturan Profil Toko Dinamis & Upload Logo Struk Thermal"""
    from app.services.setting_service import get_store_settings, save_store_settings, get_manual_deposit_settings, save_manual_deposit_settings
    
    if request.method == 'POST':
        form_type = request.form.get('form_type')
        if form_type == 'manual_deposit':
            save_manual_deposit_settings(request.form)
            flash('✅ Informasi rekening deposit transfer manual berhasil disimpan!', 'success')
            return redirect(url_for('admin.store_settings'))

        logo_file = request.files.get('store_logo')
        try:
            save_store_settings(request.form, logo_file=logo_file)
            flash('Pengaturan profil toko & logo berhasil disimpan!', 'success')
        except Exception as e:
            flash(f'Gagal menyimpan pengaturan toko: {str(e)}', 'danger')
        return redirect(url_for('admin.store_settings'))
        
    store = get_store_settings()
    manual_depo = get_manual_deposit_settings()
    
    from app.services.dana_mutasi_service import get_device_status, get_dana_device_token
    dana_device_status = get_device_status()
    dana_device_token = get_dana_device_token()
    dana_webhook_url = request.host_url.rstrip('/') + '/api/callback/dana-mutasi'

    return render_template('admin/store_settings.html',
                           store=store,
                           manual_depo=manual_depo,
                           dana_device_status=dana_device_status,
                           dana_device_token=dana_device_token,
                           dana_webhook_url=dana_webhook_url,
                           page_title='Pengaturan Toko & Logo Struk')


@admin_bp.route('/store_settings/regenerate_dana_token', methods=['POST'])
def store_settings_regenerate_dana_token():
    """Membuat ulang token autentikasi device HP DANA."""
    from app.services.dana_mutasi_service import regenerate_dana_device_token
    new_token = regenerate_dana_device_token()
    flash(f'✅ Token Device DANA berhasil diperbarui: {new_token}', 'success')
    return redirect(url_for('admin.store_settings'))


@admin_bp.route('/store_settings/delete_logo', methods=['POST'])
@csrf.exempt
def store_settings_delete_logo():
    """Menghapus logo toko dan kembali ke default"""
    from app.services.setting_service import delete_store_logo
    try:
        delete_store_logo()
        flash('Logo toko berhasil dihapus.', 'info')
    except Exception as e:
        flash(f'Gagal menghapus logo toko: {str(e)}', 'danger')
    return redirect(url_for('admin.store_settings'))


# =====================================================================
# RUTE PENGATURAN TIER & DOWNLINE VIP
# =====================================================================
@admin_bp.route('/tier_settings', methods=['GET', 'POST'])
def tier_settings():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))
        
    from app.models.setting import Setting
    from app.models.user import User
    from app.models.commission import CommissionLog
    from app.services.tier_service import get_tier_settings
    
    keys = [
        'upgrade_fee_reseller',
        'upgrade_fee_vip',
        'discount_reseller',
        'discount_vip',
        'commission_flat',
        'payout_date',
        'history_retention_days'
    ]
    
    if request.method == 'POST':
        try:
            for k in keys:
                val = request.form.get(k, '').strip()
                s = Setting.query.filter_by(key=k).first()
                if not s:
                    s = Setting(key=k, value=val)
                    db.session.add(s)
                else:
                    s.value = val
            db.session.commit()
            from app.services.setting_service import invalidate_setting_cache
            invalidate_setting_cache()
            flash('Pengaturan Golongan Akun & Skema Downline VIP berhasil disimpan!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Gagal menyimpan pengaturan: {str(e)}', 'error')
        return redirect(url_for('admin.tier_settings'))
        
    # GET Request
    tier_cfg = get_tier_settings()
    
    total_users = User.query.count()
    member_count = User.query.filter((User.role == 'user') | (User.role == None)).count()
    reseller_count = User.query.filter_by(role='reseller').count()
    vip_count = User.query.filter_by(role='vip').count()
    total_commission_circulating = db.session.query(db.func.sum(User.commission_balance)).scalar() or 0.0
    total_commission_paid = db.session.query(db.func.sum(CommissionLog.commission_amount)).filter_by(status='paid_out').scalar() or 0.0
    
    return render_template('admin/tier_settings.html',
                           settings=tier_cfg,
                           total_users=total_users,
                           member_count=member_count,
                           reseller_count=reseller_count,
                           vip_count=vip_count,
                           total_commission_circulating=total_commission_circulating,
                           total_commission_paid=total_commission_paid,
                           page_title='Tier & Downline VIP')


@admin_bp.route('/tier_settings/downgrade_expired', methods=['POST'])
def downgrade_expired_action():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))
    from app.services.tier_service import check_and_downgrade_expired_users
    count = check_and_downgrade_expired_users()
    flash(f'Pemeriksaan selesai: {count} akun yang masa aktifnya telah habis berhasil di-downgrade ke Member.', 'success' if count > 0 else 'info')
    return redirect(url_for('admin.tier_settings'))


@admin_bp.route('/tier_settings/prune_history', methods=['POST'])
def prune_history_action():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))
    from app.services.commission_service import prune_commission_history
    count = prune_commission_history()
    flash(f'Housekeeping selesai: {count} baris riwayat transaksi & komisi lebih dari 120 hari berhasil dibersihkan.', 'success' if count > 0 else 'info')
    return redirect(url_for('admin.tier_settings'))


@admin_bp.route('/tier_settings/send_reminders', methods=['POST'])
def send_tier_reminders_action():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))
    from app.services.tier_service import send_h12_whatsapp_reminders
    count = send_h12_whatsapp_reminders()
    flash(f'Pengingat H-12 diproses: {count} pesan WhatsApp berhasil dikirim ke pelanggan yang mendekati jatuh tempo.', 'success' if count > 0 else 'info')
    return redirect(url_for('admin.tier_settings'))


# =====================================================================
# MANAJEMEN DEVELOPER / MERCHANT OPEN API GATEWAY (POS IPAY)
# =====================================================================
@admin_bp.route('/merchant_api', methods=['GET'])
@admin_bp.route('/merchant-api', methods=['GET'])
def merchant_api_index():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    from flask import current_app
    from app.models.merchant import (
        MerchantApiKey,
        MerchantProvisionRequest,
        PosBroadcast,
        ensure_merchant_provision_table
    )
    from app.models.user import User
    from app.models.transaction import Transaction
    from app.services.setting_service import get_pos_settings

    # Self-healing: Pastikan semua tabel terkait Merchant & POS terbuat di database
    try:
        from app.extensions import db
        MerchantApiKey.__table__.create(db.engine, checkfirst=True)
        ensure_merchant_provision_table()
        # Auto-migration kolom tenant_id dan master_recovery_key jika belum ada di database
        with db.engine.connect() as conn:
            from sqlalchemy import text
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(merchant_api_keys);")).fetchall()]
            if 'tenant_id' not in cols:
                conn.execute(text("ALTER TABLE merchant_api_keys ADD COLUMN tenant_id VARCHAR(64);"))
            if 'master_recovery_key' not in cols:
                conn.execute(text("ALTER TABLE merchant_api_keys ADD COLUMN master_recovery_key VARCHAR(32);"))
            conn.commit()
    except Exception as e_create:
        current_app.logger.warning(f"[MERCHANT_API] Check/create table warning: {e_create}")

    try:
        merchants = MerchantApiKey.query.order_by(MerchantApiKey.id.desc()).all()
    except Exception as e_mch:
        current_app.logger.error(f"[MERCHANT_API] Error querying MerchantApiKey: {e_mch}")
        try:
            from app.extensions import db
            db.session.rollback()
            MerchantApiKey.__table__.create(db.engine, checkfirst=True)
            merchants = MerchantApiKey.query.order_by(MerchantApiKey.id.desc()).all()
        except Exception as e_retry:
            current_app.logger.error(f"[MERCHANT_API] Retry query failed: {e_retry}")
            merchants = []

    try:
        users = User.query.filter_by(is_active=True).order_by(User.name.asc()).all()
    except Exception as e_usr:
        current_app.logger.error(f"[MERCHANT_API] Error querying users: {e_usr}")
        users = []

    try:
        pos_settings = get_pos_settings()
    except Exception as e_pos:
        current_app.logger.error(f"[MERCHANT_API] Error getting POS settings: {e_pos}")
        pos_settings = {
            'enabled': '0',
            'web_url': 'http://localhost:3000',
            'announcement_title': 'Aplikasi Kasir Web POS Konter HP & Minimarket Modern',
            'announcement_message': 'Fitur kasir digital terintegrasi saldo GarudaTel sedang dalam tahap penyempurnaan akhir sebelum rilis publik.'
        }

    # Query tiket deposit per merchant & terpusat (Defensive & Single-Query)
    all_deposit_requests = []
    pending_deposits_count = 0
    try:
        from sqlalchemy import or_
        mch_map_by_id = {m.merchant_id: m for m in merchants}
        mch_map_by_user = {m.user_id: m for m in merchants if m.user_id}
        mch_user_ids = list(mch_map_by_user.keys())
        mch_ids = list(mch_map_by_id.keys())

        conds = [Transaction.payment_method == 'API_GATEWAY']
        if mch_user_ids:
            conds.append(Transaction.user_id.in_(mch_user_ids))
        if mch_ids:
            conds.append(Transaction.provider_ref.in_(mch_ids))

        all_deposit_requests = Transaction.query.filter(
            Transaction.sku_code.in_(['DEPOSIT_SALDO', 'DEPOSIT_MANUAL']),
            or_(*conds)
        ).order_by(Transaction.id.desc()).limit(100).all()

        for dep in all_deposit_requests:
            m_obj = mch_map_by_id.get(dep.provider_ref) or mch_map_by_user.get(dep.user_id)
            dep.merchant_name = m_obj.name if m_obj else (dep.user.name if dep.user else f"User #{dep.user_id}")
            dep.merchant_code = m_obj.merchant_id if m_obj else (dep.provider_ref or "-")
            dep.merchant_tenant_id = m_obj.get_tenant_id() if m_obj and hasattr(m_obj, 'get_tenant_id') else "-"

        # Urutkan: PENDING paling atas, lalu ID desc
        all_deposit_requests.sort(key=lambda x: (0 if x.status == 'PENDING' else 1, -x.id))
        pending_deposits_count = sum(1 for d in all_deposit_requests if d.status == 'PENDING')

        for m in merchants:
            m.deposit_requests = [d for d in all_deposit_requests if d.provider_ref == m.merchant_id or d.user_id == m.user_id][:15]

    except Exception as e_dep:
        current_app.logger.warning(f"[MERCHANT_API] Gagal query deposit requests: {e_dep}")
        all_deposit_requests = []
        for m in merchants:
            if not hasattr(m, 'deposit_requests'):
                m.deposit_requests = []
        pending_deposits_count = 0

    # Query Antrean Pengajuan Aktivasi 1-Klik POS
    try:
        provision_requests = MerchantProvisionRequest.query.order_by(MerchantProvisionRequest.id.desc()).limit(25).all()
        pending_provisions_count = MerchantProvisionRequest.query.filter_by(status='PENDING').count()
    except Exception as e_prov:
        current_app.logger.warning(f"[MERCHANT_API] Gagal query provision requests: {e_prov}")
        provision_requests = []
        pending_provisions_count = 0

    # Query Broadcast Layar Kasir POS
    try:
        pos_broadcasts = PosBroadcast.query.order_by(PosBroadcast.id.desc()).limit(15).all()
    except Exception as e_bc:
        current_app.logger.warning(f"[MERCHANT_API] Gagal query pos broadcasts: {e_bc}")
        pos_broadcasts = []

    # Query Monitor Transaksi Jalur POS (API_GATEWAY)
    try:
        pos_transactions = Transaction.query.filter(
            Transaction.payment_method == 'API_GATEWAY',
            ~Transaction.sku_code.in_(['DEPOSIT_SALDO', 'DEPOSIT_MANUAL'])
        ).order_by(Transaction.id.desc()).limit(30).all()

        mch_map_by_id = {m.merchant_id: m for m in merchants}
        mch_map_by_user = {m.user_id: m for m in merchants}
        for t in pos_transactions:
            m_obj = mch_map_by_id.get(t.provider_ref) or mch_map_by_user.get(t.user_id)
            t.merchant_name = m_obj.name if m_obj else (t.user.name if t.user else f"User #{t.user_id}")
            t.merchant_code = m_obj.merchant_id if m_obj else (t.provider_ref or "-")
            t.has_webhook = bool(m_obj and m_obj.webhook_url)
    except Exception as e_trx:
        current_app.logger.warning(f"[MERCHANT_API] Gagal query pos transactions: {e_trx}")
        pos_transactions = []

    # Hitung toko POS dengan saldo kritis (< Rp 50.000)
    low_balance_merchants_count = 0
    for m in merchants:
        if m.is_active and m.user and float(m.user.balance or 0) < 50000:
            low_balance_merchants_count += 1

    return render_template(
        'admin/merchant_api.html',
        merchants=merchants,
        users=users,
        pos_settings=pos_settings,
        all_deposit_requests=all_deposit_requests,
        pending_deposits_count=pending_deposits_count,
        provision_requests=provision_requests,
        pending_provisions_count=pending_provisions_count,
        pos_broadcasts=pos_broadcasts,
        pos_transactions=pos_transactions,
        low_balance_merchants_count=low_balance_merchants_count,
        page_title='API Merchant & POS'
    )


@admin_bp.route('/merchant-api/provision/approve/<int:prov_id>', methods=['POST'])
def merchant_api_approve_provision(prov_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    from app.services.merchant_service import approve_provision_request
    prov, err = approve_provision_request(prov_id)
    if err or not prov:
        flash(f"Gagal menyetujui permohonan aktivasi POS: {err}", "danger")
    else:
        flash(
            f"✓ Permohonan toko '{prov.store_name}' ({prov.phone}) DISETUJUI! "
            f"Merchant ID {prov.merchant_id} & API Key telah dibuat dan dikirim otomatis ke POS.",
            "success"
        )
    return redirect(url_for('admin.merchant_api_index'))


@admin_bp.route('/merchant-api/provision/reject/<int:prov_id>', methods=['POST'])
def merchant_api_reject_provision(prov_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    from app.services.merchant_service import reject_provision_request
    reason = request.form.get('reason', '').strip() or "Permohonan ditolak oleh Admin iPay."
    prov, err = reject_provision_request(prov_id, reason=reason)
    if err or not prov:
        flash(f"Gagal menolak permohonan: {err}", "danger")
    else:
        flash(f"Permohonan toko '{prov.store_name}' ditolak. Alasan: {reason}", "warning")
    return redirect(url_for('admin.merchant_api_index'))


@admin_bp.route('/merchant-api/deposit/approve/<int:trx_id>', methods=['POST'])
def merchant_api_approve_deposit(trx_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    from app.models.transaction import Transaction
    from app.models.user import User
    from app.models.merchant import MerchantApiKey
    from datetime import datetime

    trx = Transaction.query.get_or_404(trx_id)
    if trx.status == 'SUCCESS':
        flash(f"Tiket deposit {trx.ref_id} sudah disetujui sebelumnya.", "info")
        return redirect(url_for('admin.merchant_api_index'))

    user = User.query.filter_by(id=trx.user_id).with_for_update().first()
    if not user:
        flash("User pemilik akun deposit tidak ditemukan.", "danger")
        return redirect(url_for('admin.merchant_api_index'))

    # Tambah saldo akun
    old_bal = float(user.balance or 0.0)
    add_amount = float(trx.amount or 0.0)
    user.balance = old_bal + add_amount

    trx.status = 'SUCCESS'
    trx.payment_status = 'PAID'
    approve_note = f"Disetujui Admin pada {datetime.now().strftime('%d/%m/%Y %H:%M WIB')}"
    if trx.sn:
        trx.sn = f"{trx.sn} | {approve_note}"
    else:
        trx.sn = approve_note

    db.session.commit()

    # Coba kirim webhook callback ke merchant POS jika URL terdaftar
    try:
        from app.services.merchant_service import dispatch_merchant_webhook
        mch = MerchantApiKey.query.filter_by(user_id=user.id).first()
        if mch and mch.webhook_url:
            dispatch_merchant_webhook(mch, {
                'event': 'deposit.approved',
                'ref_id': trx.ref_id,
                'amount': trx.amount,
                'status': 'success',
                'balance': user.balance,
                'timestamp': datetime.now().isoformat()
            })
    except Exception as e:
        print(f"[Webhook Deposit Dispatch Warning]: {e}")

    # Notifikasi saldo rendah / update saldo jika ada
    try:
        from app.services.balance_notification_service import check_and_notify_low_balance
        check_and_notify_low_balance(user.id, old_bal, user.balance)
    except Exception:
        pass

    flash(
        f"✓ Tiket deposit {trx.ref_id} sebesar Rp {add_amount:,.0f} BERHASIL DISETUJUI! "
        f"Saldo akun {user.name} ({user.phone}) kini menjadi Rp {user.balance:,.0f}.",
        "success"
    )
    return redirect(url_for('admin.merchant_api_index'))


@admin_bp.route('/merchant-api/deposit/reject/<int:trx_id>', methods=['POST'])
def merchant_api_reject_deposit(trx_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    from app.models.transaction import Transaction
    from app.models.merchant import MerchantApiKey
    from datetime import datetime

    trx = Transaction.query.get_or_404(trx_id)
    if trx.status == 'SUCCESS':
        flash(f"Tiket deposit {trx.ref_id} yang sudah disetujui tidak dapat ditolak.", "warning")
        return redirect(url_for('admin.merchant_api_index'))

    reason = request.form.get('reason', '').strip() or 'Mutasi transfer dana tidak ditemukan / bukti tidak valid'

    trx.status = 'FAILED'
    trx.payment_status = 'UNPAID'
    reject_note = f"Ditolak Admin: {reason} ({datetime.now().strftime('%d/%m/%Y %H:%M WIB')})"
    if trx.sn:
        trx.sn = f"{trx.sn} | {reject_note}"
    else:
        trx.sn = reject_note

    db.session.commit()

    # Coba kirim webhook callback ke merchant POS jika URL terdaftar
    try:
        from app.services.merchant_service import dispatch_merchant_webhook
        mch = MerchantApiKey.query.filter_by(user_id=trx.user_id).first()
        if mch and mch.webhook_url:
            dispatch_merchant_webhook(mch, {
                'event': 'deposit.rejected',
                'ref_id': trx.ref_id,
                'amount': trx.amount,
                'status': 'failed',
                'reason': reason,
                'timestamp': datetime.now().isoformat()
            })
    except Exception as e:
        print(f"[Webhook Deposit Dispatch Warning]: {e}")

    flash(f"Tiket deposit {trx.ref_id} sebesar Rp {trx.amount:,.0f} DITOLAK. Alasan: {reason}", "warning")
    return redirect(url_for('admin.merchant_api_index'))


@admin_bp.route('/merchant_api/settings', methods=['POST'])
@admin_bp.route('/merchant-api/settings', methods=['POST'])
def merchant_api_save_settings():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    from app.services.setting_service import save_pos_settings
    save_pos_settings(request.form)
    flash('Pengaturan & status Fitur Kasir Web POS berhasil diperbarui!', 'success')
    return redirect(url_for('admin.merchant_api_index'))


@admin_bp.route('/merchant_api/create', methods=['POST'])
def merchant_api_create():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    from app.services.merchant_service import generate_merchant_credentials

    user_id = request.form.get('user_id', type=int)
    name = request.form.get('name', '').strip()
    webhook_url = request.form.get('webhook_url', '').strip()
    ip_whitelist = request.form.get('ip_whitelist', '').strip()

    if not user_id:
        flash('Silakan pilih akun pengguna pemilik API Key.', 'danger')
        return redirect(url_for('admin.merchant_api_index'))

    mch, err = generate_merchant_credentials(
        user_id=user_id,
        name=name,
        webhook_url=webhook_url,
        ip_whitelist=ip_whitelist
    )

    if err:
        flash(f'Gagal membuat API Key: {err}', 'danger')
    else:
        flash(f'Kredensial API {mch.merchant_id} berhasil dibuat untuk kasir "{mch.name}".', 'success')

    return redirect(url_for('admin.merchant_api_index'))


@admin_bp.route('/merchant_api/toggle/<int:key_id>', methods=['POST'])
def merchant_api_toggle(key_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    from app.models.merchant import MerchantApiKey
    mch = MerchantApiKey.query.get_or_404(key_id)
    mch.is_active = not mch.is_active
    db.session.commit()

    flash(f"Status API Key {mch.merchant_id} diubah menjadi {'AKTIF' if mch.is_active else 'NONAKTIF'}.", 'info')
    return redirect(url_for('admin.merchant_api_index'))


@admin_bp.route('/merchant_api/regenerate/<int:key_id>', methods=['POST'])
def merchant_api_regenerate(key_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    import secrets
    from app.models.merchant import MerchantApiKey
    from app.services.merchant_service import push_credentials_to_pos

    mch = MerchantApiKey.query.get_or_404(key_id)
    mch.secret_key = f"SEC_{secrets.token_hex(16)}"
    db.session.commit()

    _, sync_msg = push_credentials_to_pos(mch)
    flash(
        f"Secret Key untuk {mch.merchant_id} berhasil di-reset & disinkronkan ke POS ({sync_msg}).",
        'warning'
    )
    return redirect(url_for('admin.merchant_api_index'))


@admin_bp.route('/merchant_api/update/<int:key_id>', methods=['POST'])
def merchant_api_update(key_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    from app.models.merchant import MerchantApiKey
    from app.services.merchant_service import push_credentials_to_pos

    mch = MerchantApiKey.query.get_or_404(key_id)
    mch.name = request.form.get('name', mch.name).strip() or mch.name
    mch.webhook_url = request.form.get('webhook_url', '').strip() or None
    mch.ip_whitelist = request.form.get('ip_whitelist', '').strip() or None

    new_role = request.form.get('user_role', '').strip().lower()
    if new_role in ['user', 'reseller', 'vip'] and mch.user:
        mch.user.role = new_role

    db.session.commit()
    push_credentials_to_pos(mch)

    flash(
        f"✓ Konfigurasi '{mch.name}' ({mch.merchant_id}) & Level Harga ({new_role.upper() if new_role else 'Tetap'}) berhasil diperbarui!",
        'success'
    )
    return redirect(url_for('admin.merchant_api_index'))


@admin_bp.route('/merchant-api/push-credentials/<int:key_id>', methods=['POST'])
def merchant_api_push_credentials(key_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    from app.models.merchant import MerchantApiKey
    from app.services.merchant_service import push_credentials_to_pos

    mch = MerchantApiKey.query.get_or_404(key_id)
    ok, msg = push_credentials_to_pos(mch)
    flash(
        f"⚡ Sinkronisasi Kredensial {mch.merchant_id} ({mch.name}): {msg}",
        'success' if ok else 'warning'
    )
    return redirect(url_for('admin.merchant_api_index'))


@admin_bp.route('/merchant-api/generate-masterkey/<int:key_id>', methods=['POST'])
@admin_bp.route('/merchant_api/generate-masterkey/<int:key_id>', methods=['POST'])
def merchant_api_generate_masterkey(key_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    import secrets
    import hashlib
    from threading import Thread
    from app.models.merchant import MerchantApiKey
    from app.services.merchant_service import _send_webhook_worker

    mch = MerchantApiKey.query.get_or_404(key_id)
    tenant_id = mch.get_tenant_id() if hasattr(mch, 'get_tenant_id') else f"store-{mch.id}"

    # Format Master Recovery Key: RCV-XXXX-XXXX-XXXX (12 hex digits grouped by 4)
    raw_hex = secrets.token_hex(6).upper()
    master_key = f"RCV-{raw_hex[0:4]}-{raw_hex[4:8]}-{raw_hex[8:12]}"

    mch.master_recovery_key = master_key
    mch.tenant_id = tenant_id
    db.session.commit()

    # Push langsung update Master Recovery Key ke Webhook POS jika webhook_url terpasang
    synced_pos = False
    if mch.webhook_url:
        try:
            sign = hashlib.md5(f"{mch.merchant_id}{mch.secret_key}{master_key}".encode()).hexdigest()
            payload = {
                "event": "master_key.synced",
                "merchant_id": mch.merchant_id,
                "tenant_id": tenant_id,
                "master_key": master_key,
                "recovery_key": master_key,
                "sign": sign,
                "message": f"Master Recovery Key untuk toko {mch.name} (ID: {tenant_id}) berhasil di-generate dari Admin iPay!"
            }
            Thread(target=_send_webhook_worker, args=(mch.webhook_url, payload), daemon=True).start()
            # Juga kirim langsung ke port internal POS IPAY (127.0.0.1:3001) untuk menjamin penerimaan seketika
            Thread(target=_send_webhook_worker, args=(f"http://127.0.0.1:3001/api/ppob/webhook?tenant_id={tenant_id}", payload), daemon=True).start()
            synced_pos = True
        except Exception as e:
            print(f"[MasterKey Webhook Sync Error]: {e}")

    flash(
        f"🔑 Master Recovery Key untuk '{mch.name}' (ID Toko: {tenant_id}) berhasil dibuat: {master_key}" + 
        (" dan disinkronkan otomatis ke POS!" if synced_pos else "."),
        "success"
    )
    return redirect(url_for('admin.merchant_api_index'))


@admin_bp.route('/merchant-api/open-pos/<int:key_id>')
@admin_bp.route('/merchant_api/open-pos/<int:key_id>')
def merchant_api_open_pos(key_id):
    """1-Klik Buka dan Masuk Otomatis ke POS Kasir Toko Ini Tanpa Password (SSO Bypass)"""
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    from app.models.merchant import MerchantApiKey
    from app.services.merchant_service import create_sso_ticket
    import urllib.parse

    mch = MerchantApiKey.query.get_or_404(key_id)
    pos_base_url = os.getenv('POS_BASE_URL', 'https://ipaypos.my.id')

    user_phone = mch.user.phone if mch.user else ''
    user_name = mch.user.name if (mch.user and mch.user.name) else (mch.name or 'Owner Toko')

    sso_code = create_sso_ticket(
        mch,
        name=user_name,
        phone=user_phone,
        ttl_seconds=300
    )

    params = {
        'sso_code': sso_code,
        'sso_merchant': mch.merchant_id,
        'sso_base_url': request.host_url.rstrip('/')
    }

    redirect_url = f"{pos_base_url.rstrip('/')}/?{urllib.parse.urlencode(params)}"
    return redirect(redirect_url)


@admin_bp.route('/merchant-api/reset-password/<int:key_id>', methods=['POST'])
@admin_bp.route('/merchant_api/reset-password/<int:key_id>', methods=['POST'])
def merchant_api_reset_password(key_id):
    """Reset Kata Sandi & PIN Kasir Langsung dari Admin iPay (Dual-Layer: SQLite + Webhook + WA Baileys)"""
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    import sqlite3
    import requests
    from threading import Thread
    from app.models.merchant import MerchantApiKey
    from app.services.merchant_service import _send_webhook_worker

    mch = MerchantApiKey.query.get_or_404(key_id)
    tenant_id = mch.get_tenant_id() if hasattr(mch, 'get_tenant_id') else f"store-{mch.id}"

    new_password = (request.form.get('new_password') or 'admin123').strip()
    new_pin = (request.form.get('new_pin') or '112233').strip()
    notify_wa = request.form.get('notify_wa') in ['1', 'on', 'true', True]

    if len(new_password) < 6:
        flash("Kata sandi baru minimal 6 karakter.", "danger")
        return redirect(url_for('admin.merchant_api_index'))
    if not new_pin.isdigit() or len(new_pin) != 6:
        flash("PIN baru harus 6 digit angka.", "danger")
        return redirect(url_for('admin.merchant_api_index'))

    # 1. Update langsung ke database tenant lokal jika ada di VPS
    db_paths = [
        f"/var/www/pos-ipay/data/tenants/{tenant_id}.db",
        f"/root/pos-ipay/data/tenants/{tenant_id}.db",
        os.path.abspath(os.path.join(BASE_DIR, '..', 'POS IPAY', 'data', 'tenants', f"{tenant_id}.db")),
        os.path.abspath(os.path.join(BASE_DIR, '..', 'pos-ipay', 'data', 'tenants', f"{tenant_id}.db")),
    ]
    direct_updated = False
    for p in db_paths:
        if os.path.exists(p):
            try:
                conn = sqlite3.connect(p)
                cur = conn.cursor()
                cur.execute("UPDATE users SET password = ?, pin = ? WHERE role = 'owner' OR username = 'owner'", (new_password, new_pin))
                if cur.rowcount == 0:
                    cur.execute("UPDATE users SET password = ?, pin = ? WHERE id = (SELECT id FROM users ORDER BY id ASC LIMIT 1)", (new_password, new_pin))
                conn.commit()
                conn.close()
                direct_updated = True
                break
            except Exception as e:
                print(f"[Direct Reset DB Error] {p}: {e}")

    # 2. Push webhook ke POS IPAY lokal (127.0.0.1:3001) agar di-hash dengan scrypt modern
    payload = {
        "event": "admin.reset_credentials",
        "merchant_id": mch.merchant_id,
        "tenant_id": tenant_id,
        "new_password": new_password,
        "new_pin": new_pin,
        "message": f"Kredensial kasir {mch.name} (ID: {tenant_id}) di-reset oleh Admin iPay."
    }
    try:
        Thread(target=_send_webhook_worker, args=(f"http://127.0.0.1:3001/api/ppob/webhook?tenant_id={tenant_id}", payload), daemon=True).start()
    except Exception as e:
        print(f"[Webhook Reset Error]: {e}")

    # 3. Kirim notifikasi WhatsApp via Bot Baileys ke HP Pemilik Toko
    phone = mch.user.phone if mch.user else ''
    wa_sent = False
    if notify_wa and phone:
        wa_text = (
            f"🔐 *[RESET KATA SANDI POS KASIR]*\n\n"
            f"Halo Pemilik Toko *{mch.name}*,\n"
            f"Kredensial login akun kasir POS Anda (`{tenant_id}`) telah diatur ulang oleh Admin iPay:\n\n"
            f"• *Kata Sandi*: `{new_password}`\n"
            f"• *6-Digit PIN*: `{new_pin}`\n\n"
            f"🔗 *Masuk Kasir*: https://ipaypos.my.id\n"
            f"_Gunakan nomor WhatsApp Anda untuk masuk cepat._"
        )
        try:
            Thread(target=lambda: requests.post(
                "http://127.0.0.1:5000/api/v1/whatsapp/send",
                json={"phone": phone, "message": wa_text},
                timeout=5
            ), daemon=True).start()
            wa_sent = True
        except Exception as e:
            print(f"[WA Send Reset Error]: {e}")

    flash(
        f"✓ Kata Sandi & PIN toko '{mch.name}' (ID: {tenant_id}) BERHASIL DIRESET!\n"
        f"Sandi Baru: {new_password} | PIN Baru: {new_pin}" +
        (f" (Notifikasi telah dikirim ke WA {phone})" if (wa_sent and phone) else ""),
        "success"
    )
    return redirect(url_for('admin.merchant_api_index'))


@admin_bp.route('/merchant-api/ping-webhook/<int:key_id>', methods=['POST'])
def merchant_api_ping_webhook(key_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    from app.models.merchant import MerchantApiKey
    from app.services.merchant_service import ping_merchant_webhook

    mch = MerchantApiKey.query.get_or_404(key_id)
    ok, latency, msg = ping_merchant_webhook(mch)
    if ok:
        flash(f"🩺 Ping Webhook '{mch.name}' ({mch.webhook_url}) BERHASIL! Respon: {msg}", "success")
    else:
        flash(f"⚠️ Ping Webhook '{mch.name}' GAGAL: {msg}", "danger")
    return redirect(url_for('admin.merchant_api_index'))


@admin_bp.route('/merchant-api/adjust-balance/<int:key_id>', methods=['POST'])
def merchant_api_adjust_balance(key_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    import time
    import random
    from datetime import datetime
    from app.models.merchant import MerchantApiKey
    from app.models.user import User
    from app.models.transaction import Transaction
    from app.services.merchant_service import dispatch_merchant_webhook

    mch = MerchantApiKey.query.get_or_404(key_id)
    user = User.query.filter_by(id=mch.user_id).with_for_update().first()
    if not user:
        flash("Akun pemilik toko POS tidak ditemukan.", "danger")
        return redirect(url_for('admin.merchant_api_index'))

    action = request.form.get('action_type', 'add').strip().lower()
    raw_amount = request.form.get('amount', '0').replace('.', '').replace(',', '').strip()
    notes = request.form.get('notes', '').strip() or 'Penyesuaian Saldo Kasir POS oleh Admin'

    try:
        amount = float(raw_amount)
    except ValueError:
        amount = 0.0

    if amount <= 0:
        db.session.rollback()
        flash("Nominal saldo harus lebih besar dari Rp 0.", "danger")
        return redirect(url_for('admin.merchant_api_index'))

    old_bal = float(user.balance or 0.0)
    if action == 'sub':
        user.balance = max(0.0, old_bal - amount)
        label_act = "DIPOTONG"
    else:
        user.balance = old_bal + amount
        label_act = "DITAMBAH"

    ref_id = f"POS-BAL-{int(time.time())}-{random.randint(10, 99)}"
    trx = Transaction(
        ref_id=ref_id,
        user_id=user.id,
        sku_code='DEPOSIT_MANUAL',
        product_name=f"{'Top-Up' if action == 'add' else 'Koreksi'} Saldo Kasir POS ({mch.name})",
        target_number=user.phone or mch.merchant_id,
        amount=amount if action == 'add' else -amount,
        payment_method='ADMIN_POS',
        payment_status='PAID',
        status='SUCCESS',
        provider_ref=mch.merchant_id,
        sn=f"{notes} | Saldo: Rp {old_bal:,.0f} -> Rp {user.balance:,.0f}",
        is_prepaid=True
    )
    db.session.add(trx)
    db.session.commit()

    if mch.webhook_url:
        dispatch_merchant_webhook(mch, {
            'event': 'balance.updated',
            'ref_id': ref_id,
            'status': 'success',
            'price': amount,
            'balance': user.balance,
            'sn': notes
        })

    flash(
        f"💰 Saldo toko '{mch.name}' ({user.phone}) berhasil {label_act} Rp {amount:,.0f}. "
        f"Saldo sekarang: Rp {user.balance:,.0f}.",
        "success"
    )
    return redirect(url_for('admin.merchant_api_index'))


@admin_bp.route('/merchant-api/trx/resend-webhook/<int:trx_id>', methods=['POST'])
def merchant_api_resend_trx_webhook(trx_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    from app.models.transaction import Transaction
    from app.models.merchant import MerchantApiKey
    from app.services.merchant_service import dispatch_merchant_webhook
    from app.routes.transaction import sync_single_transaction

    trx = Transaction.query.get_or_404(trx_id)

    # Jika masih PENDING/PROCESSING, cek status terbaru ke Digiflazz/VIP dulu
    if trx.status in ['PENDING', 'PROCESSING', 'PROSES']:
        try:
            sync_single_transaction(trx)
        except Exception:
            pass

    mch = None
    if trx.provider_ref:
        mch = MerchantApiKey.query.filter_by(merchant_id=trx.provider_ref).first()
    if not mch and trx.user_id:
        mch = MerchantApiKey.query.filter_by(user_id=trx.user_id).order_by(MerchantApiKey.is_active.desc()).first()

    if not mch or not mch.webhook_url:
        flash(
            f"Transaksi {trx.ref_id} saat ini berstatus {trx.status} (SN: {trx.sn or '-'}), namun toko belum mengatur URL Webhook.",
            "warning"
        )
        return redirect(url_for('admin.merchant_api_index'))

    ok, code, resp_txt = dispatch_merchant_webhook(mch, {
        "ref_id": trx.ref_id,
        "status": (trx.status or 'PENDING').lower(),
        "sn": trx.sn or "",
        "sku_code": trx.sku_code or "",
        "price": float(trx.amount or 0.0)
    }, sync=True)

    if ok:
        flash(
            f"✓ Webhook & SN Transaksi {trx.ref_id} ({trx.status}) BERHASIL dikirim ulang ke '{mch.name}' (HTTP {code}).",
            "success"
        )
    else:
        flash(
            f"⚠️ Gagal push ulang webhook {trx.ref_id} ke {mch.webhook_url}: {resp_txt or f'HTTP {code}'}",
            "danger"
        )
    return redirect(url_for('admin.merchant_api_index'))


@admin_bp.route('/merchant-api/broadcast/create', methods=['POST'])
def merchant_api_broadcast_create():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    from app.models.merchant import PosBroadcast, ensure_merchant_provision_table, get_wib_datetime
    from app.services.merchant_service import dispatch_pos_broadcast

    ensure_merchant_provision_table()

    title = request.form.get('title', '').strip()
    message = request.form.get('message', '').strip()
    level = request.form.get('level', 'info').strip().lower()
    target_merchant_id = request.form.get('target_merchant_id', 'ALL').strip() or 'ALL'

    if not title or not message:
        flash("Judul dan isi pesan Broadcast Kasir POS wajib diisi.", "danger")
        return redirect(url_for('admin.merchant_api_index'))

    b = PosBroadcast(
        title=title[:150],
        message=message,
        level=level if level in ['info', 'warning', 'promo', 'urgent'] else 'info',
        target_merchant_id=target_merchant_id,
        is_active=True,
        created_at=get_wib_datetime()
    )
    db.session.add(b)
    db.session.commit()

    dispatch_pos_broadcast(b)

    target_label = "Seluruh Kasir POS" if target_merchant_id == 'ALL' else f"Kasir {target_merchant_id}"
    flash(f"📢 Pesan Broadcast '{b.title}' berhasil dipublikasikan ke {target_label}!", "success")
    return redirect(url_for('admin.merchant_api_index'))


@admin_bp.route('/merchant-api/broadcast/toggle/<int:b_id>', methods=['POST'])
def merchant_api_broadcast_toggle(b_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    from app.models.merchant import PosBroadcast
    b = PosBroadcast.query.get_or_404(b_id)
    b.is_active = not b.is_active
    db.session.commit()

    flash(f"Status broadcast '{b.title}' diubah menjadi {'AKTIF' if b.is_active else 'NONAKTIF'}.", "info")
    return redirect(url_for('admin.merchant_api_index'))


@admin_bp.route('/merchant-api/broadcast/delete/<int:b_id>', methods=['POST'])
def merchant_api_broadcast_delete(b_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    from app.models.merchant import PosBroadcast
    b = PosBroadcast.query.get_or_404(b_id)
    db.session.delete(b)
    db.session.commit()

    flash("Pesan broadcast kasir berhasil dihapus.", "info")
    return redirect(url_for('admin.merchant_api_index'))


@admin_bp.route('/merchant_api/delete/<int:key_id>', methods=['POST'])
def merchant_api_delete(key_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    from app.models.merchant import MerchantApiKey
    mch = MerchantApiKey.query.get_or_404(key_id)
    m_id = mch.merchant_id
    db.session.delete(mch)
    db.session.commit()

    flash(f"Kredensial API {m_id} berhasil dihapus permanen.", 'success')
    return redirect(url_for('admin.merchant_api_index'))






