import logging
import threading
from datetime import datetime, timezone, timedelta
from flask import current_app
from app.extensions import db
from app.models.user import User
from app.wa_helper import kirim_wa

logger = logging.getLogger(__name__)

# Standardisasi Timezone WIB (Waktu Indonesia Barat / GMT+7)
WIB_TZ = timezone(timedelta(hours=7))

def get_wib_now():
    return datetime.now(WIB_TZ)

def format_wib(dt=None, fmt='%d/%m/%Y %H:%M'):
    if dt is None:
        dt = get_wib_now()
    elif isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except Exception:
            return dt
    if hasattr(dt, 'tzinfo') and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc).astimezone(WIB_TZ)
    elif hasattr(dt, 'astimezone'):
        dt = dt.astimezone(WIB_TZ)
    return dt.strftime(fmt)

def format_rupiah(amount):
    try:
        val = float(amount or 0.0)
        return f"{val:,.0f}".replace(',', '.')
    except Exception:
        return "0"

def get_app_store_name():
    try:
        from app.services.setting_service import get_store_name
        return get_store_name() or "GarudaTel"
    except Exception:
        return "GarudaTel"

# ==============================================================================
# 1. NOTIFIKASI PENAMBAHAN / PENGURANGAN SALDO VIA ADMIN (USER & UPLINE)
# ==============================================================================
def _build_adjustment_message_user(store_name, user_name, old_balance, amount, new_balance, action, note, admin_source, ref_id, wib_str):
    """Menyusun pesan WhatsApp ramah & profesional untuk pengguna toko."""
    old_str = format_rupiah(old_balance)
    amt_str = format_rupiah(amount)
    new_str = format_rupiah(new_balance)
    clean_note = note.strip() if note else '-'

    if action == 'add':
        return (
            f"Halo Kak *{user_name}*, 😊\n\n"
            f"Kabar baik! Saldo akun Anda di *{store_name}* telah berhasil *DITAMBAHKAN* oleh Admin ({admin_source}).\n\n"
            f"📋 *DETAIL PENAMBAHAN SALDO:*\n"
            f"• Ref ID: `{ref_id}`\n"
            f"• Saldo Awal: *Rp {old_str}*\n"
            f"• Nominal Masuk: *+Rp {amt_str}*\n"
            f"• Saldo Sekarang: *Rp {new_str}*\n"
            f"• Waktu: {wib_str} WIB\n"
            f"• Keterangan: _{clean_note}_\n\n"
            f"Terima kasih atas kepercayaannya bersama {store_name}. Selamat bertransaksi kembali, semoga usaha dan penjualan Kakak semakin lancar, sukses, dan berkah! 🚀🙏"
        )
    else:
        return (
            f"Halo Kak *{user_name}*, 😊\n\n"
            f"Pemberitahuan resmi dari *{store_name}*: Telah dilakukan *PENYESUAIAN SALDO* pada akun Anda oleh Admin ({admin_source}).\n\n"
            f"📋 *DETAIL PENYESUAIAN SALDO:*\n"
            f"• Ref ID: `{ref_id}`\n"
            f"• Saldo Awal: *Rp {old_str}*\n"
            f"• Nominal Penyesuaian: *-Rp {amt_str}*\n"
            f"• Saldo Sekarang: *Rp {new_str}*\n"
            f"• Waktu: {wib_str} WIB\n"
            f"• Keterangan: _{clean_note}_\n\n"
            f"Jika Kakak memiliki pertanyaan terkait penyesuaian ini, jangan ragu untuk menghubungi layanan pelanggan kami. Terima kasih atas pengertian dan kerja samanya! 🙏"
        )

def _build_adjustment_message_upline(store_name, upline_name, user_name, user_phone, old_balance, amount, new_balance, action, ref_id, wib_str):
    """Menyusun pesan WhatsApp kemitraan ramah untuk upline."""
    old_str = format_rupiah(old_balance)
    amt_str = format_rupiah(amount)
    new_str = format_rupiah(new_balance)

    if action == 'add':
        return (
            f"Halo Kak *{upline_name}*, 😊\n\n"
            f"Pemberitahuan kemitraan dari *{store_name}*:\n\n"
            f"Mitra / Downline Anda:\n"
            f"👤 Nama: *{user_name}*\n"
            f"📱 No. WhatsApp: `{user_phone}`\n\n"
            f"Telah menerima penambahan saldo oleh Admin:\n"
            f"• Saldo Awal: *Rp {old_str}*\n"
            f"• Nominal Masuk: *+Rp {amt_str}*\n"
            f"• Saldo Akhir: *Rp {new_str}*\n"
            f"• Ref ID: `{ref_id}`\n"
            f"• Waktu: {wib_str} WIB\n\n"
            f"Informasi ini disampaikan otomatis sebagai transparansi jaringan kemitraan Anda. Terima kasih atas kerja sama dan bimbingannya yang luar biasa! 🌟🤝"
        )
    else:
        return (
            f"Halo Kak *{upline_name}*, 😊\n\n"
            f"Pemberitahuan kemitraan dari *{store_name}*:\n\n"
            f"Telah dilakukan penyesuaian saldo oleh Admin untuk mitra/downline Anda:\n"
            f"👤 Nama: *{user_name}*\n"
            f"📱 No. WhatsApp: `{user_phone}`\n\n"
            f"• Saldo Awal: *Rp {old_str}*\n"
            f"• Nominal Penyesuaian: *-Rp {amt_str}*\n"
            f"• Saldo Akhir: *Rp {new_str}*\n"
            f"• Ref ID: `{ref_id}`\n"
            f"• Waktu: {wib_str} WIB\n\n"
            f"Informasi ini disampaikan otomatis sebagai transparansi jaringan kemitraan Anda. Salam sukses selalu! 🌟🤝"
        )

