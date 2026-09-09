import secrets
from datetime import datetime, timezone, timedelta
from sqlalchemy import func
from app.extensions import db
from app.models.trusted_device import TrustedDevice
from app.models.user import User
from app.models.transaction import Transaction
from app.models.branch_mutation import BranchMutation
from app.wa_helper import kirim_wa
import logging

logger = logging.getLogger(__name__)

def now_wib():
    """Mengembalikan datetime objek dalam zona waktu WIB (UTC+7)."""
    return datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)

def register_device_request(user, device_uuid, device_name, user_agent=None, ip_address=None, base_url=None):
    """
    Mendaftarkan atau memperbarui permintaan otorisasi perangkat kasir cabang toko.
    Hanya dapat digunakan oleh akun VIP yang aktif.
    """
    if not user or not user.is_vip_active():
        return False, None, "Fitur Kunci Kasir & Multi-Cabang hanya tersedia untuk akun VIP aktif."

    if not device_uuid or not str(device_uuid).strip():
        return False, None, "Token identitas perangkat tidak valid."

    clean_device_name = str(device_name or '').strip()
    if not clean_device_name:
        return False, None, "Nama Cabang / Perangkat kasir wajib diisi (contoh: Cabang 1 - Pasar Baru)."

    # Format info perangkat
    clean_ua = str(user_agent or 'Browser Web').strip()[:250]
    clean_ip = str(ip_address or '-').strip()[:50]

    # Generate approval token unik (berlaku 15 menit)
    approval_token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(minutes=15)

    # Cek apakah device sudah ada untuk user ini
    device = TrustedDevice.query.filter_by(user_id=user.id, device_uuid=device_uuid).first()
    if device:
        # Jika sebelumnya sudah approved, perbarui nama/info tanpa mereset jika tidak diminta
        device.device_name = clean_device_name
        device.device_info = clean_ua
        device.ip_address = clean_ip
        device.approval_token = approval_token
        device.approval_expires_at = expires_at
        device.status = 'pending'
    else:
        device = TrustedDevice(
            user_id=user.id,
            device_uuid=device_uuid,
            device_name=clean_device_name,
            device_info=clean_ua,
            ip_address=clean_ip,
            status='pending',
            approval_token=approval_token,
            approval_expires_at=expires_at,
            created_at=datetime.utcnow()
        )
        db.session.add(device)

    db.session.commit()

    # Kirim notifikasi WhatsApp interaktif 1-klik ke Owner
    domain = (base_url or 'https://ipay.my.id').rstrip('/')
    approve_url = f"{domain}/vip/device/approve/{approval_token}"
    reject_url = f"{domain}/vip/device/reject/{approval_token}"

    wib_str = now_wib().strftime('%d-%m-%Y %H:%M WIB')

    pesan_wa = (
        f"🦅 *[GARUDATELL - OTORISASI KASIR CABANG]*\n\n"
        f"Halo *{user.name}*, ada permintaan pendaftaran perangkat kasir baru untuk toko Anda:\n\n"
        f"🏪 *Nama Cabang:* {clean_device_name}\n"
        f"💻 *Perangkat:* {clean_ua[:80]}\n"
        f"🌐 *Alamat IP:* {clean_ip}\n"
        f"⏰ *Waktu:* {wib_str}\n\n"
        f"Apakah Anda mengizinkan perangkat ini melakukan transaksi menggunakan *Saldo Toko* Anda?\n\n"
        f"✅ *SETUJUI PERANGKAT (1-KLIK):*\n"
        f"{approve_url}\n\n"
        f"❌ *TOLAK PERANGKAT:*\n"
        f"{reject_url}\n\n"
        f"⚠️ _Tautan persetujuan ini berlaku selama 15 menit. Hanya setujui jika perangkat ini adalah staf/kasir resmi toko Anda._"
    )

    try:
        wa_sent = kirim_wa(user.phone, pesan_wa)
        if not wa_sent:
            logger.warning(f"[-] Bot WA gagal mengirim pesan otorisasi ke {user.phone}")
    except Exception as e:
        logger.error(f"[-] Error kirim WA otorisasi kasir: {e}")

    return True, device, "Permintaan izin telah dikirim ke WhatsApp Owner toko. Menunggu persetujuan..."

