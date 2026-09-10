from datetime import datetime, timezone, timedelta
import time
import re
import logging
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction
from app.models.setting import Setting

logger = logging.getLogger(__name__)

def get_wib_now():
    """Mengembalikan objek datetime saat ini dalam zona waktu WIB (UTC+7) naive."""
    return datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)

def get_setting_value(key, default=""):
    try:
        s = Setting.query.filter_by(key=key).first()
        if s and s.value is not None and str(s.value).strip() != "":
            return str(s.value).strip()
    except Exception:
        pass
    return default

def get_setting_float(key, default=0.0):
    val = get_setting_value(key, "")
    try:
        return float(val) if val else default
    except (ValueError, TypeError):
        return default

def get_setting_int(key, default=0):
    val = get_setting_value(key, "")
    try:
        return int(val) if val else default
    except (ValueError, TypeError):
        return default

def get_tier_settings():
    """Mengembalikan konfigurasi sistem tingkatan akun dan langganan."""
    return {
        'upgrade_fee_reseller': get_setting_float('upgrade_fee_reseller', 15000.0),
        'upgrade_fee_vip': get_setting_float('upgrade_fee_vip', 20000.0),
        'discount_reseller': get_setting_float('discount_reseller', 100.0),
        'discount_vip': get_setting_float('discount_vip', 200.0),
        'commission_flat': get_setting_float('commission_flat', 100.0),
        'payout_date': get_setting_int('payout_date', 28),
        'history_retention_days': get_setting_int('history_retention_days', 120),
    }

def get_user_product_price(user, product_or_sell_price, base_price=None):
    """
    Menghitung harga produk dinamis berdasarkan tingkatan akun pengguna.
    - Member: harga normal (sell_price)
    - Reseller: sell_price - discount_reseller (dengan floor base_price + 100)
    - VIP: sell_price - discount_vip (dengan floor base_price + 100)
    """
    if hasattr(product_or_sell_price, 'sell_price'):
        sell_price = float(product_or_sell_price.sell_price or 0.0)
        prod_base = float(getattr(product_or_sell_price, 'base_price', 0.0) or 0.0)
    else:
        sell_price = float(product_or_sell_price or 0.0)
        prod_base = float(base_price or 0.0)

    if not user or not getattr(user, 'is_authenticated', False):
        return sell_price

    role = user.get_effective_role() if hasattr(user, 'get_effective_role') else getattr(user, 'role', 'user')

    if role == 'vip':
        discount = get_setting_float('discount_vip', 200.0)
        floor = (prod_base + 100.0) if prod_base > 0 else (sell_price - discount)
        return round(max(floor, sell_price - discount), 2)

    elif role == 'reseller':
        discount = get_setting_float('discount_reseller', 100.0)
        floor = (prod_base + 100.0) if prod_base > 0 else (sell_price - discount)
        return round(max(floor, sell_price - discount), 2)

    return sell_price

def ensure_user_referral_code(user):
    """Memastikan user (terutama VIP) memiliki kode referral unik."""
    if not user.referral_code:
        import string
        import random
        chars = string.ascii_uppercase + string.digits
        for _ in range(20):
            code = 'GT-' + ''.join(random.choice(chars) for _ in range(6))
            if not User.query.filter_by(referral_code=code).first():
                user.referral_code = code
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                break
    return user.referral_code

