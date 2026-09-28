import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
from unittest.mock import patch, MagicMock
from app import create_app
from app.extensions import db
from app.models.support_ticket import SupportTicket
from app.models.user import User
from app.models.transaction import Transaction
from app.services.telegram_service import handle_cs_bot_update, send_cs_ticket

def test_cs_two_way():
    app = create_app()
    with app.app_context():
        client = app.test_client()

        print("=== 1. TEST POST /tiket/kirim (User sends ticket on web) ===")
        u = User.query.first()
        trx = Transaction.query.filter_by(user_id=u.id).first() if u else None

        with client.session_transaction() as sess:
            sess['_user_id'] = str(u.id) if u else '1'
            sess['_fresh'] = True

        with patch('requests.post') as mock_post:
            mock_post.return_value.json.return_value = {'ok': True, 'result': {'message_id': 9999}}
            res_kirim = client.post('/tiket/kirim', data={
                'transaction_ref': trx.ref_id if trx else 'NONE',
                'category': 'Transaksi Pending / Belum Masuk',
                'user_name': 'Tester 2 Arah',
                'user_phone': '081234567899',
                'message': 'Mohon bantuannya min pulsa belum masuk dari tadi'
            }, headers={'X-Requested-With': 'XMLHttpRequest'})

            assert res_kirim.status_code == 200
            data_k = res_kirim.get_json()
            assert data_k.get('success') is True
            t_num = data_k.get('ticket_number')
            auto_reply = data_k.get('auto_reply')
            print(f"  [PASS] Tiket #{t_num} berhasil dibuat!")
            print(f"  [PASS] Balasan otomatis formalitas sistem: \"{auto_reply}\"")

            # Verify payload sent to Telegram had NO whatsapp links
            args, kwargs = mock_post.call_args
            tg_payload = kwargs.get('json', {})
            tg_text = tg_payload.get('text', '')
            assert 'wa.me' not in tg_text, "wa.me should NOT be in telegram message"
            assert 'Hubungi WhatsApp Pelapor' not in str(tg_payload), "WhatsApp button should NOT be in inline keyboard"
            print("  [PASS] Pesan ke Bot 1 Telegram TIDAK memiliki link atau tombol WhatsApp!")

        print("\n=== 2. TEST BOT 1 CS RECEIVING MANUAL ADMIN REPLY FROM TELEGRAM ===")
        # Admin replies to the ticket message in Telegram:
        sample_admin_reply_update = {
            'update_id': 1001,
            'message': {
                'message_id': 5555,
                'chat': {'id': 7236113204},
                'from': {'id': 1234, 'first_name': 'Admin Super', 'username': 'admin_garuda'},
                'reply_to_message': {
                    'message_id': 9999,
                    'text': f"🎫 TIKET BANTUAN CS BARU #{t_num}\nPelapor: Tester 2 Arah\nDETAIL KELUHAN PENGGUNA:\n\"Mohon bantuannya min pulsa belum masuk dari tadi\""
                },
                'text': 'Halo kak, sudah kami push ulang ke provider dan statusnya SUKSES. SN: 123456789. Silakan dicek kembali ya kak.'
            }
        }

        with patch('requests.post') as mock_post:
            mock_post.return_value.json.return_value = {'ok': True}
            handle_cs_bot_update(app, sample_admin_reply_update, bot_token='test_token')

        # Verify Database state
        ticket = SupportTicket.query.filter_by(ticket_number=t_num).first()
        assert ticket.admin_reply is not None, "Admin reply must be saved in database"
        assert 'Halo kak, sudah kami push ulang' in ticket.admin_reply
        assert ticket.admin_name == 'Admin Super'
        assert ticket.status == 'PROCESS'
        print(f"  [PASS] Balasan manual Admin tersimpan di DB: \"{ticket.admin_reply}\"")
        print(f"  [PASS] Admin Replied At WIB: {ticket.admin_replied_at_wib}")
        print(f"  [PASS] Status tiket otomatis berubah ke: {ticket.status}")

        print("\n=== 2B. TEST BOT 1 CS CALLBACK BUTTON [SELESAIKAN TIKET] ===")
        sample_cb_update = {
            'update_id': 1002,
            'callback_query': {
                'id': 'cb_test_999',
                'from': {'id': 1234, 'first_name': 'Admin Super', 'username': 'admin_garuda'},
                'message': {'message_id': 9999, 'chat': {'id': 7236113204}},
                'data': f'reply_tpl:{t_num}:resolved'
            }
        }
        with patch('requests.post') as mock_post:
            mock_post.return_value.json.return_value = {'ok': True}
            handle_cs_bot_update(app, sample_cb_update, bot_token='test_token')

        db.session.expire_all()
        ticket = SupportTicket.query.filter_by(ticket_number=t_num).first()
        print(f"  [DEBUG] Status ticket setelah callback: {ticket.status}")
        assert ticket.status == 'RESOLVED', f"Status ticket harus berubah ke RESOLVED tapi didapat {ticket.status}"
        print(f"  [PASS] Klik tombol inline [✅ Selesaikan Tiket] sukses! Status: {ticket.status}")

        print("\n=== 2C. TEST BOT 1 CS CALLBACK BUTTON [BALAS MANUAL] ===")
        sample_prompt_update = {
            'update_id': 1003,
            'callback_query': {
                'id': 'cb_test_prompt',
                'from': {'id': 1234, 'first_name': 'Admin Super', 'username': 'admin_garuda'},
                'message': {'message_id': 9999, 'chat': {'id': 7236113204}},
                'data': f'reply_prompt:{t_num}'
            }
        }
        with patch('requests.post') as mock_post:
            mock_post.return_value.json.return_value = {'ok': True}
            handle_cs_bot_update(app, sample_prompt_update, bot_token='test_token')
            assert mock_post.called
            calls = [c[1].get('json', {}) for c in mock_post.call_args_list]
            prompt_sent = any(f"/balas {t_num}" in c.get('text', '') for c in calls)
            assert prompt_sent, "Pesan panduan balas manual dengan format /balas harus dikirim ke Telegram"
        print("  [PASS] Klik tombol inline [✍️ Balas Manual] mengirimkan panduan /balas ke Telegram!")

        print("\n=== 2D. TEST COMMAND /balas CS-XXXX (PERSIS SEPERTI DI SCREENSHOT) ===")
        sample_cmd_update = {
            'update_id': 1004,
            'message': {
                'message_id': 5556,
                'chat': {'id': 7236113204},
                'from': {'id': 1234, 'first_name': 'Admin Super', 'username': 'admin_garuda'},
                'text': f"/balas {t_num} penyesuaian saldo ini kaka"
            }
        }
        with patch('requests.post') as mock_post:
            mock_post.return_value.json.return_value = {'ok': True}
            handle_cs_bot_update(app, sample_cmd_update, bot_token='test_token')

        db.session.expire_all()
        ticket = SupportTicket.query.filter_by(ticket_number=t_num).first()
        assert "penyesuaian saldo ini kaka" in ticket.admin_reply
        print(f"  [PASS] Perintah /balas {t_num} sukses tersimpan di DB: \"{ticket.admin_reply}\"")

        print("\n=== 3. TEST WEB API /api/tiket/<num> & /api/tiket/user-tickets ===")
        res_api_single = client.get(f'/api/tiket/{t_num}')
        assert res_api_single.status_code == 200
        json_single = res_api_single.get_json()
        assert json_single.get('has_admin_reply') is True
        assert json_single.get('admin_reply') == ticket.admin_reply
        print("  [PASS] API /api/tiket/<num> mengembalikan detail balasan admin lengkap!")

        res_api_list = client.get('/api/tiket/user-tickets')
        assert res_api_list.status_code == 200
        json_list = res_api_list.get_json()
        assert len(json_list.get('tickets', [])) > 0
        print("  [PASS] API /api/tiket/user-tickets mengembalikan tiket untuk live auto-polling!")

        print("\n=== 4. TEST HALAMAN /bantuan WEB USER ===")
        res_bantuan = client.get('/bantuan')
        assert res_bantuan.status_code == 200
        html_bantuan = res_bantuan.data.decode('utf-8')
        assert 'wa-direct-box' not in html_bantuan, "wa-direct-box harus sudah hilang dari halaman bantuan"
        assert 'Butuh Bantuan Mendesak?' not in html_bantuan, "Kolom Butuh Bantuan Mendesak WA harus hilang"
        assert 'Pusat Komplain & Balasan CS (2 Arah)' in html_bantuan
        assert t_num in html_bantuan
        assert 'Halo kak, sudah kami push ulang' in html_bantuan
        print("  [PASS] Halaman /bantuan bebas dari kolom WhatsApp & menampilkan chat 2 arah dengan sempurna!")

        print("\n======================================================")
        print("   SELURUH PENGUJIAN ALUR 2 ARAH CS BERHASIL 100%!   ")
        print("======================================================")

if __name__ == '__main__':
    test_cs_two_way()
