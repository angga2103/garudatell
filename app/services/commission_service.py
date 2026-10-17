from datetime import datetime, timezone, timedelta
import time
import logging
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction
from app.models.product import Product
from app.models.commission import CommissionLog, get_wib_datetime
from app.services.tier_service import get_tier_settings, get_setting_float, get_setting_int

logger = logging.getLogger(__name__)

EXCLUDED_SKUS = {
    'DEPOSIT_SALDO',
    'DEPOSIT_MANUAL',
    'COMMISSION_PAYOUT',
    'UPGRADE_RESELLER',
    'UPGRADE_VIP'
}

def award_downline_commission(transaction):
    """
    Memberikan komisi kepada Upline VIP jika transaksi downline berhasil (SUCCESS).
    - Memverifikasi apakah pembeli memiliki Upline.
    - Memverifikasi Upline berstatus VIP Aktif.
    - Menghitung komisi dengan proteksi margin (safety guard).
    - Menambahkan ke commission_balance Upline dan mencatat CommissionLog.
    """
    if not transaction or transaction.status != 'SUCCESS':
        return False

    sku = str(getattr(transaction, 'sku_code', '') or '').strip()
    if sku in EXCLUDED_SKUS or 'DEPOSIT' in sku.upper() or 'UPGRADE' in sku.upper():
        return False

    # Cek apakah transaksi sudah pernah diberi komisi (Idempotency)
    existing_log = CommissionLog.query.filter_by(transaction_id=transaction.id).first()
    if existing_log:
        return False

    # Ambil data pembeli
    buyer = User.query.get(transaction.user_id)
    if not buyer or not buyer.upline_id:
        return False

    # Ambil data Upline
    upline = User.query.get(buyer.upline_id)
    if not upline:
        return False

    # Syarat mutlak: Hanya Upline berstatus VIP Aktif yang berhak memperoleh komisi
    if not upline.is_vip_active():
        logger.info(f"[COMMISSION] Upline {upline.id} tidak aktif sebagai VIP saat transaksi {transaction.id}. Komisi dilewati.")
        return False

    # Hitung besaran komisi dengan batas pengaman margin
    commission_cfg = get_setting_float('commission_flat', 100.0)
    prod = Product.query.filter_by(sku_code=sku).first()

    if prod and prod.base_price:
        margin = max(0.0, float(prod.sell_price or 0.0) - float(prod.base_price or 0.0))
        # Batasi komisi maksimal 30% dari margin kotor agar server tidak defisit
        max_allowed = max(0.0, margin * 0.30)
        final_comm = min(commission_cfg, max_allowed)
        if margin < 150.0:
            final_comm = min(final_comm, 50.0)
    else:
        final_comm = min(commission_cfg, 100.0)

    final_comm = round(final_comm, 2)
    if final_comm <= 0:
        return False

    try:
        # Tambahkan ke saldo komisi upline
        upline.commission_balance = round(float(upline.commission_balance or 0.0) + final_comm, 2)

        # Catat di log komisi
        log = CommissionLog(
            upline_id=upline.id,
            downline_id=buyer.id,
            transaction_id=transaction.id,
            trx_amount=float(transaction.amount or 0.0),
            commission_amount=final_comm,
            status='earned',
            created_at=get_wib_datetime()
        )
        db.session.add(log)
        db.session.commit()
        logger.info(f"[COMMISSION] Komisi Rp {final_comm} diberikan ke Upline VIP {upline.id} ({upline.phone}) dari transaksi Downline {buyer.id}")
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"[COMMISSION] Gagal memberikan komisi untuk trx {transaction.id}: {e}")
        return False

