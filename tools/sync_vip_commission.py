import os
import sys

# Tambahkan direktori root proyek ke sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE_DIR)

from app import create_app, db
from app.models.user import User
from app.services.commission_service import sync_user_commission_balance


def format_rp(num):
    return f"Rp {num:,.0f}".replace(',', '.')


def run_sync(identifier='saudi'):
    app = create_app()
    with app.app_context():
        print("=" * 65)
        print("    SINKRONISASI SALDO KOMISI DOWNLINE VIP GARUDATEL")
        print("=" * 65)

        if identifier.lower() == '--all':
            vips = User.query.filter(User.role.in_(['vip', 'reseller'])).all()
            print(f"Memproses {len(vips)} pengguna VIP/Reseller...")
            for v in vips:
                ok, msg, rep = sync_user_commission_balance(v)
                if ok:
                    print(f"  [OK] {v.name} ({v.phone}): {format_rp(rep['old_commission_balance'])} -> {format_rp(rep['new_commission_balance'])} (Downlines: {rep['downline_count']})")
                else:
                    print(f"  [SKIP] {v.name}: {msg}")
            print("=" * 65)
            print("[SELESAI] Seluruh komisi pengguna VIP/Reseller berhasil disinkronkan.")
            return

        print(f"Target Pencarian: '{identifier}'")
        users = User.query.filter(
            (User.name.ilike(f"%{identifier}%")) |
            (User.phone.ilike(f"%{identifier}%")) |
            (User.email.ilike(f"%{identifier}%"))
        ).all()

        if not users:
            print(f"[X] Tidak ditemukan pengguna dengan kata kunci '{identifier}'.")
            print("Pengguna VIP aktif yang terdaftar di database:")
            for v in User.query.filter(User.role == 'vip').all():
                print(f"  - ID: {v.id} | Nama: {v.name} | HP: {v.phone} | Komisi: {format_rp(v.commission_balance or 0)}")
            return

        for user in users:
            print("-" * 65)
            print(f"ID Pengguna      : {user.id}")
            print(f"Nama Lengkap     : {user.name}")
            print(f"Nomor WhatsApp   : {user.phone}")
            print(f"Golongan Akun    : {str(user.role).upper()}")
            print(f"Saldo Komisi Lama: {format_rp(user.commission_balance or 0)}")
            print("-" * 65)

            ok, msg, rep = sync_user_commission_balance(user)
            if not ok:
                print(f"[ERROR] {msg}")
                continue

            print("DETAIL AUDIT & PERHITUNGAN ULANG KOMISI:")
            print(f"  • Jumlah Downline Aktif           : {rep['downline_count']} member")
            print(f"  • Log Transaksi Baru Ditemukan    : {rep['backfilled_logs']} transaksi ({format_rp(rep['backfilled_amount'])})")
            print(f"  • Total Riwayat Transaksi Komisi : {rep['total_logs_count']} catatan")
            print(f"  • Komisi Sudah Dicairkan (Lalu)   : {format_rp(rep['total_paid_out'])} (status: paid_out)")
            print(f"  • Komisi Riil Belum Dicairkan    : {format_rp(rep['new_commission_balance'])} (status: earned)")
            print("-" * 65)
            print(f"HASIL SINKRONISASI:")
            print(f"  • Saldo Komisi Awal               : {format_rp(rep['old_commission_balance'])}")
            print(f"  • Saldo Komisi Seharusnya (Sinkron): {format_rp(rep['new_commission_balance'])}")
            selisih = rep['difference']
            tanda = "+" if selisih >= 0 else ""
            print(f"  • Penyesuaian Saldo               : {tanda}{format_rp(selisih)}")
            print("=" * 65)
            print(f"✅ {msg}")
            print("=" * 65)


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else 'saudi'
    run_sync(target)
