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

@trx_bp.route('/inquiry_bill', methods=['POST'])
@trx_bp.route('/api/inquiry_bill', methods=['POST'])
@trx_bp.route('/inquiry_pasca', methods=['POST'])
@csrf.exempt
def inquiry_bill():
    """
    Endpoint Cek Tagihan Pascabayar (PLN, dll) ke Digiflazz sebelum pembayaran.
    Menghasilkan ref_id unik yang WAJIB digunakan kembali saat eksekusi pay-pasca.
    """
    if not current_user.is_authenticated:
        return jsonify({
            'status': 'error',
            'error': True,
            'message': 'Silakan login terlebih dahulu untuk cek tagihan',
            'requires_login': True
        }), 401

    try:
        req_data = request.get_json(silent=True) or request.form.to_dict() or {}
        sku_input = str(req_data.get('sku_code') or req_data.get('sku') or '').strip()
        customer_no = str(req_data.get('customer_no') or req_data.get('target_number') or req_data.get('id_pelanggan') or req_data.get('nomor') or '').strip()

        if not sku_input or not customer_no:
            return jsonify({'status': 'error', 'message': 'SKU Produk dan ID Pelanggan / Nomor Meter wajib diisi'}), 400

        if len(customer_no) < 8:
            return jsonify({'status': 'error', 'message': 'ID Pelanggan / Nomor Meter minimal 8 digit'}), 400

        # Cari produk di katalog
        product = Product.query.filter_by(sku_code=sku_input).first()
        if not product:
            return jsonify({'status': 'error', 'message': 'Produk tagihan tidak ditemukan di database'}), 404

        # Generate ref_id unik khusus inquiry pascabayar
        ref_id = f"GT-PASCA-{int(time.time()*1000)}{random.randint(10, 99)}"

        from app.services.digiflazz import inquiry_pasca
        ok, res_data, msg = inquiry_pasca(sku_input, customer_no, ref_id)

        if not ok or not res_data:
            return jsonify({
                'status': 'error',
                'message': msg or 'Gagal mengecek tagihan ke server PLN',
                'data': res_data or {}
            }), 400

        # Ekstrak data respons Digiflazz
        desc = res_data.get('desc') or {}
        tarif = desc.get('tarif', '-')
        daya = desc.get('daya', '-')
        lembar_tagihan = desc.get('lembar_tagihan', 1)
        tagihan_obj = desc.get('tagihan') or {}
        details = tagihan_obj.get('detail') or []

        tagihan_pokok = 0.0
        denda_total = 0.0
        periode_list = []
        if details and isinstance(details, list):
            for d in details:
                tagihan_pokok += float(d.get('nilai_tagihan', 0))
                denda_total += float(d.get('denda', 0))
                if d.get('periode'):
                    periode_list.append(str(d.get('periode')))

        # Fallback jika detail tidak memuat nilai_tagihan
        digi_admin = float(res_data.get('admin', 0))
        digi_price = float(res_data.get('price', 0))
        if tagihan_pokok == 0 and digi_price > 0:
            tagihan_pokok = max(0.0, digi_price - digi_admin)

        # Biaya admin / margin sistem GarudaTel
        admin_fee_garudatel = float(product.sell_price) if product.sell_price else 4200.0
        total_bayar = tagihan_pokok + denda_total + admin_fee_garudatel

        periode_str = ", ".join(periode_list) if periode_list else "-"

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
            'admin_fee': admin_fee_garudatel,
            'total_bayar': total_bayar,
            'message': 'Tagihan berhasil ditemukan',
            'data': res_data
        }), 200

    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Sistem Error saat cek tagihan: {str(e)}'}), 500


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
        inquiry_ref_id = str(req_data.get('inquiry_ref_id') or req_data.get('ref_id') or '').strip()

        if not sku_input or not target_number:
            return jsonify({'status': 'error', 'error': True, 'message': 'Data SKU atau Nomor Tujuan tidak lengkap'}), 400

        # 3. IDENTIFIKASI PRODUK & PROVIDER
        is_bebas_nominal = False
        is_pasca_bill = False
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
        bebas_sku_list = ['post685480', 'post685481', 'post685482', 'post685483', 'post685485', 'post706873']

        # Cek produk di database terlebih dahulu
        db_product = Product.query.filter_by(sku_code=sku_input).first()

        bebas_brand_match = None
        for b_name in bebas_sku_map.keys():
            if sku_upper == b_name or f"{b_name}_BEBAS" in sku_upper or f"BEBAS_{b_name}" in sku_upper:
                bebas_brand_match = b_name
                break

        # Kriteria Deteksi Bebas Nominal Akurat:
        if sku_input in bebas_sku_list:
            is_bebas_nominal = True
        elif db_product and 'BEBAS' in (db_product.name or '').upper() and ('PASCABAYAR' in (db_product.category or '').upper() or 'E-MONEY' in (db_product.brand or '').upper() or 'WALLET' in (db_product.category or '').upper()):
            is_bebas_nominal = True
        elif bebas_brand_match and (float(amt_raw or 0) > 0 or 'BEBAS' in sku_upper):
            is_bebas_nominal = True
        elif 'BEBAS' in sku_upper and not ('BEBAS PUAS' in sku_upper or 'XL' in sku_upper):
            is_bebas_nominal = True

        # Kriteria Deteksi Tagihan Pascabayar (PLN Pascabayar, NonTaglis, dll)
        if not is_bebas_nominal:
            if inquiry_ref_id and (inquiry_ref_id.startswith('GT-PASCA-') or inquiry_ref_id.startswith('PLN-PASCA-')):
                is_pasca_bill = True
            elif db_product and ('PASCABAYAR' in (db_product.category or '').upper() or 'NONTAGLIS' in (db_product.name or '').upper() or 'PASCA' in (db_product.name or '').upper()):
                is_pasca_bill = True

        nominal = 0.0
        if is_bebas_nominal:
            try:
                nominal = float(amt_raw)
            except (ValueError, TypeError):
                return jsonify({'status': 'error', 'error': True, 'message': 'Nominal bebas nominal tidak valid.'}), 400

            if nominal < 10000:
                return jsonify({'status': 'error', 'error': True, 'message': 'Minimal top up bebas nominal adalah Rp 10.000.'}), 400

            if not db_product:
                brand_clean = bebas_brand_match or 'DANA'
                sku_code = bebas_sku_map.get(brand_clean, 'post685481')
                db_product = Product.query.filter_by(sku_code=sku_code).first()
            else:
                sku_code = db_product.sku_code

            admin_fee = float(db_product.sell_price) if db_product else 1700.0
            amount = nominal + admin_fee
            prod_name_label = db_product.name if db_product else (bebas_brand_match or 'E-Money Bebas')
            product_name = f"{prod_name_label} Rp {int(nominal):,}"
            is_prepaid_flow = False

        elif is_pasca_bill:
            # Wajib melakukan Cek Tagihan terlebih dahulu untuk mendapatkan inquiry_ref_id dan total bayar
            if not inquiry_ref_id:
                return jsonify({
                    'status': 'error',
                    'error': True,
                    'message': 'Harap lakukan Cek Tagihan terlebih dahulu sebelum melakukan pembayaran tagihan pascabayar.'
                }), 400

            try:
                amount = float(amt_raw)
            except (ValueError, TypeError):
                return jsonify({'status': 'error', 'error': True, 'message': 'Nominal tagihan tidak valid.'}), 400

            if amount <= 0:
                return jsonify({'status': 'error', 'error': True, 'message': 'Total tagihan harus lebih dari Rp 0.'}), 400

            product = db_product or Product.query.filter_by(sku_code=sku_input).first()
            product_name = product.name if product else f"Tagihan Listrik {sku_input}"
            sku_code = product.sku_code if product else sku_input
            is_prepaid_flow = False

        else:
            # Cari produk di katalog database jika belum di-query
            product = db_product or Product.query.filter_by(sku_code=sku_input).first()
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

        # 4. GENERATE / GUNAKAN REF_ID
        if is_pasca_bill and inquiry_ref_id:
            ref_id = inquiry_ref_id
        elif is_vip:
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
                from app.services.digiflazz import inquiry_pasca, pay_pasca
                ok_inq, res_inq_data, msg_inq = inquiry_pasca(sku_code, target_number, ref_id, amount=nominal)
                if ok_inq:
                    ok_pay, res_pay_data, msg_pay = pay_pasca(sku_code, target_number, ref_id)
                    if ok_pay:
                        new_trx.status = 'SUCCESS'
                        new_trx.sn = res_pay_data.get('sn', '')
                        db.session.commit()
                        from app.services.telegram_service import async_send_trx_notification
                        async_send_trx_notification(new_trx, title="TRANSAKSI BERHASIL (PASCA)")
                        return jsonify({'status': 'success', 'success': True, 'error': False, 'message': 'Transaksi sukses masuk Digiflazz!', 'redirect': '/riwayat'}), 200
                    else:
                        user_locked.balance += amount
                        new_trx.status = 'FAILED'
                        new_trx.sn = msg_pay
                        db.session.commit()
                        from app.services.telegram_service import async_send_trx_notification
                        async_send_trx_notification(new_trx, title="TRANSAKSI GAGAL (PASCA)")
                        return jsonify({'status': 'error', 'error': True, 'success': False, 'message': 'Gagal (Pay): ' + msg_pay}), 200
                else:
                    user_locked.balance += amount
                    new_trx.status = 'FAILED'
                    new_trx.sn = msg_inq
                    db.session.commit()
                    from app.services.telegram_service import async_send_trx_notification
                    async_send_trx_notification(new_trx, title="TRANSAKSI GAGAL (PASCA)")
                    return jsonify({'status': 'error', 'error': True, 'success': False, 'message': 'Gagal (Inq): ' + msg_inq}), 200

            # C. TAGIHAN PASCABAYAR DIGIFLAZZ (PLN, DLL) DENGAN REF_ID INQUIRY
            elif is_pasca_bill:
                from app.services.digiflazz import pay_pasca
                ok_pay, res_pay_data, msg_pay = pay_pasca(sku_code, target_number, ref_id)
                if ok_pay:
                    rc_pay = str(res_pay_data.get('rc', '')).strip()
                    if rc_pay == '00':
                        new_trx.status = 'SUCCESS'
                        new_trx.sn = res_pay_data.get('sn', '')
                        award_transaction_points(new_trx.user_id, new_trx.ref_id)
                    else:
                        new_trx.status = 'PROCESSING'
                    db.session.commit()
                    from app.services.telegram_service import async_send_trx_notification
                    async_send_trx_notification(new_trx, title="TAGIHAN PLN DIPROSES (PASCA)")
                    return jsonify({
                        'status': 'success',
                        'success': True,
                        'error': False,
                        'message': 'Pembayaran tagihan berhasil diproses!',
                        'redirect': '/riwayat'
                    }), 200
                else:
                    # Gagal di server Digiflazz -> Auto-refund saldo user
                    user_locked.balance += amount
                    new_trx.status = 'FAILED'
                    new_trx.sn = msg_pay
                    db.session.commit()
                    from app.services.telegram_service import async_send_trx_notification
                    async_send_trx_notification(new_trx, title="TAGIHAN PLN GAGAL (REFUND)")
                    return jsonify({
                        'status': 'error',
                        'error': True,
                        'success': False,
                        'message': 'Pembayaran tagihan gagal: ' + msg_pay
                    }), 200

            # D. REGULER DIGIFLAZZ (PREPAID TOPUP)
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
            bebas_sku_list = ['post685480', 'post685481', 'post685482', 'post685483', 'post685485', 'post706873']
            if not trx.is_prepaid or trx.sku_code in bebas_sku_list:
                from app.services.digiflazz import inquiry_pasca, pay_pasca
                prod = Product.query.filter_by(sku_code=trx.sku_code).first()
                admin_fee = float(prod.sell_price) if prod else 1700.0
                nominal = max(0, trx.amount - admin_fee) if trx.amount > admin_fee else trx.amount
                ok_inq, res_inq, msg_inq = inquiry_pasca(trx.sku_code, trx.target_number, trx.ref_id, amount=nominal)
                if ok_inq:
                    ok_pay, res_pay, msg_pay = pay_pasca(trx.sku_code, trx.target_number, trx.ref_id)
                    if ok_pay:
                        trx.status = 'SUCCESS'
                        trx.sn = res_pay.get('sn', '')
                    else:
                        trx.status = 'FAILED'
                        trx.note = msg_pay
                else:
                    trx.status = 'FAILED'
                    trx.note = msg_inq
            else:
                product = Product.query.filter((Product.sku_code == trx.sku_code) | (Product.name == trx.product_name)).first()
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

