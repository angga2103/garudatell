import os
import sys
from datetime import datetime, timezone, timedelta

# Pastikan path workspace ada di sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction
from app.models.product import Product
from app.models.commission import CommissionLog
from app.services.tier_service import (
    get_tier_settings,
    get_user_product_price,
    process_subscription_upgrade,
    check_and_downgrade_expired_users,
    ensure_user_referral_code,
    get_wib_now
)
from app.services.commission_service import (
    award_downline_commission,
    get_vip_downline_stats,
    claim_monthly_commission,
    prune_commission_history
)

def run_tests():
    app = create_app()
    with app.app_context():
        print("=" * 65)
        print("  PENGUJIAN SISTEM TIER AKUN, SUBSCRIPTION & DOWNLINE VIP")
        print("=" * 65)

        passed = 0
        failed = 0

        def assert_test(cond, title):
            nonlocal passed, failed
            if cond:
                print(f"  [PASSED] {title}")
                passed += 1
            else:
                print(f"  [FAILED] {title}")
                failed += 1

        # -------------------------------------------------------------
        # 1. TEST TIER SETTINGS
        # -------------------------------------------------------------
        print("\n--- 1. Uji Konfigurasi Tier Settings ---")
        cfg = get_tier_settings()
        assert_test(cfg['upgrade_fee_reseller'] >= 0, f"Tarif upgrade reseller: Rp {cfg['upgrade_fee_reseller']:,.0f}")
        assert_test(cfg['upgrade_fee_vip'] >= 0, f"Tarif upgrade VIP: Rp {cfg['upgrade_fee_vip']:,.0f}")
        assert_test(cfg['discount_vip'] >= cfg['discount_reseller'], f"Diskon VIP ({cfg['discount_vip']}) >= Diskon Reseller ({cfg['discount_reseller']})")
        assert_test(cfg['payout_date'] == 28, f"Tanggal pencairan komisi: {cfg['payout_date']}")
        assert_test(cfg['history_retention_days'] == 120, f"Retensi riwayat: {cfg['history_retention_days']} hari (4 bulan)")

        # -------------------------------------------------------------
        # 2. TEST PERHITUNGAN HARGA PRODUK DINAMIS (TIER PRICING)
        # -------------------------------------------------------------
        print("\n--- 2. Uji Harga Produk Dinamis Berdasarkan Tier ---")
        prod_test = Product(
            sku_code="TEST_PRICING_SKU_CUSTOM",
            name="Produk Uji Coba Tier",
            category="PULSA",
            brand="TELKOMSEL",
            base_price=9000.0,
            sell_price=10000.0,
            is_active=True
        )

        # Dummy users
        user_member = User(name="Test Member", phone="081111111101", password_hash="hash", role="user", balance=50000.0, is_active=True)
        user_reseller = User(name="Test Reseller", phone="081111111102", password_hash="hash", role="reseller", role_expires_at=get_wib_now() + timedelta(days=20), balance=50000.0, is_active=True)
        user_vip = User(name="Test VIP", phone="081111111103", password_hash="hash", role="vip", role_expires_at=get_wib_now() + timedelta(days=20), balance=50000.0, is_active=True)

        # Harga Member: normal
        p_mem = get_user_product_price(user_member, prod_test)
        assert_test(p_mem == prod_test.sell_price, f"Harga Member sama dengan normal: Rp {p_mem:,.0f}")

        # Harga Reseller: sell_price - 100
        p_res = get_user_product_price(user_reseller, prod_test)
        expected_res = prod_test.sell_price - cfg['discount_reseller']
        assert_test(p_res == expected_res, f"Harga Reseller lebih murah Rp {cfg['discount_reseller']}: Rp {p_res:,.0f}")

        # Harga VIP: sell_price - 200
        p_vip = get_user_product_price(user_vip, prod_test)
        expected_vip = prod_test.sell_price - cfg['discount_vip']
        assert_test(p_vip == expected_vip, f"Harga VIP lebih murah Rp {cfg['discount_vip']}: Rp {p_vip:,.0f}")

        # Floor protection test
        # Produk dengan modal tipis: sell_price = 10000, base_price = 9900
        prod_thin = Product(sku_code="THIN_SKU", name="Produk Tipis", base_price=9900.0, sell_price=10000.0)
        p_vip_thin = get_user_product_price(user_vip, prod_thin)
        # Floor = base_price + 100 = 10000. Sell - discount = 9800. Max(floor, 9800) = 10000.
        assert_test(p_vip_thin >= prod_thin.base_price + 100, f"Proteksi floor harga modal aktif: Rp {p_vip_thin:,.0f} >= Modal + 100 (Rp {prod_thin.base_price + 100:,.0f})")

        # -------------------------------------------------------------
        # 3. TEST PROSES UPGRADE SUBSCRIPTION
        # -------------------------------------------------------------
        print("\n--- 3. Uji Alur Upgrade & Langganan Bulanan ---")
        # User saldo kurang
        user_miskin = User(name="User Miskin", phone="081111111104", password_hash="hash", role="user", balance=500.0, is_active=True)
        db.session.add(user_miskin)
        db.session.commit()

        ok, msg, _ = process_subscription_upgrade(user_miskin, 'vip')
        assert_test(not ok and "Saldo tidak mencukupi" in msg, f"Tolak upgrade jika saldo kurang: '{msg}'")

        # User saldo cukup upgrade ke VIP
        user_kaya = User(name="User Mitra VIP", phone="081111111105", password_hash="hash", role="user", balance=50000.0, is_active=True)
        db.session.add(user_kaya)
        db.session.commit()

        ok, msg, u_vip = process_subscription_upgrade(user_kaya, 'vip')
        assert_test(ok, f"Upgrade ke VIP berhasil: {msg}")
        assert_test(u_vip.role == 'vip', "Status role menjadi 'vip'")
        assert_test(u_vip.balance == 50000.0 - cfg['upgrade_fee_vip'], f"Saldo terpotong Rp {cfg['upgrade_fee_vip']:,.0f} (Sisa Rp {u_vip.balance:,.0f})")
        assert_test(u_vip.referral_code is not None and u_vip.referral_code.startswith('GT-'), f"Kode referral otomatis dibuat: {u_vip.referral_code}")
        assert_test(u_vip.get_remaining_days() >= 29, f"Masa aktif 30 hari tersisa: {u_vip.get_remaining_days()} hari")

        # Cek mutasi transaksi upgrade
        trx_upg = Transaction.query.filter_by(user_id=u_vip.id, sku_code='UPGRADE_VIP').first()
        assert_test(trx_upg is not None and trx_upg.status == 'SUCCESS', "Transaksi mutasi upgrade VIP tercatat di database")

        # Perpanjang VIP (akumulasi masa aktif)
        old_exp = u_vip.role_expires_at
        ok, msg, _ = process_subscription_upgrade(u_vip, 'vip')
        assert_test(ok and u_vip.role_expires_at > old_exp + timedelta(days=29), f"Perpanjangan menambah 30 hari masa aktif: {u_vip.get_remaining_days()} hari")

        # -------------------------------------------------------------
        # 4. TEST SISTEM KEMITRAAN DOWNLINE & KOMISI TRANSAKSI
        # -------------------------------------------------------------
        print("\n--- 4. Uji Downline & Pemberian Komisi ---")
        # Daftarkan downline yang merujuk ke user_kaya (VIP)
        user_downline = User(
            name="Downline Budi",
            phone="081111111106",
            password_hash="hash",
            role="user",
            upline_id=u_vip.id,
            balance=100000.0,
            is_active=True
        )
        db.session.add(user_downline)
        db.session.commit()
        assert_test(user_downline.upline_id == u_vip.id, f"Downline terhubung ke Upline VIP #{u_vip.id}")

        # Simulasikan transaksi belanja oleh Downline
        trx_downline = Transaction(
            user_id=user_downline.id,
            ref_id=f"TEST-TRX-{int(datetime.now().timestamp())}",
            product_name="Pulsa Telkomsel 10rb",
            sku_code=prod_test.sku_code,
            target_number=user_downline.phone,
            amount=10000.0,
            payment_method='SALDO',
            payment_status='PAID',
            status='SUCCESS',
            is_prepaid=True
        )
        db.session.add(trx_downline)
        db.session.commit()

        # Berikan komisi
        initial_comm = float(u_vip.commission_balance or 0.0)
        awarded = award_downline_commission(trx_downline)
        assert_test(awarded, "Pemberian komisi downline berhasil diproses")

        db.session.refresh(u_vip)
        added_comm = float(u_vip.commission_balance or 0.0) - initial_comm
        assert_test(added_comm > 0, f"Saldo komisi upline bertambah Rp {added_comm:,.0f} (Total: Rp {u_vip.commission_balance:,.0f})")

        # Log komisi tercatat
        comm_log = CommissionLog.query.filter_by(transaction_id=trx_downline.id).first()
        assert_test(comm_log is not None and comm_log.status == 'earned', f"Log komisi tercatat di database (#{comm_log.id}, status: {comm_log.status})")

        # Idempotency test (tidak boleh double komisi)
        awarded_again = award_downline_commission(trx_downline)
        assert_test(not awarded_again, "Proteksi idempotency: Transaksi yang sama tidak memberikan komisi ganda")

        # -------------------------------------------------------------
        # 5. TEST DASHBOARD STATS DOWNLINE VIP
        # -------------------------------------------------------------
        print("\n--- 5. Uji Statistik Manajemen Downline VIP ---")
        stats = get_vip_downline_stats(u_vip.id)
        assert_test(stats['total_downlines'] >= 1, f"Total downline terdaftar: {stats['total_downlines']}")
        assert_test(stats['commission_balance'] == u_vip.commission_balance, f"Saldo komisi siap cair sesuai: Rp {stats['commission_balance']:,.0f}")
        assert_test(stats['payout_date'] == 28, f"Tanggal gajian tervalidasi tgl {stats['payout_date']}")
        assert_test(len(stats['recent_logs']) >= 1, f"Riwayat log komisi dimuat: {len(stats['recent_logs'])} log")

        # -------------------------------------------------------------
        # 6. TEST PENCAIRAN KOMISI (TANGGAL 28)
        # -------------------------------------------------------------
        print("\n--- 6. Uji Aturan Pencairan Komisi (Kunci Tanggal 28) ---")
        wib_now = get_wib_now()
        is_today_28 = (wib_now.day == 28)

        if not is_today_28:
            # Jika hari ini bukan tgl 28, klaim harus DITOLAK
            ok_claim, msg_claim, _ = claim_monthly_commission(u_vip)
            assert_test(not ok_claim and "tanggal 28" in msg_claim, f"Klaim terkunci jika bukan tgl 28: '{msg_claim}'")

        # Uji simulasi klaim sukses dengan sementara mock / set setting payout_date ke hari ini
        from app.models.setting import Setting
        p_setting = Setting.query.filter_by(key='payout_date').first()
        if not p_setting:
            p_setting = Setting(key='payout_date', value=str(wib_now.day))
            db.session.add(p_setting)
        else:
            old_payout_val = p_setting.value
            p_setting.value = str(wib_now.day)
        db.session.commit()

        saldo_sebelum_klaim = float(u_vip.balance or 0.0)
        komisi_sebelum_klaim = float(u_vip.commission_balance or 0.0)

        ok_claim_sim, msg_claim_sim, amount_cair = claim_monthly_commission(u_vip)
        assert_test(ok_claim_sim, f"Simulasi pencairan komisi di tanggal pencairan sukses: Rp {amount_cair:,.0f}")

        db.session.refresh(u_vip)
        assert_test(u_vip.balance == saldo_sebelum_klaim + komisi_sebelum_klaim, f"Saldo utama bertambah dari komisi: Rp {u_vip.balance:,.0f}")
        assert_test(u_vip.commission_balance == 0.0, "Saldo komisi VIP direset menjadi Rp 0")

        # Mutasi pencairan komisi
        trx_payout = Transaction.query.filter_by(user_id=u_vip.id, sku_code='COMMISSION_PAYOUT').first()
        assert_test(trx_payout is not None and trx_payout.status == 'SUCCESS', "Mutasi pencairan COMMISSION_PAYOUT tercatat")

        # Kembalikan setting payout_date ke 28
        p_setting.value = '28'
        db.session.commit()

        # -------------------------------------------------------------
        # 7. TEST DOWNGRADE EXPIRED & RETENSI 4 BULAN
        # -------------------------------------------------------------
        print("\n--- 7. Uji Auto-Downgrade & Retensi 4 Bulan (Housekeeping) ---")
        # User expired
        user_expired = User(
            name="Reseller Kadaluarsa",
            phone="081111111107",
            password_hash="hash",
            role="reseller",
            role_expires_at=wib_now - timedelta(days=2), # sudah lewat 2 hari
            balance=1000.0,
            is_active=True
        )
        db.session.add(user_expired)
        db.session.commit()

        count_downgrade = check_and_downgrade_expired_users()
        db.session.refresh(user_expired)
        assert_test(count_downgrade >= 1 and user_expired.role == 'user', f"User kadaluarsa berhasil di-downgrade ke 'user' (total: {count_downgrade})")

        # Prune test (buat log komisi lebih dari 120 hari)
        old_log = CommissionLog(
            upline_id=u_vip.id,
            downline_id=user_downline.id,
            transaction_id=trx_downline.id,
            trx_amount=10000.0,
            commission_amount=100.0,
            status='paid_out',
            created_at=wib_now - timedelta(days=130) # 130 hari yang lalu
        )
        db.session.add(old_log)
        db.session.commit()

        pruned_count = prune_commission_history()
        assert_test(pruned_count >= 1, f"Housekeeping prune berhasil menghapus {pruned_count} log komisi > 120 hari")

        # Bersihkan data uji coba
        print("\n--- Pembersihan Data Uji Coba ---")
        try:
            CommissionLog.query.filter(CommissionLog.upline_id.in_([u_vip.id, user_miskin.id, user_kaya.id])).delete()
            Transaction.query.filter(Transaction.user_id.in_([user_kaya.id, user_downline.id, user_miskin.id, user_expired.id])).delete()
            User.query.filter(User.id.in_([user_kaya.id, user_downline.id, user_miskin.id, user_expired.id])).delete()
            db.session.commit()
            print("  [CLEANUP] Data dummy pengujian berhasil dibersihkan.")
        except Exception as e:
            db.session.rollback()
            print(f"  [CLEANUP ERROR] {e}")

        print("\n" + "=" * 65)
        print(f"  HASIL AKHIR: {passed} PASSED, {failed} FAILED")
        print("=" * 65)

        if failed > 0:
            sys.exit(1)

if __name__ == '__main__':
    run_tests()