def approve_device_by_token(token):
    """
    Otorisasi perangkat kasir via tautan 1-klik dari WhatsApp Owner.
    """
    if not token:
        return False, None, "Token persetujuan tidak valid."

    device = TrustedDevice.query.filter_by(approval_token=token).first()
    if not device:
        return False, None, "Tautan persetujuan tidak valid atau sudah pernah digunakan."

    if device.is_token_expired():
        return False, device, "Tautan persetujuan telah kedaluwarsa (lebih dari 15 menit). Silakan ajukan ulang dari perangkat kasir."

    device.status = 'approved'
    device.approved_at = datetime.utcnow()
    device.approval_token = None  # Reset token agar tidak bisa digunakan berulang

    # Aktifkan lock kasir akun secara otomatis jika belum aktif
    owner = User.query.get(device.user_id)
    if owner and not owner.is_device_lock_enabled:
        owner.is_device_lock_enabled = True

    db.session.commit()
    return True, device, f"Perangkat kasir '{device.device_name}' berhasil disetujui resmi! Perangkat ini sekarang dapat bertransaksi menggunakan saldo toko."

def reject_device_by_token(token):
    """
    Menolak perangkat kasir via tautan 1-klik dari WhatsApp Owner.
    """
    if not token:
        return False, None, "Token penolakan tidak valid."

    device = TrustedDevice.query.filter_by(approval_token=token).first()
    if not device:
        return False, None, "Tautan tidak valid atau sudah diproses."

    device.status = 'rejected'
    device.approval_token = None
    db.session.commit()
    return True, device, f"Perangkat kasir '{device.device_name}' telah ditolak."

def approve_device_manual(user_id, device_id):
    """
    Persetujuan manual langsung oleh Owner dari dashboard web VIP.
    """
    device = TrustedDevice.query.filter_by(id=device_id, user_id=user_id).first()
    if not device:
        return False, "Perangkat kasir tidak ditemukan."

    device.status = 'approved'
    device.approved_at = datetime.utcnow()
    device.approval_token = None

    owner = User.query.get(user_id)
    if owner and not owner.is_device_lock_enabled:
        owner.is_device_lock_enabled = True

    db.session.commit()
    return True, f"Perangkat '{device.device_name}' berhasil disetujui."

def revoke_device(user_id, device_id):
    """
    Mencabut izin perangkat kasir oleh Owner dari dashboard.
    Secara instan MENCABUT dan MEMUTUS akses transaksi dari perangkat tersebut.
    """
    device = TrustedDevice.query.filter_by(id=device_id, user_id=user_id).first()
    if not device:
        return False, "Perangkat kasir tidak ditemukan."

    device.status = 'revoked'
    device.approval_token = None
    device.activation_token = None
    device.activation_expires_at = None
    device.device_uuid = f"revoked_{secrets.token_hex(12)}"
    device.device_fingerprint = None
    device.revoke_active_sessions()
    db.session.commit()
    return True, f"Akses transaksi untuk '{device.device_name}' berhasil dicabut."

def toggle_device_lock(user, enabled):
    """
    Mengaktifkan atau menonaktifkan sakelar proteksi Kunci Kasir Toko.
    """
    if not user or not user.is_vip_active():
        return False, "Hanya akun VIP aktif yang dapat mengatur proteksi Kunci Kasir."

    user.is_device_lock_enabled = bool(enabled)
    db.session.commit()
    status_str = "diaktifkan" if enabled else "dinonaktifkan"
    return True, f"Proteksi Kunci Kasir Toko berhasil {status_str}."

