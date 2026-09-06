from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from app.models.admin import Admin
from app.models.product import Product
from app.models.margin import MarginTier
from app.models.user import User
from app.models.transaction import Transaction
from app.models.banner import Banner
from app.models.broadcast import BroadcastLog
from app.models.deposit_ticket import DigiDepositTicket
from app.services.digiflazz import sync_products, check_balance, request_deposit
from app.extensions import db, limiter, cache
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
        'digi_webhook_secret': clean_str(os.getenv('DIGI_WEBHOOK_SECRET'))
    }

    # Metrik Riil dari Database
    total_users = User.query.count()
    total_balance = db.session.query(db.func.sum(User.balance)).scalar() or 0.0
    
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    trx_today_count = Transaction.query.filter(Transaction.created_at >= today_start).count()
    total_trx = Transaction.query.count()

    # Deteksi IP Public VPS untuk Whitelist & Callback URL Dinamis
    server_public_ip = clean_str(os.getenv('SERVER_PUBLIC_IP'))
    if not server_public_ip:
        try:
            server_public_ip = requests.get('https://api.ipify.org', timeout=2).text.strip()
        except Exception:
            server_public_ip = '203.194.115.182'

    f_proto = request.headers.get('X-Forwarded-Proto') or request.scheme
    f_host = request.headers.get('X-Forwarded-Host') or request.host
    vip_callback_url = f"{f_proto}://{f_host}/api/callback/vipreseller"
    digi_callback_url = f"{f_proto}://{f_host}/api/callback/digiflazz"

    env_data['server_public_ip'] = server_public_ip
    env_data['vip_callback_url'] = vip_callback_url
    env_data['digi_callback_url'] = digi_callback_url

    return render_template('admin/dashboard.html',
                           total_users=total_users,
                           total_balance=total_balance,
                           trx_today_count=trx_today_count,
                           total_trx=total_trx,
                           **env_data)

@admin_bp.route('/save_config', methods=['POST'])
def save_config():
    if not os.path.exists(ENV_FILE): open(ENV_FILE, 'a').close()
    
    form_type = request.form.get('form_type')
    if form_type == 'switch_gateway':
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
            res = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={
                "chat_id": chat_id, "text": "✅ Tes koneksi dari Panel Admin Garudatel berhasil! Bot siap digunakan."
            }, timeout=10).json()
            if res.get('ok'):
                flash('✅ Tes koneksi sukses! Cek pesan masuk di Telegram Anda.', 'success')
            else:
                flash(f"❌ Gagal kirim pesan: {res.get('description')}", 'danger')
        except Exception as e:
            flash(f"❌ Error Telegram: {str(e)}", 'danger')
            
    else:
        flash(f'✅ Konfigurasi {tipe} telah tersimpan.', 'success')

    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/sync_digiflazz', methods=['POST'])