def get_vip_downline_stats(upline_id):
    """
    Mengambil dan mengagregasi data manajemen downline untuk Upline VIP:
    - Daftar downline terdaftar
    - Transaksi hari ini (jumlah dan nominal)
    - Komisi terkumpul bulan ini
    - Saldo komisi siap cair
    - Info pencairan tanggal 28
    - Riwayat transaksi downline & komisi dalam rentang 4 bulan (120 hari)
    """
    now = get_wib_datetime()
    retention_days = get_setting_int('history_retention_days', 120)
    cutoff_date = now - timedelta(days=retention_days)

    upline = User.query.get(upline_id)
    if not upline:
        return None

    # 1. Daftar Downline
    downlines = User.query.filter_by(upline_id=upline_id).order_by(User.id.desc()).all()
    downline_list = []
    downline_map = {}
    for d in downlines:
        phone_masked = d.phone[:4] + '****' + d.phone[-3:] if len(d.phone) >= 7 else d.phone
        item = {
            'id': d.id,
            'name': d.name,
            'phone_masked': phone_masked,
            'role': d.get_effective_role() if hasattr(d, 'get_effective_role') else d.role,
            'is_vip': d.is_vip_active(),
            'created_at': getattr(d, 'created_at', None)
        }
        downline_list.append(item)
        downline_map[d.id] = item

    # 2. Statistik Hari Ini
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_logs = CommissionLog.query.filter(
        CommissionLog.upline_id == upline_id,
        CommissionLog.created_at >= today_start
    ).all()

    today_trx_count = len(today_logs)
    today_trx_amount = sum(float(l.trx_amount or 0.0) for l in today_logs)
    today_commission = sum(float(l.commission_amount or 0.0) for l in today_logs)

    # 3. Statistik Bulan Ini
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_logs = CommissionLog.query.filter(
        CommissionLog.upline_id == upline_id,
        CommissionLog.created_at >= month_start
    ).all()

    month_trx_count = len(month_logs)
    month_trx_amount = sum(float(l.trx_amount or 0.0) for l in month_logs)
    month_commission = sum(float(l.commission_amount or 0.0) for l in month_logs)

    # 4. Riwayat Komisi 4 Bulan Terakhir
    recent_logs = CommissionLog.query.filter(
        CommissionLog.upline_id == upline_id,
        CommissionLog.created_at >= cutoff_date
    ).order_by(CommissionLog.id.desc()).limit(200).all()

    formatted_logs = []
    for l in recent_logs:
        dn_info = downline_map.get(l.downline_id, {})
        formatted_logs.append({
            'id': l.id,
            'downline_id': l.downline_id,
            'downline_name': dn_info.get('name', f"User #{l.downline_id}"),
            'downline_phone': dn_info.get('phone_masked', '-'),
            'transaction_id': l.transaction_id,
            'trx_amount': float(l.trx_amount or 0.0),
            'commission_amount': float(l.commission_amount or 0.0),
            'status': l.status,
            'status_label': 'Tersedia' if l.status == 'earned' else ('Dicairkan' if l.status == 'paid_out' else l.status),
            'created_at_str': l.created_at.strftime('%d/%m/%Y %H:%M') if l.created_at else '-'
        })

    # 5. Informasi Pencairan Tanggal 28
    payout_date = get_setting_int('payout_date', 28)
    is_payout_day = (now.day == payout_date)

    if now.day < payout_date:
        days_until_payout = payout_date - now.day
    elif now.day == payout_date:
        days_until_payout = 0
    else:
        # Menghitung sisa hari ke tanggal 28 bulan berikutnya
        # Perkiraan hari dalam bulan ini
        import calendar
        _, last_day = calendar.monthrange(now.year, now.month)
        days_until_payout = (last_day - now.day) + payout_date

    return {
        'downlines': downline_list,
        'total_downlines': len(downline_list),
        'today': {
            'count': today_trx_count,
            'amount': today_trx_amount,
            'commission': today_commission
        },
        'month': {
            'count': month_trx_count,
            'amount': month_trx_amount,
            'commission': month_commission
        },
        'commission_balance': float(upline.commission_balance or 0.0),
        'payout_date': payout_date,
        'is_payout_day': is_payout_day,
        'days_until_payout': days_until_payout,
        'recent_logs': formatted_logs
    }

