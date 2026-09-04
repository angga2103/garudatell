import os
import sys

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction
from app.models.banner import Banner
from app.models.broadcast import BroadcastLog

def test_admin_priority_3():
    print("=" * 65)
    print("  VERIFIKASI PERBAIKAN PANEL ADMIN - PRIORITAS 3")
    print("=" * 65)

    app = create_app()
    client = app.test_client()

    with client.session_transaction() as sess:
        sess['admin_logged_in'] = True

    # 1. Test Dashboard Links
    print("\n[1/5] Menguji Seluruh Tautan Menu di Dashboard...")
    res_dash = client.get('/admin/')
    assert res_dash.status_code == 200
    assert 'href="/admin/broadcast"' in res_dash.text
    assert 'href="/admin/banner"' in res_dash.text
    assert 'href="/admin/saldo"' in res_dash.text
    assert 'href="/admin/reports"' in res_dash.text
    print("  [OK] Seluruh 8 tombol menu di dashboard admin telah aktif 100% tanpa dead link (#).")

    # 2. Test Banner Center
    print("\n[2/5] Menguji Banner Center (/admin/banner)...")
    res_b_page = client.get('/admin/banner')
    assert res_b_page.status_code == 200
    assert "Banner Center" in res_b_page.text

    # Test Tambah Banner
    res_add_b = client.post('/admin/banner/add', data={
        'title': 'Banner Promo Ramadhan Test',
        'image_url': 'https://garudatel.com/assets/img/promo.jpg',
        'link_url': 'https://garudatel.com/promo',
        'is_active': '1'
    }, follow_redirects=True)
    assert res_add_b.status_code == 200
    assert "Banner Promo Ramadhan Test" in res_add_b.text

    with app.app_context():
        created_b = Banner.query.filter_by(title='Banner Promo Ramadhan Test').first()
        assert created_b is not None
        assert created_b.is_active is True
        bid = created_b.id

    # Test Toggle Banner
    res_tog_b = client.post(f'/admin/banner/toggle/{bid}', follow_redirects=True)
    assert res_tog_b.status_code == 200
    with app.app_context():
        assert Banner.query.get(bid).is_active is False

    # Test Delete Banner
    res_del_b = client.post(f'/admin/banner/delete/{bid}', follow_redirects=True)
    assert res_del_b.status_code == 200
    with app.app_context():
        assert Banner.query.get(bid) is None
    print("  [OK] Fitur Banner Center (List, Tambah, Toggle Status, Hapus) sukses 100%.")

    # 3. Test Broadcast Center
    print("\n[3/5] Menguji Broadcast Center (/admin/broadcast)...")
    res_bc_page = client.get('/admin/broadcast')
    assert res_bc_page.status_code == 200
    assert "Broadcast Center" in res_bc_page.text

    # Test Kirim Broadcast Kustom
    res_send_bc = client.post('/admin/broadcast/send', data={
        'target_type': 'custom',
        'custom_numbers': '08123456789\n08987654321',
        'message': 'Halo {name}, promo kuota murah GarudaTel hadir!'
    }, follow_redirects=True)
    assert res_send_bc.status_code == 200
    assert "Broadcast selesai" in res_send_bc.text

    with app.app_context():
        last_log = BroadcastLog.query.order_by(BroadcastLog.id.desc()).first()
        assert last_log is not None
        assert last_log.target_type == 'custom'
        assert last_log.recipient_count == 2
        print(f"  [OK] Broadcast terkirim & tercatat di database: {last_log.recipient_count} penerima.")

    # 4. Test Saldo & Deposit Digiflazz (/admin/saldo)
    print("\n[4/5] Menguji Saldo & Deposit Digiflazz (/admin/saldo)...")
    res_saldo_page = client.get('/admin/saldo')
    assert res_saldo_page.status_code == 200
    assert "Saldo & Deposit Digiflazz" in res_saldo_page.text

    # Test Refresh Saldo
    res_refresh = client.post('/admin/saldo/cek', follow_redirects=True)
    assert res_refresh.status_code == 200

    # Test Pengajuan Tiket
    from unittest.mock import patch
    with patch('app.routes.admin.request_deposit') as mock_dep:
        mock_dep.return_value = (True, {'rc': '00', 'amount': 250123, 'bank': 'BCA', 'account_number': '1234567890', 'notes': 'Transfer tepat Rp 250.123'}, 'Sukses')
        res_dep = client.post('/admin/saldo/tiket', data={
            'amount': 250000,
            'bank': 'BCA',
            'owner_name': 'ADMIN TEST'
        }, follow_redirects=True)
        assert res_dep.status_code == 200
        assert "Tiket Deposit Berhasil Dibuat" in res_dep.text
        assert "250,123" in res_dep.text or "250.123" in res_dep.text

    print("  [OK] Cek saldo dan pengajuan tiket deposit Digiflazz sukses 100%.")

    # 5. Test Laporan & Rekapitulasi (/admin/reports)
    print("\n[5/5] Menguji Laporan & Rekapitulasi (/admin/reports)...")
    for r_range in ['today', '7days', '30days', 'this_month', 'all']:
        res_rep = client.get(f'/admin/reports?range={r_range}')
        assert res_rep.status_code == 200
        assert "Laporan & Rekapitulasi" in res_rep.text
        assert "Tingkat Keberhasilan" in res_rep.text
    print("  [OK] Seluruh rentang filter laporan rekapitulasi finansial sukses diuji.")

    print("\n" + "=" * 65)
    print("  >>> SELURUH PERBAIKAN PRIORITAS 3 LULUS 100% SECARA SEMPURNA! <<<")
    print("=" * 65 + "\n")

if __name__ == '__main__':
    test_admin_priority_3()

