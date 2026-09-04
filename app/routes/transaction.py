from flask import Blueprint, request, jsonify, render_template, redirect, url_for, g
from flask_login import login_required, current_user
from app.extensions import db, csrf, limiter
from app.models.transaction import Transaction
from app.models.product import Product
from app.models.user import User
import time
import random
import os
import hashlib
import requests
import hmac

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

trx_bp = Blueprint('trx_bp', __name__)  # Prefix akan diatur di __init__.py

@trx_bp.route('/checkout', methods=['POST'])
@csrf.exempt
@limiter.limit("20 per minute")
def checkout():
    # 1. CUSTOM AUTH CHECK - Return JSON 401 instead of redirect
    if not current_user.is_authenticated:
        return jsonify({
            'status': 'error',
            'error': True,
            'message': 'Anda harus login terlebih dahulu',
            'requires_login': True
        }), 401

    try:
        # 2. PARSE REQUEST DATA (JSON ATAU FORM)
        req_data = request.get_json(silent=True) or request.form.to_dict() or {}
        
        sku_input = str(req_data.get('sku_code') or req_data.get('sku') or '').strip()
        target_number = str(req_data.get('target_number') or req_data.get('tujuan') or req_data.get('nomor') or '').strip()
        payment_method = str(req_data.get('payment_method') or req_data.get('metode') or 'saldo').lower().strip()
        amt_raw = req_data.get('amount') or req_data.get('nominal') or 0

        if not sku_input or not target_number:
            return jsonify({'status': 'error', 'error': True, 'message': 'Data SKU atau Nomor Tujuan tidak lengkap'}), 400

        # 3. IDENTIFIKASI PRODUK & PROVIDER
        is_bebas_nominal = False
        is_vip = False
        is_prepaid_flow = True
        product_name = ""
        sku_code = sku_input
        amount = 0.0

        sku_upper = sku_input.upper()

        # Peta Layanan Bebas Nominal
        bebas_sku_map = {
            'DANA': 'post685481',
            'GOPAY': 'post685480',
            'SHOPEEPAY': 'post685482',
            'OVO': 'post685483',
            'LINKAJA': 'post706873'
        }

        bebas_brand_match = None
        for b_name in bebas_sku_map.keys():
            if b_name in sku_upper:
                bebas_brand_match = b_name
                break

        if 'BEBAS' in sku_upper or 'EMONEY' in sku_upper or bebas_brand_match:
            is_bebas_nominal = True
            try:
                amount = float(amt_raw)
            except (ValueError, TypeError):
                return jsonify({'status': 'error', 'error': True, 'message': 'Nominal bebas nominal tidak valid.'}), 400

            if amount <= 0:
                return jsonify({'status': 'error', 'error': True, 'message': 'Nominal harus lebih besar dari Rp 0.'}), 400

            brand_clean = bebas_brand_match or 'DANA'
            sku_code = bebas_sku_map.get(brand_clean, 'post685481')
            product_name = f"{brand_clean} Bebas Rp {int(amount):,}"
            is_prepaid_flow = False

        else:
            # Cari produk di katalog database
            product = Product.query.filter_by(sku_code=sku_input).first()
            if not product:
                return jsonify({'status': 'error', 'error': True, 'message': 'Produk tidak ditemukan'}), 404
            if not product.is_active:
                return jsonify({'status': 'error', 'error': True, 'message': 'Produk sedang gangguan atau nonaktif'}), 400

            amount = float(product.sell_price)
            product_name = product.name
            sku_code = product.sku_code

            # Deteksi VIP Reseller
            if str(product.brand).startswith('VIP-') or sku_upper.startswith('VIP-'):
                is_vip = True

            cat_lower = (product.category or '').lower()
            name_lower = (product.name or '').lower()
            if 'pascabayar' in cat_lower or 'tagihan' in cat_lower:
                is_prepaid_flow = False

        # 4. GENERATE REF_ID
        if is_vip:
            ref_id = f"VIP-{int(time.time()*1000)}{random.randint(10,99)}"
        else:
            ref_id = f"GT-{int(time.time()*1000)}{random.randint(10,99)}"

        # 5. METODE PEMBAYARAN: QRIS
        if payment_method == 'qris':
            new_trx = Transaction(
                user_id=current_user.id,
                ref_id=ref_id,
                product_name=product_name,
                sku_code=sku_code,
                target_number=target_number,
                amount=amount,
                payment_method='QRIS',
                payment_status='UNPAID',
                status='UNPAID',
                is_prepaid=is_prepaid_flow
            )
            db.session.add(new_trx)
            db.session.commit()
            from app.services.telegram_service import async_send_trx_notification
            async_send_trx_notification(new_trx, title="TRANSAKSI BARU (QRIS UNPAID)")
            return jsonify({
                'status': 'success',
                'message': 'QRIS berhasil dibuat',
                'ref_id': ref_id,
                'redirect': f'/trx/invoice/{ref_id}'
            }), 200

        # 6. METODE PEMBAYARAN: SALDO
        elif payment_method == 'saldo':
            # Row locking untuk proteksi race condition / double spending
            user_locked = db.session.query(User).filter_by(id=current_user.id).with_for_update().first()

            if user_locked.balance < amount:
                db.session.rollback()
                return jsonify({
                    'status': 'error',
                    'error': True,
                    'success': False,
                    'message': 'Saldo tidak mencukupi.',
                    'insufficient_balance': True,
                    'required_amount': amount,
                    'current_balance': user_locked.balance,
                    'suggest_qris': True
                }), 200

            # Potong saldo secara atomic
            user_locked.balance -= amount

            # Catat transaksi dengan status PROCESSING
            new_trx = Transaction(
                user_id=current_user.id,
                ref_id=ref_id,
                product_name=product_name,
                sku_code=sku_code,
                target_number=target_number,
                amount=amount,
                payment_method='SALDO',
                payment_status='PAID',
                status='PROCESSING',
                is_prepaid=is_prepaid_flow
            )
            db.session.add(new_trx)
            db.session.commit()

            # EKSEKUSI KE PROVIDER SESUAI TIPE PRODUK:
            # A. VIP RESELLER (GAMES / VOUCHER)
            if is_vip:
                from app.services.vip_reseller import VIPReseller
                vip = VIPReseller()
                order_res = vip.create_order(sku_code, target_number)
                if order_res.get('result'):
                    vip_data = order_res.get('data', {})
                    if vip_data.get('trxid'):
                        new_trx.provider_ref = vip_data.get('trxid')
                    new_trx.status = 'PROCESSING'
                    db.session.commit()
                    from app.services.telegram_service import async_send_trx_notification
                    async_send_trx_notification(new_trx, title="TRANSAKSI DIPROSES (VIP)")
                    return jsonify({
                        'status': 'success', 'success': True, 'error': False,
                        'message': 'Pesanan diproses VIP-Reseller!', 'redirect': '/riwayat'
                    }), 200
                else:
                    # Gagal di VIP -> Refund saldo user
                    user_locked.balance += amount
                    new_trx.status = 'FAILED'
                    new_trx.sn = str(order_res.get('message', 'Ditolak API VIP'))
                    db.session.commit()
                    from app.services.telegram_service import async_send_trx_notification
                    async_send_trx_notification(new_trx, title="TRANSAKSI GAGAL (VIP)")
                    return jsonify({
                        'status': 'error', 'error': True, 'success': False,
                        'message': 'Gagal (VIP): ' + str(order_res.get('message', 'Error API'))
                    }), 200

            # B. BEBAS NOMINAL DIGIFLAZZ (INQUIRY + PAYMENT)
            elif is_bebas_nominal:
                username = os.getenv('DIGI_USER', '').strip()
                key = os.getenv('DIGI_KEY', '').strip()
                url = os.getenv('DIGI_URL', 'https://api.digiflazz.com/v1').strip() + '/transaction'
                sign = hashlib.md5(f"{username}{key}{ref_id}".encode()).hexdigest()

                payload_inq = {
                    "commands": "inq-pasca", "username": username, "buyer_sku_code": sku_code,
                    "customer_no": target_number, "ref_id": ref_id, "sign": sign, "amount": int(amount)
                }
                try:
                    res_inq = requests.post(url, json=payload_inq, timeout=15)
                    res_inq_json = res_inq.json() if res_inq.status_code == 200 else {}
                    rc_inq = res_inq_json.get('data', {}).get('rc')

                    if rc_inq == '00':
                        payload_pay = payload_inq.copy()
                        payload_pay['commands'] = 'pay-pasca'
                        res_pay = requests.post(url, json=payload_pay, timeout=15)
                        res_pay_json = res_pay.json() if res_pay.status_code == 200 else {}
                        if res_pay_json.get('data', {}).get('rc') == '00':
                            new_trx.status = 'SUCCESS'
                            new_trx.sn = res_pay_json.get('data', {}).get('sn', '')
                            db.session.commit()
                            from app.services.telegram_service import async_send_trx_notification
                            async_send_trx_notification(new_trx, title="TRANSAKSI BERHASIL (PASCA)")
                            return jsonify({'status': 'success', 'success': True, 'error': False, 'message': 'Transaksi sukses masuk Digiflazz!', 'redirect': '/riwayat'}), 200
                        else:
                            msg = res_pay_json.get('data', {}).get('message', 'Gagal bayar tagihan')
                            user_locked.balance += amount
                            new_trx.status = 'FAILED'
                            new_trx.sn = msg
                            db.session.commit()
                            from app.services.telegram_service import async_send_trx_notification
                            async_send_trx_notification(new_trx, title="TRANSAKSI GAGAL (PASCA)")
                            return jsonify({'status': 'error', 'error': True, 'success': False, 'message': 'Gagal (Pay): ' + msg}), 200
                    else:
                        msg = res_inq_json.get('data', {}).get('message', 'Tagihan tidak ditemukan')
                        user_locked.balance += amount
                        new_trx.status = 'FAILED'
                        new_trx.sn = msg
                        db.session.commit()
                        from app.services.telegram_service import async_send_trx_notification
                        async_send_trx_notification(new_trx, title="TRANSAKSI GAGAL (PASCA)")
                        return jsonify({'status': 'error', 'error': True, 'success': False, 'message': 'Gagal (Inq): ' + msg}), 200
                except Exception as api_e:
                    new_trx.status = 'PROCESSING'
                    new_trx.sn = 'Antrean diproses server'
                    db.session.commit()
                    from app.services.telegram_service import async_send_trx_notification
                    async_send_trx_notification(new_trx, title="TRANSAKSI DIPROSES (PASCA)")
                    return jsonify({'status': 'success', 'message': 'Transaksi dalam antrean diproses.', 'redirect': '/riwayat'}), 200

            # C. REGULER DIGIFLAZZ (PREPAID / PASCA)
            else:
                from app.services.digiflazz import create_transaction
                try:
                    digi_response = create_transaction(sku_code, target_number, ref_id)
                    if digi_response and 'data' in digi_response:
                        digi_data = digi_response['data']
                        digi_status = str(digi_data.get('status', '')).lower()
                        if 'sukses' in digi_status or 'success' in digi_status:
                            new_trx.status = 'SUCCESS'
                            new_trx.sn = digi_data.get('sn', '')
                        elif 'gagal' in digi_status or 'failed' in digi_status:
                            new_trx.status = 'FAILED'
                            user_locked.balance += amount  # Auto refund jika langsung gagal
                            new_trx.sn = digi_data.get('message', 'Gagal dari provider')
                        else:
                            new_trx.status = 'PROCESSING'
                        db.session.commit()
                    else:
                        new_trx.status = 'PROCESSING'
                        db.session.commit()
                except Exception as digi_err:
                    new_trx.status = 'PROCESSING'
                    db.session.commit()

                from app.services.telegram_service import async_send_trx_notification
                async_send_trx_notification(new_trx, title=f"TRANSAKSI {new_trx.status} (SALDO)")
                return jsonify({
                    'status': 'success',
                    'message': 'Pesanan berhasil dibuat',
                    'ref_id': ref_id,
                    'redirect': '/riwayat'
                }), 200

        else:
            return jsonify({'status': 'error', 'message': 'Metode pembayaran tidak didukung'}), 400

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': f'Sistem Error: {str(e)}'}), 500

