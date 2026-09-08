import time
import random
import secrets
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, session, make_response
from app.extensions import db, csrf, limiter
from app.models.user import User
from app.models.product import Product
from app.models.transaction import Transaction
from app.models.trusted_device import TrustedDevice
from app.services.device_service import (
    activate_cashier_device,
    login_cashier_pin,
    verify_cashier_transaction_limits,
    get_branch_cashier_history,
    now_wib
)
from app.services.tier_service import get_user_product_price
from app.services.setting_service import get_store_name

kasir_bp = Blueprint('kasir', __name__)

def get_current_cashier_device():
    """Mengambil objek TrustedDevice kasir yang sedang aktif pada sesi ini."""
    device_id = session.get('cashier_device_id')
    if not device_id:
        return None
    return TrustedDevice.query.filter_by(id=device_id, status='approved').first()

@kasir_bp.route('/')
def index():
    """
    Halaman Utama Portal Kasir:
    - Jika perangkat belum terikat -> Tampilkan not_registered.html
    - Jika perangkat terikat tapi belum login PIN -> Tampilkan pin_login.html
    - Jika sesi kasir aktif -> Tampilkan pos.html (Layar Transaksi Kasir)
    """
    device_token = request.cookies.get('gt_device_token')
    store_name = get_store_name()

    # 1. Cek Sesi Kasir Aktif
    active_device = get_current_cashier_device()
    if active_device:
        owner = User.query.get(active_device.user_id)
        if not owner or not owner.is_vip_active():
            session.pop('cashier_device_id', None)
            return render_template(
                'kasir/not_registered.html',
                store_name=store_name,
                title="Langganan VIP Toko Berakhir",
                message="Masa aktif akun VIP toko telah berakhir. Hubungi Owner untuk memperpanjang langganan VIP."
            )
        
        remaining_limit = active_device.get_remaining_daily_limit()
        today_spent = active_device.get_today_spent()

        return render_template(
            'kasir/pos.html',
            store_name=store_name,
            device=active_device,
            owner=owner,
            remaining_limit=remaining_limit,
            today_spent=today_spent
        )

    # 2. Cek Token Perangkat di Cookie
    if not device_token:
        return render_template(
            'kasir/not_registered.html',
            store_name=store_name,
            title="Perangkat Kasir Belum Terdaftar",
            message="Komputer/perangkat ini belum didaftarkan sebagai Kasir Resmi. Minta Tautan Aktivasi Kasir ke Owner Toko."
        )

    device = TrustedDevice.query.filter_by(device_uuid=device_token).first()
    if not device:
        return render_template(
            'kasir/not_registered.html',
            store_name=store_name,
            title="Perangkat Tidak Dikenal",
            message="Token kasir tidak ditemukan di database. Buka tautan aktivasi resmi dari Owner Toko."
        )

    if device.status == 'pending':
        return render_template(
            'kasir/not_registered.html',
            store_name=store_name,
            title="Menunggu Aktivasi Kasir",
            message=f"Perangkat '{device.device_name}' masih dalam status pending. Buka tautan aktivasi yang dikirimkan oleh Owner Toko."
        )

    if device.status != 'approved':
        return render_template(
            'kasir/not_registered.html',
            store_name=store_name,
            title="Izin Akses Kasir Dicabut",
            message=f"Izin akses kasir untuk '{device.device_name}' telah dicabut atau dinonaktifkan oleh Owner Toko."
        )

    # 3. Perangkat Sah & Disetujui -> Masuk Layar Input PIN Kasir
    return render_template(
        'kasir/pin_login.html',
        store_name=store_name,
        device=device
    )


@kasir_bp.route('/aktivasi/<token>')
def aktivasi(token):
    """
    Tautan aktivasi kasir satu kali pakai yang diklik oleh karyawan di komputer toko.
    """
    store_name = get_store_name()
    device_token = request.cookies.get('gt_device_token')
    if not device_token or len(device_token) < 16:
        device_token = f"gt_pos_{secrets.token_hex(16)}"

    ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
    user_agent = request.user_agent.string

    ok, device, msg = activate_cashier_device(
        token=token,
        device_uuid=device_token,
        user_agent=user_agent,
        ip_address=ip_address
    )

    resp = make_response(render_template(
        'kasir/not_registered.html',
        store_name=store_name,
        title="Aktivasi Kasir Berhasil! 🎉" if ok else "Aktivasi Gagal",
        message=msg,
        is_success=ok,
        device_token=device_token if ok else None
    ))

    if ok:
        resp.set_cookie('gt_device_token', device_token, max_age=31536000, samesite='Lax', path='/')
    return resp


