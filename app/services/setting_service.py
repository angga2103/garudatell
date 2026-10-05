import os
import time
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models.setting import Setting

import threading

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
DEFAULT_STORE_NAME = ""
DEFAULT_TAGLINE = ""
DEFAULT_FOOTER = "Terima kasih atas kepercayaan Anda!"

# In-Memory Cache (RAM) untuk eliminasi N+1 database queries
_SETTING_CACHE = {}
_SETTING_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SECONDS = 60  # Cache berlaku selama 60 detik

_STORE_SETTINGS_CACHE = None
_STORE_SETTINGS_EXPIRY = 0

def invalidate_setting_cache(key=None):
    """
    Menghapus cache setting di memori RAM.
    Jika key diberikan, hanya key tersebut yang dihapus.
    Jika key=None, seluruh cache setting dan store_settings dibersihkan seketika.
    """
    global _STORE_SETTINGS_CACHE, _STORE_SETTINGS_EXPIRY
    with _SETTING_CACHE_LOCK:
        if key:
            _SETTING_CACHE.pop(key, None)
        else:
            _SETTING_CACHE.clear()
        _STORE_SETTINGS_CACHE = None
        _STORE_SETTINGS_EXPIRY = 0

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS

def get_setting_value(key, default=""):
    """
    Mengambil nilai setting dari in-memory cache jika masih valid.
    Jika belum ada atau expired, ambil dari database dan simpan di cache.
    """
    now = time.time()
    with _SETTING_CACHE_LOCK:
        if key in _SETTING_CACHE:
            val, expiry = _SETTING_CACHE[key]
            if now < expiry:
                return val

    # Query ke database
    val = default
    try:
        s = Setting.query.filter_by(key=key).first()
        if s and s.value is not None and str(s.value).strip() != "":
            val = str(s.value).strip()
    except Exception:
        return default

    with _SETTING_CACHE_LOCK:
        _SETTING_CACHE[key] = (val, now + _CACHE_TTL_SECONDS)
    return val

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

def get_store_name():
    """Mengembalikan nama toko dinamis saat ini dari tabel Setting (Profil Toko)."""
    return get_setting_value('store_name', DEFAULT_STORE_NAME)

def get_store_settings():
    """
    Mengembalikan dictionary lengkap pengaturan toko dinamis dari RAM cache:
    - name: Nama Toko
    - tagline: Slogan / Sub-header
    - whatsapp_group: Link / info channel grup WhatsApp
    - receipt_footer: Pesan penutup struk
    - logo: Path relatif file logo (misal: /static/uploads/logo.png)
    - logo_url: URL lengkap/relatif untuk template
    """
    global _STORE_SETTINGS_CACHE, _STORE_SETTINGS_EXPIRY
    now = time.time()
    with _SETTING_CACHE_LOCK:
        if _STORE_SETTINGS_CACHE and now < _STORE_SETTINGS_EXPIRY:
            return _STORE_SETTINGS_CACHE.copy()

    logo_path = get_setting_value('store_logo', '')
    res = {
        'name': get_setting_value('store_name', DEFAULT_STORE_NAME),
        'tagline': get_setting_value('store_tagline', DEFAULT_TAGLINE),
        'whatsapp_group': get_setting_value('store_whatsapp_group', ''),
        'receipt_footer': get_setting_value('receipt_footer', DEFAULT_FOOTER),
        'logo': logo_path,
        'logo_url': logo_path if logo_path else ''
    }
    with _SETTING_CACHE_LOCK:
        _STORE_SETTINGS_CACHE = res
        _STORE_SETTINGS_EXPIRY = now + _CACHE_TTL_SECONDS

    return res.copy()

def save_store_settings(form_data, logo_file=None, upload_folder=None):
    """
    Menyimpan data pengaturan toko ke tabel Setting dan menangani upload logo.
    """
    # 1. Update text fields
    mapping = {
        'store_name': form_data.get('store_name', '').strip() or DEFAULT_STORE_NAME,
        'store_tagline': form_data.get('store_tagline', '').strip(),
        'store_whatsapp_group': form_data.get('store_whatsapp_group', '').strip(),
        'receipt_footer': form_data.get('receipt_footer', '').strip() or DEFAULT_FOOTER,
    }

    for k, val in mapping.items():
        s = Setting.query.filter_by(key=k).first()
        if not s:
            s = Setting(key=k, value=val)
            db.session.add(s)
        else:
            s.value = val

    # 2. Proses upload logo jika ada file baru yang valid
    if logo_file and logo_file.filename and allowed_file(logo_file.filename):
        if not upload_folder:
            base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
            upload_folder = os.path.join(base_dir, 'static', 'uploads')
        
        os.makedirs(upload_folder, exist_ok=True)
        
        ext = logo_file.filename.rsplit('.', 1)[1].lower()
        filename = f"store_logo_{int(time.time())}.{ext}"
        filepath = os.path.join(upload_folder, filename)
        
        logo_file.save(filepath)
        
        # Simpan URL web path
        web_path = f"/static/uploads/{filename}"
        s_logo = Setting.query.filter_by(key='store_logo').first()
        if not s_logo:
            s_logo = Setting(key='store_logo', value=web_path)
            db.session.add(s_logo)
        else:
            s_logo.value = web_path

    db.session.commit()
    invalidate_setting_cache()
    return True