@trx_bp.route('/invoice/<ref_id>')
@login_required
def invoice(ref_id):
    trx = Transaction.query.filter_by(ref_id=ref_id, user_id=current_user.id).first()
    if not trx:
        return "Transaksi tidak ditemukan", 404
        
    return render_template('user/invoice.html', trx=trx)

@trx_bp.route('/generate_qris/<ref_id>', methods=['GET'])
@login_required
def generate_qris(ref_id):
    trx = Transaction.query.filter_by(ref_id=ref_id, user_id=current_user.id).first()
    if not trx:
        return jsonify({'status': 'error', 'message': 'Transaksi tidak ditemukan'}), 404

    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
    
    active_pg = os.getenv('ACTIVE_PAYMENT_GATEWAY', 'paymentkita').lower().strip()
    
    # 1. JIKA PAYMENT GATEWAY AKTIF ADALAH PAKASIR
    if active_pg == 'pakasir':
        from app.services.pakasir_service import PakasirService
        pakasir = PakasirService()
        res_pakasir = pakasir.create_qris(trx.ref_id, trx.amount)
        if res_pakasir.get('status'):
            return jsonify({
                'status': 'success',
                'gateway': 'pakasir',
                'qr_url': res_pakasir.get('qr_url'),
                'qr_string': res_pakasir.get('qr_string'),
                'expired_at': res_pakasir.get('expired_at')
            })
        else:
            err = res_pakasir.get('error') or 'Ditolak oleh Server Pakasir'
            return jsonify({'status': 'error', 'message': f"[PAKASIR] {err}"}), 400

    # 2. DEFAULT: PAYMENTKITA
    from app.services.paymentkita_service import PaymentKitaService
    pk_config = {
        'merchant_id': os.getenv('PAYMENTKITA_MERCHANT_ID', ''),
        'secret': os.getenv('PAYMENTKITA_SECRET', '')
    }
    
    try:
        pk_service = PaymentKitaService(pk_config)
        nominal_int = int(float(trx.amount))
        res_pk = pk_service.create_order(trx.ref_id, nominal_int, "QRIS")
        
        if res_pk and isinstance(res_pk, dict):
            if res_pk.get('data'):
                data_pk = res_pk.get('data', {})
                qr_url = data_pk.get('qr_link') or data_pk.get('pay_url') or data_pk.get('qr_url')
                qr_string = data_pk.get('qr_string') or data_pk.get('qris_string')
                
                if qr_url or qr_string:
                    return jsonify({
                        'status': 'success',
                        'gateway': 'paymentkita',
                        'qr_url': qr_url,
                        'qr_string': qr_string
                    })
            
            # Tampilkan pesan error ASLI dari server jika gagal
            err = res_pk.get('error_msg') or res_pk.get('message') or 'Ditolak oleh Server Pusat'
            return jsonify({'status': 'error', 'message': f"[ERROR API] {err}"}), 400
            
        return jsonify({'status': 'error', 'message': 'Respon API kosong atau tidak valid.'}), 500
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': f"[KORSLETING] {str(e)}"}), 500

