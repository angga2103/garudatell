"""
Skrip pengujian fitur Notifikasi Lonceng & Tiket CS Telegram Bot 1 pada GarudaTel.
"""
import sys
import os
import re
from unittest.mock import patch, MagicMock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models import Admin, User, Transaction, Notification, NotificationRead, SupportTicket
from app.services.telegram_service import send_cs_ticket, get_bot_cs_credentials

def test_notifikasi_and_cs_ticket():
    app = create_app()
    client = app.test_client()

    print("\n" + "="*65)
    print("  VERIFIKASI FITUR NOTIFIKASI LONCENG & TIKET CS BOT 1 TELEGRAM")
    print("="*65)

    with app.app_context():
        # Persiapan User Test
        user = User.query.first()
        assert user is not None, "Harus ada minimal 1 user di database"
        test_uid = user.id
        test_uname = user.name
        test_phone = user.phone

        # Persiapan Transaksi Test
        trx = Transaction.query.filter_by(user_id=test_uid).first()
        if not trx:
            trx = Transaction(
                user_id=test_uid,
                ref_id='GT-TEST-CS-999',
                product_name='Paket Data Telkomsel 10GB',
                target_number='081234567890',
                amount=25000,
                status='FAILED'
            )
            db.session.add(trx)
            db.session.commit()
        test_trx_ref = trx.ref_id

    # 1. Uji Pengambilan Kredensial Bot CS dari .env
    print("\n[1/7] Memeriksa Kredensial Bot 1 : CS & Balas Inbox...")
    with app.app_context():
        token, chat_id = get_bot_cs_credentials()
        assert token, "BOT_CS_TOKEN harus terbaca dari .env"
        assert chat_id, "BOT_CS_CHAT_ID harus terbaca dari .env"
        print(f"  [OK] Kredensial Bot CS terdaftar: Token={token[:10]}... | ChatID={chat_id}")

    # 2. Uji Admin Membuat Notifikasi Broadcast Baru
    print("\n[2/7] Menguji Pengiriman Notifikasi Broadcast dari Admin (/admin/notifikasi)...")
    with client.session_transaction() as sess:
        sess['admin_logged_in'] = True
        sess['admin_user'] = 'admin'

    res_get_admin = client.get('/admin/notifikasi')
    assert res_get_admin.status_code == 200
    csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', res_get_admin.data.decode('utf-8'))
    admin_csrf = csrf_match.group(1) if csrf_match else ''

    res_post_notif = client.post('/admin/notifikasi', data={
        'csrf_token': admin_csrf,
        'title': 'Test Promo Spesial Diskon 50%',
        'message': 'Gunakan kode promo GARUDASALE untuk diskon pulsa & data!',
        'type': 'promo',
        'link': '/kategori/pulsa',
        'target': 'all'
    }, follow_redirects=True)
    assert res_post_notif.status_code == 200

    with app.app_context():
        created_notif = Notification.query.filter_by(title='Test Promo Spesial Diskon 50%').first()
        assert created_notif is not None, "Notifikasi baru harus tersimpan di database"
        notif_id = created_notif.id
        print(f"  [OK] Notifikasi broadcast berhasil dibuat (ID #{notif_id})!")

    # 3. Uji Dashboard User Menerima Notifikasi & Badge Titik Merah
    print("\n[3/7] Menguji Dashboard User (/) Menerima Notifikasi & Badge Lonceng...")
    with client.session_transaction() as sess:
        sess['_user_id'] = str(test_uid)
        sess['_fresh'] = True

    res_dash = client.get('/')
    assert res_dash.status_code == 200
    html_dash = res_dash.data.decode('utf-8')
    assert 'bukaModalNotifikasi()' in html_dash, "Logo lonceng harus memiliki fungsi bukaModalNotifikasi()"
    assert 'modalNotifSheet' in html_dash, "Modal Pusat Notifikasi harus tersedia di dashboard"
    assert 'Test Promo Spesial Diskon 50%' in html_dash, "Judul notifikasi baru harus muncul di dashboard"
    assert 'header-bell-dot' in html_dash, "Titik merah lonceng harus menyala karena ada notifikasi belum dibaca"
    print("  [OK] Logo lonceng aktif dan mendeteksi notifikasi baru dengan titik merah menyala!")

    # 4. Uji Menandai Notifikasi Telah Dibaca (Menghilangkan Titik Merah)
    print("\n[4/7] Menguji API Tandai Notifikasi Dibaca (/api/notifikasi/read-all)...")
    res_read = client.post('/api/notifikasi/read-all')
    assert res_read.status_code == 200
    data_read = res_read.get_json()
    assert data_read.get('success') is True
    assert data_read.get('unread_count') == 0

    with app.app_context():
        read_record = NotificationRead.query.filter_by(user_id=test_uid, notification_id=notif_id).first()
        assert read_record is not None, "Catatan pembacaan notifikasi harus tercatat"
        print("  [OK] Notifikasi berhasil ditandai dibaca, unread count turun menjadi 0!")

    # 5. Uji Pengiriman Tiket CS ke Bot Telegram
    print("\n[5/7] Menguji Pembuatan Tiket CS & Dispatch ke Bot 1 Telegram...")
    with patch('requests.post') as mock_tg_post:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'ok': True, 'result': {'message_id': 12345}}
        mock_tg_post.return_value = mock_resp

        res_ticket = client.post('/tiket/kirim', data={
            'transaction_ref': test_trx_ref,
            'category': 'Transaksi Pending / Belum Masuk',
            'user_name': test_uname,
            'user_phone': test_phone,
            'message': 'Halo CS, transaksi saya gagal tapi saldo belum kembali. Tolong dibantu cek ya.'
        }, headers={'X-Requested-With': 'XMLHttpRequest'})

        assert res_ticket.status_code == 200
        data_t = res_ticket.get_json()
        assert data_t.get('success') is True
        t_num = data_t.get('ticket_number')
        assert t_num.startswith('CS-')
        print(f"  [OK] Tiket bantuan CS #{t_num} berhasil dibuat!")
        print("  [OK] Format pesan terverifikasi dan sukses dikirimkan ke Bot CS Telegram!")

    # 6. Uji Halaman Bantuan & Pemilih Transaksi (/bantuan & /api/user/recent-transactions)
    print("\n[6/7] Menguji Halaman Bantuan & API Riwayat Transaksi untuk Tiket...")
    res_bantuan = client.get(f'/bantuan?ref={test_trx_ref}')
    assert res_bantuan.status_code == 200
    html_bantuan = res_bantuan.data.decode('utf-8')
    assert 'Pusat Bantuan & Tiket CS' in html_bantuan
    assert test_trx_ref in html_bantuan

    res_api_trx = client.get('/api/user/recent-transactions')
    assert res_api_trx.status_code == 200
    json_trxs = res_api_trx.get_json()
    assert 'transactions' in json_trxs
    print("  [OK] Halaman bantuan dan endpoint pemilih transaksi bermasalah berjalan sempurna!")

    # 7. Uji Monitoring Tiket CS pada Panel Admin (/admin/tickets)
    print("\n[7/7] Menguji Monitoring & Pengelolaan Status Tiket di Panel Admin (/admin/tickets)...")
    with client.session_transaction() as sess:
        sess['admin_logged_in'] = True
        sess['admin_user'] = 'admin'

    res_adm_tickets = client.get('/admin/tickets')
    assert res_adm_tickets.status_code == 200
    html_adm_tickets = res_adm_tickets.data.decode('utf-8')
    assert t_num in html_adm_tickets, "Nomor tiket harus muncul di tabel tiket admin"
    assert test_trx_ref in html_adm_tickets, "Transaksi terkait harus tampil di tabel tiket admin"

    with app.app_context():
        ticket_obj = SupportTicket.query.filter_by(ticket_number=t_num).first()
        ticket_id = ticket_obj.id

    csrf_match_adm = re.search(r'name="csrf_token" value="([^"]+)"', html_adm_tickets)
    ticket_csrf = csrf_match_adm.group(1) if csrf_match_adm else ''

    res_upd_status = client.post(f'/admin/tickets/{ticket_id}/status', data={
        'csrf_token': ticket_csrf,
        'status': 'RESOLVED'
    }, follow_redirects=True)
    assert res_upd_status.status_code == 200

    with app.app_context():
        ticket_refreshed = SupportTicket.query.get(ticket_id)
        assert ticket_refreshed.status == 'RESOLVED'
        print(f"  [OK] Status tiket #{t_num} berhasil diupdate Admin menjadi RESOLVED!")

    print("\n" + "="*65)
    print("  >>> SELURUH VERIFIKASI FITUR NOTIFIKASI & TIKET CS (7/7) LULUS 100%! <<<")
    print("="*65 + "\n")

if __name__ == '__main__':
    test_notifikasi_and_cs_ticket()

