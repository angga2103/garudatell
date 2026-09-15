import time
import secrets
from datetime import datetime, timezone
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction

def adjust_user_balance_manual(user_id, amount, action='add', note='', admin_source='Web Admin'):
    """
    Menambah ('add') atau mengurangi ('deduct') saldo toko/user secara manual oleh Admin.
    
    Fitur Utama:
    1. Update saldo user.balance secara aman (atomic dengan database transaction).
    2. Mencatat baris transaksi resmi (Transaction) sehingga:
       - Tampil di Riwayat Transaksi Admin (/admin/transactions) lengkap dengan nominal, status, dan catatan.
       - Tampil di Riwayat Mutasi User (/mutasi) secara transparan.
    3. Mengembalikan (success: bool, new_balance: float, message: str, trx: Transaction|None).
    """
    try:
        amount = float(amount)
    except (ValueError, TypeError):
        return False, 0.0, "Nominal saldo tidak valid!", None

    if amount <= 0:
        return False, 0.0, "Nominal saldo harus lebih besar dari Rp 0!", None

    user = User.query.filter_by(id=user_id).with_for_update().first()
    if not user:
        return False, 0.0, f"User/Toko ID #{user_id} tidak ditemukan!", None

    old_balance = float(user.balance or 0.0)
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    clean_source = str(admin_source or 'Admin').strip()
    clean_note = str(note or '').strip()

    if action == 'add':
        new_balance = old_balance + amount
        user.balance = new_balance
        ref_id = f"TOPUP-ADM-{int(time.time())}-{secrets.token_hex(3).upper()}"
        sn_text = f"Ditambahkan oleh Admin ({clean_source})"
        if clean_note:
            sn_text += f": {clean_note}"

        trx = Transaction(
            user_id=user.id,
            product_name="Topup Saldo Admin",
            sku_code="DEPOSIT_MANUAL",
            amount=amount,
            target_number=user.phone,
            payment_method="MANUAL_ADMIN",
            payment_status="PAID",
            status="SUCCESS",
            sn=sn_text,
            ref_id=ref_id,
            created_at=now_utc,
            updated_at=now_utc
        )
        db.session.add(trx)
        db.session.commit()

        # Kirim notifikasi WhatsApp ke User dan Upline secara asinkron
        try:
            from app.services.balance_notification_service import (
                notify_admin_balance_adjustment,
                check_and_notify_low_balance
            )
            notify_admin_balance_adjustment(
                user_id=user.id,
                old_balance=old_balance,
                amount=amount,
                new_balance=new_balance,
                action='add',
                note=clean_note,
                admin_source=clean_source,
                ref_id=ref_id
            )
            check_and_notify_low_balance(user.id, old_balance, new_balance)
        except Exception as e_notif:
            print(f"[SALDO MANUAL NOTIF ERR] Gagal trigger notifikasi WA: {e_notif}")

        msg = f"Berhasil menambahkan saldo Rp {amount:,.0f} ke toko {user.name}. Saldo baru: Rp {new_balance:,.0f}."
        print(f"[SALDO MANUAL ADD] User #{user.id} ({user.name}) +Rp {amount:,.0f} oleh {clean_source}. Ref: {ref_id}")
        return True, new_balance, msg, trx

    elif action == 'deduct':
        new_balance = max(0.0, old_balance - amount)
        user.balance = new_balance
        ref_id = f"ADJ-ADM-{int(time.time())}-{secrets.token_hex(3).upper()}"
        sn_text = f"Pengurangan/Sinkronisasi oleh Admin ({clean_source})"
        if clean_note:
            sn_text += f": {clean_note}"

        trx = Transaction(
            user_id=user.id,
            product_name="Penyesuaian Saldo Admin",
            sku_code="MANUAL_DEDUCTION",
            amount=amount,
            target_number=user.phone,
            payment_method="SALDO",
            payment_status="PAID",
            status="SUCCESS",
            sn=sn_text,
            ref_id=ref_id,
            created_at=now_utc,
            updated_at=now_utc
        )
        db.session.add(trx)
        db.session.commit()

        # Kirim notifikasi WhatsApp ke User dan Upline secara asinkron
        try:
            from app.services.balance_notification_service import (
                notify_admin_balance_adjustment,
                check_and_notify_low_balance
            )
            notify_admin_balance_adjustment(
                user_id=user.id,
                old_balance=old_balance,
                amount=amount,
                new_balance=new_balance,
                action='deduct',
                note=clean_note,
                admin_source=clean_source,
                ref_id=ref_id
            )
            check_and_notify_low_balance(user.id, old_balance, new_balance)
        except Exception as e_notif:
            print(f"[SALDO MANUAL NOTIF ERR] Gagal trigger notifikasi WA: {e_notif}")

        msg = f"Berhasil memotong/menyesuaikan saldo Rp {amount:,.0f} dari toko {user.name}. Saldo baru: Rp {new_balance:,.0f}."
        print(f"[SALDO MANUAL DEDUCT] User #{user.id} ({user.name}) -Rp {amount:,.0f} oleh {clean_source}. Ref: {ref_id}")
        return True, new_balance, msg, trx

    else:
        return False, old_balance, f"Aksi '{action}' tidak dikenali (gunakan 'add' atau 'deduct')!", None