def verify_device_for_transaction(user, device_uuid):
    """
    Memeriksa izin transaksi Saldo berdasarkan aturan Kunci Perangkat Kasir.
    - Jika user bukan VIP atau is_device_lock_enabled == False: lolos tanpa proteksi.
    - Jika user VIP dan is_device_lock_enabled == True: WAJIB lolos verifikasi approved device.
    Mengembalikan (allowed: bool, device_obj: TrustedDevice, error_message: str)
    """
    if not user or not user.is_vip_active():
        return True, None, None

    if not user.is_device_lock_enabled:
        # Jika fitur kunci kasir tidak diaktifkan oleh Owner, transaksi diizinkan
        # Namun jika ada cookie device approved, tetap kita catat device-nya untuk laporan
        if device_uuid:
            dev = TrustedDevice.query.filter_by(user_id=user.id, device_uuid=device_uuid, status='approved').first()
            if dev:
                dev.last_used_at = datetime.utcnow()
                db.session.commit()
                return True, dev, None
        return True, None, None

    # Proteksi AKTIF: Wajib ada token perangkat
    if not device_uuid:
        return False, None, "Transaksi Saldo Ditolak: Fitur Kunci Kasir Toko Aktif. Perangkat ini belum diotorisasi resmi oleh Owner toko."

    device = TrustedDevice.query.filter_by(user_id=user.id, device_uuid=device_uuid).first()
    if not device:
        return False, None, "Transaksi Saldo Ditolak: Perangkat ini belum terdaftar sebagai Kasir Resmi Toko. Hubungi Owner untuk pendaftaran."

    if device.status != 'approved':
        status_map = {
            'pending': 'Menunggu Persetujuan Owner Toko',
            'rejected': 'Ditolak oleh Owner Toko',
            'revoked': 'Akses Toko Telah Dicabut oleh Owner'
        }
        status_desc = status_map.get(device.status, device.status)
        return False, device, f"Transaksi Saldo Ditolak: Perangkat kasir ini berstatus [{status_desc}]. Transaksi tidak diizinkan."

    # Perangkat valid dan disetujui
    device.last_used_at = datetime.utcnow()
    db.session.commit()
    return True, device, None

def get_branch_usage_report(user_id, period='today'):
    """
    Menghasilkan data agregasi pemakaian saldo deposit per cabang toko dan riwayat transaksi.
    """
    from sqlalchemy import func

    now = now_wib()
    query = Transaction.query.filter(
        Transaction.user_id == user_id,
        Transaction.payment_method == 'SALDO'
    )

    if period == 'today':
        wib_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        utc_start = wib_start - timedelta(hours=7)
        query = query.filter(Transaction.created_at >= utc_start)
    elif period == 'month':
        wib_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        utc_start = wib_start - timedelta(hours=7)
        query = query.filter(Transaction.created_at >= utc_start)

    transactions = query.order_by(Transaction.created_at.desc()).all()

    # Rekapitulasi per nama cabang
    branch_map = {}
    total_trx = 0
    total_amount = 0.0

    for trx in transactions:
        b_name = trx.device_name or 'Perangkat Utama / Tanpa Nama'
        if b_name not in branch_map:
            branch_map[b_name] = {
                'branch_name': b_name,
                'total_trx': 0,
                'success_trx': 0,
                'total_spent': 0.0,
                'last_time': trx.created_at_wib
            }
        branch_map[b_name]['total_trx'] += 1
        if trx.status == 'SUCCESS':
            branch_map[b_name]['success_trx'] += 1
        branch_map[b_name]['total_spent'] += float(trx.amount or 0)

        total_trx += 1
        total_amount += float(trx.amount or 0)

    # Urutkan cabang berdasarkan total pemakaian saldo tertinggi
    branches = sorted(branch_map.values(), key=lambda x: x['total_spent'], reverse=True)

    return {
        'total_trx': total_trx,
        'total_amount': total_amount,
        'branches': branches,
        'recent_transactions': transactions[:30]
    }


# ==============================================================================
# METODE MODE KASIR CABANG MANDIRI (DEDICATED CASHIER POS VIA PIN)
# ==============================================================================