@trx_bp.route('/cancel/<ref_id>', methods=['POST'])
@login_required
def cancel_trx(ref_id):
    trx = Transaction.query.filter_by(ref_id=ref_id, user_id=current_user.id).first()
    if trx and trx.payment_status == 'UNPAID':
        trx.status = 'CANCELLED'
        trx.payment_status = 'CANCELLED'
        db.session.commit()
        from app.services.telegram_service import async_send_trx_notification
        async_send_trx_notification(trx, title="TRANSAKSI DIBATALKAN")
        return jsonify({'status': 'success', 'message': 'Transaksi dibatalkan'})
    return jsonify({'status': 'error', 'message': 'Gagal membatalkan transaksi'})

@trx_bp.route('/check_status/<ref_id>', methods=['GET'])
@login_required
def check_status(ref_id):
    trx = Transaction.query.filter_by(ref_id=ref_id, user_id=current_user.id).first()
    if not trx:
        return jsonify({'status': 'error', 'message': 'Not found'}), 404

    if trx.payment_status == 'PAID':
        return jsonify({'status': 'success', 'payment_status': 'PAID'})

    try:
        from app.services.paymentkita_service import PaymentKitaService
        from app.services.digiflazz import create_transaction
        
        pk_config = {'merchant_id': os.getenv('PAYMENTKITA_MERCHANT_ID', ''), 'secret': os.getenv('PAYMENTKITA_SECRET', '')}
        pk_service = PaymentKitaService(pk_config)
        res = pk_service.check_order(trx.ref_id)
        
        # --- DETEKSI STATUS EKSAK (ANTI-ERROR) ---
        is_paid = False
        res_str = str(res).upper()
        # Mencari secara persis pasangan key-value status Lunas
        if "'STATUS': 'PAID'" in res_str or '"STATUS": "PAID"' in res_str or "'STATUS': 'SUCCESS'" in res_str or '"STATUS": "SUCCESS"' in res_str or "'STATUS': 'SETTLEMENT'" in res_str:
            is_paid = True
            
        if is_paid:
            trx.payment_status = 'PAID'
            db.session.commit()
            
            # --- ALUR KHUSUS DEPOSIT SALDO ---
            if trx.sku_code == 'DEPOSIT_SALDO':
                user = User.query.get(trx.user_id)
                if user and trx.status != 'SUCCESS':
                    user.balance += trx.amount
                    trx.status = 'SUCCESS'
                    db.session.commit()
                return jsonify({'status': 'success', 'payment_status': 'PAID'})
                
            # --- PELATUK DIGIFLAZZ ---
            product = Product.query.filter_by(name=trx.product_name).first()
            if product:
                digi_res = create_transaction(product.sku_code, trx.target_number, trx.ref_id)
                digi_status = digi_res.get('data', {}).get('status', '').lower()
                
                if 'sukses' in digi_status or 'success' in digi_status:
                    trx.status = 'SUCCESS'
                elif 'gagal' in digi_status or 'failed' in digi_status:
                    trx.status = 'FAILED'
                else:
                    trx.status = 'PROCESSING'
                    
                trx.note = digi_res.get('data', {}).get('message', 'Sedang diproses server Digiflazz')
            else:
                trx.status = 'FAILED'
                trx.note = 'Produk tidak ditemukan di database'
                
            db.session.commit()
            return jsonify({'status': 'success', 'payment_status': 'PAID'})
            
    except Exception as e:
        pass

    return jsonify({'status': 'success', 'payment_status': trx.payment_status})