@kasir_bp.route('/login_pin', methods=['POST'])
@csrf.exempt
@limiter.limit("20 per minute")
def login_pin():
    """
    Verifikasi PIN Kasir Cabang (100% BEBAS OTP WHATSAPP OWNER).
    """
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    pin_input = str(data.get('pin', '')).strip()

    device_token = request.cookies.get('gt_device_token') or data.get('device_uuid')
    if not device_token:
        return jsonify({'status': 'error', 'message': 'Perangkat ini belum terikat sebagai kasir resmi.'}), 400

    ok, device, owner, msg = login_cashier_pin(device_token, pin_input, user_agent=request.user_agent.string)
    if not ok:
        return jsonify({'status': 'error', 'message': msg}), 400

    # Simpan sesi kasir
    session['cashier_device_id'] = device.id
    session['cashier_user_id'] = owner.id

    return jsonify({
        'status': 'success',
        'message': msg,
        'redirect': '/kasir'
    }), 200


@kasir_bp.route('/logout')
def logout():
    """Tutup sesi kasir / ganti shift (kembali ke layar input PIN)."""
    session.pop('cashier_device_id', None)
    session.pop('cashier_user_id', None)
    return redirect('/kasir')


@kasir_bp.route('/products', methods=['GET'])
def get_products():
    """Mengambil daftar produk katalog untuk layar POS dengan harga VIP Owner."""
    active_device = get_current_cashier_device()
    if not active_device:
        return jsonify({'status': 'error', 'message': 'Sesi kasir tidak aktif'}), 401

    owner = User.query.get(active_device.user_id)
    category = request.args.get('category', '').strip().upper()
    brand = request.args.get('brand', '').strip().upper()

    query = Product.query.filter_by(is_active=True)

    if category:
        if category in ['PULSA', 'DATA', 'PLN', 'GAMES']:
            query = query.filter(Product.category.ilike(f"%{category}%"))
        elif category == 'EMONEY':
            query = query.filter(
                (Product.category.ilike('%E-MONEY%')) | 
                (Product.category.ilike('%WALLET%')) | 
                (Product.category.ilike('%EMONEY%'))
            )

    if brand:
        query = query.filter(Product.brand.ilike(f"%{brand}%"))

    products = query.order_by(Product.sell_price.asc()).all()

    prods_data = []
    for p in products:
        vip_price = get_user_product_price(owner, p)
        prods_data.append({
            'sku_code': p.sku_code,
            'name': p.name,
            'brand': p.brand,
            'category': p.category,
            'price': vip_price,
            'normal_price': float(p.sell_price or 0.0),
            'desc': getattr(p, 'desc', '') or ''
        })

    return jsonify({
        'status': 'success',
        'count': len(prods_data),
        'products': prods_data
    }), 200


