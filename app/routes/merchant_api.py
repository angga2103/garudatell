import logging
import hashlib
from datetime import datetime
from flask import Blueprint, request, jsonify
from app.extensions import db, csrf, limiter
from app.models.merchant import MerchantApiKey
from app.models.product import Product
from app.models.transaction import Transaction
from app.models.user import User
from app.services.merchant_service import (
    authenticate_merchant,
    verify_signature,
    dispatch_merchant_webhook
)
from app.services.tier_service import get_user_product_price
from app.services.commission_service import award_downline_commission

logger = logging.getLogger(__name__)

merchant_api_bp = Blueprint("merchant_api_bp", __name__)

# Seluruh rute API di bawah blueprint ini dikecualikan dari proteksi form CSRF
csrf.exempt(merchant_api_bp)

# ============================================================
# SAFE UNIVERSAL DIGIFLAZZ IMPORT
# ============================================================
submit_transaction = None
inquiry_postpaid = None
pay_postpaid = None

# 1. Coba import dari modul root (yang dipakai oleh routes/user.py)
try:
    from digiflazz import submit_transaction as df_submit, inquiry_postpaid as df_inq, pay_postpaid as df_pay
    submit_transaction = df_submit
    inquiry_postpaid = df_inq
    pay_postpaid = df_pay
except ImportError:
    pass

# 2. Jika belum ketemu, coba import dari app.services.digiflazz
if not submit_transaction:
    try:
        import app.services.digiflazz as df_srv
        if hasattr(df_srv, 'submit_transaction'):
            submit_transaction = df_srv.submit_transaction
        elif hasattr(df_srv, 'create_transaction'):
            submit_transaction = df_srv.create_transaction
        elif hasattr(df_srv, 'transaksi'):
            submit_transaction = df_srv.transaksi

        inquiry_postpaid = getattr(df_srv, 'inquiry_postpaid', None) or getattr(df_srv, 'inquiry_pasca', None)
        pay_postpaid = getattr(df_srv, 'pay_postpaid', None) or getattr(df_srv, 'pay_pasca', None)
    except ImportError:
        pass

if not submit_transaction:
    try:
        from app.services.digiflazz import create_transaction as df_create
        submit_transaction = df_create
    except Exception:
        raise ImportError("Fungsi submit_transaction tidak ditemukan di digiflazz maupun app.services.digiflazz")



# =====================================================================
# 1. CEK SALDO MERCHANT (POST & GET /api/v1/profile/balance)
# =====================================================================
@merchant_api_bp.route("/profile/balance", methods=["GET", "POST"])
def check_balance():
    """
    Pengecekan sisa saldo akun merchant iPay secara real-time.
    Kompatibel penuh dengan POS IPAY PPOBService.getBalance() & testConnection().
    """
    merchant, err = authenticate_merchant(request)
    if err:
        return jsonify({"status": "failed", "message": err[0]}), err[1]

    # Validasi signature jika method POST dan parameter signature dikirimkan
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form.to_dict() or {}
        req_mch = data.get("merchant_id")
        req_sign = data.get("signature") or data.get("sign")
        if req_mch and req_sign:
            expected_str = f"{merchant.merchant_id}{merchant.secret_key}balance"
            if not verify_signature(merchant, req_sign, expected_str):
                return jsonify({"status": "failed", "message": "Signature tidak valid"}), 403

    user = merchant.user
    balance_val = float(user.balance or 0.0) if user else 0.0

    return jsonify({
        "status": "success",
        "merchant_id": merchant.merchant_id,
        "username": user.phone if user else "",
        "name": user.name if user else "",
        "role": user.get_effective_role() if hasattr(user, 'get_effective_role') else getattr(user, 'role', 'user'),
        "balance": balance_val,
        "message": "Saldo berhasil diambil"
    }), 200


