from datetime import datetime, timezone, timedelta
import time
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
