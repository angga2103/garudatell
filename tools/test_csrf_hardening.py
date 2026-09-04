"""
Verifikasi Pengetatan Proteksi CSRF GarudaTel v2:
1. Menolak seluruh request POST ke rute internal admin tanpa token CSRF (HTTP 400).
2. Menerima request POST ke rute internal admin dengan token CSRF valid.
3. Memastikan webhook eksternal tetap dapat menerima payload tanpa CSRF.
"""
import sys
import os
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.models import Transaction, Admin

def test_csrf_hardening():
    app = create_app()
    client = app.test_client()

    print("\n" + "="*70)
    print("      VERIFIKASI PENGETATAN PROTEKSI CSRF ADMIN & WEBHOOK EXEMPTION      ")
    print("="*70)

    # Login sebagai admin
    with client.session_transaction() as sess:
        sess['admin_logged_in'] = True
        sess['admin_user'] = 'admin'

    # 1. Dapatkan CSRF Token yang valid dari halaman admin
    res_get = client.get('/admin/margin')
    assert res_get.status_code == 200, "Admin harus bisa membuka /admin/margin"
    csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', res_get.data.decode('utf-8'))
    assert csrf_match, "CSRF token harus tersedia di formulir /admin/margin"
    valid_csrf = csrf_match.group(1)
    print("  [OK] Valid CSRF token berhasil diekstrak dari template admin.")

    # 2. Uji Penolakan CSRF pada Berbagai Endpoint Admin Internal
    admin_post_endpoints = [
        ('/admin/margin', {'min_price_1': '0', 'max_price_1': '10000', 'margin_1': '200'}),
        ('/admin/apply_auto_tier', {}),
        ('/admin/banner/add', {'title': 'Test Banner', 'image_url': 'https://example.com/b.png'}),
        ('/admin/broadcast/send', {'target_type': 'all', 'message': 'Test Broadcast'}),
        ('/admin/point_settings', {'point_rate': '10'}),
    ]

    print("\n[STEP 1] Menguji Penolakan Request POST Internal Admin Tanpa Token CSRF...")
    for endpoint, dummy_data in admin_post_endpoints:
        res = client.post(endpoint, data=dummy_data)
        assert res.status_code == 400, f"Endpoint {endpoint} harus menolak request tanpa CSRF (dapat {res.status_code})"
        print(f"  [OK] {endpoint} menolak request POST tanpa CSRF (HTTP 400 Bad Request).")

    # 3. Uji Penerimaan Request POST dengan CSRF Token Valid
    print("\n[STEP 2] Menguji Penerimaan Request POST Internal Admin Dengan CSRF Valid...")
    for endpoint, form_data in [
        ('/admin/point_settings', {'point_rate': '10', 'point_reward_per_trx': '1', 'csrf_token': valid_csrf}),
        ('/admin/apply_auto_tier', {'csrf_token': valid_csrf})
    ]:
        res = client.post(endpoint, data=form_data, follow_redirects=False)
        assert res.status_code in [200, 302], f"Endpoint {endpoint} dengan valid CSRF harus sukses (dapat {res.status_code})"
        print(f"  [OK] {endpoint} sukses diproses dengan CSRF token valid (Status {res.status_code}).")

    # 4. Uji Webhook Eksternal (Tetap Exempt Tanpa CSRF)
    print("\n[STEP 3] Menguji Webhook Eksternal Pihak Ketiga (Tetap @csrf.exempt)...")
    webhook_endpoints = [
        ('/trx/callback/digiflazz', {'data': {}}),
        ('/trx/callback/paymentkita', {'ref_id': 'NONEXISTENT', 'status': 'failed'}),
        ('/trx/callback/pakasir', {'order_id': 'NONEXISTENT'})
    ]

    for endpoint, payload in webhook_endpoints:
        res = client.post(endpoint, json=payload)
        # Webhook tidak boleh ditolak oleh CSRF (400 Bad Request akibat CSRF missing)
        assert res.status_code != 400 or b"CSRF" not in res.data, f"Webhook {endpoint} tidak boleh diblokir oleh CSRF"
        print(f"  [OK] Webhook {endpoint} bebas CSRF dan berhasil diakses (Status {res.status_code}).")

    print("\n" + "="*70)
    print("  >>> SELURUH VERIFIKASI PENGETATAN CSRF LULUS 100% SECARA SEMPURNA! <<<")
    print("="*70)

if __name__ == '__main__':
    test_csrf_hardening()