# =====================================================================
# 1.1 INFORMASI DEPOSIT & REKENING PEMBAYARAN (GET /api/v1/profile/deposit/info)
# =====================================================================
@merchant_api_bp.route("/profile/deposit/info", methods=["GET"])
def get_deposit_info():
    """
    Mengambil informasi saldo terkini dan saluran pembayaran deposit yang tersedia
    (DANA, ShopeePay, GoPay, Rekening Transfer Bank, QRIS).
    """
    merchant, err = authenticate_merchant(request)
    if err:
        return jsonify({"status": "failed", "message": err[0]}), err[1]

    from app.services.setting_service import get_manual_deposit_settings
    manual_depo = get_manual_deposit_settings()
    user = merchant.user
    balance_val = float(user.balance or 0.0) if user else 0.0

    channels = []
    if manual_depo.get('dana_number'):
        channels.append({
            "code": "DANA",
            "name": "DANA E-Wallet",
            "account_no": manual_depo['dana_number'],
            "account_name": manual_depo.get('dana_name', 'GarudaTel / Kasir'),
            "type": "ewallet"
        })
    if manual_depo.get('gopay_number'):
        channels.append({
            "code": "GOPAY",
            "name": "GoPay E-Wallet",
            "account_no": manual_depo['gopay_number'],
            "account_name": manual_depo.get('gopay_name', 'GarudaTel / Kasir'),
            "type": "ewallet"
        })
    if manual_depo.get('shopee_number'):
        channels.append({
            "code": "SHOPEEPAY",
            "name": "ShopeePay",
            "account_no": manual_depo['shopee_number'],
            "account_name": manual_depo.get('shopee_name', 'GarudaTel / Kasir'),
            "type": "ewallet"
        })

    return jsonify({
        "status": "success",
        "data": {
            "merchant_id": merchant.merchant_id,
            "username": user.phone if user else "",
            "balance": balance_val,
            "min_deposit": 10000,
            "wa_target": manual_depo.get('wa_target', '081775700114'),
            "instructions": manual_depo.get('instructions', ''),
            "channels": channels
        }
    }), 200


# =====================================================================
# 1.2 BUAT TIKET PERMINTAAN DEPOSIT POS (POST /api/v1/profile/deposit/create)
# =====================================================================
@merchant_api_bp.route("/profile/deposit/create", methods=["POST"])
def create_deposit_request():
    """
    Membuat tiket permintaan top-up deposit dari Web POS IPAY.
    Mencatat pesanan deposit ke database GarudaTel dan mengirim notifikasi Telegram ke Admin.
    """
    merchant, err = authenticate_merchant(request)
    if err:
        return jsonify({"status": "failed", "message": err[0]}), err[1]

    data = request.get_json(silent=True) or request.form.to_dict() or {}
    try:
        amount = float(data.get("amount") or 0)
    except (ValueError, TypeError):
        amount = 0.0

    if amount < 10000:
        return jsonify({
            "status": "failed",
            "message": "Minimal deposit adalah Rp 10.000"
        }), 400

    channel_code = str(data.get("channel") or data.get("payment_method") or "MANUAL").upper()
    notes = str(data.get("notes") or f"Deposit via Web POS IPAY ({merchant.merchant_id})").strip()

    import time
    import random
    ref_id = f"DEP-POS-{int(time.time())}-{random.randint(100, 999)}"

    user = merchant.user
    trx = Transaction(
        ref_id=ref_id,
        user_id=user.id,
        sku_code='DEPOSIT_SALDO',
        product_name=f"Deposit Saldo POS ({merchant.merchant_id})",
        target_number=user.phone or getattr(merchant, 'name', 'POS Merchant'),
        amount=amount,
        payment_method=channel_code,
        payment_status='UNPAID',
        status='PENDING',
        notes=notes,
        is_prepaid=True
    )
    db.session.add(trx)
    db.session.commit()

    # Kirim notifikasi Telegram ke admin jika aktif
    try:
        from app.services.telegram_service import async_send_trx_notification
        async_send_trx_notification(trx, title=f"TOPUP DEPOSIT POS ({merchant.merchant_id})")
    except Exception:
        pass

    from app.services.setting_service import get_manual_deposit_settings
    manual_depo = get_manual_deposit_settings()
    wa_num = manual_depo.get('wa_target', '081775700114')
    clean_wa = wa_num.replace('-', '').replace(' ', '')
    if clean_wa.startswith('0'):
        clean_wa = '62' + clean_wa[1:]

    wa_text = f"Halo Admin iPay, saya telah mengajukan deposit saldo POS via {channel_code} sebesar Rp {amount:,.0f} dengan No Ref: {ref_id} (Merchant: {merchant.merchant_id}). Mohon segera dikonfirmasi. Terima kasih."
    import urllib.parse
    wa_url = f"https://wa.me/{clean_wa}?text={urllib.parse.quote(wa_text)}"

    return jsonify({
        "status": "success",
        "data": {
            "ref_id": ref_id,
            "amount": amount,
            "channel": channel_code,
            "status": "pending",
            "wa_confirm_url": wa_url,
            "instructions": manual_depo.get('instructions', ''),
            "message": f"Tiket deposit {ref_id} berhasil dibuat. Silakan selesaikan pembayaran dan konfirmasi ke admin."
        }
    }), 200