@kasir_bp.route('/checkout', methods=['POST'])
@csrf.exempt
@limiter.limit("30 per minute")
def checkout():
    """
    Eksekusi Transaksi Penjualan dari Portal Kasir menggunakan Saldo Toko Owner.
    Menerapkan validasi limit harian dan jam operasional cabang.
    """
    active_device = get_current_cashier_device()
    if not active_device:
        return jsonify({'status': 'error', 'message': 'Sesi kasir telah berakhir. Masukkan PIN kembali.'}), 401

    owner = db.session.query(User).filter_by(id=active_device.user_id).with_for_update().first()
    if not owner or not owner.is_vip_active():
        db.session.rollback()
        return jsonify({'status': 'error', 'message': 'Akun VIP toko tidak aktif atau telah kedaluwarsa.'}), 403

    req_data = request.get_json(silent=True) or request.form.to_dict() or {}
    sku_code = str(req_data.get('sku_code', '')).strip()
    target_number = str(req_data.get('target_number', '')).strip()

    if not sku_code or not target_number:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': 'Produk dan Nomor Tujuan wajib diisi!'}), 400

    product = Product.query.filter_by(sku_code=sku_code, is_active=True).first()
    if not product:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': 'Produk tidak ditemukan atau sedang dinonaktifkan.'}), 404

    # Harga modal VIP untuk toko
    amount = get_user_product_price(owner, product)

    # 1. Validasi Batasan Operasional & Limit Harian Cabang
    lim_ok, lim_err = verify_cashier_transaction_limits(active_device, amount)
    if not lim_ok:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': lim_err}), 400

    # 2. Validasi Saldo Akun Toko
    if owner.balance < amount:
        db.session.rollback()
        return jsonify({
            'status': 'error',
            'message': 'Saldo Toko tidak mencukupi untuk melakukan transaksi ini. Hubungi Owner untuk isi deposit toko.'
        }), 400

    # 3. Potong Saldo Toko & Catat Transaksi
    owner.balance -= amount
    ref_id = f"KASIR-{int(time.time()*1000)}{random.randint(10, 99)}"

    new_trx = Transaction(
        user_id=owner.id,
        ref_id=ref_id,
        product_name=product.name,
        sku_code=product.sku_code,
        target_number=target_number,
        amount=amount,
        payment_method='SALDO',
        payment_status='PAID',
        status='PROCESSING',
        is_prepaid=True,
        device_id=active_device.id,
        device_name=active_device.device_name
    )
    db.session.add(new_trx)
    active_device.last_used_at = datetime.utcnow()
    db.session.commit()

    # 4. Eksekusi ke Provider (Digiflazz / VIP-Reseller)
    is_vip_provider = 'VIP' in (product.brand or '').upper() or 'VOUCHER' in (product.category or '').upper()
    provider_msg = "Transaksi sedang diproses..."

    if is_vip_provider:
        from app.services.vip_reseller import VIPReseller
        vip = VIPReseller()
        order_res = vip.create_order(sku_code, target_number)
        if order_res.get('result'):
            vip_data = order_res.get('data', {})
            if vip_data.get('trxid'):
                new_trx.provider_ref = vip_data.get('trxid')
            new_trx.status = 'PROCESSING'
            db.session.commit()
        else:
            # Gagal di provider -> Refund
            raw_msg = str(order_res.get('message', 'Ditolak API Provider'))
            owner.balance += amount
            new_trx.status = 'FAILED'
            new_trx.sn = raw_msg
            db.session.commit()
            return jsonify({'status': 'error', 'message': f'Gagal di server provider: {raw_msg}'}), 400
    else:
        from app.services.digiflazz import create_transaction
        ok_digi, d_data, msg_digi = create_transaction(sku_code, target_number, ref_id)
        if ok_digi and d_data:
            new_trx.status = str(d_data.get('status', 'PROCESSING')).upper()
            new_trx.sn = d_data.get('sn')
            db.session.commit()
        else:
            # Gagal di digiflazz -> Refund
            owner.balance += amount
            new_trx.status = 'FAILED'
            new_trx.sn = msg_digi
            db.session.commit()
            return jsonify({'status': 'error', 'message': f'Gagal di server provider: {msg_digi}'}), 400

    return jsonify({
        'status': 'success',
        'message': 'Transaksi Kasir Berhasil Diproses!',
        'trx': {
            'ref_id': new_trx.ref_id,
            'product_name': new_trx.product_name,
            'target_number': new_trx.target_number,
            'amount': new_trx.amount,
            'status': new_trx.status,
            'sn': new_trx.sn or '-',
            'branch_name': active_device.device_name,
            'time': new_trx.created_at_wib
        }
    }), 200


@kasir_bp.route('/history')
def history():
    """Mengambil 30 riwayat transaksi khusus cabang kasir ini."""
    active_device = get_current_cashier_device()
    if not active_device:
        return jsonify({'status': 'error', 'message': 'Sesi kasir tidak aktif'}), 401

    trxs = get_branch_cashier_history(active_device.id, limit=30)
    data = []
    for t in trxs:
        data.append({
            'ref_id': t.ref_id,
            'product_name': t.product_name,
            'target_number': t.target_number,
            'amount': t.amount,
            'status': t.status,
            'sn': t.sn or '-',
            'time': t.created_at_wib
        })

    return jsonify({'status': 'success', 'history': data}), 200

