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
from app.models.branch_mutation import BranchMutation
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
    """
    Mengambil dan memverifikasi objek TrustedDevice kasir yang sedang aktif pada sesi ini.
    Menerapkan validasi keamanan ketat:
    1. device_id sesi wajib ada dan berstatus 'approved'.
    2. Cookie 'gt_device_token' wajib cocok dengan device.device_uuid saat ini.
    3. Nomor versi sesi ('cashier_session_version') wajib cocok dengan device.session_version.
    4. Token sesi tunggal ('cashier_session_token') wajib cocok dengan device.active_session_token.
    Jika ada ketidaksesuaian (misal owner regenerate link baru, atau cookie dicopy ke browser lain),
    seluruh sesi dibatalkan seketika dan mengembalikan None.
    """
    device_id = session.get('cashier_device_id')
    if not device_id:
        return None

    device = TrustedDevice.query.filter_by(id=device_id, status='approved').first()
    if not device:
        session.clear()
        return None

    # 1. Validasi Token Identitas Perangkat Hardware (Cookie vs DB)
    cookie_token = request.cookies.get('gt_device_token')
    if not cookie_token or cookie_token != device.device_uuid:
        session.clear()
        return None

    # 2. Validasi Nomor Versi Sesi (Mencegah sesi lama tetap jalan saat owner minta link baru)
    session_ver = session.get('cashier_session_version')
    if session_ver is None or session_ver != device.session_version:
        session.clear()
        return None

    # 3. Validasi Token Sesi Aktif Tunggal (Mencegah duplikasi login / sesi paralel)
    session_tok = session.get('cashier_session_token')
    if device.active_session_token and session_tok != device.active_session_token:
        session.clear()
        return None

    return device

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
            session.clear()
            return render_template(
                'kasir/not_registered.html',
                store_name=store_name,
                title="Langganan VIP Toko Berakhir",
                message="Masa aktif akun VIP toko telah berakhir. Hubungi Owner untuk memperpanjang langganan VIP."
            )
        
        remaining_limit = active_device.get_remaining_daily_limit()
        today_spent = active_device.get_today_spent()
        shift_name = session.get('cashier_shift_name', 'Kasir Utama')

        return render_template(
            'kasir/pos.html',
            store_name=store_name,
            device=active_device,
            owner=owner,
            remaining_limit=remaining_limit,
            today_spent=today_spent,
            branch_balance=float(active_device.branch_balance or 0.0),
            shift_name=shift_name
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
    # Buat token identitas perangkat baru yang unik
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
        # Pasang cookie HttpOnly=True agar aman dari intipan JS (F12 Inspect Element)
        resp.set_cookie('gt_device_token', device_token, max_age=31536000, httponly=True, samesite='Lax', path='/')
    return resp


@kasir_bp.route('/login_pin', methods=['POST'])
@csrf.exempt
@limiter.limit("20 per minute")
def login_pin():
    """
    Verifikasi PIN Kasir Cabang (100% BEBAS OTP WHATSAPP OWNER).
    Menerapkan validasi sidik jari perangkat dan token sesi tunggal aktif.
    """
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    pin_input = str(data.get('pin', '')).strip()
    fingerprint_input = str(data.get('fingerprint', '')).strip() or None

    device_token = request.cookies.get('gt_device_token') or data.get('device_uuid')
    if not device_token:
        return jsonify({'status': 'error', 'message': 'Perangkat ini belum terikat sebagai kasir resmi.'}), 400

    ok, device, owner, msg = login_cashier_pin(
        device_uuid=device_token,
        pin=pin_input,
        user_agent=request.user_agent.string,
        fingerprint=fingerprint_input
    )
    if not ok:
        return jsonify({'status': 'error', 'message': msg}), 400

    shift_name = str(data.get('shift_name', '')).strip() or 'Kasir Toko'

    # Simpan sesi kasir beserta nomor versi sesi dan token sesi aktif tunggal
    session['cashier_device_id'] = device.id
    session['cashier_user_id'] = owner.id
    session['cashier_shift_name'] = shift_name
    session['cashier_session_version'] = device.session_version
    session['cashier_session_token'] = device.active_session_token

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
    session.pop('cashier_shift_name', None)
    session.pop('cashier_session_version', None)
    session.pop('cashier_session_token', None)
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
    search_q = request.args.get('q', '').strip()

    query = Product.query.filter_by(is_active=True)

    if category and category != 'ALL':
        if category == 'PULSA':
            query = query.filter(Product.category.ilike("%pulsa%"))
        elif category == 'DATA':
            query = query.filter(
                (Product.category.ilike('%data%')) | 
                (Product.category.ilike('%kuota%')) | 
                (Product.category.ilike('%internet%'))
            )
        elif category in ['TELPSMS', 'TELP_SMS', 'TELP']:
            query = query.filter(
                (Product.category.ilike('%telp%')) | 
                (Product.category.ilike('%sms%'))
            )
        elif category in ['MASAAKTIF', 'MASA_AKTIF']:
            query = query.filter(Product.category.ilike("%masa%"))
        elif category == 'PLN':
            query = query.filter(Product.category.ilike("%pln%"))
        elif category == 'EMONEY':
            query = query.filter(
                (Product.category.ilike('%e-money%')) | 
                (Product.category.ilike('%wallet%')) | 
                (Product.category.ilike('%emoney%'))
            )
        elif category in ['GAMES', 'GAME']:
            query = query.filter(
                (Product.category.ilike('%game%')) | 
                (Product.category.ilike('%voucher%'))
            )
        elif category in ['TV', 'STREAMING']:
            query = query.filter(
                (Product.category.ilike('%tv%')) | 
                (Product.category.ilike('%parabola%')) | 
                (Product.category.ilike('%streaming%'))
            )
        else:
            query = query.filter(Product.category.ilike(f"%{category}%"))

    if brand:
        query = query.filter(Product.brand.ilike(f"%{brand}%"))

    if search_q:
        query = query.filter(
            (Product.name.ilike(f"%{search_q}%")) | 
            (Product.sku_code.ilike(f"%{search_q}%")) | 
            (Product.brand.ilike(f"%{search_q}%"))
        )

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


@kasir_bp.route('/brands', methods=['GET'])
def get_brands():
    """Mengambil daftar brand unik untuk kategori tertentu."""
    category = request.args.get('category', '').strip().upper()
    query = Product.query.filter_by(is_active=True)

    if category == 'EMONEY':
        query = query.filter(
            (Product.category.ilike('%e-money%')) | 
            (Product.category.ilike('%wallet%')) | 
            (Product.category.ilike('%emoney%'))
        )
    elif category in ['GAMES', 'GAME']:
        query = query.filter(
            (Product.category.ilike('%game%')) | 
            (Product.category.ilike('%voucher%'))
        )
    elif category in ['TV', 'STREAMING']:
        query = query.filter(
            (Product.category.ilike('%tv%')) | 
            (Product.category.ilike('%parabola%')) | 
            (Product.category.ilike('%streaming%'))
        )
    elif category == 'PULSA':
        query = query.filter(Product.category.ilike('%pulsa%'))
    elif category == 'DATA':
        query = query.filter(
            (Product.category.ilike('%data%')) | 
            (Product.category.ilike('%kuota%')) | 
            (Product.category.ilike('%internet%'))
        )
    elif category in ['TELPSMS', 'TELP_SMS']:
        query = query.filter(
            (Product.category.ilike('%telp%')) | 
            (Product.category.ilike('%sms%'))
        )
    elif category in ['MASAAKTIF', 'MASA_AKTIF']:
        query = query.filter(Product.category.ilike('%masa%'))

    raw_brands = [b[0].strip() for b in query.with_entities(Product.brand).distinct().order_by(Product.brand.asc()).all() if b[0]]
    clean_brands = []
    for b in raw_brands:
        cb = b.replace('VIP-', '').strip()
        if cb and cb not in clean_brands:
            clean_brands.append(cb)

    return jsonify({'status': 'success', 'brands': clean_brands}), 200


@kasir_bp.route('/checkout', methods=['POST'])
@csrf.exempt
@limiter.limit("30 per minute")
def checkout():
    """
    Eksekusi Transaksi Penjualan dari Portal Kasir menggunakan Saldo Khusus Cabang Ini.
    Menerapkan validasi saldo cabang, limit harian, dan jam operasional cabang.
    """
    active_device = get_current_cashier_device()
    if not active_device:
        return jsonify({'status': 'error', 'message': 'Sesi kasir telah berakhir. Masukkan PIN kembali.'}), 401

    owner = db.session.query(User).filter_by(id=active_device.user_id).first()
    if not owner or not owner.is_vip_active():
        return jsonify({'status': 'error', 'message': 'Akun VIP toko tidak aktif atau telah kedaluwarsa.'}), 403

    req_data = request.get_json(silent=True) or request.form.to_dict() or {}
    sku_code = str(req_data.get('sku_code', '')).strip()
    target_number = str(req_data.get('target_number', '')).strip()
    shift_name = session.get('cashier_shift_name', 'Kasir Toko')

    if not sku_code or not target_number:
        return jsonify({'status': 'error', 'message': 'Produk dan Nomor Tujuan wajib diisi!'}), 400

    product = Product.query.filter_by(sku_code=sku_code, is_active=True).first()
    if not product:
        return jsonify({'status': 'error', 'message': 'Produk tidak ditemukan atau sedang dinonaktifkan.'}), 404

    # Harga modal VIP untuk toko
    amount = get_user_product_price(owner, product)

    # 1. Validasi Batasan Operasional & Limit Harian Cabang
    lim_ok, lim_err = verify_cashier_transaction_limits(active_device, amount)
    if not lim_ok:
        return jsonify({'status': 'error', 'message': lim_err}), 400

    # 2. Validasi Saldo Khusus Cabang Ini (Branch Balance)
    locked_device = db.session.query(TrustedDevice).filter_by(id=active_device.id).with_for_update().first() or active_device
    cur_branch_bal = float(locked_device.branch_balance or 0.0)
    if cur_branch_bal < amount:
        return jsonify({
            'status': 'error',
            'is_low_balance': True,
            'message': f'Saldo kasir cabang tidak mencukupi (Sisa: Rp {cur_branch_bal:,.0f}, Diperlukan: Rp {amount:,.0f}). Silakan gunakan tombol "Minta Tambah Saldo ke Bos".'
        }), 400

    # 3. Potong Saldo Cabang & Catat Transaksi + Mutasi
    bal_before = cur_branch_bal
    locked_device.branch_balance = bal_before - amount
    bal_after = float(locked_device.branch_balance)

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
        device_id=locked_device.id,
        device_name=locked_device.device_name
    )
    db.session.add(new_trx)

    # Catat mutasi cabang
    mut_sale = BranchMutation(
        device_id=locked_device.id,
        user_id=owner.id,
        type='SALE',
        amount=amount,
        balance_before=bal_before,
        balance_after=bal_after,
        description=f"Penjualan {product.name} ({target_number})",
        shift_name=shift_name,
        created_at=datetime.utcnow()
    )
    db.session.add(mut_sale)
    locked_device.last_used_at = datetime.utcnow()
    db.session.commit()

    # 4. Eksekusi ke Provider (Digiflazz / VIP-Reseller)
    is_vip_provider = 'VIP' in (product.brand or '').upper() or 'VOUCHER' in (product.category or '').upper()

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
            # Gagal di provider -> Refund ke saldo cabang
            raw_msg = str(order_res.get('message', 'Ditolak API Provider'))
            locked_device.branch_balance += amount
            mut_ref = BranchMutation(
                device_id=locked_device.id,
                user_id=owner.id,
                type='REFUND',
                amount=amount,
                balance_before=bal_after,
                balance_after=bal_after + amount,
                description=f"Refund transaksi gagal ({raw_msg})",
                shift_name=shift_name,
                created_at=datetime.utcnow()
            )
            db.session.add(mut_ref)
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
            # Gagal di digiflazz -> Refund ke saldo cabang
            raw_msg = str(msg_digi or 'Ditolak Digiflazz')
            locked_device.branch_balance += amount
            mut_ref = BranchMutation(
                device_id=locked_device.id,
                user_id=owner.id,
                type='REFUND',
                amount=amount,
                balance_before=bal_after,
                balance_after=bal_after + amount,
                description=f"Refund transaksi gagal ({raw_msg})",
                shift_name=shift_name,
                created_at=datetime.utcnow()
            )
            db.session.add(mut_ref)
            new_trx.status = 'FAILED'
            new_trx.sn = raw_msg
            db.session.commit()
            return jsonify({'status': 'error', 'message': f'Gagal di server provider: {raw_msg}'}), 400

    # 5. Cek Peringatan Saldo Menipis (Alert otomatis WhatsApp ke Owner jika < Rp 100.000)
    from app.services.device_service import check_and_notify_low_balance
    check_and_notify_low_balance(active_device, shift_name=shift_name, base_url=request.host_url)

    return jsonify({
        'status': 'success',
        'message': 'Transaksi Kasir Berhasil Diproses!',
        'remaining_branch_balance': float(active_device.branch_balance or 0.0),
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
    """Mengambil riwayat transaksi khusus cabang kasir ini."""
    active_device = get_current_cashier_device()
    if not active_device:
        return jsonify({'status': 'error', 'message': 'Sesi kasir tidak aktif'}), 401

    limit = int(request.args.get('limit', 50))
    trxs = get_branch_cashier_history(active_device.id, limit=limit)
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

    return jsonify({
        'status': 'success',
        'history': data,
        'current_balance': float(active_device.branch_balance or 0.0)
    }), 200


@kasir_bp.route('/mutations')
def mutations():
    """Mengambil riwayat mutasi saldo masuk/keluar cabang kasir."""
    active_device = get_current_cashier_device()
    if not active_device:
        return jsonify({'status': 'error', 'message': 'Sesi kasir tidak aktif'}), 401

    from app.services.device_service import get_branch_mutations
    muts = get_branch_mutations(active_device.id, limit=50)
    data = []
    for m in muts:
        data.append({
            'id': m.id,
            'type': m.type,
            'amount': m.amount,
            'balance_before': m.balance_before,
            'balance_after': m.balance_after,
            'description': m.description or '',
            'shift_name': m.shift_name or 'Kasir Toko',
            'time': m.created_at_wib,
            'date': m.date_wib,
            'clock': m.time_wib
        })

    return jsonify({
        'status': 'success',
        'mutations': data,
        'current_balance': float(active_device.branch_balance or 0.0)
    }), 200


@kasir_bp.route('/request_deposit', methods=['POST'])
@csrf.exempt
@limiter.limit("10 per minute")
def request_deposit():
    """Kasir cabang mengirimkan permohonan saldo ke WhatsApp Owner."""
    active_device = get_current_cashier_device()
    if not active_device:
        return jsonify({'status': 'error', 'message': 'Sesi kasir tidak aktif'}), 401

    data = request.get_json(silent=True) or request.form.to_dict() or {}
    requested_amount = data.get('amount')
    note = data.get('note', '')
    shift_name = session.get('cashier_shift_name', 'Kasir Toko')

    from app.services.device_service import request_branch_deposit_via_wa
    ok, msg = request_branch_deposit_via_wa(
        device_id=active_device.id,
        requested_amount=requested_amount,
        shift_name=shift_name,
        note=note,
        base_url=request.host_url
    )
    if ok:
        return jsonify({'status': 'success', 'message': msg}), 200
    return jsonify({'status': 'error', 'message': msg}), 400