# =====================================================================
# 2. INQUIRY TAGIHAN PASCABAYAR (POST /api/v1/transaction/inquiry)
# =====================================================================
@merchant_api_bp.route("/transaction/inquiry", methods=["POST"])
def inquiry_bill():
    """
    Cek nama pelanggan dan jumlah tagihan (PLN Pasca, PDAM, BPJS, dll).
    Kompatibel penuh dengan POS IPAY PPOBService.checkInquiry().
    """
    merchant, err = authenticate_merchant(request)
    if err:
        return jsonify({"status": "failed", "message": err[0]}), err[1]

    data = request.get_json(silent=True) or request.form.to_dict() or {}
    sku = str(data.get("buyer_sku_code") or data.get("sku") or "").strip()
    customer_no = str(data.get("customer_no") or data.get("target_number") or data.get("nomor") or "").strip()
    ref_id = str(data.get("ref_id") or "").strip()
    sign = str(data.get("sign") or data.get("signature") or "").strip()

    if not sku or not customer_no or not ref_id or not sign:
        return jsonify({
            "status": "failed",
            "message": "Parameter tidak lengkap. Wajib menyertakan buyer_sku_code, customer_no, ref_id, dan sign."
        }), 400

    # Validasi Signature: MD5(merchant_id + secret_key + ref_id)
    expected_str = f"{merchant.merchant_id}{merchant.secret_key}{ref_id}"
    if not verify_signature(merchant, sign, expected_str):
        return jsonify({"status": "failed", "message": "Signature tidak valid"}), 403

    # Cari produk pascabayar
    product = Product.query.filter_by(sku_code=sku).first()
    if not product:
        from app.services.pascabayar_service import get_or_create_pascabayar_product
        product = get_or_create_pascabayar_product(sku)
        if not product:
            return jsonify({"status": "failed", "message": f"Produk tagihan dengan SKU '{sku}' tidak ditemukan"}), 404

    # Cutoff PLN (23:30 - 01:00 WIB)
    is_pln = 'PLN' in (product.category or '').upper() or 'PLN' in (product.name or '').upper()
    from app.services.digiflazz import is_pln_cutoff_time, get_pln_cutoff_message
    if is_pln and is_pln_cutoff_time():
        return jsonify({
            "status": "failed",
            "message": get_pln_cutoff_message()
        }), 400

    # Eksekusi inquiry ke Digiflazz
    inq_func = inquiry_postpaid
    if not inq_func:
        from app.services.digiflazz import inquiry_pasca
        inq_func = inquiry_pasca

    inq_res = inq_func(sku, customer_no, ref_id)
    if isinstance(inq_res, tuple):
        ok = inq_res[0]
        res_data = inq_res[1] if len(inq_res) > 1 and isinstance(inq_res[1], dict) else {}
        msg = inq_res[2] if len(inq_res) > 2 else ''
    elif isinstance(inq_res, dict):
        res_data = inq_res.get('data', {}) if isinstance(inq_res.get('data'), dict) else inq_res
        msg = res_data.get('message', '')
        rc_val = str(res_data.get('rc') or '').strip()
        ok = rc_val == '00' or 'sukses' in str(res_data.get('status', '')).lower()
    else:
        ok = bool(inq_res)
        res_data = {}
        msg = ''

    if not ok or not res_data:
        return jsonify({
            "status": "failed",
            "message": msg or "Gagal mengecek tagihan ke provider"
        }), 400

    # Ekstrak data tagihan
    customer_name = res_data.get('customer_name') or '-'
    admin_fee = float(res_data.get('admin') or 0.0)
    price_val = float(res_data.get('price') or 0.0)
    tagihan_pokok = max(0.0, price_val - admin_fee) if price_val > admin_fee else price_val
    total_amount = price_val if price_val > 0 else (tagihan_pokok + admin_fee)

    desc = res_data.get('desc') or {}
    meter_no = desc.get('meter_no') or customer_no

    return jsonify({
        "status": "success",
        "customer_name": customer_name,
        "customer_no": customer_no,
        "meter_no": meter_no,
        "amount": tagihan_pokok,
        "admin": admin_fee,
        "total_amount": total_amount,
        "ref_id": ref_id,
        "message": msg or "Tagihan ditemukan"
    }), 200


