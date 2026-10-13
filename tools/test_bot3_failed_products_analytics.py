#!/usr/bin/env python3
"""
Pengujian End-to-End 100% untuk Fitur Laporan Analisa Produk & Seller Sering Gagal
pada Bot 3 : Panel & Fitur Admin Telegram (GarudaTel v2).
"""
import os
import sys
from unittest.mock import patch, MagicMock

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.product import Product
from app.models.transaction import Transaction
from app.services.telegram_service import (
    get_bot_admin_credentials,
    get_admin_inline_keyboard,
    format_seller_handle_and_name,
    get_failed_products_analytics,
    render_failed_products_report,
    render_failed_product_detail,
    render_failed_sellers_report,
    get_disabled_sellers_list,
    render_disabled_catalog_sellers_menu,
    render_disabled_catalog_seller_products,
    handle_admin_callback,
    handle_admin_message,
)


def assert_valid_telegram_keyboard(markup):
    """Memastikan seluruh callback_data di bawah batas 64 byte resmi API Telegram."""
    assert isinstance(markup, dict) and 'inline_keyboard' in markup
    for row in markup['inline_keyboard']:
        for btn in row:
            if 'callback_data' in btn:
                cb_bytes = len(btn['callback_data'].encode('utf-8'))
                assert cb_bytes <= 64, f"callback_data > 64 bytes ({cb_bytes}): {btn['callback_data']}"


