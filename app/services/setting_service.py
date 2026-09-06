import os
import time
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models.setting import Setting

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
DEFAULT_STORE_NAME = "GarudaTel"
DEFAULT_TAGLINE = "Platform PPOB & Top Up Terpercaya"
DEFAULT_FOOTER = "Terima kasih atas kepercayaan Anda!"

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS

def get_setting_value(key, default=""):
    try:
        s = Setting.query.filter_by(key=key).first()
        if s and s.value is not None and s.value.strip() != "":
            return s.value.strip()
    except Exception:
        pass
    return default

def get_store_name():
    """Mengembalikan nama toko dinamis saat ini (default: GarudaTel)."""
    return get_setting_value('store_name', DEFAULT_STORE_NAME)

def get_store_settings():
    """
    Mengembalikan dictionary lengkap pengaturan toko dinamis:
    - name: Nama Toko
    - tagline: Slogan / Sub-header
    - whatsapp_group: Link / info channel grup WhatsApp
    - receipt_footer: Pesan penutup struk
    - logo: Path relatif file logo (misal: /static/uploads/logo.png)
    - logo_url: URL lengkap/relatif untuk template
    """
    logo_path = get_setting_value('store_logo', '')
    return {
        'name': get_setting_value('store_name', DEFAULT_STORE_NAME),
        'tagline': get_setting_value('store_tagline', DEFAULT_TAGLINE),
        'whatsapp_group': get_setting_value('store_whatsapp_group', ''),
        'receipt_footer': get_setting_value('receipt_footer', DEFAULT_FOOTER),
        'logo': logo_path,
        'logo_url': logo_path if logo_path else ''
    }

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
    return True