def sync_single_transaction(trx):
    """
    Menyinkronkan status 1 transaksi yang masih PROCESSING/PENDING ke provider (Digiflazz / VIP-Reseller).
    Mengembalikan boolean True jika status berubah, False jika tetap atau gagal cek.
    """
    if not trx or trx.status not in ['PROCESSING', 'PENDING', 'PROSES']:
        return False

    old_status = trx.status
    changed = False

    try:
        # A. VIP-Reseller
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
                    award_transaction_points(trx.user_id, trx.ref_id)
                    changed = True
                elif v_status in ['error', 'failed', 'gagal']:
                    if old_status != 'FAILED' and trx.payment_status == 'PAID' and trx.payment_method == 'SALDO':
                        user = User.query.filter_by(id=trx.user_id).first()
                        if user:
                            user.balance += trx.amount
                    trx.status = 'FAILED'
                    trx.sn = v_data.get('note', 'Gagal di server VIP')
                    changed = True
                db.session.commit()
                if changed:
                    from app.services.telegram_service import async_send_trx_notification
                    async_send_trx_notification(trx, title=f"TRANSAKSI {trx.status} (VIP)")
        else:
            # B. Digiflazz (Bebas Nominal / Pasca vs Prabayar Reguler)
            bebas_sku_list = ['post685480', 'post685481', 'post685482', 'post685483', 'post685485', 'post706873']
            is_pasca_flow = not trx.is_prepaid or trx.sku_code in bebas_sku_list

            from app.services.digiflazz import check_transaction_status
            ok, d_data, msg = check_transaction_status(trx.sku_code, trx.target_number, trx.ref_id, is_pasca=is_pasca_flow)
            if ok and d_data:
                d_status = str(d_data.get('status', '')).lower()
                rc = str(d_data.get('rc', '')).strip()
                sn = d_data.get('sn', '')

                if 'sukses' in d_status or 'success' in d_status or rc == '00':
                    trx.status = 'SUCCESS'
                    if sn:
                        trx.sn = sn
                    award_transaction_points(trx.user_id, trx.ref_id)
                    changed = True
                elif 'gagal' in d_status or 'failed' in d_status or rc in ['41', '42', '50']:
                    if old_status != 'FAILED' and trx.payment_status == 'PAID' and trx.payment_method == 'SALDO':
                        user = User.query.filter_by(id=trx.user_id).first()
                        if user:
                            user.balance += trx.amount
                    trx.status = 'FAILED'
                    trx.sn = sn or d_data.get('message', msg)
                    changed = True
                elif 'pending' in d_status or 'process' in d_status or rc == '03':
                    if hasattr(trx, 'note') and d_data.get('message'):
                        trx.note = d_data.get('message')

                db.session.commit()
                if changed:
                    from app.services.telegram_service import async_send_trx_notification
                    async_send_trx_notification(trx, title=f"TRANSAKSI {trx.status} (DIGIFLAZZ SYNC)")
    except Exception as e:
        print(f"[SYNC ERROR] {trx.ref_id}: {e}")
        db.session.rollback()

    return changed