def delete_store_logo(upload_folder=None):
    """Menghapus logo toko dan mereset ke default."""
    s_logo = Setting.query.filter_by(key='store_logo').first()
    if s_logo and s_logo.value:
        old_path = s_logo.value
        if not upload_folder:
            base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
            upload_folder = os.path.join(base_dir, 'static', 'uploads')
            
        filename = os.path.basename(old_path)
        full_file = os.path.join(upload_folder, filename)
        if os.path.exists(full_file):
            try:
                os.remove(full_file)
            except Exception:
                pass
                
        s_logo.value = ""
        db.session.commit()
        invalidate_setting_cache()
    return True


def is_vip_reseller_enabled():
    """
    Memeriksa apakah provider VIP-Reseller aktif.
    Default bernilai True (aktif). Jika di-set ke '0'/'false'/'off', mengembalikan False.
    """
    val = get_setting_value('vip_reseller_enabled', '1')
    if str(val).lower() in ['0', 'false', 'off', 'nonaktif', 'disabled']:
        return False
    return True


def set_vip_reseller_status(enabled: bool):
    """
    Mengubah status aktif/nonaktif provider VIP-Reseller.
    Menyimpan ke tabel Setting dan menyinkronkan ke cache/.env.
    """
    val_str = '1' if enabled else '0'
    s = Setting.query.filter_by(key='vip_reseller_enabled').first()
    if not s:
        s = Setting(key='vip_reseller_enabled', value=val_str, description='Status Aktif Provider VIP-Reseller (1=ON, 0=OFF)')
        db.session.add(s)
    else:
        s.value = val_str
    db.session.commit()
    invalidate_setting_cache('vip_reseller_enabled')
    
    # Sinkronisasi opsional ke .env jika file ada
    try:
        from dotenv import set_key
        base_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        env_file = os.path.join(base_dir, '.env')
        if os.path.exists(env_file):
            set_key(env_file, 'VIP_RESELLER_ENABLED', val_str)
    except Exception:
        pass
        
    return enabled


# =====================================================================
# PENGATURAN DEPOSIT TRANSFER MANUAL E-WALLET
# =====================================================================
DEFAULT_MANUAL_DEPO = {
    'dana_number': '081775700114',
    'dana_name': 'GarudaTel / Kasir',
    'shopee_number': '081775700114',
    'shopee_name': 'GarudaTel / Kasir',
    'gopay_number': '081775700114',
    'gopay_name': 'GarudaTel / Kasir',
    'wa_target': '081775700114',
    'is_active': '1',
    'instructions': 'Pastikan nominal transfer sama persis dengan total di atas (jangan dibulatkan) agar proses verifikasi saldo Anda cepat dan akurat.'
}

def get_manual_deposit_settings():
    """
    Mengambil data nomor rekening dan pemilik akun E-Wallet untuk deposit transfer manual.
    Jika belum ada di database Setting, menggunakan nilai default.
    """
    return {
        'dana_number': get_setting_value('manual_depo_dana_number', DEFAULT_MANUAL_DEPO['dana_number']),
        'dana_name': get_setting_value('manual_depo_dana_name', DEFAULT_MANUAL_DEPO['dana_name']),
        'shopee_number': get_setting_value('manual_depo_shopee_number', DEFAULT_MANUAL_DEPO['shopee_number']),
        'shopee_name': get_setting_value('manual_depo_shopee_name', DEFAULT_MANUAL_DEPO['shopee_name']),
        'gopay_number': get_setting_value('manual_depo_gopay_number', DEFAULT_MANUAL_DEPO['gopay_number']),
        'gopay_name': get_setting_value('manual_depo_gopay_name', DEFAULT_MANUAL_DEPO['gopay_name']),
        'wa_target': get_setting_value('manual_depo_wa_target', DEFAULT_MANUAL_DEPO['wa_target']),
        'is_active': get_setting_value('manual_depo_active', DEFAULT_MANUAL_DEPO['is_active']),
        'instructions': get_setting_value('manual_depo_instructions', DEFAULT_MANUAL_DEPO['instructions'])
    }