def process_subscription_upgrade(user, target_role):
    """
    Memproses upgrade langganan akun ke Reseller atau VIP selama 30 hari.
    Memotong saldo secara atomic dan mencatat riwayat transaksi/mutasi.
    """
    target_role = str(target_role).lower().strip()
    if target_role not in ['reseller', 'vip']:
        return False, "Target golongan tidak valid. Pilih Reseller atau VIP.", None

    tier_cfg = get_tier_settings()
    fee = tier_cfg['upgrade_fee_vip'] if target_role == 'vip' else tier_cfg['upgrade_fee_reseller']

    user_locked = db.session.query(User).filter_by(id=user.id).with_for_update().first()
    if not user_locked:
        return False, "Pengguna tidak ditemukan.", None

    if (user_locked.balance or 0.0) < fee:
        db.session.rollback()
        return False, f"Saldo tidak mencukupi. Biaya upgrade Rp {fee:,.0f}, saldo Anda Rp {user_locked.balance:,.0f}.", None

    now = get_wib_now()

    # Perpanjangan vs Upgrade baru
    if user_locked.role == target_role and user_locked.role_expires_at and user_locked.role_expires_at > now:
        user_locked.role_expires_at = user_locked.role_expires_at + timedelta(days=30)
    else:
        user_locked.role = target_role
        user_locked.role_expires_at = now + timedelta(days=30)

    # Potong saldo
    user_locked.balance -= fee
    user_locked.last_reminded_at = None

    # Jika VIP, pastikan punya referral code
    if target_role == 'vip':
        ensure_user_referral_code(user_locked)

    # Catat Transaksi / Mutasi
    ref_id = f"UPG-{int(time.time()*1000)}"
    role_title = "VIP" if target_role == 'vip' else "RESELLER"
    exp_str = user_locked.role_expires_at.strftime('%d/%m/%Y %H:%M')

    trx = Transaction(
        user_id=user_locked.id,
        ref_id=ref_id,
        product_name=f"Langganan Akun {role_title} (30 Hari)",
        sku_code=f"UPGRADE_{role_title}",
        target_number=user_locked.phone,
        amount=fee,
        payment_method='SALDO',
        payment_status='PAID',
        status='SUCCESS',
        sn=f"Masa aktif hingga {exp_str} WIB",
        is_prepaid=True
    )
    db.session.add(trx)
    db.session.commit()

    logger.info(f"[TIER_SERVICE] User {user_locked.id} ({user_locked.phone}) berhasil upgrade ke {target_role}. Berakhir: {exp_str}")
    return True, f"Selamat! Akun Anda berhasil di-upgrade ke {role_title} (aktif s/d {exp_str} WIB).", user_locked

def check_and_downgrade_expired_users():
    """
    Mengecek akun Reseller/VIP yang masa aktifnya telah habis dan mengembalikannya ke Member ('user').
    """
    now = get_wib_now()
    expired_users = User.query.filter(
        User.role.in_(['reseller', 'vip']),
        User.role_expires_at.isnot(None),
        User.role_expires_at <= now
    ).all()

    count = 0
    for u in expired_users:
        logger.info(f"[TIER_SERVICE] Masa aktif langganan {u.role.upper()} user {u.id} ({u.phone}) telah habis pada {u.role_expires_at}. Downgrade ke member.")
        u.role = 'user'
        count += 1

    if count > 0:
        db.session.commit()
    return count

def send_h12_whatsapp_reminders():
    """
    Mengirimkan pesan WhatsApp pengingat perpanjangan kepada Reseller dan VIP
    saat masa aktif tersisa 12 hari (H-12 sebelum jatuh tempo).
    """
    from app.wa_helper import kirim_wa
    from app.services.setting_service import get_store_name

    now = get_wib_now()
    store_name = get_store_name()

    active_subscribers = User.query.filter(
        User.role.in_(['reseller', 'vip']),
        User.role_expires_at.isnot(None),
        User.role_expires_at > now
    ).all()

    sent_count = 0
    for u in active_subscribers:
        diff = u.role_expires_at - now
        days_left = diff.days

        if days_left == 12:
            already_reminded = False
            if u.last_reminded_at:
                if (now - u.last_reminded_at).total_seconds() < 86400:
                    already_reminded = True

            if not already_reminded and u.phone:
                exp_date_str = u.role_expires_at.strftime('%d %B %Y pukul %H:%M')
                role_label = u.role.upper()
                msg = (
                    f"Halo Kak *{u.name}*! 👋\n\n"
                    f"Pemberitahuan resmi dari *{store_name}*:\n"
                    f"Masa aktif langganan akun *{role_label}* Anda tersisa *12 hari lagi* "
                    f"dan akan jatuh tempo pada *{exp_date_str} WIB*.\n\n"
                    f"💡 *Manfaat akun {role_label}:*\n"
                    f"• Harga produk termurah di bawah harga pasar\n"
                    f"• {'Menerima komisi pasif transaksi Downline' if u.role == 'vip' else 'Margin keuntungan lebih tinggi'}\n\n"
                    f"Jangan sampai ketinggalan! Anda dapat memperpanjang masa aktif kapan saja "
                    f"melalui menu *Akun > Upgrade Langganan* di web {store_name}.\n\n"
                    f"Terima kasih atas kepercayaan dan kemitraan Anda! 🙏"
                )

                ok = kirim_wa(u.phone, msg)
                if ok:
                    u.last_reminded_at = now
                    sent_count += 1
                    logger.info(f"[TIER_SERVICE] Pengingat H-12 WA terkirim ke user {u.id} ({u.phone})")

    if sent_count > 0:
        db.session.commit()
    return sent_count