@trx_bp.route('/detail/<ref_id>', methods=['GET'])
@login_required
def trx_detail(ref_id):
    trx = Transaction.query.filter_by(ref_id=ref_id, user_id=current_user.id).first()
    if not trx:
        return jsonify({'status': 'error', 'message': 'Transaksi tidak ditemukan'}), 404
        
    if trx.status in ['PROCESSING', 'PENDING', 'PROSES']:
        sync_single_transaction(trx)
            
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
    Dokumentasi resmi: https://developer.digiflazz.com/api/buyer/webhook
    Header: X-Hub-Signature: sha1=<hmac_sha1>
    Body: {"data": {"ref_id": "...", "status": "Sukses", "rc": "00", ...}}
    """
    try:
        from app.services.digiflazz import verify_webhook_signature, get_rc_message

        raw_bytes = request.get_data()
        raw_json = request.get_json(silent=True) or request.form.to_dict() or {}
        
        # Unpack struktur resmi Digiflazz {"data": {...}} jika tersedia
        data = raw_json.get('data') if isinstance(raw_json.get('data'), dict) else raw_json

        ref_id = data.get('ref_id') or data.get('trx_id')
        if not ref_id:
            return jsonify({'status': 'error', 'message': 'Missing ref_id'}), 400

        # Cari transaksi di database
        trx = Transaction.query.filter_by(ref_id=ref_id).first()
        if not trx:
            return jsonify({'status': 'error', 'message': 'Transaction not found'}), 404

        # Autentikasi Keamanan:
        # 1. Prioritaskan header resmi X-Hub-Signature (HMAC-SHA1)
        x_hub_sig = request.headers.get('X-Hub-Signature') or request.headers.get('X-Digiflazz-Delivery')
        is_signature_valid = False

        if x_hub_sig:
            is_signature_valid = verify_webhook_signature(raw_bytes, x_hub_sig)

        # 2. Fallback jika callback menyertakan sign MD5 di body (kompatibilitas backward & test suite)
        if not is_signature_valid:
            username = os.getenv('DIGI_USER', '').strip()
            key = os.getenv('DIGI_KEY', '').strip()
            expected_sign = hashlib.md5(f"{username}{key}{ref_id}".encode()).hexdigest()
            received_sign = data.get('sign') or data.get('signature', '')
            if received_sign and received_sign == expected_sign:
                is_signature_valid = True

        # 3. Fallback toleran jika Secret di panel Digiflazz tidak diatur (opsional di Digiflazz)
        # Sesuai dokumentasi resmi, Digiflazz mengirim User-Agent: Digiflazz-Hookshot atau X-Digiflazz-Event: update
        if not is_signature_valid:
            ua = request.headers.get('User-Agent', '')
            evt = request.headers.get('X-Digiflazz-Event', '')
            if 'Digiflazz-Hookshot' in ua or evt == 'update' or request.headers.get('X-Digiflazz-Delivery'):
                is_signature_valid = True
                print(f"[SECURITY INFO] Digiflazz webhook verified via Digiflazz-Hookshot header for {ref_id}")

        if not is_signature_valid:
            print(f"[SECURITY] Invalid Digiflazz webhook signature for {ref_id}")
            return jsonify({'status': 'error', 'message': 'Invalid signature'}), 403

        # Idempotency check: jika status transaksi sudah SUCCESS, abaikan callback berulang
        if trx.status == 'SUCCESS':
            return jsonify({'status': 'success', 'message': 'Transaction already completed'}), 200

        old_status = trx.status
        status = str(data.get('status', '')).lower()
        rc = str(data.get('rc', '')).strip()
        sn = data.get('sn', '')
        message = data.get('message') or get_rc_message(rc)

        if 'sukses' in status or 'success' in status or rc == '00':
            trx.status = 'SUCCESS'
            trx.sn = sn or trx.sn
            award_transaction_points(trx.user_id, ref_id)
        elif 'gagal' in status or 'failed' in status or 'error' in status or rc in ['41', '42', '50']:
            # AUTO-REFUND hanya jika status sebelumnya belum FAILED (mencegah double refund)
            if old_status != 'FAILED' and trx.payment_status == 'PAID' and trx.payment_method == 'SALDO':
                user = User.query.filter_by(id=trx.user_id).with_for_update().first()
                if user:
                    user.balance += trx.amount
                    print(f"[REFUND] User {user.id} refunded Rp {trx.amount} for failed trx {ref_id}")
            trx.status = 'FAILED'
            if message:
                trx.sn = message
        elif 'pending' in status or 'process' in status or rc == '03':
            if trx.status != 'SUCCESS':
                trx.status = 'PROCESSING'

        if hasattr(trx, 'note') and message:
            trx.note = message

        trx.updated_at = db.func.now()
        db.session.commit()

        # Pencatatan log terstruktur
        try:
            log_dir = os.path.join(BASE_DIR, 'storage', 'logs')
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, 'digiflazz_webhook.log'), 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ref_id={ref_id} status={trx.status} rc={rc} sn={sn}\n")
        except Exception:
            pass

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
            
    # 2. Jika transaksi produk pascabayar / prabayar, trigger Digiflazz
    elif trx.status in ['UNPAID', 'PENDING', 'PROCESSING']:
        try:
            bebas_sku_list = ['post685480', 'post685481', 'post685482', 'post685483', 'post685485', 'post706873']
            is_pasca_flow = not trx.is_prepaid or trx.sku_code in bebas_sku_list

            if is_pasca_flow:
                from app.services.digiflazz import pay_pasca
                ok_pay, res_pay, msg_pay = pay_pasca(trx.sku_code, trx.target_number, trx.ref_id)
                if ok_pay:
                    rc_pay = str(res_pay.get('rc', '')).strip()
                    if rc_pay == '00':
                        trx.status = 'SUCCESS'
                        trx.sn = res_pay.get('sn', '')
                        award_transaction_points(trx.user_id, trx.ref_id)
                    else:
                        trx.status = 'PROCESSING'
                else:
                    trx.status = 'FAILED'
                    trx.sn = msg_pay
            else:
                from app.services.digiflazz import create_transaction
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


@trx_bp.route('/callback/vipreseller', methods=['POST'])
@csrf.exempt
def callback_vipreseller():
    """
    Webhook callback dari VIP-Reseller (VIPayment) untuk update status pesanan otomatis.
    Dokumentasi resmi: https://vip-reseller.co.id
    Payload: { trxid, status, sn, note, price, balance, service, data_no, client_trxid }
    """
    try:
        raw_json = request.get_json(silent=True) or request.form.to_dict() or {}
        data = raw_json.get('data') if isinstance(raw_json.get('data'), dict) else raw_json

        if not data:
            return jsonify({'result': False, 'message': 'Payload kosong'}), 400

        trxid = str(data.get('trxid') or data.get('trx_id') or '').strip()
        client_trxid = str(data.get('client_trxid') or data.get('ref_id') or '').strip()
        status = str(data.get('status', '')).lower().strip()
        sn = data.get('sn') or ''
        note = data.get('note') or data.get('message') or ''

        if not trxid and not client_trxid:
            return jsonify({'result': False, 'message': 'Parameter trxid atau client_trxid tidak ditemukan'}), 400

        # Cari transaksi berdasarkan provider_ref atau ref_id
        trx = None
        if trxid:
            trx = Transaction.query.filter_by(provider_ref=trxid).first()
        if not trx and client_trxid:
            trx = Transaction.query.filter_by(ref_id=client_trxid).first()
        if not trx and trxid:
            trx = Transaction.query.filter_by(ref_id=trxid).first()

        if not trx:
            return jsonify({'result': True, 'message': 'Transaksi tidak ditemukan atau sudah terselesaikan'}), 200

        # Idempotency check: jika status transaksi sudah SUCCESS, abaikan callback berulang
        if trx.status == 'SUCCESS':
            return jsonify({'result': True, 'message': 'Transaksi sudah berstatus SUCCESS'}), 200

        old_status = trx.status

        if 'success' in status or 'sukses' in status:
            trx.status = 'SUCCESS'
            trx.sn = sn or trx.sn or 'Berhasil dari VIP-Reseller'
            award_transaction_points(trx.user_id, trx.ref_id)

        elif 'error' in status or 'failed' in status or 'gagal' in status:
            # Auto-refund saldo user jika transaksi gagal dan pembayaran sudah PAID
            if old_status != 'FAILED' and trx.payment_status == 'PAID':
                user = User.query.filter_by(id=trx.user_id).with_for_update().first()
                if user:
                    user.balance += trx.amount
                    print(f"[REFUND VIP] User {user.id} di-refund Rp {trx.amount} untuk transaksi gagal {trx.ref_id}")
            trx.status = 'FAILED'
            if note:
                trx.sn = str(note)
            elif not trx.sn:
                trx.sn = 'Pesanan ditolak/gagal di server VIP-Reseller'

        elif 'waiting' in status or 'process' in status or 'pending' in status:
            if trx.status != 'SUCCESS':
                trx.status = 'PROCESSING'

        trx.updated_at = db.func.now()
        db.session.commit()

        print(f"[WEBHOOK VIP-RESELLER] {trx.ref_id}: {old_status} -> {trx.status}")
        from app.services.telegram_service import async_send_trx_notification
        async_send_trx_notification(trx, title=f"VIP-RESELLER UPDATE: {trx.status}")

        return jsonify({'result': True, 'message': 'Callback berhasil diproses', 'status': trx.status}), 200

    except Exception as e:
        db.session.rollback()
        print(f"[ERROR WEBHOOK VIP-RESELLER] {str(e)}")
        return jsonify({'result': False, 'message': f'Internal error: {str(e)}'}), 500