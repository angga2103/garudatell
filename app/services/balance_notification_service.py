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
    """Mengambil nama web/toko dinamis dari pengaturan profil toko (tabel Setting key 'store_name')."""
    try:
        from app.services.setting_service import get_store_name
        name = get_store_name()
        if name and name.strip() and name.strip().lower() != "garudatel":
            return name.strip()
        from app.models.setting import Setting
        s = Setting.query.filter_by(key='store_name').first()
        if s and s.value and s.value.strip() and s.value.strip().lower() != "garudatel":
            return s.value.strip()
        return name.strip() if name and name.strip().lower() != "garudatel" else ""
    except Exception:
        return ""

# ==============================================================================
# 1. NOTIFIKASI PENAMBAHAN / PENGURANGAN SALDO VIA ADMIN (USER & UPLINE)
# ==============================================================================
def _build_adjustment_message_user(store_name, user_name, old_balance, amount, new_balance, action, note, admin_source, ref_id, wib_str):
    """Menyusun pesan WhatsApp ramah & profesional untuk pengguna toko."""
    old_str = format_rupiah(old_balance)
    amt_str = format_rupiah(amount)
    new_str = format_rupiah(new_balance)
    clean_note = note.strip() if note else '-'

    store_in = f" di *{store_name}*" if store_name else ""
    store_from = f" dari *{store_name}*" if store_name else ""
    store_thanks = f" bersama {store_name}" if store_name else ""

    if action == 'add':
        return (
            f"Halo Kak *{user_name}*, 😊\n\n"
            f"Kabar baik! Saldo akun Anda{store_in} telah berhasil *DITAMBAHKAN* oleh Admin ({admin_source}).\n\n"
            f"📋 *DETAIL PENAMBAHAN SALDO:*\n"
            f"• Ref ID: `{ref_id}`\n"
            f"• Saldo Awal: *Rp {old_str}*\n"
            f"• Nominal Masuk: *+Rp {amt_str}*\n"
            f"• Saldo Sekarang: *Rp {new_str}*\n"
            f"• Waktu: {wib_str} WIB\n"
            f"• Keterangan: _{clean_note}_\n\n"
            f"Terima kasih atas kepercayaannya{store_thanks}. Selamat bertransaksi kembali, semoga usaha dan penjualan Kakak semakin lancar, sukses, dan berkah! 🚀🙏"
        )
    else:
        return (
            f"Halo Kak *{user_name}*, 😊\n\n"
            f"Pemberitahuan resmi{store_from}: Telah dilakukan *PENYESUAIAN SALDO* pada akun Anda oleh Admin ({admin_source}).\n\n"
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
    store_from = f" dari *{store_name}*" if store_name else ""

    if action == 'add':
        return (
            f"Halo Kak *{upline_name}*, 😊\n\n"
            f"Pemberitahuan kemitraan{store_from}:\n\n"
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
            f"Pemberitahuan kemitraan{store_from}:\n\n"
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
        f"⚠️ *PERINGATAN SISA SALDO MINIM*\n"
        f"Saat ini sisa saldo akun Anda berada di bawah batas aman:\n"
        f"💰 *Sisa Saldo Saat Ini:* *Rp {bal_str}* (di bawah Rp 100.000)\n\n"
        f"Agar aktivitas transaksi dan pemesanan pelanggan di toko Kakak tetap berjalan lancar tanpa kendala, yuk segera lakukan isi ulang (Top Up) saldo akun Anda.\n\n"
        f"Terima kasih banyak atas perhatiannya, semoga rezeki dan penjualan toko Kakak semakin berkah & melimpah! 🙏✨"
    )

def _build_low_balance_message_upline(store_name, upline_name, user_name, user_phone, current_balance, option1=None, option2=None, dana_number=None, dana_name=None, expiry_time_str=None):
    bal_str = format_rupiah(current_balance)
    store_from = f" dari *{store_name}*" if store_name else ""
    
    topup_section = ""
    if option1 and option2 and dana_number:
        opt1_str = format_rupiah(option1)
        opt2_str = format_rupiah(option2)
        target_name = dana_name or "ANGGA DIAN PRATAMA PUTRA"
        if not expiry_time_str:
            expiry_dt = get_wib_now() + timedelta(hours=8)
            expiry_time_str = expiry_dt.strftime('%H.%M WIB')

        topup_section = (
            f"\n\nAtau Kakak dapat langsung membantu melakukan pengisian saldo (Top-Up) untuk mitra tersebut via Transfer Tunai *DANA* Otomatis ke:\n"
            f"📱 No. *DANA*: `{dana_number}`\n"
            f"👤 A/N: *{target_name}*\n\n"
            f"Pilih salah satu nominal berikut:\n"
            f"🔹 Pilihan 1: *Rp {opt1_str}*\n"
            f"🔹 Pilihan 2: *Rp {opt2_str}*\n\n"
            f"⚡ *SISTEM AUTO OTOMATIS AKTIF:*\n"
            f"Saldo akan *langsung otomatis masuk* ke akun mitra Anda dalam hitungan detik *tanpa harus kirim bukti transfer*, asalkan nominal yang Kakak transfer *sama persis sampai 3 digit angka terakhir*.\n\n"
            f"⏰ *Batas Waktu:* Sebelum pukul *{expiry_time_str}* (nominal tiket otomatis diperbarui setelah batas waktu)."
        )

    return (
        f"Halo Kak *{upline_name}*, 😊\n\n"
        f"Pemberitahuan kemitraan{store_from}:\n\n"
        f"Mitra / Downline Anda:\n"
        f"👤 Nama: *{user_name}*\n"
        f"📱 No. WhatsApp: `{user_phone}`\n"
        f"💰 *Sisa Saldo:* *Rp {bal_str}* (di bawah batas Rp 100.000)\n\n"
        f"Demi menjaga kelancaran transaksi penjualan toko mitra Anda serta kelangsungan bonus komisi kemitraan Anda, Kakak dapat mengingatkan mitra tersebut untuk segera melakukan isi saldo."
        f"{topup_section}\n\n"
        f"Terima kasih atas peran aktif Kakak dalam membimbing jaringan kemitraan! 🚀🤝"
    )

def cleanup_expired_upline_tickets(max_hours=8):
    """
    Membatalkan seluruh tiket UPLINE_TOPUP yang masih PENDING tetapi sudah
    melewati batas waktu (default 8 jam) agar tidak menggantung di sistem.
    """
    try:
        from app.models.transaction import Transaction
        from app.extensions import db
        from datetime import datetime, timedelta

        cutoff = datetime.utcnow() - timedelta(hours=max_hours)
        expired_tickets = Transaction.query.filter(
            Transaction.sku_code == 'DEPOSIT_MANUAL',
            Transaction.status == 'PENDING',
            Transaction.sn.like('%UPLINE_TOPUP:%'),
            Transaction.created_at < cutoff
        ).all()

        if expired_tickets:
            for t in expired_tickets:
                t.status = 'CANCELLED'
                t.payment_status = 'CANCELLED'
                t.sn = f"{t.sn or ''} | EXPIRED (Batas waktu {max_hours} jam habis)"
            db.session.commit()
            logger.info(f"[EXPIRED TICKETS] {len(expired_tickets)} tiket upline topup kadaluarsa berhasil dibatalkan.")
    except Exception as e:
        db.session.rollback()
        logger.error(f"[CLEANUP EXPIRED TICKETS ERR]: {e}")


def create_upline_downline_deposit_tickets(downline_user, upline_user, amounts=(250000, 500000)):
    """
    Membuat 2 tiket deposit DANA otomatis atas nama Downline agar Upline
    bisa memilih salah satu nominal transfer langsung dari WhatsApp.
    Ketika salah satu tiket dibayar, tiket pasangannya otomatis dibatalkan.
    """
    try:
        from app.services.dana_mutasi_service import generate_unique_code
        from app.services.setting_service import get_manual_deposit_settings
        from app.models.transaction import Transaction
        import uuid, time, random

        # Bersihkan tiket-tiket lama yang sudah melewati batas 8 jam
        cleanup_expired_upline_tickets(max_hours=8)

        depo_settings = get_manual_deposit_settings()
        dest_number = depo_settings.get('dana_number') or "081775700114"
        dest_name = depo_settings.get('dana_name') or "ANGGA DIAN PRATAMA PUTRA"

        # Cek apakah sudah ada tiket pending aktif dalam 8 jam terakhir untuk upline-downline ini
        cutoff_active = datetime.utcnow() - timedelta(hours=8)
        existing_tickets = Transaction.query.filter(
            Transaction.sku_code == 'DEPOSIT_MANUAL',
            Transaction.user_id == downline_user.id,
            Transaction.status == 'PENDING',
            Transaction.payment_status == 'UNPAID',
            Transaction.created_at >= cutoff_active,
            Transaction.sn.like(f"%UPLINE_TOPUP:{upline_user.id}:%")
        ).order_by(Transaction.id.asc()).all()

        if len(existing_tickets) >= 2:
            return int(existing_tickets[0].amount), int(existing_tickets[1].amount), dest_number, dest_name

        # Jika ada sisa tiket lama yang tidak lengkap, batalkan
        for old in existing_tickets:
            old.status = 'CANCELLED'
            old.payment_status = 'CANCELLED'
        if existing_tickets:
            db.session.commit()

        pair_id = uuid.uuid4().hex[:8]
        tickets = []

        for nominal in amounts:
            unique_code, total_transfer = generate_unique_code(nominal)
            ref_id = f"DEP-DANA-{int(time.time())}{random.randint(100, 999)}"

            downline_label = getattr(downline_user, 'name', '') or f"#{downline_user.id}"
            trx = Transaction(
                ref_id=ref_id,
                user_id=downline_user.id,
                sku_code='DEPOSIT_MANUAL',
                product_name=f"Top-up DANA Mitra ({downline_label})",
                target_number=dest_number,
                amount=float(total_transfer),
                base_price=0.0,
                payment_method='dana_auto',
                payment_status='UNPAID',
                status='PENDING',
                is_prepaid=True,
                sn=f"UPLINE_TOPUP:{upline_user.id}:{pair_id} | Nominal Pokok: Rp {int(nominal):,} | Kode Unik: {unique_code:03d} | Total: Rp {total_transfer:,} | Rek: {dest_number} a.n {dest_name} (DANA)"
            )
            db.session.add(trx)
            tickets.append(total_transfer)

        db.session.commit()
        return tickets[0], tickets[1], dest_number, dest_name
    except Exception as e:
        db.session.rollback()
        logger.error(f"[UPLINE TOPUP] Gagal membuat tiket deposit: {e}")
        return None, None, None, None

def send_upline_topup_success_notifications(upline_id, downline_user, amount, new_balance):
    """
    Mengirim notifikasi WhatsApp keberhasilan Top-up:
    1. Ke Upline (konfirmasi transfer diterima & saldo downline telah bertambah)
    2. Ke Downline (kabar gembira saldo telah diisikan oleh upline)
    """
    try:
        amt_str = format_rupiah(amount)
        new_bal_str = format_rupiah(new_balance)
        wib_str = format_wib()

        upline = db.session.get(User, int(upline_id)) if upline_id else None

        # 1. Kirim ke Upline
        if upline and upline.phone:
            msg_upline = (
                f"✅ *TOP-UP DOWNLINE BERHASIL*\n\n"
                f"Terima kasih Kak *{upline.name}*, 😊\n"
                f"Pembayaran sebesar *Rp {amt_str}* via Transfer Tunai DANA telah kami terima.\n\n"
                f"📥 Saldo sebesar *Rp {amt_str}* telah otomatis ditambahkan ke akun mitra / downline Anda:\n"
                f"👤 Nama: *{downline_user.name}*\n"
                f"📱 No. WhatsApp: `{downline_user.phone}`\n"
                f"💰 *Sisa Saldo Baru Mitra:* *Rp {new_bal_str}*\n"
                f"⏰ Waktu: {wib_str} WIB\n\n"
                f"Transaksi mitra kini dapat berjalan lancar kembali dan bonus komisi Kakak terus mengalir. Sukses selalu untuk kemitraan Anda! 🚀🤝"
            )
            kirim_wa(upline.phone, msg_upline)
            logger.info(f"[UPLINE TOPUP SUCCESS] Notif WA terkirim ke Upline #{upline.id} ({upline.phone})")

        # 2. Kirim ke Downline
        if downline_user and downline_user.phone:
            upline_name_str = upline.name if upline else "Upline Anda"
            msg_downline = (
                f"🎁 *SALDO MASUK DARI UPLINE*\n\n"
                f"Halo Kak *{downline_user.name}*, 😊\n"
                f"Kabar gembira! Upline Anda (*{upline_name_str}*) baru saja membantu melakukan pengisian saldo akun Anda:\n\n"
                f"💵 *Nominal Masuk:* *+Rp {amt_str}*\n"
                f"💳 *Sisa Saldo Anda Sekarang:* *Rp {new_bal_str}*\n"
                f"⏰ Waktu: {wib_str} WIB\n\n"
                f"Saldo sudah aktif dan siap digunakan untuk bertransaksi kembali di toko Anda. Selamat bertransaksi dan semoga penjualan semakin laris & berkah! ✨🙏"
            )
            kirim_wa(downline_user.phone, msg_downline)
            logger.info(f"[UPLINE TOPUP SUCCESS] Notif WA terkirim ke Downline #{downline_user.id} ({downline_user.phone})")

    except Exception as e:
        logger.error(f"[UPLINE TOPUP NOTIF ERR] {e}")

def _dispatch_low_balance_worker(app, user_id, current_balance):
    """Worker background untuk mengirim alert saldo minim via WA."""
    with app.app_context():
        try:
            user = db.session.get(User, int(user_id))
            if not user:
                return

            store_name = get_app_store_name()
            u_name = user.name
            u_phone = user.phone
            upline_id = getattr(user, 'upline_id', None)

            # 1. Kirim ke User (Downline)
            if u_phone:
                msg_user = _build_low_balance_message_user(store_name, u_name, current_balance)
                ok_user = kirim_wa(u_phone, msg_user)
                logger.info(f"[WA LOW BAL ALERT] Kirim ke User #{user_id} ({u_phone}): {'Sukses' if ok_user else 'Gagal'}")

            # 2. Kirim ke Upline jika ada
            if upline_id:
                upline = db.session.get(User, int(upline_id))
                if upline and upline.phone:
                    opt1, opt2, d_num, d_name = create_upline_downline_deposit_tickets(user, upline)
                    msg_upline = _build_low_balance_message_upline(
                        store_name, upline.name, u_name, u_phone, current_balance,
                        option1=opt1, option2=opt2, dana_number=d_num, dana_name=d_name
                    )
                    ok_upline = kirim_wa(upline.phone, msg_upline)
                    logger.info(f"[WA LOW BAL ALERT] Kirim ke Upline #{upline.id} ({upline.phone}): {'Sukses' if ok_upline else 'Gagal'}")

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

    user = db.session.get(User, int(user_id))
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


def scan_and_notify_all_low_balance_users(force_all=False):
    """
    Memindai seluruh akun pengguna aktif yang saat ini memiliki saldo < Rp 100.000.
    Jika force_all=True: abaikan cooldown 12 jam (berguna saat admin memicu manual / pertama kali).
    Jika force_all=False: hormati cooldown 12 jam agar tidak spam.
    
    Returns:
        dict: {
            'total_low': int,
            'notified_users': int,
            'notified_uplines': int,
            'details': list
        }
    """
    store_name = get_app_store_name()
    now_naive = datetime.utcnow()

    # Ambil user aktif yang saldonya di bawah batas Rp 100.000
    low_users = User.query.filter(
        User.balance < LOW_BALANCE_THRESHOLD,
        User.is_active == True
    ).all()

    total_low = len(low_users)
    notified_users = 0
    notified_uplines = 0
    details = []

    for u in low_users:
        last_notif = getattr(u, 'last_low_balance_notified_at', None)
        should_notify = force_all or (last_notif is None)
        if not should_notify and last_notif:
            diff_hours = (now_naive - last_notif).total_seconds() / 3600.0
            if diff_hours >= LOW_BALANCE_COOLDOWN_HOURS:
                should_notify = True

        if should_notify:
            u.last_low_balance_notified_at = now_naive
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

            cur_bal = float(u.balance or 0.0)

            # 1. Kirim WA ke User
            if u.phone:
                try:
                    msg_user = _build_low_balance_message_user(store_name, u.name, cur_bal)
                    ok_user = kirim_wa(u.phone, msg_user)
                    if ok_user:
                        notified_users += 1
                        logger.info(f"[SCAN LOW BAL] WA terkirim ke User #{u.id} ({u.phone})")
                except Exception as e_u:
                    logger.error(f"[SCAN LOW BAL] Gagal kirim ke user #{u.id} ({u.phone}): {e_u}")

            # 2. Kirim WA ke Upline jika ada
            if u.upline and u.upline.phone:
                try:
                    opt1, opt2, d_num, d_name = create_upline_downline_deposit_tickets(u, u.upline)
                    msg_upline = _build_low_balance_message_upline(
                        store_name, u.upline.name, u.name, u.phone, cur_bal,
                        option1=opt1, option2=opt2, dana_number=d_num, dana_name=d_name
                    )
                    ok_upline = kirim_wa(u.upline.phone, msg_upline)
                    if ok_upline:
                        notified_uplines += 1
                        logger.info(f"[SCAN LOW BAL] WA terkirim ke Upline #{u.upline.id} ({u.upline.phone})")
                except Exception as e_up:
                    logger.error(f"[SCAN LOW BAL] Gagal kirim ke upline #{u.upline.id} ({u.upline.phone}): {e_up}")

            details.append({
                'user_id': u.id,
                'name': u.name,
                'phone': u.phone,
                'balance': cur_bal
            })

    logger.info(f"[SCAN LOW BAL FINISHED] Total: {total_low}, User Notif: {notified_users}, Upline Notif: {notified_uplines}")
    return {
        'total_low': total_low,
        'notified_users': notified_users,
        'notified_uplines': notified_uplines,
        'details': details
    }