def create_branch_cashier(user, branch_name, pin, daily_limit=0.0, hours_start=None, hours_end=None, is_24_hours=False, base_url=None):
    """
    Owner VIP membuat profil cabang kasir baru lengkap dengan PIN 4-6 digit dan batasan operasional.
    Menghasilkan tautan aktivasi satu kali pakai untuk dipasang di komputer cabang.
    """
    if not user or not user.is_vip_active():
        return False, None, None, "Hanya akun VIP aktif yang dapat membuat dan mengelola Cabang Kasir."

    clean_name = str(branch_name or '').strip()
    if not clean_name:
        return False, None, None, "Nama Cabang Toko wajib diisi (contoh: Cabang 1 - Pasar Baru)."

    pin_str = str(pin or '').strip()
    if not pin_str.isdigit() or len(pin_str) < 4 or len(pin_str) > 6:
        return False, None, None, "PIN Kasir wajib berupa 4 hingga 6 digit angka."

    # Cek duplikasi nama cabang untuk user ini (hanya cabang yang masih aktif/pending)
    existing_branch = TrustedDevice.query.filter(
        TrustedDevice.user_id == user.id,
        func.lower(TrustedDevice.device_name) == clean_name.lower(),
        TrustedDevice.status.in_(['approved', 'pending'])
    ).first()
    if existing_branch:
        return False, None, None, f"Nama cabang '{clean_name}' sudah terdaftar dan masih aktif. Gunakan nama cabang lain."

    # Generate token aktivasi (berlaku 24 jam) & UUID sementara
    activation_token = secrets.token_urlsafe(32)
    activation_expires_at = datetime.utcnow() + timedelta(hours=24)
    temp_uuid = f"pending_act_{secrets.token_hex(12)}"

    # Pengaturan jam operasional (24 Jam vs Custom Hours)
    clean_h_start = None if is_24_hours else (str(hours_start).strip() if hours_start and str(hours_start).strip() else None)
    clean_h_end = None if is_24_hours else (str(hours_end).strip() if hours_end and str(hours_end).strip() else None)

    device = TrustedDevice(
        user_id=user.id,
        device_uuid=temp_uuid,
        device_name=clean_name,
        status='pending',
        daily_limit=float(daily_limit or 0.0),
        operating_hours_start=clean_h_start,
        operating_hours_end=clean_h_end,
        activation_token=activation_token,
        activation_expires_at=activation_expires_at,
        session_version=1,
        created_at=datetime.utcnow()
    )
    device.set_pin(pin_str)
    db.session.add(device)

    # Pastikan sakelar lock kasir akun aktif
    if not user.is_device_lock_enabled:
        user.is_device_lock_enabled = True

    db.session.commit()

    domain = (base_url or 'https://ipay.my.id').rstrip('/')
    activation_url = f"{domain}/kasir/aktivasi/{activation_token}"

    return True, device, activation_url, "Cabang kasir berhasil dibuat! Bagikan tautan aktivasi ke komputer cabang toko."


def activate_cashier_device(token, device_uuid, user_agent=None, ip_address=None, fingerprint=None):
    """
    Mengikat (bind) komputer cabang toko secara permanen via link aktivasi satu kali pakai.
    Memutuskan seketika sesi apapun dari komputer/browser sebelumnya.
    """
    if not token or not str(token).strip():
        return False, None, "Tautan aktivasi tidak valid."

    device = TrustedDevice.query.filter_by(activation_token=token).first()
    if not device:
        return False, None, "Tautan aktivasi tidak valid atau sudah pernah digunakan sebelumnya."

    # Periksa batas kedaluwarsa tautan aktivasi (2 jam)
    if device.is_activation_expired():
        return False, device, "Tautan aktivasi telah kedaluwarsa (maksimal 2 jam sejak dibuat). Hubungi Owner untuk membuat tautan baru."

    # Ikat identitas browser & hardware fingerprint
    device.device_uuid = str(device_uuid).strip()
    device.device_info = str(user_agent or 'Komputer Toko')[:250]
    device.ip_address = str(ip_address or '-')[:50]
    if fingerprint:
        device.device_fingerprint = str(fingerprint).strip()[:128]
    device.status = 'approved'
    device.approved_at = datetime.utcnow()
    device.last_used_at = datetime.utcnow()
    device.activation_token = None  # Hanguskan token setelah dipakai (one-time use)
    device.activation_expires_at = None

    # Putuskan seluruh sesi browser sebelumnya
    device.revoke_active_sessions()

    # Pastikan status owner aktif
    owner = User.query.get(device.user_id)
    if owner and not owner.is_device_lock_enabled:
        owner.is_device_lock_enabled = True

    db.session.commit()
    return True, device, f"Komputer kasir berhasil diaktivasi sebagai Kasir Resmi: {device.device_name}!"


