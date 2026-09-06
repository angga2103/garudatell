from datetime import datetime, timedelta
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction
from app.models.point_log import PointLog

def get_user_mutations(user_id, limit=100):
    """
    Mengambil dan menyusun riwayat mutasi saldo pengguna secara kronologis,
    menghitung running balance ('Sisa: Rp ...') secara presisi mundur dari saldo aktif,
    serta menghitung ringkasan statistik finansial (Pemasukan, Pengeluaran, Refund).
    """
    user = User.query.get(user_id)
    if not user:
        return {
            'mutations': [],
            'stats': {
                'current_balance': 0.0,
                'total_pemasukan': 0.0,
                'total_pengeluaran': 0.0,
                'total_refund': 0.0,
                'count': 0
            }
        }

    current_balance = float(user.balance or 0.0)
    events = []

    # 1. Ambil transaksi pengguna
    try:
        user_trxs = Transaction.query.filter_by(user_id=user_id).order_by(Transaction.id.asc()).all()
    except Exception as e:
        print(f"[MUTASI_SERVICE] Error query transactions: {e}")
        user_trxs = []

    for trx in user_trxs:
        c_time = trx.created_at or datetime.utcnow()
        u_time = trx.updated_at or (c_time + timedelta(seconds=2))
        
        # Konversi ke WIB (+7 jam)
        c_time_wib = c_time + timedelta(hours=7)
        u_time_wib = u_time + timedelta(hours=7)
        c_str = c_time_wib.strftime('%Y-%m-%d %H:%M:%S')
        u_str = u_time_wib.strftime('%Y-%m-%d %H:%M:%S')

        sku = (trx.sku_code or '').strip()
        pay_method = (trx.payment_method or '').strip().upper()
        pay_status = (trx.payment_status or '').strip().upper()
        trx_status = (trx.status or '').strip().upper()
        amount = float(trx.amount or 0.0)

        # KASUS A: Top Up / Deposit Saldo Sukses
        if sku in ['DEPOSIT_SALDO', 'DEPOSIT_MANUAL']:
            # Hanya catat sebagai mutasi jika telah dibayar / sukses
            if pay_status in ['PAID', 'SUCCESS', 'SUKSES', 'SETTLEMENT'] or trx_status in ['SUCCESS', 'SUKSES', 'PAID']:
                events.append({
                    'id': f"dep-{trx.id}",
                    'raw_id': trx.id,
                    'type': 'pemasukan',
                    'title': f"Topup {trx.ref_id}",
                    'subtitle': f"Deposit Saldo via {trx.payment_method or 'QRIS'}",
                    'product_name': trx.product_name or 'Deposit Saldo',
                    'target': '-',
                    'amount': amount,
                    'direction': '+',
                    'status': 'Sukses',
                    'status_badge': 'Sukses',
                    'status_color': 'success',
                    'ref_id': trx.ref_id,
                    'sn': trx.sn or '-',
                    'payment_method': trx.payment_method or 'QRIS',
                    'timestamp': c_time,
                    'date_str': c_str,
                    'is_refund': False
                })

        # KASUS B: Pembelian Produk Menggunakan Saldo
        elif pay_method == 'SALDO' or (pay_status == 'PAID' and pay_method in ['SALDO', 'BALANCE']):
            # Event Pengeluaran Saldo saat order dibuat
            events.append({
                'id': f"buy-{trx.id}",
                'raw_id': trx.id,
                'type': 'pengeluaran',
                'title': 'Pembelian Produk',
                'subtitle': f"{trx.product_name} - {trx.target_number}",
                'product_name': trx.product_name or 'Pembelian Produk',
                'target': trx.target_number or '-',
                'amount': amount,
                'direction': '-',
                'status': trx.status or 'Diproses',
                'status_badge': 'Sukses' if trx_status in ['SUCCESS', 'SUKSES'] else ('Diproses' if trx_status in ['PENDING', 'PROCESSING'] else 'Gagal'),
                'status_color': 'success' if trx_status in ['SUCCESS', 'SUKSES'] else ('warning' if trx_status in ['PENDING', 'PROCESSING'] else 'danger'),
                'ref_id': trx.ref_id,
                'sn': trx.sn or '-',
                'payment_method': 'SALDO',
                'timestamp': c_time,
                'date_str': c_str,
                'is_refund': False
            })

            # KASUS C: Refund Otomatis jika Pembelian Saldo Berstatus Gagal
            if trx_status in ['FAILED', 'GAGAL', 'CANCELLED', 'BATAL']:
                events.append({
                    'id': f"ref-{trx.id}",
                    'raw_id': trx.id,
                    'type': 'refund',
                    'title': 'Penambahan Saldo/Refund',
                    'subtitle': f"Pengembalian Dana: {trx.product_name} ({trx.target_number})",
                    'product_name': f"Refund: {trx.product_name}",
                    'target': trx.target_number or '-',
                    'amount': amount,
                    'direction': '+',
                    'status': 'Refund Selesai',
                    'status_badge': 'Refund Selesai',
                    'status_color': 'info',
                    'ref_id': trx.ref_id,
                    'sn': trx.sn or 'Pengembalian dana ke saldo pengguna',
                    'payment_method': 'SALDO (REFUND)',
                    'timestamp': u_time if u_time > c_time else (c_time + timedelta(seconds=2)),
                    'date_str': u_str if u_time > c_time else c_str,
                    'is_refund': True
                })

    # 2. Ambil PointLog klaim poin menjadi saldo jika ada
    try:
        point_claims = PointLog.query.filter_by(user_id=user_id, type='CLAIM_TO_SALDO').order_by(PointLog.id.asc()).all()
        for pl in point_claims:
            b_add = float(pl.balance_added or 0.0)
            if b_add > 0:
                p_time = pl.created_at or datetime.utcnow()
                p_time_wib = p_time + timedelta(hours=7)
                events.append({
                    'id': f"point-{pl.id}",
                    'raw_id': pl.id,
                    'type': 'pemasukan',
                    'title': 'Penambahan Saldo/Klaim Poin',
                    'subtitle': pl.description or 'Penukaran reward poin ke saldo utama',
                    'product_name': 'Klaim Poin Reward',
                    'target': '-',
                    'amount': b_add,
                    'direction': '+',
                    'status': 'Sukses',
                    'status_badge': 'Sukses',
                    'status_color': 'success',
                    'ref_id': f"POINT-{pl.id}",
                    'sn': f"Klaim {abs(pl.points)} Poin",
                    'payment_method': 'POIN',
                    'timestamp': p_time,
                    'date_str': p_time_wib.strftime('%Y-%m-%d %H:%M:%S'),
                    'is_refund': False
                })
    except Exception as e:
        print(f"[MUTASI_SERVICE] PointLog query optional note: {e}")

    # 3. Urutkan semua event secara kronologis (terlama ke terbaru)
    events.sort(key=lambda x: x['timestamp'])

    # 4. Hitung Running Balance mundur dari current_balance
    # Event terakhir (terbaru) memiliki balance_after = current_balance
    if events:
        n = len(events)
        curr = current_balance
        for i in range(n - 1, -1, -1):
            ev = events[i]
            ev['balance_after'] = max(0.0, curr)
            delta = ev['amount'] if ev['direction'] == '+' else -ev['amount']
            balance_before = curr - delta
            ev['balance_before'] = max(0.0, balance_before)
            curr = balance_before

    # 5. Hitung Statistik Finansial
    total_pemasukan = sum(ev['amount'] for ev in events if ev['type'] == 'pemasukan')
    total_pengeluaran = sum(ev['amount'] for ev in events if ev['type'] == 'pengeluaran')
    total_refund = sum(ev['amount'] for ev in events if ev['type'] == 'refund')

    # 6. Urutkan untuk tampilan antarmuka (terbaru ke terlama)
    events.reverse()

    # Potong sesuai limit
    mutations = events[:limit]

    return {
        'mutations': mutations,
        'stats': {
            'current_balance': current_balance,
            'total_pemasukan': total_pemasukan,
            'total_pengeluaran': total_pengeluaran,
            'total_refund': total_refund,
            'count': len(events)
        }
    }