@trx_bp.route('/detail/<ref_id>', methods=['GET'])
@login_required
def trx_detail(ref_id):
    trx = Transaction.query.filter_by(ref_id=ref_id, user_id=current_user.id).first()
    if not trx:
        return jsonify({'status': 'error', 'message': 'Transaksi tidak ditemukan'}), 404
        
    # Tambahkan kata 'PROSES' ke dalam kamus pengecekan
    if trx.status in ['PROCESSING', 'PENDING', 'PROSES']:
        try:
            # Jika ID berawalan VP (ID Resmi VIP) atau VIP
            if str(trx.ref_id).startswith('VP') or str(trx.ref_id).startswith('VIP'):
                from app.services.vip_reseller import VIPReseller
                vip = VIPReseller()
                res = vip.check_status(trx.ref_id)
                if res and res.get('result'):
                    v_data = res.get('data', {})
                    if isinstance(v_data, list) and len(v_data) > 0:
                        v_data = v_data[0]
                        
                    v_status = str(v_data.get('status', '')).lower()
                    if v_status in ['success', 'sukses']:
                        trx.status = 'SUCCESS'
                        trx.sn = v_data.get('sn', 'SN tidak tersedia')
                    elif v_status in ['error', 'failed', 'gagal']:
                        trx.status = 'FAILED'
                        trx.sn = v_data.get('note', 'Gagal di server VIP')
                    db.session.commit()
            else:
                # Alur Digiflazz Lama
                from app.services.digiflazz import create_transaction
                product = Product.query.filter_by(name=trx.product_name).first()
                if product:
                    res = create_transaction(product.sku_code, trx.target_number, trx.ref_id)
                    data = res.get('data', {})
                    d_status = data.get('status', '').lower()
                    if 'sukses' in d_status or 'success' in d_status:
                        trx.status = 'SUCCESS'
                        trx.sn = data.get('sn', '')
                    elif 'gagal' in d_status or 'failed' in d_status:
                        trx.status = 'FAILED'
                        trx.sn = data.get('sn', '')
                    db.session.commit()
        except Exception as e:
            print("[ERROR CEK STATUS]:", e)
            pass 
            
    return jsonify({
        'status': 'success',
        'trx_status': trx.status,
        'product_name': trx.product_name,
        'target': trx.target_number,
        'sn': trx.sn or getattr(trx, 'note', '') or 'Sedang diproses server...',
        'date': trx.created_at.strftime('%d-%m-%Y %H:%M') if trx.created_at else ''
    })