def login_cashier_pin(device_uuid, pin, user_agent=None, fingerprint=None):
    """
    Otentikasi Kasir Cabang di komputer toko menggunakan PIN Kasir (100% BEBAS OTP WA OWNER).
    Menerapkan validasi sidik jari perangkat dan token sesi tunggal aktif (anti-kloning).
    """
    if not device_uuid or not str(device_uuid).strip():
        return False, None, None, "Perangkat ini belum terikat sebagai kasir resmi toko."

    device = TrustedDevice.query.filter_by(device_uuid=device_uuid).first()
    if not device:
        return False, None, None, "Perangkat belum terdaftar. Buka tautan aktivasi dari Owner untuk mendaftar."

    if device.status == 'pending':
        return False, None, None, "Perangkat kasir ini masih menunggu aktivasi resmi oleh Owner."
    if device.status != 'approved':
        return False, None, None, f"Izin akses perangkat kasir ini berstatus [{device.status}]. Hubungi Owner."

    # Cek status akun VIP Owner
    owner = User.query.get(device.user_id)
    if not owner or not owner.is_vip_active():
        return False, None, None, "Akun Toko VIP belum aktif atau masa aktif langganan telah habis."

    # Cek jam kerja toko
    if not device.is_within_operating_hours():
        return False, None, None, f"Kasir berada di luar jam operasional toko ({device.operating_hours_start} - {device.operating_hours_end} WIB)."

    # Cek PIN Kasir
    if not device.check_pin(pin):
        return False, None, None, "PIN Kasir salah! Silakan coba lagi atau hubungi Owner."

    # Validasi Sidik Jari Perangkat (Hardware Fingerprint Anti-Hijacking)
    if fingerprint:
        if device.device_fingerprint:
            if not device.check_fingerprint(fingerprint):
                return False, None, None, "Sidik jari perangkat/browser tidak sesuai dengan data aktivasi kasir toko. Hubungi Owner jika mengganti perangkat."
        else:
            # Bind fingerprint jika baru pertama kali terekam
            device.device_fingerprint = str(fingerprint).strip()[:128]

    # Buat token sesi tunggal aktif (mencegah login paralel/kloning)
    new_session_token = secrets.token_hex(16)
    device.active_session_token = new_session_token
    device.last_used_at = datetime.utcnow()
    db.session.commit()

    return True, device, owner, "Login Kasir berhasil! Selamat bertransaksi."


def update_branch_settings(user_id, device_id, branch_name=None, new_pin=None, daily_limit=None, hours_start=None, hours_end=None, is_24_hours=None):
    """
    Memperbarui nama cabang, PIN kasir, limit harian, atau jam operasional oleh Owner.
    Mendukung opsi peralihan ke '24 Jam Nonstop' (is_24_hours=True).
    """
    device = TrustedDevice.query.filter_by(id=device_id, user_id=user_id).first()
    if not device:
        return False, "Cabang kasir tidak ditemukan."

    if branch_name and str(branch_name).strip():
        clean_name = str(branch_name).strip()
        # Cek duplikasi jika nama berubah
        if clean_name.lower() != device.device_name.lower():
            dup = TrustedDevice.query.filter(
                TrustedDevice.user_id == user_id,
                TrustedDevice.id != device_id,
                func.lower(TrustedDevice.device_name) == clean_name.lower(),
                TrustedDevice.status.in_(['approved', 'pending'])
            ).first()
            if dup:
                return False, f"Nama cabang '{clean_name}' sudah digunakan oleh cabang lain."
        device.device_name = clean_name

    if new_pin and str(new_pin).strip():
        pin_str = str(new_pin).strip()
        if not pin_str.isdigit() or len(pin_str) < 4 or len(pin_str) > 6:
            return False, "PIN Kasir baru wajib berupa 4 hingga 6 digit angka."
        device.set_pin(pin_str)

    if daily_limit is not None:
        try:
            device.daily_limit = max(0.0, float(daily_limit))
        except (ValueError, TypeError):
            pass

    if is_24_hours is True:
        device.operating_hours_start = None
        device.operating_hours_end = None
    else:
        if hours_start is not None:
            clean_s = str(hours_start).strip()
            device.operating_hours_start = clean_s if clean_s and clean_s != 'None' else None

        if hours_end is not None:
            clean_e = str(hours_end).strip()
            device.operating_hours_end = clean_e if clean_e and clean_e != 'None' else None

    db.session.commit()
    return True, f"Pengaturan cabang kasir '{device.device_name}' berhasil diperbarui."


