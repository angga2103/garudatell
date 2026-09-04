import os
import sys

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.point_log import PointLog
from app.models.setting import Setting
from app.routes.transaction import award_transaction_points

def test_point_feature():
    print("=" * 70)
    print("  VERIFIKASI FITUR POIN MEMBER, KLAIM TAHUNAN & ADMIN POINT CENTER")
    print("=" * 70)

    app = create_app()
    client = app.test_client()

    with app.app_context():
        # Dapatkan test user
        user = User.query.first()
        assert user is not None, "User harus ada di database"
        user_id = user.id
        initial_balance = user.balance or 0.0

        # Reset setting ke default
        rate_set = Setting.query.filter_by(key='point_rate').first()
        if not rate_set:
            rate_set = Setting(key='point_rate', value='1')
            db.session.add(rate_set)
        else:
            rate_set.value = '1'

        force_set = Setting.query.filter_by(key='point_claim_force_open').first()
        if not force_set:
            force_set = Setting(key='point_claim_force_open', value='0')
            db.session.add(force_set)
        else:
            force_set.value = '0'
        db.session.commit()

    # Sesi login member
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['admin_logged_in'] = False

    # 1. UJI DASHBOARD: Saldo QRIS telah diganti menjadi Poin Member
    print("\n[1/6] Memeriksa Dashboard User (/)...")
    res_dash = client.get('/')
    assert res_dash.status_code == 200
    html_dash = res_dash.data.decode('utf-8')
    assert 'Saldo QRIS' not in html_dash, "String 'Saldo QRIS' masih ditemukan di dashboard!"
    assert 'Poin Member' in html_dash, "Label 'Poin Member' harus ada di dashboard!"
    assert 'href="/poin"' in html_dash, "Link ke /poin harus ada di dashboard!"
    print("  [OK] Dashboard berhasil menampilkan 'Poin Member' (Saldo QRIS berhasil diubah 100%)!")

    # 2. UJI HALAMAN MEMBER: /poin (Masa Akumulasi Poin)
    print("\n[2/6] Memeriksa Halaman Poin Member (/poin) pada Periode Normal (Akumulasi)...")
    res_poin = client.get('/poin')
    assert res_poin.status_code == 200
    html_poin = res_poin.data.decode('utf-8')
    assert 'POIN MEMBER' in html_poin
    assert 'MASA AKUMULASI POIN AKTIF' in html_poin
    assert 'KLAIM TERKUNCI' in html_poin
    assert 'Skema &amp; Aturan Poin Member' in html_poin or 'Skema & Aturan Poin Member' in html_poin
    print("  [OK] Halaman /poin menampilkan status Masa Akumulasi Poin dan klaim terkunci.")

    # 3. UJI LOGIKA KLAIM DITOLAK SAAT DI LUAR PERIODE (1-7 Jan)
    print("\n[3/6] Menguji Penolakan Klaim di Luar Periode (8 Jan - 31 Des)...")
    res_claim_fail = client.post('/poin/claim', json={})
    assert res_claim_fail.status_code == 400
    claim_fail_json = res_claim_fail.get_json()
    assert claim_fail_json['status'] == 'error'
    assert '1 minggu pertama' in claim_fail_json['message']
    print(f"  [OK] Klaim ditolak aman sesuai aturan: '{claim_fail_json['message']}'")

    # 4. UJI PERIODE KLAIM AKTIF & PROSES KLAIM KE SALDO
    print("\n[4/6] Menguji Klaim Poin Berhasil (Simulasi Periode Terbuka)...")
    with app.app_context():
        # Set testing mode force open & beri user 200 poin
        u = User.query.get(user_id)
        u.points = 200
        u.balance = 50000.0
        st = Setting.query.filter_by(key='point_claim_force_open').first()
        st.value = '1'
        db.session.commit()

    # Periksa halaman poin saat periode terbuka
    res_poin_open = client.get('/poin')
    assert 'PERIODE KLAIM SEDANG DIBUKA!' in res_poin_open.data.decode('utf-8')
    assert 'KLAIM POIN KE SALDO SEKARANG' in res_poin_open.data.decode('utf-8')

    # Eksekusi klaim poin via POST /poin/claim
    res_claim_success = client.post('/poin/claim', json={})
    assert res_claim_success.status_code == 200
    claim_succ_json = res_claim_success.get_json()
    assert claim_succ_json['status'] == 'success'
    print(f"  [OK] Respons Klaim Sukses: {claim_succ_json['message']}")

    with app.app_context():
        u_after = User.query.get(user_id)
        assert u_after.points == 0, f"Poin harus 0 setelah klaim, dapat: {u_after.points}"
        assert u_after.balance == 50200.0, f"Saldo harus bertambah 200 jadi 50200, dapat: {u_after.balance}"
        
        # Cek PointLog
        last_log = PointLog.query.filter_by(user_id=user_id, type='CLAIM_TO_SALDO').first()
        assert last_log is not None
        assert last_log.points == -200
        assert last_log.balance_added == 200.0
        print("  [OK] Saldo user bertambah (+Rp 200), poin direset menjadi 0, dan PointLog tercatat rapi!")

    # 5. UJI REWARD POIN DARI TRANSAKSI
    print("\n[5/6] Menguji Pemberian Reward Poin atas Transaksi Sukses...")
    import time
    test_ref = f'TRX-TEST-UNIT-{int(time.time()*1000)}'
    with app.app_context():
        u_init = User.query.get(user_id)
        pts_before = u_init.points or 0
        award_transaction_points(user_id, test_ref)
        u_reward = User.query.get(user_id)
        assert u_reward.points == pts_before + 1, f"User harus dapat +1 poin, sebelum: {pts_before}, sekarang: {u_reward.points}"
        
        # Test idempotency (tidak dobel reward jika dipanggil ulang dengan ref_id sama)
        award_transaction_points(user_id, test_ref)
        u_reward_repeat = User.query.get(user_id)
        assert u_reward_repeat.points == pts_before + 1, "Reward tidak boleh dobel untuk transaksi yang sama!"
        print("  [OK] Reward poin transaksi otomatis masuk & terbukti idempoten!")

    # 6. UJI ADMIN PANEL: Edit Poin, Reset Poin & Edit Aturan Poin Dinamis
    print("\n[6/6] Menguji Fitur Poin di Panel Admin (/admin/users & /admin/point_settings)...")
    with client.session_transaction() as sess:
        sess['admin_logged_in'] = True

    # A. Cek kolom poin di tabel user admin
    res_adm_users = client.get('/admin/users')
    assert res_adm_users.status_code == 200
    assert 'Poin' in res_adm_users.data.decode('utf-8')
    assert 'eu_points' in res_adm_users.data.decode('utf-8')

    # B. Update poin user via modal edit
    res_update_user = client.post('/admin/user/update_action', data={
        'user_id': user_id,
        'name': 'User Test Point',
        'phone': '081299998888',
        'balance': '50000',
        'points': '350',
        'role': 'user',
        'status': '1'
    }, follow_redirects=True)
    assert res_update_user.status_code == 200
    with app.app_context():
        u_up = User.query.get(user_id)
        assert u_up.points == 350, f"Poin harus 350 setelah diedit admin, dapat: {u_up.points}"
        print("  [OK] Admin berhasil mengedit jumlah poin user menjadi 350 Pts!")

    # C. Reset poin user via endpoint reset_points
    res_reset = client.post(f'/admin/user/reset_points/{user_id}', follow_redirects=True)
    assert res_reset.status_code == 200
    with app.app_context():
        u_reset = User.query.get(user_id)
        assert u_reset.points == 0, f"Poin harus 0 setelah direset, dapat: {u_reset.points}"
        print("  [OK] Admin berhasil mereset poin user menjadi 0 Pts!")

    # D. Edit Aturan Dinamis di /admin/point_settings
    res_save_settings = client.post('/admin/point_settings', data={
        'point_rate': '2',
        'point_reward_per_trx': '5',
        'point_claim_start_day': '1',
        'point_claim_end_day': '7',
        'point_claim_force_open': '0',
        'point_rules_content': '### Aturan Khusus 2027\n- Poin dapat diklaim awal Januari.'
    }, follow_redirects=True)
    assert res_save_settings.status_code == 200
    with app.app_context():
        st_rate = Setting.query.filter_by(key='point_rate').first()
        assert st_rate.value == '2'
        st_reward = Setting.query.filter_by(key='point_reward_per_trx').first()
        assert st_reward.value == '5'
        st_rules = Setting.query.filter_by(key='point_rules_content').first()
        assert 'Aturan Khusus 2027' in st_rules.value
        print("  [OK] Admin berhasil memperbarui aturan dinamis & kurs konversi (1 Poin = Rp 2)!")

    # E. Kembalikan default setting
    with app.app_context():
        Setting.query.filter_by(key='point_rate').first().value = '1'
        Setting.query.filter_by(key='point_reward_per_trx').first().value = '1'
        Setting.query.filter_by(key='point_claim_force_open').first().value = '0'
        Setting.query.filter_by(key='point_rules_content').first().value = (
            '### Skema & Aturan Poin Member GarudaTel\n'
            '1. **Perolehan Poin**: Setiap transaksi sukses menghasilkan poin reward.\n'
            '2. **Periode Klaim**: Hanya dapat diklaim 1 minggu di awal Januari (1-7 Januari).\n'
            '3. **Akumulasi**: Poin tidak hangus dan otomatis diakumulasikan untuk tahun berikutnya.'
        )
        db.session.commit()

    print("\n" + "=" * 70)
    print("  >>> SELURUH FITUR POIN MEMBER TERVERIFIKASI & LULUS 100%! <<<")
    print("=" * 70 + "\n")

if __name__ == '__main__':
    test_point_feature()