def claim_monthly_commission(user):
    """
    Mencairkan saldo komisi ke Saldo Utama akun GarudaTel.
    HANYA dapat dilakukan jika:
    1. Pengguna adalah VIP Aktif
    2. Hari ini tepat tanggal pencairan (default 28) WIB
    3. Saldo komisi > 0
    """
    now = get_wib_datetime()
    payout_date = get_setting_int('payout_date', 28)

    if now.day != payout_date:
        return False, f"Pencairan komisi hanya dapat dilakukan setiap tanggal {payout_date} WIB (00:00 - 23:59).", 0.0

    if not user.is_vip_active():
        return False, "Hanya akun VIP aktif yang berhak mencairkan saldo komisi.", 0.0

    user_locked = db.session.query(User).filter_by(id=user.id).with_for_update().first()
    claim_amount = float(user_locked.commission_balance or 0.0)

    if claim_amount <= 0:
        db.session.rollback()
        return False, "Tidak ada saldo komisi yang dapat dicairkan saat ini.", 0.0

    # Transfer saldo komisi ke Saldo Utama
    user_locked.balance = round(float(user_locked.balance or 0.0) + claim_amount, 2)
    user_locked.commission_balance = 0.0

    # Catat Transaksi / Mutasi Saldo
    ref_id = f"COM-{int(time.time()*1000)}"
    trx = Transaction(
        user_id=user_locked.id,
        ref_id=ref_id,
        product_name=f"Pencairan Komisi Downline (Tgl {payout_date})",
        sku_code="COMMISSION_PAYOUT",
        target_number=user_locked.phone,
        amount=claim_amount,
        payment_method='KOMISI',
        payment_status='PAID',
        status='SUCCESS',
        sn=f"Cair ke Saldo Utama Rp {claim_amount:,.0f}",
        is_prepaid=True
    )
    db.session.add(trx)

    # Tandai seluruh log berstatus 'earned' menjadi 'paid_out'
    CommissionLog.query.filter_by(upline_id=user_locked.id, status='earned').update({
        'status': 'paid_out',
        'payout_date': now
    })

    db.session.commit()
    logger.info(f"[COMMISSION] User {user_locked.id} berhasil mencairkan komisi Rp {claim_amount:,.0f} ke saldo utama.")

    # Kirim notifikasi asinkron ke Admin / Bot Notifikasi Telegram
    try:
        from app.services.telegram_service import async_send_vip_commission_claim_notification
        downline_count = User.query.filter_by(upline_id=user_locked.id).count()
        async_send_vip_commission_claim_notification(
            user_name=user_locked.name,
            user_phone=user_locked.phone,
            user_id=user_locked.id,
            claim_amount=claim_amount,
            ref_id=ref_id,
            new_balance=float(user_locked.balance or 0.0),
            downline_count=downline_count
        )
    except Exception as e_notif:
        logger.error(f"[COMMISSION NOTIF ERR] Gagal trigger notifikasi pencairan komisi: {e_notif}")

    return True, f"Selamat! Saldo komisi sebesar Rp {claim_amount:,.0f} telah berhasil dicairkan ke Saldo Utama Anda.", claim_amount

def prune_commission_history():
    """
    Menghapus riwayat CommissionLog yang berumur lebih dari batas retensi (default 120 hari / 4 bulan)
    agar database VPS tetap ramping dan query tetap responsif.
    """
    now = get_wib_datetime()
    retention_days = get_setting_int('history_retention_days', 120)
    cutoff = now - timedelta(days=retention_days)

    deleted = CommissionLog.query.filter(CommissionLog.created_at < cutoff).delete()
    if deleted > 0:
        db.session.commit()
        logger.info(f"[COMMISSION] Housekeeping: {deleted} baris data komisi lebih dari {retention_days} hari berhasil dibersihkan.")
    return deleted