@trx_bp.route('/topup_deposit', methods=['POST'])
@csrf.exempt
@login_required
def topup_deposit():
    data = request.get_json()
    amount = data.get('amount')
    
    if not amount or int(amount) < 10000:
        return jsonify({'status': 'error', 'message': 'Minimal pengisian saldo adalah Rp 10.000'}), 400

    ref_id = f"DEP-{int(time.time())}{random.randint(100, 999)}"
    
    # Mencatat pesanan virtual ke Database
    trx = Transaction(
        ref_id=ref_id,
        user_id=current_user.id,
        sku_code='DEPOSIT_SALDO',
        product_name='Deposit Saldo',
        target_number=getattr(current_user, 'phone', 'Akun Saya'),
        amount=int(amount),
        payment_method='qris',
        payment_status='UNPAID',
        status='UNPAID',
        is_prepaid=True
    )
    db.session.add(trx)
    db.session.commit()
    from app.services.telegram_service import async_send_trx_notification
    async_send_trx_notification(trx, title="TOPUP DEPOSIT QRIS DIBUAT")
    
    return jsonify({'status': 'success', 'ref_id': ref_id})


# =====================================================================
# WEBHOOK CALLBACKS - FASE 3: SECURITY & AUTOMATION
# =====================================================================

@trx_bp.route('/callback/digiflazz', methods=['POST'])
@csrf.exempt
def callback_digiflazz():
    """
    Webhook callback dari Digiflazz untuk update status transaksi otomatis.
    Dokumentasi: https://developer.digiflazz.com/api/buyer/webhook
    """
    try:
        # Parse request
        data = request.get_json() or request.form.to_dict()
        
        # Validasi signature untuk keamanan
        username = os.getenv('DIGI_USER', '').strip()
        key = os.getenv('DIGI_KEY', '').strip()
        
        # Digiflazz signature: MD5(username + api_key + ref_id)
        ref_id = data.get('ref_id') or data.get('trx_id')
        status = data.get('status', '').lower()
        
        if not ref_id:
            return jsonify({'status': 'error', 'message': 'Missing ref_id'}), 400
        
        # Generate expected signature
        expected_sign = hashlib.md5(f"{username}{key}{ref_id}".encode()).hexdigest()
        received_sign = data.get('sign') or data.get('signature', '')
        
        # Validasi signature (CRITICAL SECURITY)
        if received_sign != expected_sign:
            print(f"[SECURITY] Invalid Digiflazz signature for {ref_id}")
            return jsonify({'status': 'error', 'message': 'Invalid signature'}), 403
        
        # Cari transaksi
        trx = Transaction.query.filter_by(ref_id=ref_id).first()
        
        if not trx:
            return jsonify({'status': 'error', 'message': 'Transaction not found'}), 404
        
        # Idempotency check: jika status transaksi sudah SUCCESS, abaikan callback berulang
        if trx.status == 'SUCCESS':
            return jsonify({'status': 'success', 'message': 'Transaction already completed'}), 200

        # Update status berdasarkan callback
        old_status = trx.status
        
        if 'sukses' in status or 'success' in status:
            trx.status = 'SUCCESS'
            trx.sn = data.get('sn', '') or trx.sn
            award_transaction_points(trx.user_id, ref_id)
        elif 'gagal' in status or 'failed' in status or 'error' in status:
            # AUTO-REFUND hanya jika status sebelumnya belum FAILED (mencegah double refund)
            if old_status != 'FAILED' and trx.payment_status == 'PAID':
                user = User.query.filter_by(id=trx.user_id).with_for_update().first()
                if user:
                    user.balance += trx.amount
                    print(f"[REFUND] User {user.id} refunded Rp {trx.amount} for failed trx {ref_id}")
            trx.status = 'FAILED'
            if data.get('message'):
                trx.sn = data.get('message')
        elif 'pending' in status or 'process' in status:
            if trx.status != 'SUCCESS':
                trx.status = 'PROCESSING'
        
        # Simpan message dari Digiflazz
        if hasattr(trx, 'note'):
            trx.note = data.get('message', 'Updated via webhook')
        
        trx.updated_at = db.func.now()
        db.session.commit()
        
        print(f"[WEBHOOK DIGIFLAZZ] {ref_id}: {old_status} -> {trx.status}")
        from app.services.telegram_service import async_send_trx_notification
        async_send_trx_notification(trx, title=f"DIGIFLAZZ UPDATE: {trx.status}")
        
        return jsonify({'status': 'success', 'message': 'Callback processed'}), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"[ERROR WEBHOOK DIGIFLAZZ] {str(e)}")
        return jsonify({'status': 'error', 'message': 'Internal error'}), 500