# =====================================================================
# 3. EKSEKUSI PEMBELIAN (POST /api/v1/transaction/create)
# =====================================================================
@merchant_api_bp.route("/transaction/create", methods=["POST"])
def create_transaction():
    """
    Eksekusi transaksi pembelian pulsa/data/game/tagihan dengan:
    1. Idempotency Guard (anti-dobel transaksi).
    2. Atomic Lock & Saldo Pre-Check.
    3. Multi-Provider Router (Digiflazz / VIP-Reseller).
    4. Auto-Refund jika transaksi ditolak provider.
    5. Webhook Dispatch.
    """
    merchant, err = authenticate_merchant(request)
    if err:
        return jsonify({"status": "failed", "message": err[0]}), err[1]

    data = request.get_json(silent=True) or request.form.to_dict() or {}
    sku = str(data.get("buyer_sku_code") or data.get("sku") or "").strip()
    customer_no = str(data.get("customer_no") or data.get("target_number") or data.get("nomor") or "").strip()
    ref_id = str(data.get("ref_id") or "").strip()
    sign = str(data.get("sign") or data.get("signature") or "").strip()

    if not sku or not customer_no or not ref_id or not sign:
        return jsonify({
            "status": "failed",
            "message": "Parameter tidak lengkap. Wajib menyertakan buyer_sku_code, customer_no, ref_id, dan sign."
        }), 400

    # Validasi Signature: MD5(merchant_id + secret_key + ref_id)
    expected_str = f"{merchant.merchant_id}{merchant.secret_key}{ref_id}"
    if not verify_signature(merchant, sign, expected_str):
        return jsonify({"status": "failed", "message": "Signature tidak valid"}), 403

    # =================================================================
    # IDEMPOTENCY GUARD: Cek transaksi berulang dengan ref_id yang sama
    # =================================================================
    existing_trx = Transaction.query.filter_by(ref_id=ref_id).first()
    if existing_trx:
        stat = (existing_trx.status or 'PENDING').lower()
        return jsonify({
            "status": "success" if stat == "success" else stat,
            "data": {
                "ref_id": ref_id,
                "status": stat,
                "sn": existing_trx.sn or "",
                "buyer_sku_code": existing_trx.sku_code,
                "customer_no": existing_trx.target_number,
                "price": float(existing_trx.amount or 0.0),
                "message": "Transaksi sebelumnya telah terdaftar"
            },
            "message": "Transaksi sebelumnya telah terdaftar"
        }), 200

    # =================================================================
    # VALIDASI PRODUK & HITUNG HARGA SESUAI TIER MERCHANT
    # =================================================================
    product = Product.query.filter_by(sku_code=sku).first()
    if not product:
        from app.services.pascabayar_service import get_or_create_pascabayar_product
        product = get_or_create_pascabayar_product(sku)
        if not product:
            return jsonify({"status": "failed", "message": f"Produk SKU '{sku}' tidak ditemukan"}), 404

    if not product.is_active:
        return jsonify({"status": "failed", "message": f"Produk '{product.name}' sedang gangguan atau nonaktif"}), 400

    # Harga jual dinamis sesuai level akun pemilik merchant (Member / Reseller / VIP)
    user = merchant.user
    price_to_deduct = float(get_user_product_price(user, product))

    # =================================================================
    # ATOMIC BALANCE CHECK & LOCK (Anti-Double Spending)
    # =================================================================
    user_locked = db.session.query(User).filter_by(id=user.id).with_for_update().first()
    if not user_locked:
        db.session.rollback()
        return jsonify({"status": "failed", "message": "Pengguna tidak ditemukan"}), 404

    current_bal = float(user_locked.balance or 0.0)
    if current_bal < price_to_deduct:
        db.session.rollback()
        return jsonify({
            "status": "failed",
            "message": f"Saldo deposit akun iPay tidak mencukupi! Sisa: Rp {current_bal:,.0f}, Diperlukan: Rp {price_to_deduct:,.0f}"
        }), 400

    # Potong saldo user
    user_locked.balance = current_bal - price_to_deduct

    # Buat record transaksi status PENDING
    is_pasca = 'PASCABAYAR' in (product.category or '').upper() or 'PASCA' in (product.name or '').upper()
    is_prepaid = not is_pasca
    trx = Transaction(
        user_id=user_locked.id,
        ref_id=ref_id,
        product_name=product.name,
        sku_code=sku,
        target_number=customer_no,
        amount=price_to_deduct,
        payment_method='API_GATEWAY',
        payment_status='PAID',
        status='PENDING',
        is_prepaid=is_prepaid
    )
    db.session.add(trx)
    db.session.commit()

    # =================================================================
    # FORWARD TRANSAKSI KE PROVIDER (Digiflazz / VIP-Reseller)
    # =================================================================
    is_vip_provider = getattr(product, 'provider', '') == 'vip'
    res_status = 'pending'
    res_sn = ''
    res_msg = ''

    try:
        if is_vip_provider:
            # VIP-Reseller Provider (Layanan Game)
            from app.services.vip_reseller import VIPReseller
            vip = VIPReseller()
            vip_res = vip.order(sku, customer_no, ref_id)
            if vip_res.get('result'):
                v_data = vip_res.get('data', {})
                v_stat = (v_data.get('status') or '').lower()
                res_sn = v_data.get('sn') or ''
                res_msg = vip_res.get('message') or ''
                if v_stat in ['success', 'sukses']:
                    res_status = 'success'
                elif v_stat in ['waiting', 'pending', 'processing']:
                    res_status = 'pending'
                else:
                    res_status = 'failed'
            else:
                res_status = 'failed'
                res_msg = vip_res.get('message', 'Ditolak VIP-Reseller')

        elif not is_prepaid:
            # Pascabayar Digiflazz
            p_func = pay_postpaid
            if not p_func:
                from app.services.digiflazz import pay_pasca
                p_func = pay_pasca

            p_call = p_func(sku, customer_no, ref_id)
            if isinstance(p_call, tuple):
                ok = p_call[0]
                p_data = p_call[1] if len(p_call) > 1 and isinstance(p_call[1], dict) else {}
                p_msg = p_call[2] if len(p_call) > 2 else ''
            elif isinstance(p_call, dict):
                p_data = p_call.get('data', {}) if isinstance(p_call.get('data'), dict) else p_call
                p_msg = p_data.get('message', '')
                rc_val = str(p_data.get('rc') or '').strip()
                st_val = str(p_data.get('status') or '').lower()
                ok = (rc_val == '00' or 'sukses' in st_val or 'success' in st_val)
            else:
                ok = bool(p_call)
                p_data = {}
                p_msg = ''

            res_msg = p_msg
            if ok:
                res_status = 'success'
                res_sn = p_data.get('sn') or ''
            else:
                res_status = 'failed'

        else:
            # Prabayar Digiflazz
            s_func = submit_transaction
            if not s_func:
                from app.services.digiflazz import create_transaction
                s_func = create_transaction

            res_call = s_func(sku, customer_no, ref_id, testing=False)
            if isinstance(res_call, tuple):
                ok = res_call[0]
                d_data = res_call[1] if len(res_call) > 1 and isinstance(res_call[1], dict) else {}
                d_msg = res_call[2] if len(res_call) > 2 else (d_data.get('message', '') if d_data else '')
            elif isinstance(res_call, dict):
                d_data = res_call.get('data', {}) if isinstance(res_call.get('data'), dict) else res_call
                d_msg = d_data.get('message', '')
                rc_raw = str(d_data.get('rc') or '').strip()
                st_raw = str(d_data.get('status') or '').lower()
                ok = (rc_raw == '00' or 'sukses' in st_raw or 'success' in st_raw or rc_raw == '03' or 'pending' in st_raw)
            else:
                ok = bool(res_call)
                d_data = {}
                d_msg = str(res_call)

            res_msg = d_msg
            rc = str(d_data.get('rc') or '').strip() if d_data else ''
            d_stat = str(d_data.get('status') or '').lower() if d_data else ''
            # Tangkap SN atau keterangan dari provider (penting untuk cek kuota / token)
            res_sn = (d_data.get('sn') or '') if d_data else ''
            if not res_sn and d_data:
                res_sn = d_data.get('message') or ''

            if rc == '00' or 'sukses' in d_stat or 'success' in d_stat:
                res_status = 'success'
            elif rc == '03' or 'pending' in d_stat or 'menunggu' in d_stat or 'processing' in d_stat:
                res_status = 'pending'
            else:
                res_status = 'failed'

    except Exception as ex_provider:
        logger.error(f"[MERCHANT_API] Exception calling provider for ref_id {ref_id}: {ex_provider}")
        res_status = 'failed'
        res_msg = str(ex_provider)

    # =================================================================
    # UPDATE STATUS AKHIR & AUTO-REFUND JIKA GAGAL
    # =================================================================
    if res_status == 'success':
        trx.status = 'SUCCESS'
        trx.sn = res_sn
        db.session.commit()

        # Berikan komisi downline ke upline VIP jika berlaku
        try:
            award_downline_commission(trx)
        except Exception:
            pass

        dispatch_merchant_webhook(merchant, {
            "ref_id": ref_id,
            "status": "success",
            "sn": res_sn,
            "sku_code": sku,
            "price": price_to_deduct
        })

        return jsonify({
            "status": "success",
            "data": {
                "ref_id": ref_id,
                "status": "success",
                "sn": res_sn,
                "buyer_sku_code": sku,
                "customer_no": customer_no,
                "price": price_to_deduct,
                "message": res_msg or "Transaksi Berhasil"
            },
            "message": res_msg or "Transaksi Berhasil"
        }), 200

    elif res_status == 'pending':
        trx.status = 'PENDING'
        trx.sn = res_sn
        db.session.commit()

        return jsonify({
            "status": "pending",
            "data": {
                "ref_id": ref_id,
                "status": "pending",
                "sn": res_sn,
                "buyer_sku_code": sku,
                "customer_no": customer_no,
                "price": price_to_deduct,
                "message": res_msg or "Transaksi sedang diproses provider"
            },
            "message": res_msg or "Transaksi sedang diproses provider"
        }), 200

    else:
        # Transaksi Gagal: Kembalikan saldo pengguna (Auto-Refund)
        try:
            u_refund = db.session.query(User).filter_by(id=user.id).with_for_update().first()
            if u_refund:
                u_refund.balance = float(u_refund.balance or 0.0) + price_to_deduct
            trx.status = 'FAILED'
            trx.sn = ''
            trx.notes = f"Gagal: {res_msg} (Saldo di-refund otomatis)"
            db.session.commit()
            logger.info(f"[MERCHANT_API] Trx {ref_id} gagal, saldo Rp {price_to_deduct} berhasil di-refund ke user #{user.id}")
        except Exception as ex_refund:
            db.session.rollback()
            logger.error(f"[MERCHANT_API] Gagal refund saldo untuk trx {ref_id}: {ex_refund}")

        dispatch_merchant_webhook(merchant, {
            "ref_id": ref_id,
            "status": "failed",
            "sn": "",
            "sku_code": sku,
            "price": price_to_deduct
        })

        return jsonify({
            "status": "failed",
            "data": {
                "ref_id": ref_id,
                "status": "failed",
                "sn": "",
                "buyer_sku_code": sku,
                "customer_no": customer_no,
                "price": price_to_deduct,
                "message": res_msg or "Transaksi ditolak provider, saldo dikembalikan otomatis"
            },
            "message": res_msg or "Transaksi ditolak provider, saldo dikembalikan otomatis"
        }), 400