def sync_user_commission_balance(user_or_identifier):
    """
    Menghitung ulang dan menyinkronkan saldo komisi (commission_balance) seorang Upline VIP:
    1. Mencari user berdasarkan ID, nama, nomor WhatsApp, atau email.
    2. Mendeteksi seluruh downline aktif.
    3. Memeriksa transaksi sukses downline yang belum tercatat di CommissionLog (backfill aman).
    4. Menghitung total saldo komisi riil berstatus 'earned' (belum dicairkan).
    5. Memperbarui user.commission_balance agar 100% sinkron dan akurat.
    """
    if isinstance(user_or_identifier, User):
        user = user_or_identifier
    elif isinstance(user_or_identifier, int) or str(user_or_identifier).isdigit():
        user = User.query.get(int(user_or_identifier))
    else:
        q = str(user_or_identifier).strip()
        user = User.query.filter(
            (User.name.ilike(f"%{q}%")) |
            (User.phone.ilike(f"%{q}%")) |
            (User.email.ilike(f"%{q}%"))
        ).first()

    if not user:
        return False, f"Pengguna '{user_or_identifier}' tidak ditemukan!", None

    old_balance = float(user.commission_balance or 0.0)

    # 1. Ambil seluruh downline
    downlines = User.query.filter_by(upline_id=user.id).all()
    downline_ids = [d.id for d in downlines]

    backfilled_count = 0
    backfilled_amount = 0.0

    # 2. Cek apakah ada transaksi sukses downline yang belum pernah tercatat di CommissionLog
    if downline_ids:
        unlogged_trxs = Transaction.query.filter(
            Transaction.user_id.in_(downline_ids),
            Transaction.status == 'SUCCESS',
            ~Transaction.sku_code.in_(EXCLUDED_SKUS)
        ).all()

        commission_cfg = get_setting_float('commission_flat', 100.0)

        for trx in unlogged_trxs:
            sku = str(getattr(trx, 'sku_code', '') or '').strip()
            if 'DEPOSIT' in sku.upper() or 'UPGRADE' in sku.upper():
                continue

            existing_log = CommissionLog.query.filter_by(transaction_id=trx.id).first()
            if not existing_log:
                prod = Product.query.filter_by(sku_code=sku).first()
                if prod and prod.base_price:
                    margin = max(0.0, float(prod.sell_price or 0.0) - float(prod.base_price or 0.0))
                    max_allowed = max(0.0, margin * 0.30)
                    final_comm = min(commission_cfg, max_allowed)
                    if margin < 150.0:
                        final_comm = min(final_comm, 50.0)
                else:
                    final_comm = min(commission_cfg, 100.0)

                final_comm = round(final_comm, 2)
                if final_comm > 0:
                    new_log = CommissionLog(
                        upline_id=user.id,
                        downline_id=trx.user_id,
                        transaction_id=trx.id,
                        trx_amount=float(trx.amount or 0.0),
                        commission_amount=final_comm,
                        status='earned',
                        created_at=getattr(trx, 'created_at', None) or get_wib_datetime()
                    )
                    db.session.add(new_log)
                    backfilled_count += 1
                    backfilled_amount += final_comm

        if backfilled_count > 0:
            db.session.commit()

    # 3. Hitung total komisi riil berstatus 'earned' (belum dicairkan)
    earned_comm = db.session.query(db.func.sum(CommissionLog.commission_amount)).filter_by(
        upline_id=user.id,
        status='earned'
    ).scalar() or 0.0

    # Total yang sudah pernah dicairkan ('paid_out')
    paid_comm = db.session.query(db.func.sum(CommissionLog.commission_amount)).filter_by(
        upline_id=user.id,
        status='paid_out'
    ).scalar() or 0.0

    # Total riwayat log komisi
    total_logs_count = CommissionLog.query.filter_by(upline_id=user.id).count()

    # 4. Sinkronkan ke commission_balance
    new_balance = round(float(earned_comm), 2)
    user.commission_balance = new_balance
    db.session.commit()

    report = {
        'user_id': user.id,
        'name': user.name,
        'phone': user.phone,
        'role': user.role,
        'is_vip': user.is_vip_active() if hasattr(user, 'is_vip_active') else (user.role == 'vip'),
        'downline_count': len(downlines),
        'backfilled_logs': backfilled_count,
        'backfilled_amount': backfilled_amount,
        'total_logs_count': total_logs_count,
        'total_paid_out': paid_comm,
        'old_commission_balance': old_balance,
        'new_commission_balance': new_balance,
        'difference': round(new_balance - old_balance, 2)
    }

    logger.info(f"[COMMISSION SYNC] User {user.name} ({user.phone}) commission synced: {old_balance} -> {new_balance}")
    return True, f"Saldo komisi {user.name} berhasil disinkronkan menjadi Rp {new_balance:,.0f}", report

