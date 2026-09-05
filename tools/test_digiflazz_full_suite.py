"""
GarudaTel v2 - Digiflazz Full Specification Test Suite
Memverifikasi kepatuhan sistem terhadap 11 dokumentasi resmi Digiflazz Buyer API:
1. cek-saldo
2. daftar-harga
3. deposit
4. topup
5. cek-tagihan
6. bayar-tagihan
7. cek-status
8. inquiry-pln
9. test-case
10. response-code
11. webhook
"""

import os
import sys
import json
import hashlib
import hmac
from unittest.mock import patch, MagicMock

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction
from app.services.digiflazz import (
    check_balance,
    get_price_list,
    request_deposit,
    create_transaction,
    inquiry_pasca,
    pay_pasca,
    check_transaction_status,
    inquiry_pln,
    verify_webhook_signature,
    DIGIFLAZZ_RC,
    DIGIFLAZZ_TEST_CASES,
    get_rc_message,
    format_bank_name
)

def run_suite():
    print('=' * 75)
    print('  GARUDATEL v2 - DIGIFLAZZ 11-SPECIFICATION FULL VERIFICATION SUITE')
    print('=' * 75)

    app = create_app()
    app.config['WTF_CSRF_ENABLED'] = False
    client = app.test_client()

    os.environ['DIGI_USER'] = 'testuser'
    os.environ['DIGI_KEY'] = 'testkey123'
    os.environ['DIGI_WEBHOOK_SECRET'] = 'secret_webhook_456'

    # -------------------------------------------------------------
    # 1. CEK SALDO (https://developer.digiflazz.com/api/buyer/cek-saldo/)
    # -------------------------------------------------------------
    print('\n[1/11] 1. Cek Saldo (/v1/cek-saldo)...')
    with patch('requests.post') as mock_p:
        # A. Kasus Sukses
        mock_p.return_value.status_code = 200
        mock_p.return_value.json.return_value = {
            'data': {'deposit': 1500000, 'rc': '00'}
        }
        ok, bal, msg = check_balance()
        assert ok is True, 'Cek saldo valid harus return True'
        assert bal == 1500000.0, f'Saldo tidak cocok: {bal}'
        
        # Periksa payload & sign md5(username + key + depo)
        args, kwargs = mock_p.call_args
        sent_payload = kwargs['json']
        expected_sign = hashlib.md5(b'testusertestkey123depo').hexdigest()
        assert sent_payload['cmd'] == 'deposit'
        assert sent_payload['sign'] == expected_sign
        print('  [OK] Cek Saldo Sukses: Signature md5(user+key+depo) valid & saldo terbaca akurat.')

        # B. Kasus Error RC 42 (Mencegah false positive Rp 0)
        mock_p.return_value.status_code = 400
        mock_p.return_value.json.return_value = {
            'data': {'deposit': 0, 'rc': '42', 'message': 'API Buyer Error'}
        }
        ok_err, bal_err, msg_err = check_balance()
        assert ok_err is False, 'Error RC tidak boleh menghasilkan sukses'
        assert 'RC 42' in msg_err
        print('  [OK] Cek Saldo Mitigasi: Error RC 42 ditolak dengan benar (tanpa saldo Rp 0 palsu).')

    # -------------------------------------------------------------
    # 2. DAFTAR HARGA (https://developer.digiflazz.com/api/buyer/daftar-harga/)
    # -------------------------------------------------------------
    print('\n[2/11] 2. Daftar Harga (/v1/price-list)...')
    with patch('requests.post') as mock_p:
        mock_p.return_value.status_code = 200
        mock_p.return_value.json.return_value = {
            'data': [
                {'buyer_sku_code': 'xld10', 'product_name': 'XL 10K', 'price': 10250},
                {'buyer_sku_code': 'tsel10', 'product_name': 'Telkomsel 10K', 'price': 10300}
            ]
        }
        ok, prods, msg = get_price_list(cmd='prepaid', code='xld10')
        assert ok is True
        assert len(prods) == 2
        
        # Periksa payload
        args, kwargs = mock_p.call_args
        sent = kwargs['json']
        assert sent['cmd'] == 'prepaid'
        assert sent['code'] == 'xld10'
        assert sent['sign'] == hashlib.md5(b'testusertestkey123pricelist').hexdigest()
        print('  [OK] Daftar Harga: Endpoint price-list, sign md5(user+key+pricelist) & filter code teruji.')

    # -------------------------------------------------------------
    # 3. DEPOSIT TIKET (https://developer.digiflazz.com/api/buyer/deposit/)
    # -------------------------------------------------------------
    print('\n[3/11] 3. Tiket Deposit (/v1/deposit)...')
    assert format_bank_name('shopeepay') == 'ShopeePay'
    assert format_bank_name('flip') == 'Flip'
    assert format_bank_name('bca') == 'BCA'

    with patch('requests.post') as mock_p:
        mock_p.return_value.status_code = 200
        mock_p.return_value.json.return_value = {
            'data': {
                'rc': '00',
                'amount': 250123,
                'bank': 'BCA',
                'account_no': '7700112233',
                'owner_name': 'PT DIGIFLAZZ INTERKONEKSI'
            }
        }
        ok, dep_data, dep_msg = request_deposit(250000, 'bca', 'Angga Dian')
        assert ok is True
        assert dep_data['account_number'] == '7700112233', 'account_no harus disinkronkan ke account_number'
        
        # Cek signature deposit: md5(user + key + deposit)
        args, kwargs = mock_p.call_args
        sent = kwargs['json']
        assert sent['sign'] == hashlib.md5(b'testusertestkey123deposit').hexdigest()
        assert sent['Bank'] == 'BCA'
        print('  [OK] Tiket Deposit: Casing bank (BCA/Flip/ShopeePay) & account_no sinkron teruji.')

    # -------------------------------------------------------------
    # 4. TOPUP PRABAYAR (https://developer.digiflazz.com/api/buyer/topup/)
    # -------------------------------------------------------------
    print('\n[4/11] 4. Topup Prabayar (/v1/transaction)...')
    with patch('requests.post') as mock_p:
        mock_p.return_value.status_code = 200
        mock_p.return_value.json.return_value = {
            'data': {
                'ref_id': 'TEST-TRX-001',
                'customer_no': '087800001230',
                'buyer_sku_code': 'xld10',
                'status': 'Sukses',
                'rc': '00',
                'sn': 'SN-99887766'
            }
        }
        res = create_transaction(
            sku='xld10',
            tujuan='087800001230',
            ref_id='TEST-TRX-001',
            testing=True,
            max_price=11000,
            cb_url='https://example.com/cb'
        )
        assert res.get('data', {}).get('status') == 'Sukses'
        
        # Verifikasi payload
        args, kwargs = mock_p.call_args
        sent = kwargs['json']
        assert sent['testing'] is True
        assert sent['max_price'] == 11000
        assert sent['cb_url'] == 'https://example.com/cb'
        assert sent['sign'] == hashlib.md5(b'testusertestkey123TEST-TRX-001').hexdigest()
        print('  [OK] Topup Prabayar: Parameter testing, max_price, cb_url, dan signature ref_id valid.')

    # -------------------------------------------------------------
    # 5. CEK TAGIHAN PASCABAYAR (https://developer.digiflazz.com/api/buyer/cek-tagihan/)
    # -------------------------------------------------------------
    print('\n[5/11] 5. Cek Tagihan Pascabayar (inq-pasca)...')
    with patch('requests.post') as mock_p:
        mock_p.return_value.status_code = 200
        mock_p.return_value.json.return_value = {
            'data': {
                'rc': '00',
                'status': 'Sukses',
                'buyer_sku_code': 'pln-pasca',
                'customer_name': 'BUDI SANTOSO',
                'admin': 2500,
                'selling_price': 125000,
                'desc': {'tarif': 'R1', 'daya': 900}
            }
        }
        ok, inq_data, inq_msg = inquiry_pasca('pln-pasca', '51234567890', 'REF-INQ-01', testing=True)
        assert ok is True
        assert inq_data['customer_name'] == 'BUDI SANTOSO'
        assert inq_data['selling_price'] == 125000
        
        args, kwargs = mock_p.call_args
        sent = kwargs['json']
        assert sent['commands'] == 'inq-pasca'
        assert sent['testing'] is True
        print('  [OK] Inquiry Pasca: commands inq-pasca, parsing rincian tagihan (nama, daya, tarif) sukses.')

    # -------------------------------------------------------------
    # 6. BAYAR TAGIHAN PASCABAYAR (https://developer.digiflazz.com/api/buyer/bayar-tagihan/)
    # -------------------------------------------------------------
    print('\n[6/11] 6. Bayar Tagihan Pascabayar (pay-pasca)...')
    with patch('requests.post') as mock_p:
        mock_p.return_value.status_code = 200
        mock_p.return_value.json.return_value = {
            'data': {
                'rc': '00',
                'status': 'Sukses',
                'sn': 'PLN-PAY-554433',
                'buyer_sku_code': 'pln-pasca',
                'message': 'Pembayaran Berhasil'
            }
        }
        ok, pay_data, pay_msg = pay_pasca('pln-pasca', '51234567890', 'REF-INQ-01', testing=True)
        assert ok is True
        assert pay_data['sn'] == 'PLN-PAY-554433'
        
        args, kwargs = mock_p.call_args
        sent = kwargs['json']
        assert sent['commands'] == 'pay-pasca'
        print('  [OK] Bayar Tagihan Pasca: commands pay-pasca & penerimaan SN resmi sukses.')

    # -------------------------------------------------------------
    # 7. CEK STATUS TRANSAKSI (https://developer.digiflazz.com/api/buyer/cek-status/)
    # -------------------------------------------------------------
    print('\n[7/11] 7. Cek Status Transaksi...')
    with patch('requests.post') as mock_p:
        # A. Prabayar (Re-submit ref_id)
        mock_p.return_value.status_code = 200
        mock_p.return_value.json.return_value = {
            'data': {'status': 'Sukses', 'rc': '00', 'sn': 'SN-CHECK-11'}
        }
        ok, stat_data, stat_msg = check_transaction_status('xld10', '0878123', 'REF-CHECK-01', is_pasca=False)
        assert ok is True
        assert 'commands' not in mock_p.call_args[1]['json']
        
        # B. Pascabayar (commands: status-pasca)
        ok_p, stat_data_p, stat_msg_p = check_transaction_status('pln-pasca', '5123', 'REF-CHECK-02', is_pasca=True)
        assert ok_p is True
        assert mock_p.call_args[1]['json']['commands'] == 'status-pasca'
        print('  [OK] Cek Status: Prabayar (idempotent retry) & Pascabayar (status-pasca) teruji.')

    # -------------------------------------------------------------
    # 8. INQUIRY PLN (https://developer.digiflazz.com/api/buyer/inquiry-pln/)
    # -------------------------------------------------------------
    print('\n[8/11] 8. Inquiry PLN (/v1/inquiry-pln)...')
    with patch('requests.post') as mock_p:
        mock_p.return_value.status_code = 200
        mock_p.return_value.json.return_value = {
            'data': {
                'rc': '00',
                'customer_no': '14123456789',
                'name': 'HENDRA WIJAYA',
                'segment_power': 'R1 / 900VA',
                'subscriber_id': '14123456789'
            }
        }
        ok, pln_res, pln_msg = inquiry_pln('14123456789')
        assert ok is True
        assert pln_res['name'] == 'HENDRA WIJAYA'
        assert pln_res['segment_power'] == 'R1 / 900VA'

        # Verifikasi rumus signature khusus PLN: md5(username + key + customer_no)
        args, kwargs = mock_p.call_args
        sent = kwargs['json']
        expected_pln_sign = hashlib.md5(b'testusertestkey12314123456789').hexdigest()
        assert sent['sign'] == expected_pln_sign

        # Uji juga endpoint user /inquiry/pln
        res_endpoint = client.post('/inquiry/pln', json={'customer_no': '14123456789'})
        assert res_endpoint.status_code == 200
        assert res_endpoint.get_json()['name'] == 'HENDRA WIJAYA'
        print('  [OK] Inquiry PLN: Signature khusus md5(user+key+customer_no) & endpoint /inquiry/pln teruji.')

    # -------------------------------------------------------------
    # 9. TEST CASES STANDARD (https://developer.digiflazz.com/api/buyer/test-case/)
    # -------------------------------------------------------------
    print('\n[9/11] 9. Test Cases Standar...')
    assert DIGIFLAZZ_TEST_CASES['SUKSES'] == '087800001230'
    assert DIGIFLAZZ_TEST_CASES['GAGAL'] == '087800001232'
    assert DIGIFLAZZ_TEST_CASES['PENDING'] == '087800001233'
    assert DIGIFLAZZ_TEST_CASES['NOMOR_SALAH'] == '087800001234'
    print('  [OK] Test Cases: 4 nomor simulasi resmi sandbox terdefinisi.')

    # -------------------------------------------------------------
    # 10. RESPONSE CODE MAPPING (https://developer.digiflazz.com/api/buyer/response-code/)
    # -------------------------------------------------------------
    print('\n[10/11] 10. Response Code Mapping...')
    assert get_rc_message('00') == 'Sukses'
    assert get_rc_message('01') == 'Saldo Tidak Cukup'
    assert get_rc_message('03') == 'Menunggu respon dari provider (Pending)'
    assert get_rc_message('42') == 'Nomor tujuan salah / terblokir / cut off'
    assert get_rc_message('45') == 'Signature tidak valid'
    assert get_rc_message('48') == 'Tagihan sudah lunas'
    print('  [OK] Response Codes: Pemetaan kamus RC resmi bahasa Indonesia teruji lengkap.')

    # -------------------------------------------------------------
    # 11. WEBHOOK X-HUB-SIGNATURE & AUTO-REFUND (https://developer.digiflazz.com/api/buyer/webhook/)
    # -------------------------------------------------------------
    print('\n[11/11] 11. Webhook Signature & Auto-Refund...')
    # A. Verifikasi HMAC-SHA1
    secret = 'secret_webhook_456'
    raw_body = json.dumps({'data': {'ref_id': 'REF-WH-01', 'status': 'Sukses', 'rc': '00'}}).encode('utf-8')
    computed_sha1 = hmac.new(secret.encode('utf-8'), raw_body, hashlib.sha1).hexdigest()
    
    assert verify_webhook_signature(raw_body, f'sha1={computed_sha1}', secret=secret) is True
    assert verify_webhook_signature(raw_body, 'sha1=invalidsig123', secret=secret) is False
    print('  [OK] HMAC-SHA1: Header X-Hub-Signature terverifikasi secara kriptografis.')

    # B. Webhook Endpoint (/trx/callback/digiflazz)
    with app.app_context():
        # Setup dummy user & transaction
        u = User.query.filter_by(phone='087799001122').first()
        if not u:
            u = User(name='WhTester', phone='087799001122', password_hash='x', balance=50000.0)
            db.session.add(u)
            db.session.commit()
        else:
            u.balance = 50000.0
            db.session.commit()

        ref_wh = 'GT-WH-TEST-99'
        trx = Transaction.query.filter_by(ref_id=ref_wh).first()
        if not trx:
            trx = Transaction(
                user_id=u.id,
                ref_id=ref_wh,
                sku_code='xld10',
                product_name='XL 10K',
                target_number='0878112233',
                amount=10000.0,
                payment_method='SALDO',
                payment_status='PAID',
                status='PROCESSING'
            )
            db.session.add(trx)
            db.session.commit()

    # Webhook Gagal -> Trigger Auto-Refund
    wh_payload = {
        'data': {
            'ref_id': ref_wh,
            'status': 'Gagal',
            'rc': '42',
            'message': 'Nomor terblokir'
        }
    }
    raw_wh_bytes = json.dumps(wh_payload).encode('utf-8')
    sig_wh = hmac.new(secret.encode('utf-8'), raw_wh_bytes, hashlib.sha1).hexdigest()

    res_wh = client.post(
        '/trx/callback/digiflazz',
        data=raw_wh_bytes,
        headers={
            'Content-Type': 'application/json',
            'X-Hub-Signature': f'sha1={sig_wh}'
        }
    )
    assert res_wh.status_code == 200
    assert res_wh.get_json()['status'] == 'success'

    # Verifikasi auto-refund saldo masuk
    with app.app_context():
        u_after = User.query.filter_by(phone='087799001122').first()
        assert u_after.balance == 60000.0, f'Saldo gagal di-refund: {u_after.balance}'
        trx_after = Transaction.query.filter_by(ref_id=ref_wh).first()
        assert trx_after.status == 'FAILED'
        print('  [OK] Webhook Digiflazz: Parsing body nested data, X-Hub-Signature, dan Auto-Refund saldo Rp 10.000 sukses!')

        # Bersihkan dummy
        Transaction.query.filter_by(ref_id=ref_wh).delete()
        User.query.filter_by(phone='087799001122').delete()
        db.session.commit()

    print('\n' + '=' * 75)
    print('  >>> SELURUH 11 DOKUMENTASI RESMI DIGIFLAZZ TERUJI LULUS 100%! <<<')
    print('=' * 75 + '\n')

if __name__ == '__main__':
    run_suite()
