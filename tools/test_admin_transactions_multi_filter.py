import os
import sys
import unittest
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse
import re

# Ensure root dir is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.product import Product
from app.models.transaction import Transaction

class TestAdminTransactionsMultiFilter(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'TESTING': True,
            'WTF_CSRF_ENABLED': False
        })
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

        # 1. Setup Test Users (Stores)
        self.store_ngoro = User(
            name="Toko Ngoro",
            phone="081299990011",
            balance=500000.0,
            role="reseller",
            is_active=True
        )
        self.store_ngoro.set_password("pass123")

        self.store_lain = User(
            name="Toko Mojokerto",
            phone="081299990022",
            balance=250000.0,
            role="user",
            is_active=True
        )
        self.store_lain.set_password("pass123")

        db.session.add_all([self.store_ngoro, self.store_lain])
        db.session.commit()

        # 2. Setup Test Products
        self.prod_amazone = Product(
            sku_code="AMZ10K",
            name="Pulsa Amazone 10K",
            category="Pulsa",
            brand="Telkomsel",
            seller_name="amazone",
            base_price=10000.0,
            sell_price=11000.0,
            is_active=True
        )
        self.prod_digipro = Product(
            sku_code="DGP10K",
            name="Pulsa DigiPro 10K",
            category="Pulsa",
            brand="Telkomsel",
            seller_name="digipro",
            base_price=10000.0,
            sell_price=11000.0,
            is_active=True
        )
        db.session.add_all([self.prod_amazone, self.prod_digipro])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _make_trx(self, ref_id, user_id, amount=10000.0, status="SUCCESS", payment_status="PAID",
                  seller_name="amazone", sku_code="AMZ10K", created_at=None, **kwargs):
        return Transaction(
            ref_id=ref_id,
            user_id=user_id,
            sku_code=sku_code,
            product_name="Pulsa Test",
            target_number="081234567890",
            amount=amount,
            payment_method="BALANCE",
            payment_status=payment_status,
            status=status,
            seller_name=seller_name,
            created_at=created_at or datetime.utcnow(),
            **kwargs
        )

    def test_multi_filter_exact_scenario(self):
        """
        Pengujian skenario tepat user:
        Toko Ngoro + Tanggal 13 Oktober 2026 + Status GAGAL + Seller Amazone
        """
        # Tanggal target: 13 Oktober 2026 WIB
        # WIB adalah UTC+7, jadi 13 Oktober 2026 10:00 WIB = 13 Oktober 2026 03:00 UTC
        dt_13_okt_wib_morning = datetime(2026, 10, 13, 3, 0, 0) # 10:00 WIB
        dt_13_okt_wib_night = datetime(2026, 10, 13, 14, 0, 0)   # 21:00 WIB
        dt_12_okt_wib = datetime(2026, 10, 12, 10, 0, 0)         # 17:00 WIB (kemarin)

        # Trx 1: MATCH (Toko Ngoro, 13 Okt, GAGAL, amazone)
        t1 = self._make_trx("TRX-MATCH-01", self.store_ngoro.id, status="FAILED", seller_name="amazone", created_at=dt_13_okt_wib_morning)

        # Trx 2: MATCH (Toko Ngoro, 13 Okt, GAGAL, Amazone uppercase)
        t2 = self._make_trx("TRX-MATCH-02", self.store_ngoro.id, status="FAILED", seller_name="Amazone", created_at=dt_13_okt_wib_night)

        # Trx 3: BUKAN MATCH - Toko beda (Toko Mojokerto)
        t3 = self._make_trx("TRX-FAIL-STORE", self.store_lain.id, status="FAILED", seller_name="amazone", created_at=dt_13_okt_wib_morning)

        # Trx 4: BUKAN MATCH - Tanggal beda (12 Okt)
        t4 = self._make_trx("TRX-FAIL-DATE-12", self.store_ngoro.id, status="FAILED", seller_name="amazone", created_at=dt_12_okt_wib)

        # Trx 5: BUKAN MATCH - Status beda (SUCCESS)
        t5 = self._make_trx("TRX-FAIL-STATUS", self.store_ngoro.id, status="SUCCESS", seller_name="amazone", created_at=dt_13_okt_wib_morning)

        # Trx 6: BUKAN MATCH - Seller beda (digipro)
        t6 = self._make_trx("TRX-FAIL-SELLER", self.store_ngoro.id, status="FAILED", seller_name="digipro", sku_code="DGP10K", created_at=dt_13_okt_wib_morning)

        db.session.add_all([t1, t2, t3, t4, t5, t6])
        db.session.commit()

        # Query dengan multi-filter: Toko Ngoro, 13 Okt, FAILED, amazone
        url = f"/admin/transactions?store_id={self.store_ngoro.id}&start_date=2026-10-13&end_date=2026-10-13&status=FAILED&seller=amazone"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        # Harus memuat TRX-MATCH-01 dan TRX-MATCH-02
        self.assertIn("TRX-MATCH-01", res.text)
        self.assertIn("TRX-MATCH-02", res.text)

        # Tidak boleh memuat transaksi lain
        self.assertNotIn("TRX-FAIL-STORE", res.text)
        self.assertNotIn("TRX-FAIL-DATE-12", res.text)
        self.assertNotIn("TRX-FAIL-STATUS", res.text)
        self.assertNotIn("TRX-FAIL-SELLER", res.text)

        # Cek badge filter aktif muncul di halaman
        self.assertIn("Toko:", res.text)
        self.assertIn("Toko Ngoro", res.text)
        self.assertIn("2026-10-13", res.text)
        self.assertIn("amazone", res.text)
        self.assertIn("FAILED", res.text)

    def test_wib_boundary_conversion(self):
        """
        Pengujian konversi batas waktu WIB ke UTC:
        13 Oktober 2026 00:00:01 WIB = 12 Oktober 2026 17:00:01 UTC (harus MASUK)
        13 Oktober 2026 23:59:50 WIB = 13 Oktober 2026 16:59:50 UTC (harus MASUK)
        12 Oktober 2026 23:59:50 WIB = 12 Oktober 2026 16:59:50 UTC (harus KELUAR)
        14 Oktober 2026 00:00:10 WIB = 13 Oktober 2026 17:00:10 UTC (harus KELUAR)
        """
        t_early_in = self._make_trx("TRX-WIB-EARLY-IN", self.store_ngoro.id, status="FAILED", created_at=datetime(2026, 10, 12, 17, 0, 1))
        t_late_in = self._make_trx("TRX-WIB-LATE-IN", self.store_ngoro.id, status="FAILED", created_at=datetime(2026, 10, 13, 16, 59, 50))
        t_just_before = self._make_trx("TRX-WIB-JUST-BEFORE", self.store_ngoro.id, status="FAILED", created_at=datetime(2026, 10, 12, 16, 59, 50))
        t_just_after = self._make_trx("TRX-WIB-JUST-AFTER", self.store_ngoro.id, status="FAILED", created_at=datetime(2026, 10, 13, 17, 0, 10))

        db.session.add_all([t_early_in, t_late_in, t_just_before, t_just_after])
        db.session.commit()

        url = f"/admin/transactions?store_id={self.store_ngoro.id}&start_date=2026-10-13&end_date=2026-10-13"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        self.assertIn("TRX-WIB-EARLY-IN", res.text)
        self.assertIn("TRX-WIB-LATE-IN", res.text)
        self.assertNotIn("TRX-WIB-JUST-BEFORE", res.text)
        self.assertNotIn("TRX-WIB-JUST-AFTER", res.text)

    def test_status_alias_gagal_and_seller_case_insensitive(self):
        """
        Pengujian filter status alias:
        status=GAGAL harus memfilter transaksi FAILED / GAGAL / CANCELLED / BATAL.
        seller=AMAZONE (uppercase) harus cocok dengan seller 'amazone'.
        """
        t_gagal = self._make_trx("TRX-STATUS-GAGAL", self.store_ngoro.id, status="FAILED", seller_name="amazone")
        t_sukses = self._make_trx("TRX-STATUS-SUKSES", self.store_ngoro.id, status="SUCCESS", seller_name="amazone")
        db.session.add_all([t_gagal, t_sukses])
        db.session.commit()

        # Gunakan status=GAGAL dan seller=AMAZONE
        url = f"/admin/transactions?status=GAGAL&seller=AMAZONE"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        self.assertIn("TRX-STATUS-GAGAL", res.text)
        self.assertNotIn("TRX-STATUS-SUKSES", res.text)

    def test_pagination_parameter_preservation(self):
        """
        PENGUJIAN UTAMA PERBAIKAN BUG PAGINATION:
        Memastikan tombol 'Berikutnya', 'Sebelumnya', dan nomor halaman
        100% membawa seluruh parameter filter aktif (store_id, start_date, end_date, status, seller).
        Halaman ke-2 harus TETAP terfilter hanya untuk Toko Ngoro dan kriteria lainnya.
        """
        # Buat 30 transaksi yang MATCH kriteria Toko Ngoro + FAILED + amazone + 13 Okt
        base_time = datetime(2026, 10, 13, 5, 0, 0)
        match_trxs = []
        for i in range(1, 31):
            t = self._make_trx(
                ref_id=f"TRX-NGORO-PAGINATE-{i:02d}",
                user_id=self.store_ngoro.id,
                amount=10000.0,
                status="FAILED",
                payment_status="PAID",
                seller_name="amazone",
                created_at=base_time + timedelta(minutes=i)
            )
            match_trxs.append(t)

        # Buat 10 transaksi Toko Lain yang FAILED (untuk memastikan halaman 2 tidak bocor ke toko lain)
        other_trxs = []
        for i in range(1, 11):
            t = self._make_trx(
                ref_id=f"TRX-LAIN-PAGINATE-{i:02d}",
                user_id=self.store_lain.id,
                amount=10000.0,
                status="FAILED",
                payment_status="PAID",
                seller_name="amazone",
                created_at=base_time + timedelta(minutes=i)
            )
            other_trxs.append(t)

        db.session.add_all(match_trxs + other_trxs)
        db.session.commit()

        # Buka Halaman 1 dengan Filter Lengkap
        url_page1 = f"/admin/transactions?store_id={self.store_ngoro.id}&start_date=2026-10-13&end_date=2026-10-13&status=FAILED&seller=amazone&page=1"
        res1 = self.client.get(url_page1)
        self.assertEqual(res1.status_code, 200)

        # Cek Total Transaksi di pagination bar (Harus 30, bukan 40)
        self.assertIn("Total: <b>30</b> transaksi", res1.text)
        self.assertIn("Menampilkan halaman <b>1</b> dari <b>2</b>", res1.text)

        # Verifikasi bahwa tombol 'Berikutnya' memiliki link yang membawa SEMUA query param
        next_links = re.findall(r'href="([^"]+)"[^>]*title="Halaman Berikutnya"', res1.text)
        self.assertTrue(len(next_links) >= 1, "Tombol 'Halaman Berikutnya' tidak ditemukan di HTML!")
        next_href = next_links[0].replace('&amp;', '&')

        parsed_url = urlparse(next_href)
        params = parse_qs(parsed_url.query)

        # Pastikan parameter page bernilai 2
        self.assertEqual(params.get('page'), ['2'])
        # Pastikan store_id terbawa
        self.assertEqual(params.get('store_id'), [str(self.store_ngoro.id)])
        # Pastikan start_date dan end_date terbawa
        self.assertEqual(params.get('start_date'), ['2026-10-13'])
        self.assertEqual(params.get('end_date'), ['2026-10-13'])
        # Pastikan status FAILED terbawa
        self.assertEqual(params.get('status'), ['FAILED'])
        # Pastikan seller amazone terbawa
        self.assertEqual(params.get('seller'), ['amazone'])

        # SEKARANG KLIK HALAMAN 2:
        res2 = self.client.get(next_href)
        self.assertEqual(res2.status_code, 200)

        # Halaman 2 HARUS menampilkan kelanjutan sisa 5 transaksi Toko Ngoro (30 total - 25 per page = 5)
        self.assertIn("Menampilkan halaman <b>2</b> dari <b>2</b>", res2.text)
        # Transaksi pertama yang dibuat (ref TRX-NGORO-PAGINATE-01 s/d 05 karena order desc) ada di page 2
        self.assertIn("TRX-NGORO-PAGINATE-01", res2.text)
        self.assertIn("TRX-NGORO-PAGINATE-05", res2.text)

        # SANGAT PENTING: Halaman 2 TIDAK BOLEH memuat satupun transaksi dari Toko Lain!
        self.assertNotIn("TRX-LAIN-PAGINATE", res2.text)

        # Periksa tombol 'Sebelumnya' pada Halaman 2
        prev_links = re.findall(r'href="([^"]+)"[^>]*title="Halaman Sebelumnya"', res2.text)
        self.assertTrue(len(prev_links) >= 1, "Tombol 'Halaman Sebelumnya' tidak ditemukan di Halaman 2!")
        prev_href = prev_links[0].replace('&amp;', '&')
        params_prev = parse_qs(urlparse(prev_href).query)

        self.assertEqual(params_prev.get('page'), ['1'])
        self.assertEqual(params_prev.get('store_id'), [str(self.store_ngoro.id)])
        self.assertEqual(params_prev.get('seller'), ['amazone'])
        self.assertEqual(params_prev.get('status'), ['FAILED'])
        self.assertEqual(params_prev.get('start_date'), ['2026-10-13'])

        print("\n[OK] Bug Pagination TERSELESAIKAN: Seluruh parameter multi-filter bertahan 100% pada navigasi halaman!")

if __name__ == '__main__':
    unittest.main()