def award_transaction_points(user_id, trx_ref_id):
    """Memberikan reward poin transaksi sukses kepada member secara idempoten."""
    try:
        from app.models.setting import Setting
        from app.models.point_log import PointLog
        from app.models.user import User

        if not user_id:
            return

        desc = f'Reward transaksi {trx_ref_id}'
        existing = PointLog.query.filter_by(user_id=user_id, type='EARN_TRX', description=desc).first()
        if existing:
            return

        st = Setting.query.filter_by(key='point_reward_per_trx').first()
        pts_reward = int(st.value) if st and st.value and st.value.isdigit() else 1
        if pts_reward <= 0:
            return

        user = User.query.get(user_id)
        if user:
            user.points = (user.points or 0) + pts_reward
            plog = PointLog(
                user_id=user.id,
                type='EARN_TRX',
                points=pts_reward,
                balance_added=0.0,
                description=desc
            )
            db.session.add(plog)
            db.session.commit()
            print(f"[POIN] Member {user.id} +{pts_reward} Pts for trx {trx_ref_id}")
    except Exception as err:
        db.session.rollback()
        print(f"[POIN ERROR] Error awarding points: {err}")


def process_paid_order(trx):
    """
    Menjalankan pemrosesan otomatis setelah transaksi berstatus PAID.
    Berlaku seragam dan idempoten untuk seluruh gateway pembayaran.
    """
    trx.payment_status = 'PAID'
    
    # 1. Jika ini transaksi deposit saldo
    if trx.sku_code in ['DEPOSIT_SALDO', 'DEPOSIT_MANUAL']:
        user = User.query.filter_by(id=trx.user_id).with_for_update().first()
        if user and trx.status != 'SUCCESS':
            user.balance += trx.amount
            trx.status = 'SUCCESS'
            print(f"[DEPOSIT] User {user.id} balance +Rp {trx.amount}")
            
    # 2. Jika transaksi produk reguler, trigger Digiflazz
    elif trx.status in ['UNPAID', 'PENDING', 'PROCESSING']:
        from app.services.digiflazz import create_transaction
        try:
            product = Product.query.filter_by(sku_code=trx.sku_code).first()
            if product:
                digi_res = create_transaction(product.sku_code, trx.target_number, trx.ref_id)
                digi_status = digi_res.get('data', {}).get('status', '').lower()
                
                if 'sukses' in digi_status or 'success' in digi_status:
                    trx.status = 'SUCCESS'
                    trx.sn = digi_res.get('data', {}).get('sn', '')
                    award_transaction_points(trx.user_id, trx.ref_id)
                else:
                    trx.status = 'PROCESSING'
        except Exception as e:
            print(f"[ERROR] Digiflazz trigger after payment: {str(e)}")
            trx.status = 'PENDING'

    trx.updated_at = db.func.now()
    db.session.commit()
    from app.services.telegram_service import async_send_trx_notification
    title_status = "PEMBAYARAN DITERIMA & SUKSES" if trx.status == 'SUCCESS' else "PEMBAYARAN DITERIMA (DIPROSES)"
    async_send_trx_notification(trx, title=title_status)


