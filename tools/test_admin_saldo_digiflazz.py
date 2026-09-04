import os
import sys
from unittest.mock import patch

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.deposit_ticket import DigiDepositTicket

def test_admin_saldo_digiflazz():
    print("=" * 65)
    print("  VERIFIKASI REVISI PANEL SALDO & DEPOSIT DIGIFLAZZ")
    print("=" * 65)

    app = create_app()
    client = app.test_client()

    with client.session_transaction() as sess:
        sess['admin_logged_in'] = True

    # 1. Test GET /admin/saldo (Tampilan Halaman)
    print("\n[1/4] Menguji Tampilan Halaman /admin/saldo...")
    with patch('app.routes.admin.check_balance') as mock_bal:
        mock_bal.return_value = (True, 350000.0, "Berhasil mengambil saldo Digiflazz")
        res = client.get('/admin/saldo')
        assert res.status_code == 200, f"Gagal GET /admin/saldo: {res.status_code}"
        assert "Saldo & Deposit Digiflazz" in res.text
        assert "Rp 350,000" in res.text or "350.000" in res.text or "350,000" in res.text
        assert "Minta Tiket Deposit Digiflazz Baru" in res.text
        print("  [OK] Halaman /admin/saldo berhasil memuat saldo Digiflazz real-time dan form deposit.")

    # 2. Test POST /admin/saldo/cek (Refresh Saldo)
    print("\n[2/4] Menguji Refresh Saldo Digiflazz (/admin/saldo/cek)...")
    with patch('app.routes.admin.check_balance') as mock_bal:
        mock_bal.return_value = (True, 500000.0, "Sukses")
        res_cek = client.post('/admin/saldo/cek', follow_redirects=True)
        assert res_cek.status_code == 200
        assert "Saldo Digiflazz saat ini" in res_cek.text or "500,000" in res_cek.text or "500.000" in res_cek.text
        print("  [OK] Endpoint /admin/saldo/cek berhasil memperbarui saldo.")

    # 3. Test POST /admin/saldo/tiket (Minta Tiket Deposit Baru)
    print("\n[3/4] Menguji Pengajuan Tiket Deposit Digiflazz (/admin/saldo/tiket)...")
    mock_digi_response = {
        "rc": "00",
        "amount": 500412,
        "notes": "Silahkan transfer Rp. 500.412 ke BCA 1234567890 a.n PT DIGIFLAZZ",
        "bank": "BCA",
        "account_number": "1234567890",
        "account_name": "PT DIGIFLAZZ INTERKONEKSI INDONESIA"
    }

    with patch('app.routes.admin.request_deposit') as mock_depo:
        mock_depo.return_value = (True, mock_digi_response, "Tiket deposit berhasil dibuat!")
        res_depo = client.post('/admin/saldo/tiket', data={
            'amount': 500000,
            'bank': 'BCA',
            'owner_name': 'ANGGA DIAN'
        }, follow_redirects=True)

        assert res_depo.status_code == 200
        assert "Tiket Deposit Berhasil Dibuat" in res_depo.text
        assert "500,412" in res_depo.text or "500.412" in res_depo.text
        print("  [OK] Pengajuan tiket deposit sukses dan kode unik 500.412 tercatat!")

    # Verifikasi tiket di database dan di halaman aktif
    with app.app_context():
        ticket = DigiDepositTicket.query.order_by(DigiDepositTicket.id.desc()).first()
        assert ticket is not None
        assert ticket.amount_requested == 500000.0
        assert ticket.amount_transfer == 500412.0
        assert ticket.bank == 'BCA'
        assert ticket.owner_name == 'ANGGA DIAN'
        assert ticket.status == 'PENDING'
        ticket_id = ticket.id
        print(f"  [OK] Tiket #{ticket_id} tersimpan rapi di basis data DigiDepositTicket.")

    # 4. Test Pembatalan Tiket Aktif
    print(f"\n[4/4] Menguji Pembatalan Tiket Aktif #{ticket_id}...")
    res_batal = client.post(f'/admin/saldo/tiket/batal/{ticket_id}', follow_redirects=True)
    assert res_batal.status_code == 200
    assert "telah dibatalkan" in res_batal.text

    with app.app_context():
        ticket_check = DigiDepositTicket.query.get(ticket_id)
        assert ticket_check.status == 'CANCELLED'
        print("  [OK] Tiket deposit berhasil dibatalkan statusnya.")

    print("\n" + "=" * 65)
    print("  >>> SELURUH FITUR SALDO & DEPOSIT DIGIFLAZZ LULUS 100%! <<<")
    print("=" * 65 + "\n")

if __name__ == '__main__':
    test_admin_saldo_digiflazz()