# =====================================================================
# 4. CEK STATUS TRANSAKSI TERTENTU (GET & POST)
# =====================================================================
@merchant_api_bp.route("/transaction/status", methods=["POST"])
@merchant_api_bp.route("/transaction/status/<ref_id>", methods=["GET"])
def check_transaction_status(ref_id=None):
    """
    Mengecek status riwayat transaksi berdasarkan ref_id.
    """
    merchant, err = authenticate_merchant(request)
    if err:
        return jsonify({"status": "failed", "message": err[0]}), err[1]

    if not ref_id and request.method == "POST":
        data = request.get_json(silent=True) or request.form.to_dict() or {}
        ref_id = data.get("ref_id")

    if not ref_id:
        return jsonify({"status": "failed", "message": "ref_id diperlukan"}), 400

    trx = Transaction.query.filter_by(ref_id=ref_id, user_id=merchant.user_id).first()
    if not trx:
        return jsonify({"status": "failed", "message": f"Transaksi ref_id '{ref_id}' tidak ditemukan"}), 404

    stat = (trx.status or 'PENDING').lower()
    return jsonify({
        "status": "success",
        "data": {
            "ref_id": trx.ref_id,
            "status": stat,
            "sn": trx.sn or "",
            "buyer_sku_code": trx.sku_code,
            "customer_no": trx.target_number,
            "price": float(trx.amount or 0.0),
            "created_at": trx.created_at.strftime('%Y-%m-%d %H:%M:%S') if trx.created_at else ""
        }
    }), 200