@trx_bp.route('/callback/paymentkita', methods=['POST'])
@csrf.exempt
def callback_paymentkita():
    """
    Webhook callback dari PaymentKita untuk update status pembayaran QRIS.
    Dokumentasi: Sesuaikan dengan docs PaymentKita
    """
    try:
        # Parse request
        data = request.get_json() or request.form.to_dict()
        
        # Validasi signature untuk keamanan
        merchant_id = os.getenv('PAYMENTKITA_MERCHANT_ID', '')
        secret = os.getenv('PAYMENTKITA_SECRET', '')
        
        ref_id = data.get('ref_id') or data.get('reference_id') or data.get('order_id')
        status = data.get('status', '').lower()
        
        if not ref_id:
            return jsonify({'status': 'error', 'message': 'Missing ref_id'}), 400
        
        # Generate expected signature (sesuaikan dengan dokumentasi PaymentKita)
        amount = str(data.get('amount', ''))
        signature_string = f"{merchant_id}{secret}{ref_id}{amount}{status}"
        expected_sign = hashlib.md5(signature_string.encode()).hexdigest()
        received_sign = data.get('signature') or data.get('sign', '')
        
        # Validasi signature (CRITICAL SECURITY)
        if received_sign and received_sign != expected_sign:
            print(f"[SECURITY] Invalid PaymentKita signature for {ref_id}")
            return jsonify({'status': 'error', 'message': 'Invalid signature'}), 403
        
        # Cari transaksi
        trx = Transaction.query.filter_by(ref_id=ref_id).first()
        
        if not trx:
            return jsonify({'status': 'error', 'message': 'Transaction not found'}), 404
        
        # Idempotency check: jika status pembayaran sudah PAID, abaikan webhook duplikat
        if trx.payment_status == 'PAID':
            return jsonify({'status': 'success', 'message': 'Payment already processed'}), 200

        # Update payment status berdasarkan callback
        old_payment_status = trx.payment_status
        
        if status in ['paid', 'success', 'settlement']:
            process_paid_order(trx)
        elif status in ['failed', 'expired', 'cancelled']:
            trx.payment_status = 'FAILED'
            trx.status = 'CANCELLED'
            trx.updated_at = db.func.now()
            db.session.commit()
        
        print(f"[WEBHOOK PAYMENTKITA] {ref_id}: {old_payment_status} -> {trx.payment_status}")
        return jsonify({'status': 'success', 'message': 'Callback processed'}), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"[ERROR WEBHOOK PAYMENTKITA] {str(e)}")
        return jsonify({'status': 'error', 'message': 'Internal error'}), 500