def regenerate_activation_link(user_id, device_id, base_url=None):
    """
    Menghasilkan link aktivasi baru jika komputer cabang ganti PC atau instal ulang browser.
    Secara instan MENCABUT dan MEMUTUS akses dari komputer/browser kasir cabang sebelumnya.
    """
    device = TrustedDevice.query.filter_by(id=device_id, user_id=user_id).first()
    if not device:
        return False, None, "Cabang kasir tidak ditemukan."

    new_token = secrets.token_urlsafe(32)
    device.activation_token = new_token
    device.activation_expires_at = datetime.utcnow() + timedelta(hours=24)

    # Lepas ikatan identitas browser lama secara instan agar browser lama langsung tertendang
    device.device_uuid = f"pending_act_{secrets.token_hex(12)}"
    device.status = 'pending'
    device.device_fingerprint = None

    # Putuskan dan batalkan seluruh sesi aktif di browser lama
    device.revoke_active_sessions()

    db.session.commit()

    domain = (base_url or 'https://ipay.my.id').rstrip('/')
    activation_url = f"{domain}/kasir/aktivasi/{new_token}"
    return True, activation_url, "Tautan aktivasi baru berhasil dibuat! Akses kasir sebelumnya telah dicabut. Buka tautan baru ini di komputer kasir toko."


def verify_cashier_transaction_limits(device, amount):
    """
    Memvalidasi jam operasional dan plafon belanja harian cabang kasir sebelum checkout.
    """
    if not device:
        return False, "Perangkat kasir tidak teridentifikasi."

    if not device.is_within_operating_hours():
        return False, f"Transaksi ditolak: Di luar jam kerja kasir ({device.operating_hours_start} - {device.operating_hours_end} WIB)."

    if device.daily_limit and device.daily_limit > 0:
        spent = device.get_today_spent()
        if spent + float(amount) > float(device.daily_limit):
            sisa = max(0.0, float(device.daily_limit) - spent)
            return False, f"Transaksi ditolak: Batas limit harian cabang ini telah tercapai. Sisa kuota hari ini: Rp {sisa:,.0f} (Maksimal: Rp {device.daily_limit:,.0f}/hari)."

    return True, None


def get_branch_cashier_history(device_id, limit=50):
    """
    Mengambil riwayat transaksi khusus cabang kasir ini (terisolasi dari transaksi cabang lain).
    """
    from app.models.transaction import Transaction
    trxs = Transaction.query.filter_by(device_id=device_id).order_by(Transaction.created_at.desc()).limit(limit).all()
    return trxs


def transfer_balance_to_branch(owner_id, device_id, amount, shift_name=None):
    """
    Owner mentransfer/mengalokasikan saldo dari Saldo Utama ke Saldo Cabang Kasir.
    Owner TIDAK BISA mengirim saldo melebihi saldo utama miliknya sendiri.
    """
    try:
        amt = float(amount)
        if amt <= 0:
            return False, "Nominal transfer saldo harus lebih dari Rp 0."
    except (ValueError, TypeError):
        return False, "Nominal transfer tidak valid."

    owner = db.session.query(User).filter_by(id=owner_id).with_for_update().first()
    if not owner or not owner.is_vip_active():
        db.session.rollback()
        return False, "Hanya akun VIP aktif yang dapat mentransfer saldo ke cabang."

    device = db.session.query(TrustedDevice).filter_by(id=device_id, user_id=owner_id).with_for_update().first()
    if not device:
        db.session.rollback()
        return False, "Cabang kasir tidak ditemukan."

    # Validasi saldo Owner
    if (owner.balance or 0.0) < amt:
        db.session.rollback()
        sisa = owner.balance or 0.0
        return False, f"Gagal: Saldo Utama Anda tidak mencukupi (Tersedia: Rp {sisa:,.0f}, Diminta: Rp {amt:,.0f}). Tarik saldo dari cabang lain terlebih dahulu atau isi deposit Anda."

    bal_before = float(device.branch_balance or 0.0)
    device.branch_balance = bal_before + amt
    bal_after = float(device.branch_balance)
    owner.balance -= amt

    # Catat ke tabel mutasi saldo cabang
    clean_shift = str(shift_name or 'Kasir Toko').strip()
    mut = BranchMutation(
        device_id=device.id,
        user_id=owner.id,
        type='TOPUP_FROM_OWNER',
        amount=amt,
        balance_before=bal_before,
        balance_after=bal_after,
        description=f"Penambahan saldo deposit dari Owner (Penerima: {clean_shift})",
        shift_name=clean_shift,
        created_at=datetime.utcnow()
    )
    db.session.add(mut)
    db.session.commit()

    return True, f"Berhasil mengirim saldo Rp {amt:,.0f} ke {device.device_name}. Saldo cabang saat ini: Rp {bal_after:,.0f}."