# ==========================================
# MANAJEMEN DOWNLINE KEMITRAAN OLEH ADMIN
# ==========================================

def clean_phone_number(raw_phone):
    """
    Membersihkan dan menstandardisasi format nomor WhatsApp/HP.
    Mengembalikan tuple (format_08, format_62, raw_clean).
    Contoh: '+62 812-3456-7890' -> ('081234567890', '6281234567890', '081234567890')
    """
    if not raw_phone:
        return "", "", ""
    digits = re.sub(r'\D', '', str(raw_phone).strip())
    if not digits:
        return "", "", ""

    if digits.startswith('628'):
        std_08 = '08' + digits[3:]
        std_62 = digits
    elif digits.startswith('08'):
        std_08 = digits
        std_62 = '62' + digits[1:]
    elif digits.startswith('8'):
        std_08 = '08' + digits[1:]
        std_62 = '62' + digits[1:]
    else:
        std_08 = digits
        std_62 = digits

    return std_08, std_62, digits


def find_user_by_phone(phone_input):
    """
    Mencari entitas User berdasarkan variasi format nomor WhatsApp/HP atau ID/referral.
    """
    if not phone_input:
        return None

    raw_str = str(phone_input).strip()
    std_08, std_62, digits = clean_phone_number(raw_str)

    candidates = [raw_str]
    if std_08:
        candidates.append(std_08)
    if std_62:
        candidates.append(std_62)
    if digits:
        candidates.append(digits)

    # Hilangkan duplikat
    seen = set()
    unique_candidates = [x for x in candidates if not (x in seen or seen.add(x))]

    # Cari nomor telepon
    user = User.query.filter(User.phone.in_(unique_candidates)).first()
    if user:
        return user

    # Fallback pencarian referral code jika ada
    user = User.query.filter_by(referral_code=raw_str.upper()).first()
    if user:
        return user

    return None


def is_circular_upline(potential_downline_id, upline_id):
    """
    Mendeteksi siklus referensi melingkar (circular referral loop).
    Memeriksa apakah candidate downline (potential_downline_id) berada di jalur upline atas upline_id.
    Jika ya, maka relasi dilarang karena akan menciptakan siklus tertutup:
    A -> B -> A atau A -> B -> C -> A.
    """
    if potential_downline_id == upline_id:
        return True

    visited = set([upline_id])
    curr = User.query.get(upline_id)

    while curr and curr.upline_id:
        if curr.upline_id == potential_downline_id:
            return True
        if curr.upline_id in visited:
            break
        visited.add(curr.upline_id)
        curr = User.query.get(curr.upline_id)

    return False