def sync_digiflazz():
    success, message = sync_products()
    if success: flash(message, 'success')
    else: flash(message, 'danger')
    return redirect(url_for('admin.dashboard'))

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

    query = Product.query
    if search_q:
        search_pattern = f"%{search_q}%"
        query = query.filter(
            db.or_(
                Product.name.ilike(search_pattern),
                Product.sku_code.ilike(search_pattern),
                Product.brand.ilike(search_pattern)
            )
        )
    if category_filter:
        query = query.filter(Product.category == category_filter)

    total_products_count = Product.query.count()
    filtered_count = query.count()
    
    pagination = query.order_by(Product.id.asc()).paginate(page=page, per_page=50, error_out=False)
    products = pagination.items

    # Dapatkan semua kategori unik untuk filter dropdown
    raw_cats = db.session.query(Product.category).distinct().order_by(Product.category).all()
    categories = [c[0] for c in raw_cats if c[0]]

    return render_template('admin/produk.html',
                           products=products,
                           pagination=pagination,
                           search_q=search_q,
                           category_filter=category_filter,
                           categories=categories,
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

    query = Transaction.query

    if search_q:
        search_pattern = f"%{search_q}%"
        query = query.filter(
            db.or_(
                Transaction.ref_id.ilike(search_pattern),
                Transaction.target_number.ilike(search_pattern),
                Transaction.product_name.ilike(search_pattern),
                Transaction.sku_code.ilike(search_pattern)
            )
        )

    if status_filter:
        query = query.filter(Transaction.status == status_filter.upper())

    if payment_filter:
        query = query.filter(Transaction.payment_status == payment_filter.upper())

    total_count = Transaction.query.count()
    success_count = Transaction.query.filter_by(status='SUCCESS').count()
    total_revenue = db.session.query(db.func.sum(Transaction.amount)).filter(Transaction.status == 'SUCCESS').scalar() or 0.0

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = Transaction.query.filter(Transaction.created_at >= today_start).count()

    pagination = query.order_by(Transaction.id.desc()).paginate(page=page, per_page=25, error_out=False)
    trxs = pagination.items

    return render_template('admin/transactions.html',
                           transactions=trxs,
                           pagination=pagination,
                           search_q=search_q,
                           status_filter=status_filter,
                           payment_filter=payment_filter,
                           total_count=total_count,
                           success_count=success_count,
                           total_revenue=total_revenue,
                           today_count=today_count)

@admin_bp.route('/transactions/update_status/<int:id>', methods=['POST'])
def update_transaction_status(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    trx = Transaction.query.get_or_404(id)
    new_status = request.form.get('status')
    new_payment_status = request.form.get('payment_status')
    sn = request.form.get('sn')

    old_status = trx.status
    if new_status:
        trx.status = new_status.upper()
    if new_payment_status:
        trx.payment_status = new_payment_status.upper()
    if sn is not None and sn.strip():
        trx.sn = sn.strip()

    # Jika admin meng-approve transaksi deposit menjadi SUCCESS
    if trx.status == 'SUCCESS' and old_status != 'SUCCESS':
        if trx.sku_code in ['DEPOSIT_SALDO', 'DEPOSIT_MANUAL']:
            user = User.query.get(trx.user_id)
            if user:
                user.balance += trx.amount
                trx.payment_status = 'PAID'
                print(f"[ADMIN DEPOSIT APPROVE] User {user.id} balance +Rp {trx.amount} for trx {trx.ref_id}")

    db.session.commit()
    from app.services.telegram_service import async_send_trx_notification
    async_send_trx_notification(trx, title=f"ADMIN UPDATE: {trx.status}")
    flash(f"Status transaksi {trx.ref_id} berhasil diperbarui!", 'success')
    return redirect(request.referrer or url_for('admin.transactions'))

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

@admin_bp.route('/users')
def users():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))
    
    # Mengambil semua user, diurutkan dari yang terbaru (ID terbesar)
    all_users = User.query.order_by(User.id.desc()).all()
    return render_template('admin/users.html', users=all_users)


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
        
        # Memperbarui Saldo
        balance_raw = request.form.get('balance')
        if balance_raw is not None and balance_raw != '':
            try:
                user.balance = float(balance_raw)
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
            
        # Memperbarui Role & Status
        user.role = request.form.get('role', 'user')
        status_val = request.form.get('status')
        user.is_active = True if str(status_val) in ('1', 'true', 'True') else False
        
        db.session.commit()
        status_text = "diaktifkan" if user.is_active else "diblokir"
        flash(f'Data pengguna {user.name} berhasil diperbarui (Status: {status_text})!', 'success')
        
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
            
        # Mengirim sinyal ke Mesin Baileys Node.js
        try:
            response = requests.post('http://127.0.0.1:3000/api/pair', json={'number': bot_number}, timeout=30)
            return jsonify(response.json())
        except requests.exceptions.RequestException:
            # Jika port 3000 belum menyala, coba auto-recovery
            ok, msg = _ensure_wa_bot_running()
            if ok:
                try:
                    response = requests.post('http://127.0.0.1:3000/api/pair', json={'number': bot_number}, timeout=30)
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
    
    try:
        r = requests.post('http://127.0.0.1:3000/api/reset', timeout=5)
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

        # Susun pesan WhatsApp untuk user
        display_name = user_name or 'Pengguna / Calon Member'
        wa_message = (
            f"Halo kak {display_name}!\n\n"
            f"Berikut adalah *Kode OTP Darurat* Anda untuk akun GarudaTel:\n\n"
            f"👉 *{otp_code}*\n\n"
            f"⚠️ *PENTING:* Kode OTP ini bersifat rahasia dan *HANYA BERLAKU 10 MENIT* "
            f"khusus untuk nomor ini ({clean_num}).\n\n"
            f"Silakan masukkan kode pada formulir verifikasi Anda di website GarudaTel. Terima kasih!"
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
    try:
        data = request.get_json()
        r = requests.post('http://127.0.0.1:3000/api/send', json=data, timeout=10)
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


# =====================================================================
# LAPORAN & REKAPITULASI
# =====================================================================
@admin_bp.route('/reports')
def reports():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    time_range = request.args.get('range', '30days')
    now = datetime.utcnow()

    if time_range == 'today':
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif time_range == '7days':
        start_date = now - timedelta(days=7)
    elif time_range == 'this_month':
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif time_range == 'all':
        start_date = None
    else:  # default '30days'
        start_date = now - timedelta(days=30)

    query = Transaction.query
    if start_date:
        query = query.filter(Transaction.created_at >= start_date)

    total_trx = query.count()
    success_trx = query.filter(Transaction.status == 'SUCCESS').count()
    pending_trx = query.filter(Transaction.status == 'PENDING').count()
    failed_trx = query.filter(Transaction.status == 'FAILED').count()

    total_omset = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.status == 'SUCCESS',
        (Transaction.created_at >= start_date) if start_date else True,
        Transaction.payment_method != 'admin_manual'
    ).scalar() or 0.0

    success_rate = round((success_trx / total_trx * 100), 1) if total_trx > 0 else 0.0

    # Top 5 Produk
    top_products_raw = db.session.query(
        Transaction.product_name,
        db.func.count(Transaction.id).label('sales_count'),
        db.func.sum(Transaction.amount).label('subtotal')
    ).filter(
        Transaction.status == 'SUCCESS',
        (Transaction.created_at >= start_date) if start_date else True,
        Transaction.sku_code != 'ADMIN_BALANCE'
    ).group_by(Transaction.product_name).order_by(db.desc('sales_count')).limit(5).all()

    top_products = [
        {'name': p[0], 'sales': p[1], 'revenue': p[2] or 0.0}
        for p in top_products_raw
    ]

    # Metode Pembayaran
    methods_raw = db.session.query(
        Transaction.payment_method,
        db.func.count(Transaction.id).label('trx_count'),
        db.func.sum(Transaction.amount).label('volume')
    ).filter(
        Transaction.status == 'SUCCESS',
        (Transaction.created_at >= start_date) if start_date else True
    ).group_by(Transaction.payment_method).all()

    payment_methods = [
        {'method': m[0] or 'N/A', 'count': m[1], 'volume': m[2] or 0.0}
        for m in methods_raw
    ]

    return render_template('admin/reports.html',
                           time_range=time_range,
                           total_trx=total_trx,
                           success_trx=success_trx,
                           pending_trx=pending_trx,
                           failed_trx=failed_trx,
                           total_omset=total_omset,
                           success_rate=success_rate,
                           top_products=top_products,
                           payment_methods=payment_methods)


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
    filter_status = request.args.get('status', 'ALL').upper()
    query = SupportTicket.query

    if filter_status in ['OPEN', 'PROCESS', 'RESOLVED', 'CLOSED']:
        query = query.filter_by(status=filter_status)

    all_tickets = query.order_by(SupportTicket.created_at.desc()).limit(150).all()
    
    # Statistik tiket
    total_open = SupportTicket.query.filter_by(status='OPEN').count()
    total_process = SupportTicket.query.filter_by(status='PROCESS').count()
    total_resolved = SupportTicket.query.filter_by(status='RESOLVED').count()

    return render_template('admin/tickets.html',
                           tickets=all_tickets,
                           current_filter=filter_status,
                           total_open=total_open,
                           total_process=total_process,
                           total_resolved=total_resolved)


@admin_bp.route('/tickets/<int:id>/status', methods=['POST'])
def update_ticket_status(id):
    """Memperbarui status tiket bantuan CS."""
    from app.models.support_ticket import SupportTicket
    ticket = SupportTicket.query.get_or_404(id)
    new_status = request.form.get('status', 'RESOLVED').upper()
    if new_status in ['OPEN', 'PROCESS', 'RESOLVED', 'CLOSED']:
        ticket.status = new_status
        db.session.commit()
        flash(f'✅ Status tiket #{ticket.ticket_number} diperbarui menjadi {new_status}.', 'success')
    else:
        flash('Status tidak valid!', 'danger')
    return redirect(url_for('admin.tickets'))