def withdraw_balance_from_branch(owner_id, device_id, amount):
    """
    Owner menarik sebagian/seluruh saldo dari Cabang Kasir kembali ke Saldo Utama Owner.
    Saldo yang ditarik bisa dialihkan ke cabang lain atau dipakai sendiri oleh Owner.
    """
    try:
        amt = float(amount)
        if amt <= 0:
            return False, "Nominal penarikan saldo harus lebih dari Rp 0."
    except (ValueError, TypeError):
        return False, "Nominal penarikan tidak valid."

    owner = db.session.query(User).filter_by(id=owner_id).with_for_update().first()
    if not owner or not owner.is_vip_active():
        db.session.rollback()
        return False, "Hanya akun VIP aktif yang dapat menarik saldo cabang."

    device = db.session.query(TrustedDevice).filter_by(id=device_id, user_id=owner_id).with_for_update().first()
    if not device:
        db.session.rollback()
        return False, "Cabang kasir tidak ditemukan."

    cur_branch_bal = float(device.branch_balance or 0.0)
    if cur_branch_bal < amt:
        db.session.rollback()
        return False, f"Gagal: Saldo cabang {device.device_name} hanya tersisa Rp {cur_branch_bal:,.0f}."

    bal_before = cur_branch_bal
    device.branch_balance = bal_before - amt
    bal_after = float(device.branch_balance)
    owner.balance = (owner.balance or 0.0) + amt

    # Catat mutasi penarikan
    mut = BranchMutation(
        device_id=device.id,
        user_id=owner.id,
        type='WITHDRAW_TO_OWNER',
        amount=amt,
        balance_before=bal_before,
        balance_after=bal_after,
        description="Penarikan saldo cabang oleh Owner",
        shift_name="Owner",
        created_at=datetime.utcnow()
    )
    db.session.add(mut)
    db.session.commit()

    return True, f"Berhasil menarik saldo Rp {amt:,.0f} dari {device.device_name} ke Saldo Utama Anda. Saldo cabang tersisa: Rp {bal_after:,.0f}."


def request_branch_deposit_via_wa(device_id, requested_amount=None, shift_name=None, note=None, base_url=None):
    """
    Mengirimkan permohonan deposit saldo dari Kasir Cabang ke WhatsApp Owner.
    """
    device = TrustedDevice.query.get(device_id)
    if not device:
        return False, "Perangkat kasir tidak ditemukan."

    owner = User.query.get(device.user_id)
    if not owner or not owner.phone:
        return False, "Nomor WhatsApp Owner tidak ditemukan."

    req_amt_str = f"Rp {float(requested_amount):,.0f}" if requested_amount else "Sesuai Kebutuhan Toko"
    cur_bal_str = f"Rp {float(device.branch_balance or 0.0):,.0f}"
    clean_shift = str(shift_name or 'Kasir Toko').strip()
    clean_note = str(note or '-').strip()
    domain = (base_url or 'https://ipay.my.id').rstrip('/')

    pesan_wa = (
        f"🔔 *PERMINTAAN SALDO KASIR TOKO*\n\n"
        f"Halo Bos, kasir cabang Anda mengajukan permohonan penambahan saldo deposit:\n\n"
        f"🏪 *Cabang:* {device.device_name}\n"
        f"👤 *Shift Bertugas:* {clean_shift}\n"
        f"💰 *Sisa Saldo Cabang:* {cur_bal_str}\n"
        f"💵 *Nominal Diminta:* {req_amt_str}\n"
        f"📝 *Catatan:* {clean_note}\n\n"
        f"Silakan buka dashboard untuk mentransfer saldo ke cabang ini:\n"
        f"👉 {domain}/vip/devices\n\n"
        f"_Pesan otomatis dari Portal Kasir GarudaTel._"
    )

    sukses = kirim_wa(owner.phone, pesan_wa)
    if sukses:
        return True, "Permintaan saldo berhasil dikirimkan langsung ke WhatsApp Owner!"
    return True, "Permintaan saldo telah diproses ke WhatsApp Owner."