def assign_downline_by_phone(upline_user, downline_phone):
    """
    Menetapkan pengguna dengan nomor telepon `downline_phone` sebagai downline dari `upline_user`.
    Validasi:
    1. Calon downline harus terdaftar di sistem.
    2. Tidak boleh menetapkan diri sendiri.
    3. Proteksi siklus melingkar (anti-circular loop).
    4. Mendukung re-assignment jika user sebelumnya memiliki upline lain.
    """
    if not upline_user:
        return False, "Pengguna upline tidak ditemukan.", None

    phone_str = str(downline_phone or "").strip()
    if not phone_str:
        return False, "Nomor WhatsApp calon downline wajib diisi.", None

    candidate = find_user_by_phone(phone_str)
    if not candidate:
        return False, f"Pengguna dengan nomor WhatsApp '{phone_str}' belum terdaftar di sistem!", None

    if candidate.id == upline_user.id:
        return False, "Pengguna tidak dapat dijadikan downline bagi dirinya sendiri!", None

    if is_circular_upline(candidate.id, upline_user.id):
        return False, f"Ditolak! '{candidate.name}' ({candidate.phone}) berada di atas rantai upline '{upline_user.name}'. Hubungan melingkar (circular loop) tidak diizinkan.", None

    if candidate.upline_id == upline_user.id:
        return False, f"Pengguna '{candidate.name}' ({candidate.phone}) sudah menjadi downline dari '{upline_user.name}'.", candidate

    old_upline_note = ""
    if candidate.upline_id:
        old_upline = User.query.get(candidate.upline_id)
        if old_upline:
            old_upline_note = f" (Dipindahkan dari upline sebelumnya: {old_upline.name} - {old_upline.phone})"

    # Tetapkan upline_id baru
    candidate.upline_id = upline_user.id

    # Pastikan upline memiliki kode referral unik
    ensure_user_referral_code(upline_user)

    try:
        db.session.commit()
        logger.info(f"[TIER_SERVICE] Admin assign downline: User #{candidate.id} ({candidate.phone}) -> Upline #{upline_user.id} ({upline_user.phone}){old_upline_note}")
        return True, f"Berhasil menambahkan '{candidate.name}' ({candidate.phone}) sebagai downline '{upline_user.name}'!{old_upline_note}", candidate
    except Exception as e:
        db.session.rollback()
        logger.error(f"[TIER_SERVICE] Gagal assign downline: {e}")
        return False, f"Gagal menyimpan relasi downline: {str(e)}", None


def remove_downline(upline_user, downline_id):
    """
    Melepaskan relasi downline seorang pengguna dari upline_user.
    """
    if not upline_user:
        return False, "Pengguna upline tidak ditemukan."

    downline = User.query.get(downline_id)
    if not downline:
        return False, "Pengguna downline tidak ditemukan."

    if downline.upline_id != upline_user.id:
        return False, f"'{downline.name}' bukan merupakan downline dari '{upline_user.name}'."

    downline.upline_id = None
    try:
        db.session.commit()
        logger.info(f"[TIER_SERVICE] Admin melepaskan downline: User #{downline.id} ({downline.phone}) dari Upline #{upline_user.id}")
        return True, f"Downline '{downline.name}' ({downline.phone}) berhasil dilepas dari kemitraan '{upline_user.name}'."
    except Exception as e:
        db.session.rollback()
        logger.error(f"[TIER_SERVICE] Gagal melepas downline: {e}")
        return False, f"Gagal melepaskan downline: {str(e)}"


def get_user_downlines_list(user_id):
    """
    Mengambil daftar seluruh downline aktif seorang user untuk ditampilkan di UI panel admin.
    """
    user = User.query.get(user_id)
    if not user:
        return []

    downlines = User.query.filter_by(upline_id=user.id).order_by(User.id.desc()).all()
    results = []
    for d in downlines:
        results.append({
            'id': d.id,
            'name': d.name,
            'phone': d.phone,
            'email': d.email or '-',
            'role': d.get_effective_role() if hasattr(d, 'get_effective_role') else d.role,
            'balance': float(d.balance or 0.0),
            'points': int(d.points or 0),
            'is_active': bool(d.is_active)
        })
    return results