@trx_bp.route('/callback/pakasir', methods=['POST'])
@csrf.exempt
def callback_pakasir():
    """
    Webhook callback dari Pakasir untuk update status pembayaran QRIS otomatis.
    Dokumentasi resmi: https://app.pakasir.com
    Payload: { amount, order_id, project, status, payment_method, completed_at }
    """
    try:
        data = request.get_json(silent=True) or request.form.to_dict()
        if not data:
            return jsonify({'status': 'error', 'message': 'Payload kosong'}), 400

        project = str(data.get('project', '')).strip()
        ref_id = str(data.get('order_id', '')).strip()
        status = str(data.get('status', '')).lower().strip()

        if not ref_id:
            return jsonify({'status': 'error', 'message': 'Missing order_id'}), 400

        # Validasi keamanan project slug jika diatur di .env
        expected_project = os.getenv('PAKASIR_PROJECT', '').strip()
        if expected_project and project and project != expected_project:
            print(f"[SECURITY] Invalid Pakasir project slug: {project} (expected {expected_project})")
            return jsonify({'status': 'error', 'message': 'Invalid project'}), 403

        # Cari transaksi
        trx = Transaction.query.filter_by(ref_id=ref_id).first()
        if not trx:
            return jsonify({'status': 'error', 'message': 'Transaction not found'}), 404

        # Idempotency check: jika status pembayaran sudah PAID, respons 200 langsung
        if trx.payment_status == 'PAID':
            return jsonify({'status': 'success', 'message': 'Payment already processed'}), 200

        old_payment_status = trx.payment_status

        if status in ['completed', 'success', 'paid', 'settlement']:
            process_paid_order(trx)
            print(f"[WEBHOOK PAKASIR] {ref_id}: {old_payment_status} -> PAID")
            return jsonify({'status': 'success', 'message': 'Callback processed'}), 200

        elif status in ['failed', 'expired', 'cancelled']:
            trx.payment_status = 'FAILED'
            trx.status = 'CANCELLED'
            trx.updated_at = db.func.now()
            db.session.commit()
            print(f"[WEBHOOK PAKASIR] {ref_id}: {old_payment_status} -> FAILED")
            return jsonify({'status': 'success', 'message': 'Transaction cancelled'}), 200

        return jsonify({'status': 'ignored', 'message': f'Status {status} ignored'}), 200

    except Exception as e:
        db.session.rollback()
        print(f"[ERROR WEBHOOK PAKASIR] {str(e)}")
        return jsonify({'status': 'error', 'message': 'Internal error'}), 500