def check_and_notify_low_balance(device, shift_name=None, base_url=None):
    """
    Peringatan otomatis jika sisa saldo kasir berada di bawah ambang batas (contoh: < Rp 100.000).
    """
    if not device or not device.is_low_balance():
        return False

    owner = User.query.get(device.user_id)
    if not owner or not owner.phone:
        return False

    threshold = float(device.low_balance_alert or 100000.0)
    cur_bal = float(device.branch_balance or 0.0)
    clean_shift = str(shift_name or 'Kasir').strip()
    domain = (base_url or 'https://ipay.my.id').rstrip('/')

    pesan = (
        f"⚠️ *PERINGATAN SALDO KASIR MENIPIS*\n\n"
        f"Toko/Cabang: *{device.device_name}*\n"
        f"Shift: *{clean_shift}*\n"
        f"Sisa Saldo Kasir: *Rp {cur_bal:,.0f}* (Batas Peringatan: Rp {threshold:,.0f})\n\n"
        f"Saldo cabang ini hampir habis. Segera tambahkan saldo dari dashboard agar transaksi kasir tidak terganggu:\n"
        f"👉 {domain}/vip/devices\n\n"
        f"_Notifikasi proteksi saldo GarudaTel POS._"
    )

    import threading
    def _send_wa():
        try:
            kirim_wa(owner.phone, pesan)
        except Exception as e:
            logger.warning(f"Gagal kirim alert low balance WA: {e}")

    # Kirim secara asynchronous agar tidak membebani kecepatan transaksi checkout kasir
    threading.Thread(target=_send_wa, daemon=True).start()
    return True


def get_branch_mutations(device_id, limit=50):
    """
    Mengambil riwayat mutasi keluar/masuk saldo cabang kasir.
    """
    return BranchMutation.query.filter_by(device_id=device_id).order_by(BranchMutation.created_at.desc()).limit(limit).all()


def delete_branch_cashier(user_id, device_id):
    """
    Menghapus cabang kasir secara aman (soft-delete).
    Jika masih terdapat saldo cabang, otomatis dikembalikan utuh ke Saldo Utama Owner.
    """
    device = TrustedDevice.query.filter_by(id=device_id, user_id=user_id).first()
    if not device:
        return False, "Cabang kasir tidak ditemukan."

    owner = db.session.query(User).filter_by(id=user_id).with_for_update().first()
    if not owner:
        return False, "Akun Owner tidak ditemukan."

    refund_amount = float(device.branch_balance or 0.0)
    if refund_amount > 0:
        owner.balance += refund_amount
        device.branch_balance = 0.0
        mut = BranchMutation(
            device_id=device.id,
            user_id=owner.id,
            type='WITHDRAW_TO_OWNER',
            amount=refund_amount,
            balance_before=refund_amount,
            balance_after=0.0,
            description=f"Pengembalian saldo penutupan cabang '{device.device_name}' ke Saldo Utama",
            shift_name="Sistem",
            created_at=datetime.utcnow()
        )
        db.session.add(mut)

    branch_name = device.device_name
    device.status = 'deleted'
    device.activation_token = None
    device.approval_token = None
    device.device_uuid = f"deleted_{secrets.token_hex(12)}"
    device.revoke_active_sessions()

    db.session.commit()

    msg = f"Cabang '{branch_name}' berhasil dihapus!"
    if refund_amount > 0:
        msg += f" Sisa saldo Rp {refund_amount:,.0f} telah otomatis dikembalikan ke Saldo Utama Bos."
    return True, msg


def sync_pending_cashier_transactions(device_id):
    """
    Menyinkronkan transaksi kasir cabang yang masih PROCESSING / PENDING ke provider secara real-time.
    Jika transaksi dinyatakan GAGAL, otomatis refund ke saldo cabang dan catat mutasi.
    """
    device = TrustedDevice.query.filter_by(id=device_id).first()
    if not device:
        return []

    pending_trxs = Transaction.query.filter(
        Transaction.device_id == device_id,
        Transaction.status.in_(['PROCESSING', 'PENDING', 'PROSES'])
    ).order_by(Transaction.created_at.desc()).limit(10).all()

    if not pending_trxs:
        return []

    from app.routes.transaction import sync_single_transaction

    for trx in pending_trxs:
        try:
            sync_single_transaction(trx)
        except Exception as e:
            logger.error(f"[-] Error sync single cashier trx {trx.ref_id}: {e}")

    return pending_trxs