# =====================================================================
# 5. SINKRONISASI KATALOG PRODUK (GET /api/v1/products)
# =====================================================================
@merchant_api_bp.route("/products", methods=["GET"])
def list_products():
    """
    Mengambil katalog produk aktif beserta harga jual sesuai tier akun merchant.
    """
    merchant, err = authenticate_merchant(request)
    if err:
        return jsonify({"status": "failed", "message": err[0]}), err[1]

    category = request.args.get("category")
    brand = request.args.get("brand")
    p_type = request.args.get("type")

    query = Product.query.filter_by(is_active=True)
    if category:
        query = query.filter(Product.category.ilike(f"%{category}%"))
    if brand:
        query = query.filter(Product.brand.ilike(f"%{brand}%"))

    products = query.order_by(Product.brand.asc(), Product.sell_price.asc()).all()

    user = merchant.user
    product_list = []
    for p in products:
        is_pasca = 'PASCABAYAR' in (p.category or '').upper() or 'PASCA' in (p.name or '').upper()
        prod_type = "postpaid" if is_pasca else "prepaid"
        if p_type and prod_type != p_type.lower().strip():
            continue

        dyn_price = float(get_user_product_price(user, p))
        product_list.append({
            "sku": p.sku_code,
            "name": p.name,
            "category": p.category,
            "brand": p.brand,
            "type": prod_type,
            "base_price": float(p.base_price or 0.0),
            "price": dyn_price,
            "is_active": bool(p.is_active)
        })

    return jsonify({
        "status": "success",
        "total": len(product_list),
        "data": product_list
    }), 200