def save_manual_deposit_settings(form_data):
    """
    Menyimpan perubahan informasi nomor dan nama pemilik E-Wallet deposit transfer manual.
    """
    dana_num = form_data.get('dana_number', '').strip() or DEFAULT_MANUAL_DEPO['dana_number']
    dana_nm = form_data.get('dana_name', '').strip() or DEFAULT_MANUAL_DEPO['dana_name']
    shopee_num = form_data.get('shopee_number', '').strip() or dana_num
    shopee_nm = form_data.get('shopee_name', '').strip() or dana_nm
    gopay_num = form_data.get('gopay_number', '').strip() or dana_num
    gopay_nm = form_data.get('gopay_name', '').strip() or dana_nm
    wa_num = form_data.get('wa_target', '').strip() or dana_num
    
    # Checkbox aktif atau radio / hidden / programmatic call
    active_val = form_data.get('manual_depo_active')
    if active_val is None and 'is_active' in form_data:
        active_val = form_data.get('is_active')
    is_act = '1' if active_val in ['1', 'on', 'true', True] else '0'
    instructions = form_data.get('instructions', '').strip() or DEFAULT_MANUAL_DEPO['instructions']

    mapping = {
        'manual_depo_dana_number': (dana_num, 'Nomor E-Wallet DANA Deposit Manual'),
        'manual_depo_dana_name': (dana_nm, 'Atas Nama Akun DANA Deposit Manual'),
        'manual_depo_shopee_number': (shopee_num, 'Nomor E-Wallet ShopeePay Deposit Manual'),
        'manual_depo_shopee_name': (shopee_nm, 'Atas Nama Akun ShopeePay Deposit Manual'),
        'manual_depo_gopay_number': (gopay_num, 'Nomor E-Wallet GoPay Deposit Manual'),
        'manual_depo_gopay_name': (gopay_nm, 'Atas Nama Akun GoPay Deposit Manual'),
        'manual_depo_wa_target': (wa_num, 'Nomor WhatsApp Admin Tujuan Konfirmasi Deposit'),
        'manual_depo_active': (is_act, 'Status Aktif Deposit Manual E-Wallet (1=ON, 0=OFF)'),
        'manual_depo_instructions': (instructions, 'Instruksi / Catatan Tambahan Transfer Manual')
    }

    for k, (val, desc) in mapping.items():
        s = Setting.query.filter_by(key=k).first()
        if not s:
            s = Setting(key=k, value=val, description=desc)
            db.session.add(s)
        else:
            s.value = val
            if desc:
                s.description = desc

    db.session.commit()
    invalidate_setting_cache()
    return True


def get_pos_settings():
    """
    Mengambil konfigurasi Web POS & Merchant API:
    - enabled: '1' jika aktif/publik, '0' jika dalam tahap pengembangan/preview
    - web_url: URL domain Web POS produksi (e.g. https://pos.garudatel.com)
    - announcement_title: Judul pengumuman preview
    - announcement_message: Deskripsi fitur
    """
    return {
        'enabled': get_setting_value('pos_feature_enabled', '0'),
        'web_url': get_setting_value('pos_web_url', os.getenv('POS_WEB_URL', 'http://localhost:3000')),
        'announcement_title': get_setting_value('pos_announcement_title', 'Aplikasi Kasir Web POS Konter HP & Minimarket Modern'),
        'announcement_message': get_setting_value('pos_announcement_message', 'Fitur kasir digital terintegrasi saldo GarudaTel sedang dalam tahap penyempurnaan akhir sebelum rilis publik.')
    }


def save_pos_settings(form_data):
    """
    Menyimpan konfigurasi status on/off dan URL Web POS ke database.
    """
    enabled_val = '1' if form_data.get('pos_feature_enabled') in ['1', 'true', 'on', True] else '0'
    web_url_val = form_data.get('pos_web_url', '').strip() or 'http://localhost:3000'
    title_val = form_data.get('pos_announcement_title', '').strip() or 'Aplikasi Kasir Web POS Konter HP & Minimarket Modern'
    msg_val = form_data.get('pos_announcement_message', '').strip() or 'Fitur kasir digital terintegrasi saldo GarudaTel sedang dalam tahap penyempurnaan akhir sebelum rilis publik.'

    mapping = {
        'pos_feature_enabled': (enabled_val, 'Status Fitur Kasir Web POS (1=Aktif, 0=Dalam Pengembangan)'),
        'pos_web_url': (web_url_val, 'URL Domain Web POS Produksi'),
        'pos_announcement_title': (title_val, 'Judul Halaman Pengumuman Web POS'),
        'pos_announcement_message': (msg_val, 'Pesan Ringkasan Pengumuman Web POS')
    }

    for k, (val, desc) in mapping.items():
        s = Setting.query.filter_by(key=k).first()
        if not s:
            s = Setting(key=k, value=val, description=desc)
            db.session.add(s)
        else:
            s.value = val
            if desc:
                s.description = desc

    db.session.commit()
    invalidate_setting_cache()
    return True