def _dispatch_admin_adjustment_worker(app, user_id, old_balance, amount, new_balance, action, note, admin_source, ref_id):
    """Worker asynchronous untuk mengirim notifikasi penambahan/pengurangan saldo via WA."""
    with app.app_context():
        try:
            user = User.query.get(user_id)
            if not user:
                return

            store_name = get_app_store_name()
            wib_str = format_wib()

            # 1. Kirim ke WhatsApp User
            if user.phone:
                msg_user = _build_adjustment_message_user(
                    store_name=store_name,
                    user_name=user.name,
                    old_balance=old_balance,
                    amount=amount,
                    new_balance=new_balance,
                    action=action,
                    note=note,
                    admin_source=admin_source,
                    ref_id=ref_id,
                    wib_str=wib_str
                )
                ok_user = kirim_wa(user.phone, msg_user)
                logger.info(f"[WA NOTIF ADJ] Kirim ke User #{user.id} ({user.phone}): {'Sukses' if ok_user else 'Gagal'}")

            # 2. Kirim ke WhatsApp Upline jika ada
            if user.upline and user.upline.phone:
                msg_upline = _build_adjustment_message_upline(
                    store_name=store_name,
                    upline_name=user.upline.name,
                    user_name=user.name,
                    user_phone=user.phone,
                    old_balance=old_balance,
                    amount=amount,
                    new_balance=new_balance,
                    action=action,
                    ref_id=ref_id,
                    wib_str=wib_str
                )
                ok_upline = kirim_wa(user.upline.phone, msg_upline)
                logger.info(f"[WA NOTIF ADJ] Kirim ke Upline #{user.upline.id} ({user.upline.phone}): {'Sukses' if ok_upline else 'Gagal'}")

        except Exception as e:
            logger.error(f"[WA NOTIF ADJ] Error saat mengirim notifikasi: {e}")

def notify_admin_balance_adjustment(user_id, old_balance, amount, new_balance, action='add', note='', admin_source='Admin', ref_id=None):
    """
    Memicu pengiriman notifikasi WhatsApp otomatis ke user dan upline di background thread.
    Aman, non-blocking, dan tidak memperlambat respon web/bot.
    """
    try:
        app = current_app._get_current_object()
        clean_ref = str(ref_id or f"TRX-ADM-{int(datetime.utcnow().timestamp())}")
        thread = threading.Thread(
            target=_dispatch_admin_adjustment_worker,
            args=(app, user_id, old_balance, amount, new_balance, action, note, admin_source, clean_ref),
            daemon=True
        )
        thread.start()
    except Exception as e:
        logger.error(f"[WA NOTIF ADJ] Gagal memulai thread: {e}")


# ==============================================================================
# 2. NOTIFIKASI PERINGATAN SALDO MINIM (< Rp 100.000) (USER & UPLINE)
# ==============================================================================
LOW_BALANCE_THRESHOLD = 100000.0  # Rp 100.000
LOW_BALANCE_COOLDOWN_HOURS = 12   # Hindari spam jika transaksi beruntun di bawah 100k

def _build_low_balance_message_user(store_name, user_name, current_balance):
    bal_str = format_rupiah(current_balance)
    return (
        f"Halo Kak *{user_name}*, 😊\n\n"
        f"Pengingat ramah dari *{store_name}*:\n\n"
        f"⚠️ *PERINGATAN SISA SALDO MINIM*\n"
        f"Saat ini sisa saldo akun Anda berada di bawah batas aman:\n"
        f"💰 *Sisa Saldo Saat Ini:* *Rp {bal_str}* (di bawah Rp 100.000)\n\n"
        f"Agar aktivitas transaksi dan pemesanan pelanggan di toko Kakak tetap berjalan lancar tanpa kendala, yuk segera lakukan isi ulang (Top Up) saldo akun Anda.\n\n"
        f"📌 *Cara Top Up Praktis:*\n"
        f"1. Buka menu *Deposit Saldo* di web {store_name}\n"
        f"2. Masukkan nominal & bayar mudah via QRIS (Otomatis masuk hitungan detik!)\n\n"
        f"Terima kasih banyak atas perhatiannya, semoga rezeki dan penjualan toko Kakak semakin berkah & melimpah! 🙏✨"
    )

