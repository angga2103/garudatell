import os
import sys
import time
import random
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.notification import Notification, NotificationRead
from app.models.support_ticket import SupportTicket
from app.routes.user import get_user_notifications

class TestNotificationFiltering(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Dummy user
        self.user = User.query.filter_by(phone="08999998888").first()
        if not self.user:
            self.user = User(
                name="Test Notif User",
                phone="08999998888",
                email="notifuser@example.com",
                balance=100000.0,
                role="MEMBER",
                is_active=True
            )
            self.user.set_password("pass123")
            db.session.add(self.user)
            db.session.commit()

        # Bersihkan notifikasi & tiket uji coba sebelumnya untuk user ini
        Notification.query.filter_by(target_user_id=self.user.id).delete()
        SupportTicket.query.filter_by(user_id=self.user.id).delete()
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        # Bersihkan data uji coba
        if self.user:
            Notification.query.filter_by(target_user_id=self.user.id).delete()
            SupportTicket.query.filter_by(user_id=self.user.id).delete()
            db.session.commit()
        self.app_context.pop()

    def test_notification_age_filter_less_than_5_days(self):
        # 1. Notifikasi berumur 6 hari yang lalu (harus TIDAK tampil)
        n_old = Notification(
            title="Promo 6 Hari Lalu",
            message="Pesan promo usang",
            type="promo",
            target_user_id=self.user.id,
            is_broadcast=False,
            created_at=datetime.utcnow() - timedelta(days=6)
        )
        # 2. Notifikasi berumur 2 hari yang lalu (harus TAMPIL)
        n_new = Notification(
            title="Promo 2 Hari Lalu",
            message="Pesan promo aktif",
            type="promo",
            target_user_id=self.user.id,
            is_broadcast=False,
            created_at=datetime.utcnow() - timedelta(days=2)
        )
        db.session.add_all([n_old, n_new])
        db.session.commit()

        notifs, unread_count, _ = get_user_notifications(self.user.id)
        notif_ids = [n.id for n in notifs]

        self.assertNotIn(n_old.id, notif_ids, "Notifikasi > 5 hari seharusnya tidak muncul!")
        self.assertIn(n_new.id, notif_ids, "Notifikasi < 5 hari seharusnya muncul!")

    def test_cs_ticket_notification_filtering_by_status(self):
        ts = int(time.time())
        num_open = f"CS-{ts}-101"
        num_proc = f"CS-{ts}-202"
        num_res = f"CS-{ts}-303"
        num_cls = f"CS-{ts}-404"

        # Buat tiket dengan berbagai status
        t_open = SupportTicket(
            ticket_number=num_open,
            user_id=self.user.id,
            user_name=self.user.name,
            user_phone=self.user.phone,
            message="Kendala transaksi open",
            status="OPEN"
        )
        t_process = SupportTicket(
            ticket_number=num_proc,
            user_id=self.user.id,
            user_name=self.user.name,
            user_phone=self.user.phone,
            message="Kendala transaksi diproses",
            status="PROCESS"
        )
        t_resolved = SupportTicket(
            ticket_number=num_res,
            user_id=self.user.id,
            user_name=self.user.name,
            user_phone=self.user.phone,
            message="Kendala transaksi selesai",
            status="RESOLVED"
        )
        t_closed = SupportTicket(
            ticket_number=num_cls,
            user_id=self.user.id,
            user_name=self.user.name,
            user_phone=self.user.phone,
            message="Kendala transaksi ditutup",
            status="CLOSED"
        )
        db.session.add_all([t_open, t_process, t_resolved, t_closed])
        db.session.commit()

        # Buat notifikasi untuk masing-masing tiket (semua dibuat 1 hari yang lalu)
        one_day_ago = datetime.utcnow() - timedelta(days=1)
        n_open = Notification(
            title=f"Tiket #{t_open.ticket_number} Diterima",
            message="Tiket Anda sedang kami telusuri",
            link="/bantuan",
            target_user_id=self.user.id,
            is_broadcast=False,
            created_at=one_day_ago
        )
        n_process = Notification(
            title=f"Balasan CS: Tiket #{t_process.ticket_number}",
            message="Laporan sedang diinvestigasi ke provider",
            link="/bantuan",
            target_user_id=self.user.id,
            is_broadcast=False,
            created_at=one_day_ago
        )
        n_resolved = Notification(
            title=f"Balasan CS: Tiket #{t_resolved.ticket_number}",
            message="Kendala pada transaksi ini telah berhasil diselesaikan",
            link="/bantuan",
            target_user_id=self.user.id,
            is_broadcast=False,
            created_at=one_day_ago
        )
        n_closed = Notification(
            title=f"Balasan CS: Tiket #{t_closed.ticket_number}",
            message="Tiket telah ditutup oleh sistem",
            link="/bantuan",
            target_user_id=self.user.id,
            is_broadcast=False,
            created_at=one_day_ago
        )
        db.session.add_all([n_open, n_process, n_resolved, n_closed])
        db.session.commit()

        # Jalankan get_user_notifications
        notifs, unread_count, _ = get_user_notifications(self.user.id)
        notif_ids = [n.id for n in notifs]

        # Tiket OPEN dan PROCESS HARUS tampil
        self.assertIn(n_open.id, notif_ids, "Notifikasi tiket OPEN harus tampil!")
        self.assertIn(n_process.id, notif_ids, "Notifikasi tiket PROCESS harus tampil!")

        # Tiket RESOLVED dan CLOSED TIDAK BOLEH tampil
        self.assertNotIn(n_resolved.id, notif_ids, "Notifikasi tiket RESOLVED tidak boleh tampil!")
        self.assertNotIn(n_closed.id, notif_ids, "Notifikasi tiket CLOSED tidak boleh tampil!")

        # Cek atribut ticket_status yang disematkan
        open_item = next(item for item in notifs if item.id == n_open.id)
        process_item = next(item for item in notifs if item.id == n_process.id)
        self.assertEqual(open_item.ticket_status, "OPEN")
        self.assertEqual(process_item.ticket_status, "PROCESS")

    def test_notifikasi_endpoint_renders_and_badges(self):
        ts = int(time.time())
        t_active = SupportTicket(
            ticket_number=f"CS-{ts}-505",
            user_id=self.user.id,
            user_name=self.user.name,
            user_phone=self.user.phone,
            message="Kendala aktif",
            status="PROCESS"
        )
        db.session.add(t_active)
        db.session.commit()

        n_active = Notification(
            title=f"Balasan CS: Tiket #{t_active.ticket_number}",
            message="Halo kak, sedang kami bantu cek ke biller ya",
            link="/bantuan",
            target_user_id=self.user.id,
            is_broadcast=False,
            created_at=datetime.utcnow() - timedelta(hours=2)
        )
        db.session.add(n_active)
        db.session.commit()

        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(self.user.id)
            sess['_fresh'] = True

        res = client.get('/notifikasi')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn(t_active.ticket_number, html)
        self.assertIn("Diproses", html)

        # Cek API unread-count
        res_api = client.get('/api/notifikasi/unread-count')
        self.assertEqual(res_api.status_code, 200)
        data = res_api.get_json()
        self.assertTrue(data['success'])
        self.assertGreaterEqual(data['unread_count'], 1)

if __name__ == '__main__':
    unittest.main()