def run_all_tests():
    app = create_app()
    with app.app_context():
        print("=" * 72)
        print("PENGUJIAN BOT 3 : PANEL & FITUR ADMIN - ANALISA PRODUK & SELLER GAGAL")
        print("=" * 72)

        test_sku_1 = 'TEST_TSEL_UMKM_4GB_30H'
        test_sku_2 = 'TEST_ISAT_FREEDOM_10GB'
        test_sku_3 = 'TEST_XL_XTRA_COMBO_20GB'
        test_sku_normal = 'TEST_PFAST_NORMAL_PULSA'

        # Bersihkan sisa data tes jika ada
        Product.query.filter(Product.sku_code.in_([test_sku_1, test_sku_2, test_sku_3, test_sku_normal])).delete(synchronize_session=False)
        Transaction.query.filter(Transaction.sku_code.in_([test_sku_1, test_sku_2, test_sku_3, test_sku_normal])).delete(synchronize_session=False)
        db.session.commit()

        p1 = Product(
            sku_code=test_sku_1,
            name='Telkomsel Data UMKM 4GB 30 Hari',
            category='Data',
            brand='TELKOMSEL',
            base_price=28500,
            sell_price=30000,
            seller_name='Payfast Official',
            is_active=True
        )
        p2 = Product(
            sku_code=test_sku_2,
            name='Indosat Freedom Internet 10GB',
            category='Data',
            brand='INDOSAT',
            base_price=42000,
            sell_price=44000,
            seller_name='Sumber Reload',
            is_active=True
        )
        p3 = Product(
            sku_code=test_sku_3,
            name='XL Xtra Combo Plus 20GB',
            category='Data',
            brand='XL',
            base_price=55000,
            sell_price=57500,
            seller_name='Payfast Official',
            is_active=True
        )
        p_norm = Product(
            sku_code=test_sku_normal,
            name='Pulsa Telkomsel 50rb Normal',
            category='Pulsa',
            brand='TELKOMSEL',
            base_price=49800,
            sell_price=51000,
            seller_name='Payfast Official',
            is_active=True
        )
        db.session.add_all([p1, p2, p3, p_norm])
        db.session.commit()

        # Transaksi Sukses Normal untuk p_norm (10x sukses, 0x gagal)
        for i in range(10):
            db.session.add(Transaction(
                user_id=1,
                ref_id=f'TEST-B3-SUCC-NORM-{i}',
                sku_code=test_sku_normal,
                product_name='Pulsa Telkomsel 50rb Normal',
                target_number=f'08121111222{i}',
                amount=51000,
                base_price=49800,
                status='SUCCESS',
                payment_method='saldo',
                payment_status='PAID',
                sn=f'SN-NORM-{i}',
                seller_name='Payfast Official',
                seller_tele='@payfast_id'
            ))

        # Skenario 1: Telkomsel Data UMKM 4GB 30 Hari -> 9 kali gagal, 1 kali sukses • seller@payfast_id (CRITICAL)
        for i in range(9):
            db.session.add(Transaction(
                user_id=1,
                ref_id=f'TEST-B3-FAIL-TSEL-{i}',
                sku_code=test_sku_1,
                product_name='Telkomsel Data UMKM 4GB 30 Hari',
                target_number=f'08123456780{i}',
                amount=30000,
                base_price=28500,
                status='FAILED',
                payment_method='saldo',
                payment_status='REFUNDED',
                sn='RC 55: Produk sedang gangguan dari seller',
                seller_name='Payfast Official',
                seller_tele='@payfast_id',
                seller_wa='081299998888'
            ))
        db.session.add(Transaction(
            user_id=1,
            ref_id='TEST-B3-SUCC-TSEL-1',
            sku_code=test_sku_1,
            product_name='Telkomsel Data UMKM 4GB 30 Hari',
            target_number='081234567899',
            amount=30000,
            base_price=28500,
            status='SUCCESS',
            payment_method='saldo',
            payment_status='PAID',
            sn='SN1234567890',
            seller_name='Payfast Official',
            seller_tele='@payfast_id',
            seller_wa='081299998888'
        ))

        # Skenario 2: Indosat Freedom 10GB -> 2 kali gagal, 3 kali sukses (WARNING)
        for i in range(2):
            db.session.add(Transaction(
                user_id=1,
                ref_id=f'TEST-B3-FAIL-ISAT-{i}',
                sku_code=test_sku_2,
                product_name='Indosat Freedom Internet 10GB',
                target_number=f'08571234560{i}',
                amount=44000,
                base_price=42000,
                status='FAILED',
                payment_method='saldo',
                payment_status='REFUNDED',
                sn='RC 42: Cut off system',
                seller_name='Sumber Reload',
                seller_tele='@sumber_reload_cs'
            ))
        for i in range(3):
            db.session.add(Transaction(
                user_id=1,
                ref_id=f'TEST-B3-SUCC-ISAT-{i}',
                sku_code=test_sku_2,
                product_name='Indosat Freedom Internet 10GB',
                target_number=f'08571234569{i}',
                amount=44000,
                base_price=42000,
                status='SUCCESS',
                payment_method='saldo',
                payment_status='PAID',
                sn=f'SNISAT{i}',
                seller_name='Sumber Reload',
                seller_tele='@sumber_reload_cs'
            ))

        # Skenario 3: XL Xtra Combo -> 1 kali gagal, 9 kali sukses (INFO / MASIH LAYAK)
        db.session.add(Transaction(
            user_id=1,
            ref_id='TEST-B3-FAIL-XL-0',
            sku_code=test_sku_3,
            product_name='XL Xtra Combo Plus 20GB',
            target_number='087812345600',
            amount=57500,
            base_price=55000,
            status='FAILED',
            payment_method='saldo',
            payment_status='REFUNDED',
            sn='RC 42: Nomor tujuan salah',
            seller_name='Payfast Official',
            seller_tele='@payfast_id'
        ))
        for i in range(9):
            db.session.add(Transaction(
                user_id=1,
                ref_id=f'TEST-B3-SUCC-XL-{i}',
                sku_code=test_sku_3,
                product_name='XL Xtra Combo Plus 20GB',
                target_number=f'08781234569{i}',
                amount=57500,
                base_price=55000,
                status='SUCCESS',
                payment_method='saldo',
                payment_status='PAID',
                sn=f'SNXL{i}',
                seller_name='Payfast Official',
                seller_tele='@payfast_id'
            ))
        db.session.commit()

        try:
            # TEST 1: Tombol Menu Utama Bot 3
            kb_main = get_admin_inline_keyboard()
            assert_valid_telegram_keyboard(kb_main)
            cb_list = [b.get('callback_data') for r in kb_main['inline_keyboard'] for b in r]
            assert 'cmd_failed_products' in cb_list
            assert 'cmd_disabled_catalog' in cb_list
            print("[LULUS 1/11] Tombol '🚨 Analisa Produk & Seller Gagal' & '🔓 Kelola Produk Nonaktif' terdaftar di Menu Utama Bot 3.")

            # TEST 2: Format Seller Tag & Analytics Engine (CRITICAL, WARNING, INFO)
            analytics = get_failed_products_analytics(period='30d', filter_mode='all')
            item_tsel = next(x for x in analytics['items'] if x['sku_code'] == test_sku_1)
            item_isat = next(x for x in analytics['items'] if x['sku_code'] == test_sku_2)
            item_xl = next(x for x in analytics['items'] if x['sku_code'] == test_sku_3)

            assert item_tsel['compact_line'] == 'Telkomsel Data UMKM 4GB 30 Hari — 9 kali gagal, 1 kali sukses • seller@payfast_id'
            assert item_tsel['severity'] == 'CRITICAL' and item_tsel['fail_rate'] == 90.0
            assert item_isat['severity'] == 'WARNING' and item_isat['fail_rate'] == 40.0
            assert item_xl['severity'] == 'INFO' and item_xl['fail_rate'] == 10.0
            print("[LULUS 2/10] Mesin Analisa Kelayakan Produk (CRITICAL / WARNING / INFO) & seller@payfast_id akurat 100%.")

            # TEST 3: Render Laporan Utama & Filter Periode / Keparahan
            for p_code in ['1d', '7d', '30d', 'all']:
                rep_txt, rep_kb = render_failed_products_report(period=p_code, page=1, per_page=5, filter_mode='all')
                assert 'Telkomsel Data UMKM 4GB 30 Hari' in rep_txt
                assert '9 kali gagal' in rep_txt and '1 kali sukses' in rep_txt
                assert 'seller@payfast_id' in rep_txt
                assert_valid_telegram_keyboard(rep_kb)

            crit_txt, crit_kb = render_failed_products_report(period='30d', page=1, per_page=5, filter_mode='crit')
            assert 'Telkomsel Data UMKM 4GB 30 Hari' in crit_txt
            assert 'XL Xtra Combo Plus 20GB' not in crit_txt
            assert_valid_telegram_keyboard(crit_kb)
            print("[LULUS 3/10] Filter Periode (Hari Ini, 7 Hari, 30 Hari, Semua) & Filter Kritis berfungsi 100%.")

            # TEST 4: Render Detail Produk & Rapor Seller
            det_txt, det_kb = render_failed_product_detail(test_sku_1, period='30d')
            assert 'Telkomsel Data UMKM 4GB 30 Hari — 9 kali gagal, 1 kali sukses' in det_txt
            assert 'seller@payfast_id' in det_txt
            assert_valid_telegram_keyboard(det_kb)

            slr_txt, slr_kb = render_failed_sellers_report(period='30d', page=1)
            assert 'Payfast Official' in slr_txt and 'seller@payfast_id' in slr_txt
            assert_valid_telegram_keyboard(slr_kb)
            print("[LULUS 4/10] Halaman Detail Produk Gagal & Rapor Analisa Per Seller berfungsi 100%.")

            # Simulasi Interaksi Penuh di Bot 3 : Panel & Fitur Admin
            edits = []
            sends = []
            with patch('app.services.telegram_service.get_bot_admin_credentials', return_value=('BOT3_TOKEN', '999888')), \
                 patch('app.services.telegram_service._answer_callback'), \
                 patch('app.services.telegram_service._edit_message', side_effect=lambda tok, cid, mid, txt, mk=None: edits.append((txt, mk))), \
                 patch('app.services.telegram_service._send_message', side_effect=lambda tok, cid, txt, reply_markup=None: sends.append((txt, reply_markup))):

                # TEST 5: Klik Menu Utama & Klik Analisa Produk Gagal di Bot 3
                handle_admin_callback(app, {
                    'id': 'cb_menu',
                    'message': {'chat': {'id': '999888'}, 'message_id': 1},
                    'data': 'cmd_menu'
                })
                assert 'BOT 3 : PANEL & FITUR ADMIN GARUDATEL v2' in edits[-1][0]

                handle_admin_callback(app, {
                    'id': 'cb_fp',
                    'message': {'chat': {'id': '999888'}, 'message_id': 1},
                    'data': 'cmd_failed_products'
                })
                assert 'LAPORAN ANALISA PRODUK & SELLER SERING GAGAL' in edits[-1][0]
                print("[LULUS 5/10] Navigasi Menu Bot 3 -> Laporan Analisa Produk & Seller Gagal berfungsi 100%.")

                # TEST 6: Toggle Nonaktifkan & Aktifkan Produk (fp_tog)
                handle_admin_callback(app, {
                    'id': 'cb_tog1',
                    'message': {'chat': {'id': '999888'}, 'message_id': 1},
                    'data': f'fp_tog:30d:{test_sku_1}'
                })
                db.session.refresh(p1)
                assert p1.is_active is False
                assert 'NONAKTIF (Disembunyikan dari Web)' in edits[-1][0]

                handle_admin_callback(app, {
                    'id': 'cb_tog2',
                    'message': {'chat': {'id': '999888'}, 'message_id': 1},
                    'data': f'fp_tog:30d:{test_sku_1}'
                })
                db.session.refresh(p1)
                assert p1.is_active is True
                assert 'AKTIF (Ditampilkan di Web)' in edits[-1][0]
                print("[LULUS 6/10] Tombol 1-Klik Sembunyikan / Tampilkan Produk (fp_tog) berfungsi 100%.")

                # TEST 7: Sync Ulang Seller & Kontak dari Digiflazz (fp_sync) + Auto WA Komplain (fp_wa)
                with patch('app.services.digiflazz.get_price_list', return_value=(True, [{
                    'buyer_sku_code': test_sku_1,
                    'seller_name': 'Seller Baru Berkualitas',
                    'price': 28200,
                    'buyer_product_status': True,
                    'seller_product_status': True
                }], 'OK')), \
                     patch('app.services.digiflazz.check_transaction_status', return_value=(True, {
                         'seller_name': 'Seller Baru Berkualitas',
                         'tele': '@seller_baru_cs',
                         'wa': '081122334455',
                         'price': 28200
                     }, 'OK')):
                    handle_admin_callback(app, {
                        'id': 'cb_sync',
                        'message': {'chat': {'id': '999888'}, 'message_id': 1},
                        'data': f'fp_sync:30d:{test_sku_1}'
                    })
                    db.session.refresh(p1)
                    assert p1.seller_name == 'Seller Baru Berkualitas'
                    assert float(p1.base_price) == 28200.0
                    assert 'SINKRONISASI SKU & SELLER SELESAI!' in edits[-1][0]

                last_fail_trx = Transaction.query.filter_by(sku_code=test_sku_1, status='FAILED').order_by(Transaction.id.desc()).first()
                with patch('app.wa_helper.kirim_wa', return_value=True):
                    handle_admin_callback(app, {
                        'id': 'cb_wa',
                        'message': {'chat': {'id': '999888'}, 'message_id': 1},
                        'data': f'fp_wa:30d:{last_fail_trx.id}'
                    })
                    assert 'KOMPLAIN GAGAL TERKIRIM KE WA SELLER!' in edits[-1][0]
                print("[LULUS 7/10] Tombol Sync Ulang Seller Digiflazz (fp_sync) & Auto-Kirim WA Komplain (fp_wa) berfungsi 100%.")

                # TEST 8: Matikan Semua Produk Kritis Sekaligus (fp_offcrit) & Matikan Produk Per Seller (fp_slroff)
                handle_admin_callback(app, {
                    'id': 'cb_offcrit',
                    'message': {'chat': {'id': '999888'}, 'message_id': 1},
                    'data': 'fp_offcrit:30d'
                })
                db.session.refresh(p1)
                assert p1.is_active is False
                assert p1.is_admin_disabled is True, "Produk kritis yang dimatikan harus digembok dari auto-sync!"
                assert 'PRODUK KRITIS BERHASIL DINONAKTIFKAN!' in edits[-1][0]

                # UJI AMAN TOMBOL SELLER: Pastikan p_norm (produk sukses) tetap AKTIF saat seller dimatikan!
                db.session.refresh(p3)
                db.session.refresh(p_norm)
                assert p3.is_active is True
                assert p_norm.is_active is True

                xl_fail_trx = Transaction.query.filter_by(sku_code=test_sku_3, status='FAILED').first()
                handle_admin_callback(app, {
                    'id': 'cb_slroff',
                    'message': {'chat': {'id': '999888'}, 'message_id': 1},
                    'data': f'fp_slroff:30d:{xl_fail_trx.id}'
                })
                db.session.refresh(p3)
                db.session.refresh(p_norm)
                # Produk yang sering gagal dinonaktifkan & digembok:
                assert p3.is_active is False
                assert p3.is_admin_disabled is True, "Produk yang dimatikan via seller harus digembok dari auto-sync!"
                # PRODUK NORMAL TETAP AKTIF (100% AMAN!):
                assert p_norm.is_active is True, "Produk normal seller tidak boleh ikut dinonaktifkan!"
                assert 'DINONAKTIFKAN!' in edits[-1][0]

                # UJI PROTEKSI AUTO-SYNC DIGIFLAZZ:
                # Saat Auto-Sync Digiflazz berjalan dan produk di Digiflazz statusnya masih ON,
                # produk yang digembok (is_admin_disabled=True) DILARANG diaktifkan kembali!
                from app.services.digiflazz import sync_products
                with patch('app.services.digiflazz.get_price_list', return_value=(True, [{
                    'buyer_sku_code': test_sku_3,
                    'product_name': 'XL Xtra Combo Plus 20GB',
                    'category': 'Data',
                    'brand': 'XL',
                    'seller_name': 'Payfast Official',
                    'price': 55000,
                    'buyer_product_status': True,  # Di Digiflazz masih ON
                    'seller_product_status': True  # Di Digiflazz normal
                }], 'OK')):
                    sync_ok, _ = sync_products(force=True, notify_admin_bot=False)
                    db.session.refresh(p3)
                    assert p3.is_active is False, "Auto-Sync TIDAK BOLEH mengaktifkan produk yang digembok oleh Admin!"
                    assert p3.is_admin_disabled is True

                # UJI FITUR LIHAT PRODUK NONAKTIF PER SELLER (fp_slrdis):
                handle_admin_callback(app, {
                    'id': 'cb_slrdis',
                    'message': {'chat': {'id': '999888'}, 'message_id': 1},
                    'data': f'fp_slrdis:30d:{xl_fail_trx.id}:1'
                })
                assert 'DAFTAR PRODUK NONAKTIF SELLER' in edits[-1][0]
                assert test_sku_3 in edits[-1][0]
                assert_valid_telegram_keyboard(edits[-1][1])

                # UJI FITUR AKTIFKAN KEMBALI PRODUK PER SELLER (fp_slron):
                handle_admin_callback(app, {
                    'id': 'cb_slron',
                    'message': {'chat': {'id': '999888'}, 'message_id': 1},
                    'data': f'fp_slron:30d:{xl_fail_trx.id}'
                })
                db.session.refresh(p3)
                assert p3.is_active is True, "Produk harus kembali aktif setelah diaktifkan massal per seller!"
                assert p3.is_admin_disabled is False, "Gembok admin harus terbuka setelah diaktifkan kembali!"
                assert 'BERHASIL DIAKTIFKAN!' in edits[-1][0]

                # UJI CLEAN VIEW / INBOX ZERO: Produk yang sudah dinonaktifkan HILANG dari antrean aktif saat refresh!
                act_txt, act_kb = render_failed_products_report(period='30d', page=1, per_page=5, filter_mode='active')
                assert test_sku_1 not in act_txt, "Produk 1 yang sudah nonaktif tidak boleh muncul di filter aktif!"
                # Tapi saat dibuka dengan filter 'all' (arsip riwayat), produk tetap muncul:
                all_txt, all_kb = render_failed_products_report(period='30d', page=1, per_page=5, filter_mode='all')
                assert test_sku_1 in all_txt

                print("[LULUS 8/10] Gembok Admin, Proteksi Auto-Sync, Menu Produk Nonaktif per Seller, dan Tombol Aktifkan Massal berfungsi 100%.")

                # TEST 9: Konfirmasi Hapus & Eksekusi Hapus Produk dari Katalog (fp_delask & fp_delok)
                handle_admin_callback(app, {
                    'id': 'cb_delask',
                    'message': {'chat': {'id': '999888'}, 'message_id': 1},
                    'data': f'fp_delask:30d:{test_sku_2}'
                })
                assert 'KONFIRMASI HAPUS PRODUK DARI KATALOG' in edits[-1][0]

                handle_admin_callback(app, {
                    'id': 'cb_delok',
                    'message': {'chat': {'id': '999888'}, 'message_id': 1},
                    'data': f'fp_delok:30d:{test_sku_2}'
                })
                assert Product.query.filter_by(sku_code=test_sku_2).first() is None
                assert 'PRODUK BERHASIL DIHAPUS DARI KATALOG!' in edits[-1][0]
                print("[LULUS 9/10] Tombol Hapus Produk dari Katalog Database (fp_delask & fp_delok) berfungsi 100%.")

                # TEST 10: Perintah Chat Langsung di Bot 3 (/start, /produkgagal, /analisaseller)
                handle_admin_message(app, {'chat': {'id': '999888'}, 'text': '/start'})
                assert 'BOT 3 : PANEL & FITUR ADMIN GARUDATEL v2' in sends[-1][0]

                handle_admin_message(app, {'chat': {'id': '999888'}, 'text': '/produkgagal'})
                assert 'LAPORAN ANALISA PRODUK & SELLER SERING GAGAL' in sends[-1][0]

                handle_admin_message(app, {'chat': {'id': '999888'}, 'text': f'/produkgagal {test_sku_1}'})
                assert 'DETAIL ANALISA & KEPUTUSAN PRODUK' in sends[-1][0]

                handle_admin_message(app, {'chat': {'id': '999888'}, 'text': '/analisaseller'})
                assert 'RAPOR ANALISA SELLER DIGIFLAZZ SERING GAGAL' in sends[-1][0]
                print("[LULUS 10/11] Seluruh Perintah Teks Bot 3 (/start, /produkgagal, /analisaseller) berfungsi 100%.")

                # TEST 11: Fitur Katalog Produk Nonaktif Per Seller & Seleksi Aktivasi Produk (dis_act_one, dis_act_all, /produknonaktif)
                p1.seller_name = 'Payfast Official'
                p1.is_active = False
                p1.is_admin_disabled = True
                p3.seller_name = 'Payfast Official'
                p3.is_active = False
                p3.is_admin_disabled = True
                db.session.commit()

                # Uji get_disabled_sellers_list()
                d_sellers = get_disabled_sellers_list()
                assert len(d_sellers) >= 1
                payfast_group = next((s for s in d_sellers if 'PAYFAST' in s['key']), None)
                assert payfast_group is not None
                assert len(payfast_group['products']) >= 2
                payfast_hash = payfast_group['hash']

                # Uji render_disabled_catalog_sellers_menu()
                menu_txt, menu_kb = render_disabled_catalog_sellers_menu(page=1, per_page=6)
                assert_valid_telegram_keyboard(menu_kb)
                assert 'KATALOG PRODUK NONAKTIF PER SELLER' in menu_txt
                assert 'Payfast Official' in menu_txt

                # Uji callback cmd_disabled_catalog via handle_admin_callback
                handle_admin_callback(app, {
                    'id': 'cb_cat_menu',
                    'message': {'chat': {'id': '999888'}, 'message_id': 1},
                    'data': 'cmd_disabled_catalog'
                })
                assert 'KATALOG PRODUK NONAKTIF PER SELLER' in edits[-1][0]
                assert_valid_telegram_keyboard(edits[-1][1])

                # Uji buka daftar produk seller (dis_slr)
                handle_admin_callback(app, {
                    'id': 'cb_cat_slr',
                    'message': {'chat': {'id': '999888'}, 'message_id': 1},
                    'data': f'dis_slr:{payfast_hash}:1'
                })
                assert 'PRODUK NONAKTIF SELLER' in edits[-1][0]
                assert 'Payfast Official' in edits[-1][0]
                assert test_sku_1 in edits[-1][0]
                assert test_sku_3 in edits[-1][0]
                assert_valid_telegram_keyboard(edits[-1][1])

                # Uji Seleksi Aktivasi 1 Produk (dis_act_one): Aktifkan p1 saja!
                handle_admin_callback(app, {
                    'id': 'cb_act_one',
                    'message': {'chat': {'id': '999888'}, 'message_id': 1},
                    'data': f'dis_act_one:{p1.id}:{payfast_hash}'
                })
                db.session.refresh(p1)
                db.session.refresh(p3)
                assert p1.is_active is True, "Produk 1 harus aktif kembali!"
                assert p1.is_admin_disabled is False, "Gembok admin produk 1 harus terbuka!"
                assert p3.is_active is False, "Produk 3 harus tetap nonaktif karena belum dipilih!"
                # Clean View / Inbox Zero: Tombol dan entri produk 1 langsung hilang dari daftar nonaktif!
                cb_buttons = [b.get('callback_data') for r in edits[-1][1]['inline_keyboard'] for b in r if 'callback_data' in b]
                assert f'dis_act_one:{p1.id}:{payfast_hash}' not in cb_buttons, "Tombol produk 1 harus hilang dari daftar nonaktif!"
                assert f'dis_act_one:{p3.id}:{payfast_hash}' in cb_buttons, "Tombol produk 3 masih ada!"
                body_after_banner = edits[-1][0].split('━━━━━━━━━━━━━━━━━━━━━━\n\n', 1)[1]
                assert test_sku_1 not in body_after_banner, "Produk 1 harus hilang dari daftar produk nonaktif di bodi pesan!"
                assert test_sku_3 in body_after_banner, "Produk 3 masih tertinggal di daftar nonaktif!"

                # Uji Tombol Aktifkan Semua Produk Seller (dis_act_all): Aktifkan sisa produk seller Payfast
                handle_admin_callback(app, {
                    'id': 'cb_act_all',
                    'message': {'chat': {'id': '999888'}, 'message_id': 1},
                    'data': f'dis_act_all:{payfast_hash}'
                })
                db.session.refresh(p3)
                assert p3.is_active is True
                assert p3.is_admin_disabled is False
                assert 'BERHASIL DIAKTIFKAN!' in edits[-1][0]
                assert 'KATALOG PRODUK NONAKTIF PER SELLER' in edits[-1][0]

                # Uji Perintah Chat Langsung /produknonaktif
                handle_admin_message(app, {'chat': {'id': '999888'}, 'text': '/produknonaktif'})
                assert 'KATALOG PRODUK NONAKTIF PER SELLER' in sends[-1][0]
                assert_valid_telegram_keyboard(sends[-1][1])

                print("[LULUS 11/11] Fitur Katalog Produk Nonaktif Per Seller & Seleksi Aktivasi Produk (dis_act_one, dis_act_all, /produknonaktif) berfungsi 100%.")

            print("=" * 72)
            print("HASIL AKHIR: 11/11 PENGUJIAN BOT 3 PANEL & FITUR ADMIN LULUS 100%!")
            print("=" * 72)
        finally:
            Product.query.filter(Product.sku_code.in_([test_sku_1, test_sku_2, test_sku_3, test_sku_normal])).delete(synchronize_session=False)
            Transaction.query.filter(Transaction.sku_code.in_([test_sku_1, test_sku_2, test_sku_3, test_sku_normal])).delete(synchronize_session=False)
            db.session.commit()


if __name__ == '__main__':
    run_all_tests()