def _build_low_balance_message_upline(store_name, upline_name, user_name, user_phone, current_balance):
    bal_str = format_rupiah(current_balance)
    return (
        f"Halo Kak *{upline_name}*, 😊\n\n"
        f"Pemberitahuan kemitraan dari *{store_name}*:\n\n"
        f"Mitra / Downline Anda:\n"
        f"👤 Nama: *{user_name}*\n"
        f"📱 No. WhatsApp: `{user_phone}`\n"
        f"💰 *Sisa Saldo:* *Rp {bal_str}* (di bawah batas Rp 100.000)\n\n"
        f"Demi menjaga kelancaran transaksi penjualan toko mitra Anda serta kelangsungan bonus komisi kemitraan Anda, Kakak dapat mengingatkan mitra tersebut untuk segera melakukan isi saldo.\n\n"
        f"Terima kasih atas peran aktif Kakak dalam membimbing jaringan kemitraan {store_name}! 🚀🤝"
    )

def _dispatch_low_balance_worker(app, user_id, current_balance):
    """Worker background untuk mengirim alert saldo minim via WA."""
    with app.app_context():
        try:
            user = User.query.get(user_id)
            if not user:
                return

            store_name = get_app_store_name()

            # 1. Kirim ke User
            if user.phone:
                msg_user = _build_low_balance_message_user(store_name, user.name, current_balance)
                ok_user = kirim_wa(user.phone, msg_user)
                logger.info(f"[WA LOW BAL ALERT] Kirim ke User #{user.id} ({user.phone}): {'Sukses' if ok_user else 'Gagal'}")

            # 2. Kirim ke Upline jika ada
            if user.upline and user.upline.phone:
                msg_upline = _build_low_balance_message_upline(store_name, user.upline.name, user.name, user.phone, current_balance)
                ok_upline = kirim_wa(user.upline.phone, msg_upline)
                logger.info(f"[WA LOW BAL ALERT] Kirim ke Upline #{user.upline.id} ({user.upline.phone}): {'Sukses' if ok_upline else 'Gagal'}")

        except Exception as e:
            logger.error(f"[WA LOW BAL ALERT] Error saat mengirim alert saldo minim: {e}")

def check_and_notify_low_balance(user_id, old_balance, new_balance):
    """
    Mengevaluasi apakah saldo pengguna berada di bawah ambang batas (Rp 100.000).
    - Jika new_balance >= 100.000: reset cooldown flag sehingga jika nanti turun lagi di bawah 100k, langsung terpicu lagi.
    - Jika new_balance < 100.000: cek kelayakan kirim (transisi baru dari >=100k ke <100k, atau cooldown 12 jam).
    """
    try:
        new_balance = float(new_balance)
        old_balance = float(old_balance)
    except Exception:
        return False

    user = User.query.get(user_id)
    if not user:
        return False

    now_naive = datetime.utcnow()

    # KASUS 1: Saldo kembali aman (>= 100k) -> Reset status pengingat
    if new_balance >= LOW_BALANCE_THRESHOLD:
        if getattr(user, 'last_low_balance_notified_at', None) is not None:
            user.last_low_balance_notified_at = None
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        return False

    # KASUS 2: Saldo berada di bawah 100k
    last_notif = getattr(user, 'last_low_balance_notified_at', None)
    is_fresh_dip = (old_balance >= LOW_BALANCE_THRESHOLD and new_balance < LOW_BALANCE_THRESHOLD)
    is_cooldown_expired = False

    if last_notif:
        diff_hours = (now_naive - last_notif).total_seconds() / 3600.0
        if diff_hours >= LOW_BALANCE_COOLDOWN_HOURS:
            is_cooldown_expired = True
    else:
        is_cooldown_expired = True

    should_send = is_fresh_dip or is_cooldown_expired

    if should_send:
        user.last_low_balance_notified_at = now_naive
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Luncurkan pengiriman pesan di background thread
        try:
            app = current_app._get_current_object()
            t = threading.Thread(
                target=_dispatch_low_balance_worker,
                args=(app, user.id, new_balance),
                daemon=True
            )
            t.start()
            return True
        except Exception as ex:
            logger.error(f"[WA LOW BAL ALERT] Gagal start thread: {ex}")
            return False

    return False
