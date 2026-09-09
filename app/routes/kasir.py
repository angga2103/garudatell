import time
import random
import secrets
import logging
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
logger = logging.getLogger(__name__)

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


def is_crawler_or_bot(user_agent_str):
    """Mendeteksi apakah request berasal dari bot preview tautan (WhatsApp, Telegram, Facebook, dll)."""
    if not user_agent_str:
        return False
    ua = user_agent_str.lower()
    crawlers = [
        'whatsapp', 'facebookexternalhit', 'facebot', 'meta-externalagent',
        'telegrambot', 'twitterbot', 'slackbot', 'discordbot', 'linkedinbot',
        'googlebot', 'bingbot', 'applebot', 'yandex', 'duckduckbot',
        'crawler', 'spider', 'preview', 'curl', 'wget', 'python-requests', 'bytespider'
    ]
    return any(c in ua for c in crawlers)


@kasir_bp.route('/aktivasi/<token>')
def aktivasi(token):
    """
    Tautan aktivasi kasir satu kali pakai yang diklik oleh karyawan di komputer toko.
    Dilengkapi proteksi crawler (WhatsApp, Facebook, dll) dan pemulihan otomatis jika perangkat sudah aktif.
    """
    store_name = get_store_name()
    user_agent = request.user_agent.string or ''

    # 1. Deteksi & Amankan Tautan dari Link Preview Bot (WhatsApp, Telegram, Facebot, dll)
    # Bot / crawler HANYA disajikan preview meta tag tanpa membakar/menghanguskan token aktivasi!
    if is_crawler_or_bot(user_agent):
        device_preview = TrustedDevice.query.filter_by(activation_token=token).first()
        branch_name = device_preview.device_name if device_preview else 'Cabang Toko'
        return render_template(
            'kasir/preview_bot.html',
            store_name=store_name,
            branch_name=branch_name
        )

    # 2. Cek apakah browser ini SUDAH memiliki cookie kasir aktif sebelumnya
    cookie_token = request.cookies.get('gt_device_token')
    if cookie_token:
        existing_dev = TrustedDevice.query.filter_by(device_uuid=cookie_token, status='approved').first()
        if existing_dev:
            return make_response(render_template(
                'kasir/not_registered.html',
                store_name=store_name,
                title="Perangkat Kasir Sudah Terhubung! 🎉",
                message=f"Browser / komputer ini sudah terdaftar resmi sebagai Kasir: '{existing_dev.device_name}'. Anda dapat langsung membuka layar kasir.",
                is_success=True,
                device_token=cookie_token
            ))

    # 3. Eksekusi Aktivasi untuk Browser Nyata
    device_token = f"gt_pos_{secrets.token_hex(16)}"
    ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip_address and ',' in ip_address:
        ip_address = ip_address.split(',')[0].strip()

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

    resp = make_response(jsonify({
        'status': 'success',
        'message': msg,
        'redirect': '/kasir'
    }), 200)
    resp.set_cookie('gt_device_token', device.device_uuid, max_age=31536000, httponly=True, samesite='Lax', path='/')
    return resp


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
                (Product.brand.ilike('%game%')) |
                (Product.name.ilike('%diamond%'))
            )
        elif category in ['VOUCHER', 'VOUCHERS']:
            query = query.filter(
                (Product.category.ilike('%voucher%')) | 
                (Product.name.ilike('%voucher%')) | 
                (Product.brand.ilike('%voucher%')) |
                (Product.category.ilike('%aigo%')) |
                (Product.brand.in_(['VIP-ALFAMART VOUCHER', 'VIP-INDOMARET', 'VIP-SPOTIFY', 'VIP-VIDIO', 'VIP-CARREFOUR / TRANSMART', 'VIP-YOSHINOYA']))
            )
        elif category in ['TV', 'STREAMING']:
            query = query.filter(
                (Product.category.ilike('%tv%')) | 
                (Product.category.ilike('%parabola%')) | 
                (Product.category.ilike('%streaming%'))
            )
        elif category in ['PASCABAYAR', 'PPOB', 'TAGIHAN']:
            query = query.filter(
                (Product.category.ilike('%pascabayar%')) | 
                (Product.category.ilike('%pasca%')) | 
                (Product.category.ilike('%tagihan%')) |
                (Product.brand.in_(['PDAM', 'BPJS KESEHATAN', 'PBB', 'PLN PASCABAYAR', 'PLN NONTAGLIS']))
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

    # Optimasi performa: Baca diskon VIP/Reseller 1x di luar loop (mengeliminasi ratusan query DB berulang)
    from app.services.tier_service import get_setting_float
    role = owner.get_effective_role() if hasattr(owner, 'get_effective_role') else getattr(owner, 'role', 'user')
    vip_discount = get_setting_float('discount_vip', 200.0) if role == 'vip' else (get_setting_float('discount_reseller', 100.0) if role == 'reseller' else 0.0)

    prods_data = []
    for p in products:
        s_price = float(p.sell_price or 0.0)
        b_price = float(getattr(p, 'base_price', 0.0) or 0.0)
        if role in ['vip', 'reseller'] and vip_discount > 0:
            floor = (b_price + 100.0) if b_price > 0 else (s_price - vip_discount)
            final_price = round(max(floor, s_price - vip_discount), 2)
        else:
            final_price = s_price

        is_pasca = 'PASCABAYAR' in (p.category or '').upper() or 'PASCA' in (p.name or '').upper() or (p.brand or '').upper() in ['PDAM', 'BPJS KESEHATAN', 'PBB', 'PLN PASCABAYAR', 'PLN NONTAGLIS']

        prods_data.append({
            'id': p.id,
            'sku_code': p.sku_code,
            'name': p.name,
            'brand': p.brand,
            'category': p.category,
            'price': final_price,
            'normal_price': s_price,
            'is_pasca': is_pasca,
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

    if category == 'PLN':
        query = query.filter(Product.category.ilike('%pln%'))
    elif category == 'EMONEY':
        query = query.filter(
            (Product.category.ilike('%e-money%')) | 
            (Product.category.ilike('%wallet%')) | 
            (Product.category.ilike('%emoney%'))
        )
    elif category in ['GAMES', 'GAME']:
        query = query.filter(
            (Product.category.ilike('%game%')) | 
            (Product.brand.ilike('%game%')) |
            (Product.name.ilike('%diamond%'))
        )
    elif category in ['VOUCHER', 'VOUCHERS']:
        query = query.filter(
            (Product.category.ilike('%voucher%')) | 
            (Product.name.ilike('%voucher%')) | 
            (Product.brand.ilike('%voucher%')) |
            (Product.category.ilike('%aigo%')) |
            (Product.brand.in_(['VIP-ALFAMART VOUCHER', 'VIP-INDOMARET', 'VIP-SPOTIFY', 'VIP-VIDIO', 'VIP-CARREFOUR / TRANSMART', 'VIP-YOSHINOYA']))
        )
    elif category in ['TV', 'STREAMING']:
        query = query.filter(
            (Product.category.ilike('%tv%')) | 
            (Product.category.ilike('%parabola%')) | 
            (Product.category.ilike('%streaming%'))
        )
    elif category in ['PASCABAYAR', 'PPOB', 'TAGIHAN']:
        query = query.filter(
            (Product.category.ilike('%pascabayar%')) | 
            (Product.category.ilike('%pasca%')) | 
            (Product.category.ilike('%tagihan%')) |
            (Product.brand.in_(['PDAM', 'BPJS KESEHATAN', 'PBB', 'PLN PASCABAYAR', 'PLN NONTAGLIS']))
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


def execute_cashier_provider_order(trx_id, device_id, owner_id, amount, sku_code, target_number, ref_id, is_vip_provider, shift_name, bal_after, is_pasca_bill=False):
    """
    Eksekusi pemesanan ke provider (Digiflazz / VIP-Reseller / Pascabayar Biller).
    Dijalankan secara asinkron di background thread agar checkout kasir instan tanpa delay.
    """
    try:
        trx = db.session.get(Transaction, trx_id)
        locked_device = db.session.get(TrustedDevice, device_id)
        owner = db.session.get(User, owner_id)
        if not trx or not locked_device or not owner:
            return

        if is_pasca_bill:
            from app.services.digiflazz import pay_pasca
            from app.services.provider_helper import sanitize_public_sn_message
            try:
                ok_pay, res_pay, msg_pay = pay_pasca(sku_code, target_number, ref_id)
                digi_data = res_pay if isinstance(res_pay, dict) else {}
                digi_status = str(digi_data.get('status', '')).lower()
                rc = str(digi_data.get('rc', '')).strip()
                raw_msg = digi_data.get('message') or msg_pay or 'Respon biller tidak diketahui'

                if ok_pay or 'sukses' in digi_status or rc == '00':
                    trx.status = 'SUCCESS'
                    trx.sn = digi_data.get('sn') or '-'
                    from app.routes.transaction import award_transaction_points
                    award_transaction_points(owner.id, ref_id)
                    db.session.commit()
                elif 'gagal' in digi_status or rc in ['01', '41', '42', '50', '52']:
                    locked_device.branch_balance += amount
                    mut_ref = BranchMutation(
                        device_id=locked_device.id,
                        user_id=owner.id,
                        type='REFUND',
                        amount=amount,
                        balance_before=bal_after,
                        balance_after=bal_after + amount,
                        description=f"Refund tagihan ditolak biller ({raw_msg})",
                        shift_name=shift_name,
                        created_at=datetime.utcnow()
                    )
                    db.session.add(mut_ref)
                    trx.status = 'FAILED'
                    trx.sn = sanitize_public_sn_message(raw_msg, rc=rc)
                    db.session.commit()
                else:
                    trx.status = 'PROCESSING'
                    if digi_data.get('sn'):
                        trx.sn = digi_data.get('sn')
                    db.session.commit()
            except Exception as e_pasca:
                logger.error(f"Error Digiflazz cashier pasca trx {ref_id}: {e_pasca}")
                trx.status = 'PROCESSING'
                db.session.commit()
        elif is_vip_provider:
            from app.services.vip_reseller import VIPReseller
            vip = VIPReseller()
            order_res = vip.create_order(sku_code, target_number)
            if order_res.get('result'):
                vip_data = order_res.get('data', {})
                if vip_data.get('trxid'):
                    trx.provider_ref = vip_data.get('trxid')
                trx.status = 'PROCESSING'
                db.session.commit()
            else:
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
                trx.status = 'FAILED'
                from app.services.provider_helper import sanitize_public_sn_message
                trx.sn = sanitize_public_sn_message(raw_msg)
                db.session.commit()
        else:
            from app.services.digiflazz import create_transaction
            from app.services.provider_helper import sanitize_public_sn_message
            try:
                digi_res = create_transaction(sku_code, target_number, ref_id)
                digi_data = digi_res.get('data', {}) if isinstance(digi_res, dict) else {}
                digi_status = str(digi_data.get('status', '')).lower()
                rc = str(digi_data.get('rc', '')).strip()
                raw_msg = digi_data.get('message') or 'Respon operator tidak diketahui'

                if 'sukses' in digi_status or 'success' in digi_status or rc == '00':
                    trx.status = 'SUCCESS'
                    trx.sn = digi_data.get('sn') or '-'
                    from app.routes.transaction import award_transaction_points
                    award_transaction_points(owner.id, ref_id)
                    db.session.commit()
                elif 'gagal' in digi_status or 'failed' in digi_status or rc in ['01', '41', '42', '50', '52']:
                    locked_device.branch_balance += amount
                    mut_ref = BranchMutation(
                        device_id=locked_device.id,
                        user_id=owner.id,
                        type='REFUND',
                        amount=amount,
                        balance_before=bal_after,
                        balance_after=bal_after + amount,
                        description=f"Refund transaksi ditolak operator ({raw_msg})",
                        shift_name=shift_name,
                        created_at=datetime.utcnow()
                    )
                    db.session.add(mut_ref)
                    trx.status = 'FAILED'
                    trx.sn = sanitize_public_sn_message(raw_msg, rc=rc)
                    db.session.commit()
                else:
                    trx.status = 'PROCESSING'
                    if digi_data.get('sn'):
                        trx.sn = digi_data.get('sn')
                    db.session.commit()
            except Exception as e_digi:
                logger.error(f"Error Digiflazz cashier trx {ref_id}: {e_digi}")
                trx.status = 'PROCESSING'
                db.session.commit()
    except Exception as e_outer:
        logger.error(f"Error in execute_cashier_provider_order for {ref_id}: {e_outer}")


def _run_async_cashier_order(app_obj, *args):
    with app_obj.app_context():
        execute_cashier_provider_order(*args)


@kasir_bp.route('/inquiry_bill', methods=['POST'])
@csrf.exempt
@limiter.limit("30 per minute")
def cashier_inquiry_bill():
    """
    Kasir cabang melakukan Cek Tagihan Pascabayar (PDAM, BPJS, PLN Pasca, PBB, dll.) ke Digiflazz.
    Menghasilkan ref_id unik yang disimpan ke PostpaidInquiry dan wajib digunakan saat checkout pay-pasca.
    """
    active_device = get_current_cashier_device()
    if not active_device:
        return jsonify({'status': 'error', 'message': 'Sesi kasir telah berakhir. Masukkan PIN kembali.'}), 401

    owner = db.session.query(User).filter_by(id=active_device.user_id).first()
    if not owner or not owner.is_vip_active():
        return jsonify({'status': 'error', 'message': 'Akun VIP toko tidak aktif.'}), 403

    req_data = request.get_json(silent=True) or request.form.to_dict() or {}
    sku_input = str(req_data.get('sku_code', '')).strip()
    customer_no = str(req_data.get('customer_no', '')).strip()

    if not sku_input or not customer_no:
        return jsonify({'status': 'error', 'message': 'Produk dan Nomor Pelanggan wajib diisi!'}), 400

    if len(customer_no) < 6:
        return jsonify({'status': 'error', 'message': 'Nomor Pelanggan minimal 6 karakter!'}), 400

    product = Product.query.filter_by(sku_code=sku_input, is_active=True).first()
    if not product:
        return jsonify({'status': 'error', 'message': 'Produk tagihan tidak ditemukan atau sedang nonaktif.'}), 404

    # Cek Cut Off PLN jika produk PLN
    is_pln = 'PLN' in (product.category or '').upper() or 'PLN' in (product.name or '').upper() or 'PLN' in (product.brand or '').upper()
    from app.services.digiflazz import inquiry_pasca, is_pln_cutoff_time, get_pln_cutoff_message
    if is_pln and is_pln_cutoff_time():
        return jsonify({'status': 'error', 'is_cutoff': True, 'message': get_pln_cutoff_message()}), 400

    ref_id = f"KASIR-PASCA-{int(time.time()*1000)}{random.randint(10, 99)}"

    ok, res_data, msg = inquiry_pasca(sku_input, customer_no, ref_id)
    if not ok or not res_data:
        return jsonify({
            'status': 'error',
            'message': msg or 'Tagihan tidak ditemukan atau sudah dibayar.',
            'data': res_data or {}
        }), 400

    desc = res_data.get('desc') or {}
    tarif = desc.get('tarif', '-')
    daya = desc.get('daya', '-')
    lembar_tagihan = desc.get('lembar_tagihan', 1)
    tagihan_obj = desc.get('tagihan') if isinstance(desc.get('tagihan'), dict) else {}
    details = desc.get('detail') or tagihan_obj.get('detail') or []

    tagihan_pokok = 0.0
    denda_total = 0.0
    periode_list = []
    if details and isinstance(details, list):
        for d in details:
            tagihan_pokok += float(d.get('nilai_tagihan', 0))
            denda_total += float(d.get('denda', 0))
            if d.get('periode'):
                periode_list.append(str(d.get('periode')))

    digi_admin = float(res_data.get('admin', 0))
    digi_price = float(res_data.get('price', 0))
    if tagihan_pokok == 0 and digi_price > 0:
        tagihan_pokok = max(0.0, digi_price - digi_admin)

    # Biaya admin / margin toko (harga jual produk pasca)
    admin_fee_toko = float(product.sell_price) if product.sell_price else (digi_admin + 2000.0)
    total_bayar = tagihan_pokok + denda_total + admin_fee_toko
    periode_str = ", ".join(periode_list) if periode_list else "-"

    # Simpan record inquiry
    from app.models.inquiry import PostpaidInquiry
    try:
        inquiry_obj = PostpaidInquiry(
            ref_id=ref_id,
            user_id=owner.id,
            sku_code=sku_input,
            customer_no=customer_no,
            customer_name=res_data.get('customer_name', '-'),
            tarif=tarif,
            daya=daya,
            lembar_tagihan=lembar_tagihan,
            tagihan_pokok=tagihan_pokok,
            denda=denda_total,
            admin_fee=admin_fee_toko,
            total_amount=total_bayar,
            expires_at=datetime.utcnow() + timedelta(minutes=30)
        )
        db.session.add(inquiry_obj)
        db.session.commit()
    except Exception as err_inq:
        db.session.rollback()
        logger.warning(f"Gagal simpan inquiry kasir: {err_inq}")

    return jsonify({
        'status': 'success',
        'ref_id': ref_id,
        'sku_code': sku_input,
        'product_name': product.name,
        'customer_no': customer_no,
        'customer_name': res_data.get('customer_name', '-'),
        'tarif': tarif,
        'daya': daya,
        'lembar_tagihan': lembar_tagihan,
        'periode': periode_str,
        'tagihan_pokok': tagihan_pokok,
        'denda': denda_total,
        'admin_fee': admin_fee_toko,
        'total_bayar': total_bayar,
        'current_branch_balance': float(active_device.branch_balance or 0.0)
    }), 200


@kasir_bp.route('/checkout', methods=['POST'])
@csrf.exempt
@limiter.limit("30 per minute")
def checkout():
    """
    Eksekusi Transaksi Penjualan dari Portal Kasir menggunakan Saldo Khusus Cabang Ini.
    Mendukung produk Prabayar dan Pascabayar (PPOB: PDAM, BPJS, PLN Pasca, PBB).
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
    inquiry_ref_id = str(req_data.get('inquiry_ref_id') or req_data.get('ref_id') or '').strip()

    if not sku_code or not target_number:
        return jsonify({'status': 'error', 'message': 'Produk dan Nomor Tujuan wajib diisi!'}), 400

    product = Product.query.filter_by(sku_code=sku_code, is_active=True).first()
    if not product:
        return jsonify({'status': 'error', 'message': 'Produk tidak ditemukan atau sedang dinonaktifkan.'}), 404

    # Deteksi apakah transaksi ini adalah Tagihan Pascabayar (PPOB)
    is_pasca_bill = False
    if inquiry_ref_id and (inquiry_ref_id.startswith('KASIR-PASCA-') or inquiry_ref_id.startswith('GT-PASCA-')):
        is_pasca_bill = True
    elif 'PASCABAYAR' in (product.category or '').upper() or 'PASCA' in (product.name or '').upper() or (product.brand or '').upper() in ['PDAM', 'BPJS KESEHATAN', 'PBB', 'PLN PASCABAYAR', 'PLN NONTAGLIS']:
        is_pasca_bill = True

    if is_pasca_bill:
        if not inquiry_ref_id:
            return jsonify({'status': 'error', 'message': 'Harap lakukan Cek Tagihan terlebih dahulu sebelum melakukan pembayaran tagihan.'}), 400
        from app.models.inquiry import PostpaidInquiry
        inq = PostpaidInquiry.query.filter_by(ref_id=inquiry_ref_id).first()
        if not inq:
            return jsonify({'status': 'error', 'message': 'Sesi Cek Tagihan tidak ditemukan atau telah kedaluwarsa.'}), 404
        if inq.is_paid:
            return jsonify({'status': 'error', 'message': 'Tagihan ini sudah berhasil dibayar sebelumnya.'}), 400
        if inq.expires_at and inq.expires_at < datetime.utcnow():
            return jsonify({'status': 'error', 'message': 'Sesi Cek Tagihan telah kedaluwarsa (maks 30 menit). Silakan lakukan Cek Tagihan ulang.'}), 400

        # CRITICAL ANTI-TAMPERING: Kunci nominal murni dari server hasil inquiry
        amount = float(inq.total_amount)
        ref_id = inq.ref_id
        inq.is_paid = True
    else:
        # Harga modal VIP untuk toko
        amount = get_user_product_price(owner, product)
        ref_id = f"KASIR-{int(time.time()*1000)}{random.randint(10, 99)}"

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
        is_prepaid=not is_pasca_bill,
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

    # 4. Eksekusi ke Provider (Digiflazz / VIP-Reseller / Biller Pasca) - Asynchronous Background Processing
    is_vip_provider = ('VIP' in (product.brand or '').upper() or 'VOUCHER' in (product.category or '').upper()) and not is_pasca_bill

    from flask import current_app
    is_testing = current_app.config.get('TESTING', False)
    if is_testing:
        execute_cashier_provider_order(
            new_trx.id, locked_device.id, owner.id, amount, sku_code, target_number, ref_id, is_vip_provider, shift_name, bal_after, is_pasca_bill
        )
    else:
        import threading
        app_obj = current_app._get_current_object()
        thread = threading.Thread(
            target=_run_async_cashier_order,
            args=(app_obj, new_trx.id, locked_device.id, owner.id, amount, sku_code, target_number, ref_id, is_vip_provider, shift_name, bal_after, is_pasca_bill),
            daemon=True
        )
        thread.start()

    # 5. Cek Peringatan Saldo Menipis (Alert otomatis WhatsApp ke Owner jika < Rp 100.000)
    from app.services.device_service import check_and_notify_low_balance
    check_and_notify_low_balance(locked_device, shift_name=shift_name, base_url=request.host_url)

    # Respon cepat (< 100ms) agar kasir langsung diarahkan ke Riwayat Shift
    return jsonify({
        'status': 'success',
        'ref_id': new_trx.ref_id,
        'trx_status': new_trx.status,
        'message': 'Pesanan berhasil dikirim ke operator! Membuka Riwayat Shift...',
        'remaining_branch_balance': float(locked_device.branch_balance or 0.0),
        'trx': {
            'ref_id': new_trx.ref_id,
            'product_name': new_trx.product_name,
            'target_number': new_trx.target_number,
            'amount': new_trx.amount,
            'status': new_trx.status,
            'sn': new_trx.sn or '-',
            'branch_name': locked_device.device_name,
            'time': new_trx.created_at_wib
        }
    }), 200


@kasir_bp.route('/check_status/<ref_id>')
def check_status(ref_id):
    """Kasir cabang memeriksa status terkini 1 transaksi ke provider API (Real-Time)."""
    active_device = get_current_cashier_device()
    if not active_device:
        return jsonify({'status': 'error', 'message': 'Sesi kasir tidak aktif'}), 401

    trx = Transaction.query.filter_by(ref_id=ref_id, device_id=active_device.id).first()
    if not trx:
        return jsonify({'status': 'error', 'message': 'Transaksi tidak ditemukan pada cabang kasir ini'}), 404

    if trx.status in ['PROCESSING', 'PENDING', 'PROSES']:
        from app.routes.transaction import sync_single_transaction
        try:
            sync_single_transaction(trx)
        except Exception as e:
            logger.error(f"Error cashier sync single trx {ref_id}: {e}")

    fresh_device = TrustedDevice.query.get(active_device.id) or active_device

    return jsonify({
        'status': 'success',
        'trx_status': trx.status,
        'ref_id': trx.ref_id,
        'product_name': trx.product_name,
        'target_number': trx.target_number,
        'amount': trx.amount,
        'sn': trx.sn or '-',
        'time': trx.created_at_wib,
        'current_balance': float(fresh_device.branch_balance or 0.0)
    }), 200


@kasir_bp.route('/history')
def history():
    """Mengambil riwayat transaksi khusus cabang kasir ini dan menyinkronkan status secara real-time."""
    active_device = get_current_cashier_device()
    if not active_device:
        return jsonify({'status': 'error', 'message': 'Sesi kasir tidak aktif'}), 401

    # Sinkronkan otomatis transaksi yang masih PROCESSING / PENDING ke server provider secara real-time
    from app.services.device_service import sync_pending_cashier_transactions
    try:
        sync_pending_cashier_transactions(active_device.id)
    except Exception:
        pass

    # Ambil ulang data fresh dari DB untuk memastikan status & saldo cabang akurat jika terjadi refund
    fresh_device = TrustedDevice.query.get(active_device.id) or active_device

    limit = int(request.args.get('limit', 50))
    trxs = get_branch_cashier_history(fresh_device.id, limit=limit)
    data = []
    has_pending = False
    for t in trxs:
        if t.status in ['PROCESSING', 'PENDING', 'PROSES']:
            has_pending = True
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
        'has_pending': has_pending,
        'current_balance': float(fresh_device.branch_balance or 0.0)
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

