import requests
import hashlib
import hmac
import os
import time
import json
from datetime import datetime, timedelta, timezone
from app.extensions import db
from app.models.product import Product
from app.models.margin import MarginTier

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
COOLDOWN_SECONDS = 330  # 5.5 menit (batas resmi Digiflazz adalah 5 menit)


def clean_str(val):
    if not val: return ''
    return str(val).replace("'", "").replace('"', '').strip(" \t\n\r")

# =====================================================================
# JADWAL CUT OFF & MAINTENANCE HARIAN PLN (23:30 - 01:00 WIB)
# =====================================================================
def is_pln_cutoff_time(check_time=None):
    """
    Mengecek apakah waktu saat ini (atau check_time) masuk jadwal Cut Off harian PLN (23:30 - 01:00 WIB).
    Biller PLN pusat tidak melayani pembelian token maupun cek/bayar tagihan pada rentang waktu ini.
    """
    if check_time is None:
        now_wib = datetime.now(timezone.utc) + timedelta(hours=7)
    else:
        now_wib = check_time

    hour = now_wib.hour
    minute = now_wib.minute

    # 23:30 s/d 23:59 WIB ATAU 00:00 s/d 00:59 WIB
    if (hour == 23 and minute >= 30) or (hour == 0):
        return True
    return False

def get_pln_cutoff_message():
    """Pesan resmi peringatan Cut Off PLN untuk user."""
    return "Jadwal Cut Off & Maintenance Harian PLN (23:30 - 01:00 WIB). Transaksi pembelian token dan pembayaran tagihan PLN tidak dapat diproses pada waktu ini. Mohon coba kembali setelah pukul 01:00 WIB."


# =====================================================================
# 10. RESPONSE CODE MAPPING (https://developer.digiflazz.com/api/buyer/response-code/)
# =====================================================================
DIGIFLAZZ_RC = {
    "00": "Sukses",
    "01": "Saldo Tidak Cukup",
    "02": "Member Tidak Ditemukan / Tidak Aktif",
    "03": "Menunggu respon dari provider (Pending)",
    "40": "Parameter yang dikirim tidak lengkap",
    "41": "SKU produk tidak ditemukan / sedang gangguan",
    "42": "Nomor tujuan salah / terblokir / cut off",
    "43": "Ref ID duplikat (sudah pernah digunakan)",
    "44": "IP pengirim belum terdaftar di whitelist",
    "45": "Signature tidak valid",
    "46": "Server error / timeout dari provider",
    "47": "Batas waktu pembayaran habis",
    "48": "Tagihan sudah lunas",
    "49": "Tagihan belum tersedia",
    "50": "Transaksi dibatalkan oleh sistem",
    "51": "Akun dibekukan sementara",
    "52": "Saldo Buyer tidak mencukupi untuk bayar tagihan",
    "53": "Nominal pembayaran tidak sesuai",
    "54": "ID Pelanggan tidak terdaftar",
    "55": "Produk sedang gangguan",
    "62": "Seller sedang mengalami gangguan"
}

def get_rc_message(rc, default_msg=None):
    """Mendapatkan pesan bahasa Indonesia berdasarkan Response Code resmi Digiflazz."""
    if rc is None or rc == '':
        return default_msg or "Status tidak diketahui"
    rc_str = str(rc).strip()
    return DIGIFLAZZ_RC.get(rc_str, default_msg or f"Respon kode {rc_str}")

def auto_handle_product_disruption(sku_code, rc, message=None):
    """
    Smart Auto-Detect Gangguan Real-Time:
    Otomatis menonaktifkan produk (is_active = False) jika Digiflazz mengembalikan
    kode gangguan (RC 55, 62, 41, 42). Mencegah transaksi gagal beruntun pada user lain.
    """
    if not sku_code:
        return
    rc_str = str(rc).strip()
    if rc_str in ['55', '62', '41', '42']:
        try:
            prod = Product.query.filter_by(sku_code=sku_code).first()
            if prod and prod.is_active:
                prod.is_active = False
                db.session.commit()
                print(f"[AUTO-DETECT GANGGUAN] SKU '{sku_code}' dinonaktifkan otomatis di DB (RC: {rc_str} - {message or DIGIFLAZZ_RC.get(rc_str)})")
        except Exception as e_disrupt:
            print(f"[AUTO-DETECT ERROR] Gagal menonaktifkan SKU {sku_code}: {e_disrupt}")

def get_sync_cooldown_status():
    """
    Memeriksa apakah cooldown sinkronisasi 5.5 menit Digiflazz sedang aktif.
    Returns: (is_in_cooldown: bool, remaining_seconds: int, last_sync_dt: datetime|None)
    """
    cache_dir = os.path.join(BASE_DIR, 'storage', 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, 'digiflazz_last_sync.json')
    if not os.path.exists(cache_file):
        return False, 0, None

    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            d = json.load(f)
            last_ts = float(d.get('last_sync_timestamp', 0))
            if last_ts <= 0:
                return False, 0, None

            elapsed = time.time() - last_ts
            if elapsed < COOLDOWN_SECONDS:
                remaining = int(COOLDOWN_SECONDS - elapsed)
                last_dt = datetime.fromtimestamp(last_ts)
                return True, remaining, last_dt
    except Exception:
        pass
    return False, 0, None

def set_last_sync_timestamp():
    """Mencatat timestamp saat ini sebagai waktu sinkronisasi terakhir yang sukses."""
    cache_dir = os.path.join(BASE_DIR, 'storage', 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, 'digiflazz_last_sync.json')
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump({
                'last_sync_timestamp': time.time(),
                'last_sync_datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }, f)
    except Exception as e:
        print(f"[COOLDOWN CACHE ERROR] {e}")


# =====================================================================
# 9. TEST CASES STANDARD (https://developer.digiflazz.com/api/buyer/test-case/)
# =====================================================================
DIGIFLAZZ_TEST_CASES = {
    "SUKSES": "087800001230",       # Respon Sukses (RC: 00)
    "GAGAL": "087800001232",        # Respon Gagal / Gangguan (RC: 41)
    "PENDING": "087800001233",      # Respon Pending (RC: 03)
    "NOMOR_SALAH": "087800001234",  # Respon Cut Off / Nomor Salah (RC: 42)
}

def calculate_sell_price(base_price, tiers):
    """Hitung harga jual dinamis berdasarkan tabel MarginTier."""
    if not tiers:
        return base_price + 500
    for t in tiers:
        if t.min_price <= base_price <= t.max_price:
            return base_price + t.margin
    return base_price + tiers[-1].margin

# =====================================================================
# 2. DAFTAR HARGA (https://developer.digiflazz.com/api/buyer/daftar-harga/)
# =====================================================================
def get_price_list(cmd='prepaid', code=None):
    """
    Mengambil daftar harga produk resmi dari Digiflazz.
    cmd: 'prepaid' atau 'pasca'
    code: opsional kode buyer_sku_code spesifik
    """
    from dotenv import load_dotenv
    load_dotenv(override=False)
    username = clean_str(os.getenv('DIGI_USER'))
    key = clean_str(os.getenv('DIGI_KEY'))
    base_url = clean_str(os.getenv('DIGI_URL', 'https://api.digiflazz.com/v1')).rstrip('/')
    url = f"{base_url}/price-list"

    if not username or not key:
        return False, [], "Username atau API Key Digiflazz belum diatur di .env!"

    sign = hashlib.md5(f"{username}{key}pricelist".encode()).hexdigest()
    payload = {
        "cmd": str(cmd).strip().lower(),
        "username": username,
        "sign": sign
    }
    if code:
        payload["code"] = str(code).strip()

    try:
        res = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=20)
        res_json = res.json() if res.status_code == 200 else res.json()
        data = res_json.get('data', [])
        if isinstance(data, list):
            return True, data, f"Berhasil mengambil {len(data)} produk ({cmd})"
        elif isinstance(data, dict):
            rc = data.get('rc')
            msg = data.get('message', get_rc_message(rc, 'Gagal mengambil pricelist'))
            return False, [], f"RC {rc}: {msg}" if rc else msg
        return False, [], "Respon tidak valid dari server Digiflazz"
    except Exception as e:
        return False, [], f"Gagal menghubungi server Digiflazz: {str(e)}"

def sync_products(force=False, notify_admin_bot=True, include_pasca=False):
    """
    Sinkronisasi katalog produk dari Digiflazz ke database lokal.
    Dilengkapi 4 Lapis Pengaman Baja Anti-Wipeout & Anti-Limit (RC 83):
    1. Single-Endpoint Priority (Prepaid ditarik dari Digiflazz, Pasca menggunakan katalog resmi lokal)
       mencegah benturan rate-limit Digiflazz RC 83 yang hanya mengizinkan 1 request /price-list per akun.
    2. Cooldown Guard (5.5 menit / 330s) mematuhi batas resmi Digiflazz
    3. Circuit Breaker (minimal 500 SKU dari Digiflazz sebelum menyentuh produk usang)
    4. Anti-Wipeout Soft-Disable (TIDAK ADA db.session.delete; produk usang diset is_active=False)
    """
    from dotenv import load_dotenv
    load_dotenv(override=False)
    username = clean_str(os.getenv('DIGI_USER'))
    key = clean_str(os.getenv('DIGI_KEY'))

    if not username or not key:
        return False, "Gagal: Username atau API Key Digiflazz belum diatur di .env!"

    # 1. COOLDOWN GUARD: Mencegah ban/penolakan dari Digiflazz (kecuali force=True atau saat unit testing)
    try:
        from flask import current_app
        is_testing = os.getenv('FLASK_ENV') == 'testing' or bool(current_app and current_app.config.get('TESTING'))
    except Exception:
        is_testing = os.getenv('FLASK_ENV') == 'testing'
    if not force and not is_testing:
        in_cooldown, remaining, last_dt = get_sync_cooldown_status()
        if in_cooldown:
            last_str = last_dt.strftime('%H:%M:%S') if last_dt else 'beberapa saat lalu'
            return False, f"⏳ Cooldown Aktif: Sinkronisasi baru saja dilakukan pada {last_str}. Harap tunggu {remaining} detik lagi untuk mematuhi batas 5 menit Digiflazz."

    tiers = MarginTier.query.order_by(MarginTier.level.asc()).all()
    new_count = 0
    update_count = 0
    gangguan_count = 0
    seen_skus = set()
    cmds = ["prepaid"]
    if include_pasca:
        cmds.append("pasca")

    cmd_success_count = 0
    cmd_errors = []

    for cmd in cmds:
        ok, items, msg = get_price_list(cmd=cmd)
        if not ok:
            print(f"[SYNC DIGIFLAZZ] Gagal mengambil pricelist {cmd}: {msg}")
            cmd_errors.append(f"{cmd.upper()}: {msg}")
            # Jika terkena limitasi RC 83 dari Digiflazz, aktifkan cooldown lokal agar admin tidak spam
            if "83" in str(msg):
                try:
                    set_last_sync_timestamp()
                except Exception:
                    pass
            continue

        cmd_success_count += 1

        for item in items:
            sku = item.get('buyer_sku_code')
            if not sku:
                continue

            seen_skus.add(sku)

            # Deteksi status ganda: buyer_product_status & seller_product_status
            # Jika seller_product_status == False, maka operator/provider Digiflazz sedang GANGGUAN!
            buyer_status = bool(item.get('buyer_product_status', True))
            seller_status = bool(item.get('seller_product_status', True))
            product_active = buyer_status and seller_status

            if not product_active:
                gangguan_count += 1

            price = item.get('price', item.get('admin', 0))
            sell_price_calc = calculate_sell_price(price, tiers)

            # Ekstrak deskripsi produk dari Digiflazz jika tersedia
            raw_desc = clean_str(item.get('desc'))
            desc_val = raw_desc if raw_desc and raw_desc.strip() != '-' else None

            product = Product.query.filter_by(sku_code=sku).first()

            if not product:
                new_product = Product(
                    sku_code=sku,
                    name=item.get('product_name', sku),
                    category=item.get('category', 'Umum'),
                    brand=item.get('brand', 'Umum'),
                    base_price=price,
                    sell_price=sell_price_calc,
                    is_active=product_active,
                    is_manual_margin=False,
                    description=desc_val,
                    is_manual_desc=False
                )
                db.session.add(new_product)
                new_count += 1
            else:
                if product.base_price != price:
                    product.base_price = price
                    if not product.is_manual_margin:
                        product.sell_price = sell_price_calc
                    update_count += 1
                
                # Sinkronkan status aktif / gangguan secara real-time
                if product.is_active != product_active:
                    product.is_active = product_active
                    update_count += 1

                # Sinkronkan deskripsi jika tidak dikunci manual oleh admin
                if not getattr(product, 'is_manual_desc', False):
                    if product.description != desc_val:
                        product.description = desc_val
                        update_count += 1

    # 2. ALL-OR-NOTHING CHECK:
    # Jika perintah gagal, BATALKAN proses pembersihan dan amankan katalog!
    if cmd_success_count < len(cmds):
        err_detail = " | ".join(cmd_errors)
        print(f"[CIRCUIT BREAKER] Sinkronisasi tidak lengkap. Kategori gagal: {err_detail}. Katalog aman dari penghapusan.")
        db.session.rollback()
        if "83" in err_detail:
            friendly_err = (
                f"Digiflazz gagal merespon lengkap ({err_detail}).\n\n"
                "💡 <i>Catatan: Server Digiflazz membatasi pengecekan pricelist per akun (jeda 5-10 menit). "
                "Harap tunggu beberapa menit sebelum mencoba lagi, atau pastikan server/bot lain tidak sedang mengakses akun Digiflazz yang sama. "
                "Katalog produk lokal tetap dipertahankan utuh & aman.</i>"
            )
            return False, friendly_err
        return False, f"Digiflazz gagal merespon lengkap ({err_detail}). Katalog produk lokal tetap dipertahankan utuh."

    # 3. CIRCUIT BREAKER THRESHOLD (Minimal 500 SKU) & SOFT-DISABLE (NO HARD DELETE!)
    deactivated_count = 0
    min_sku_threshold = 1 if is_testing else 500

    if len(seen_skus) < min_sku_threshold:
        print(f"[CIRCUIT BREAKER] Hanya mendeteksi {len(seen_skus)} SKU dari Digiflazz (ambang batas: {min_sku_threshold}). Penonaktifan produk usang dibatalkan demi keamanan katalog.")
    else:
        from app.services.pascabayar_service import PASCABAYAR_BRANDS, PASCABAYAR_SKUS, seed_pascabayar_products
        # Cari produk lokal yang BUKAN produk VIP-Reseller, BUKAN produk Pascabayar, dan TIDAK ada dalam seen_skus Digiflazz
        obsolete_products = Product.query.filter(
            ~Product.brand.like('VIP-%'),
            ~Product.name.like('[VIP] %'),
            ~Product.category.ilike('%pasca%'),
            ~Product.category.ilike('%tagihan%'),
            ~Product.brand.in_(PASCABAYAR_BRANDS),
            ~Product.sku_code.in_(seen_skus.union(PASCABAYAR_SKUS))
        ).all()

        # KRITIS: HANYA NONAKTIFKAN (SOFT-DISABLE), JANGAN DIHAPUS (NO HARD DELETE)!
        for ob in obsolete_products:
            if ob.is_active:
                ob.is_active = False
                deactivated_count += 1

    # Selalu pastikan produk pascabayar nasional (PDAM se-Indonesia, BPJS, PLN Pasca, Telkom) tersedia & aktif
    try:
        from app.services.pascabayar_service import seed_pascabayar_products
        seed_pascabayar_products()
    except Exception as e_seed:
        print(f"[SEED PASCABAYAR WARNING] {e_seed}")

    db.session.commit()
    set_last_sync_timestamp()

    total_products = Product.query.count()

    msg_success = f"Sukses! {new_count} produk baru, {update_count} diperbarui, total produk {total_products}, {gangguan_count} terdeteksi gangguan"
    if deactivated_count > 0:
        msg_success += f", {deactivated_count} produk usang dinonaktifkan."
    else:
        msg_success += "."

    if notify_admin_bot:
        try:
            from app.services.telegram_service import send_sync_report_to_admin_bot
            send_sync_report_to_admin_bot(msg_success, is_cron=True)
        except Exception as e_tele:
            print(f"[SYNC NOTIF BOT ERROR] Gagal mengirim laporan ke Bot 3: {e_tele}")

    return True, msg_success

# =====================================================================
# 4. TRANSAKSI TOPUP PRABAYAR (https://developer.digiflazz.com/api/buyer/topup/)
# =====================================================================
def create_transaction(sku, tujuan, ref_id, testing=None, max_price=None, cb_url=None, allow_dot=None):
    """
    Mengirimkan transaksi isi ulang pulsa/data/e-money (Prabayar) ke Digiflazz.
    Signature: md5(username + key + ref_id)
    Mendukung opsi resmi: testing, max_price, cb_url, allow_dot.
    """
    from dotenv import load_dotenv
    load_dotenv(override=False)
    username = clean_str(os.getenv('DIGI_USER'))
    key = clean_str(os.getenv('DIGI_KEY'))
    base_url = clean_str(os.getenv('DIGI_URL', 'https://api.digiflazz.com/v1')).rstrip('/')
    url = f"{base_url}/transaction"

    sign = hashlib.md5(f"{username}{key}{str(ref_id).strip()}".encode()).hexdigest()
    payload = {
        "username": username,
        "buyer_sku_code": str(sku).strip(),
        "customer_no": str(tujuan).strip(),
        "ref_id": str(ref_id).strip(),
        "sign": sign
    }
    if testing is not None:
        payload["testing"] = bool(testing)
    if max_price is not None:
        try:
            payload["max_price"] = int(max_price)
        except (ValueError, TypeError):
            pass
    if cb_url:
        payload["cb_url"] = str(cb_url).strip()
    if allow_dot is not None:
        payload["allow_dot"] = bool(allow_dot)

    try:
        res = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=25)
        res_json = res.json()
        data = res_json.get('data', {}) if isinstance(res_json, dict) else {}
        rc = data.get('rc')
        if rc:
            auto_handle_product_disruption(sku, rc, data.get('message'))
        return res_json
    except Exception as e:
        return {"data": {"status": "Gagal", "message": str(e), "rc": "46"}}

def submit_transaction(sku, customer_no, ref_id, testing=None, **kwargs):
    """
    Wrapper standar untuk transaksi prabayar Digiflazz.
    Mengembalikan tuple (ok: bool, data: dict, msg: str).
    """
    res = create_transaction(sku, customer_no, ref_id, testing=testing, **kwargs)
    data = res.get('data', {}) if isinstance(res, dict) else {}
    status = str(data.get('status', '')).lower()
    rc = str(data.get('rc', '')).strip()
    msg = data.get('message', '')
    ok = (rc == '00' or 'sukses' in status or 'success' in status or rc == '03' or 'pending' in status or 'menunggu' in status)
    return ok, data, msg


def check_balance():
    from dotenv import load_dotenv
    load_dotenv(override=False)
    username = clean_str(os.getenv('DIGI_USER'))
    key = clean_str(os.getenv('DIGI_KEY'))
    base_url = clean_str(os.getenv('DIGI_URL', 'https://api.digiflazz.com/v1'))
    url = base_url.rstrip('/') + '/cek-saldo'

    if not username or not key:
        return False, 0.0, "Username atau API Key Digiflazz belum diatur di .env!"

    sign = hashlib.md5(f"{username}{key}depo".encode()).hexdigest()
    payload = {
        "cmd": "deposit",
        "username": username,
        "sign": sign
    }

    try:
        res = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=15)
        res_json = res.json()
        data = res_json.get('data', {}) if isinstance(res_json, dict) else {}
        rc = data.get('rc')

        # Sesuai dokumentasi resmi Digiflazz: jika respon mengandung rc error (misal RC 41, 42, 45, dll)
        if rc and rc != '00':
            msg = data.get('message', f"Digiflazz error (RC: {rc})")
            return False, 0.0, f"RC {rc}: {msg}"

        if res.status_code != 200:
            msg = data.get('message', f"HTTP Error {res.status_code}")
            return False, 0.0, f"Server menolak: {msg}"

        if 'deposit' in data:
            return True, float(data['deposit']), "Berhasil mengambil saldo Digiflazz"
        else:
            msg = data.get('message', 'Gagal membaca respon saldo Digiflazz')
            return False, 0.0, msg
    except Exception as e:
        return False, 0.0, f"Gagal menghubungi server Digiflazz: {str(e)}"

def format_bank_name(bank):
    """Format nama bank sesuai dokumentasi resmi Digiflazz (Flip/ShopeePay/GOPAY untuk Perorangan, BCA/MANDIRI/BRI/BNI untuk Perusahaan)."""
    b = str(bank).strip()
    if b.lower() in ['shopeepay', 'shoopepay']:
        return 'ShopeePay'
    elif b.lower() in ['gopay', 'go-pay']:
        return 'GOPAY'
    elif b.lower() == 'flip':
        return 'Flip'
    else:
        return b.upper()

def request_deposit(amount, bank, owner_name):
    from dotenv import load_dotenv
    load_dotenv(override=False)
    username = clean_str(os.getenv('DIGI_USER'))
    key = clean_str(os.getenv('DIGI_KEY'))
    base_url = clean_str(os.getenv('DIGI_URL', 'https://api.digiflazz.com/v1'))
    url = base_url.rstrip('/') + '/deposit'

    if not username or not key:
        return False, {}, "Username atau API Key Digiflazz belum diatur di .env!"

    try:
        amount_int = int(amount)
    except (ValueError, TypeError):
        return False, {}, "Nominal deposit tidak valid"

    bank_formatted = format_bank_name(bank)
    sign = hashlib.md5(f"{username}{key}deposit".encode()).hexdigest()
    payload = {
        "username": username,
        "amount": amount_int,
        "Bank": bank_formatted,
        "bank": bank_formatted,
        "owner_name": str(owner_name).strip(),
        "sign": sign
    }

    try:
        res = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=20)
        res_json = res.json()
        data = res_json.get('data', {}) if isinstance(res_json, dict) else {}
        rc = data.get('rc')

        # Sesuai dokumentasi resmi Digiflazz: hanya rc == '00' yang sukses
        if rc == '00':
            # Sinkronisasi parameter rekening sesuai dokumentasi resmi (account_no)
            if 'account_no' in data and 'account_number' not in data:
                data['account_number'] = data['account_no']
            return True, data, "Tiket deposit berhasil dibuat!"
        else:
            msg = data.get('message', get_rc_message(rc, f"Digiflazz menolak permintaan tiket (RC: {rc})"))
            return False, data, f"RC {rc}: {msg}" if rc else msg
    except Exception as e:
        return False, {}, f"Gagal menghubungi server Digiflazz: {str(e)}"

# =====================================================================
# 5. CEK TAGIHAN PASCABAYAR (https://developer.digiflazz.com/api/buyer/cek-tagihan/)
# =====================================================================
def inquiry_pasca(sku, customer_no, ref_id, testing=None, amount=None):
    """
    Melakukan pengecekan tagihan pascabayar (Inquiry).
    commands: 'inq-pasca'
    Signature: md5(username + key + ref_id)
    Untuk produk E-Money Bebas Nominal, Digiflazz mewajibkan parameter 'amount' (Int).
    """
    from dotenv import load_dotenv
    load_dotenv(override=False)
    username = clean_str(os.getenv('DIGI_USER'))
    key = clean_str(os.getenv('DIGI_KEY'))
    base_url = clean_str(os.getenv('DIGI_URL', 'https://api.digiflazz.com/v1')).rstrip('/')
    url = f"{base_url}/transaction"

    if not username or not key:
        return False, {}, "Username atau API Key Digiflazz belum diatur di .env!"

    sign = hashlib.md5(f"{username}{key}{str(ref_id).strip()}".encode()).hexdigest()
    payload = {
        "commands": "inq-pasca",
        "username": username,
        "buyer_sku_code": str(sku).strip(),
        "customer_no": str(customer_no).strip(),
        "ref_id": str(ref_id).strip(),
        "sign": sign
    }
    if amount is not None:
        try:
            payload["amount"] = int(amount)
        except (ValueError, TypeError):
            pass
    if testing is not None:
        payload["testing"] = bool(testing)

    try:
        res = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=20)
        res_json = res.json() if res.status_code in [200, 400, 401, 403] else {}
        data = res_json.get('data', {}) if isinstance(res_json, dict) else {}
        rc = data.get('rc')

        if rc == '00':
            return True, data, "Inquiry tagihan berhasil ditemukan"
        else:
            auto_handle_product_disruption(sku, rc, data.get('message'))
            msg = data.get('message', get_rc_message(rc, f"Inquiry gagal (RC: {rc})"))
            return False, data, f"RC {rc}: {msg}" if rc else msg
    except Exception as e:
        return False, {}, f"Gagal menghubungi server Digiflazz: {str(e)}"

# =====================================================================
# 6. BAYAR TAGIHAN PASCABAYAR (https://developer.digiflazz.com/api/buyer/bayar-tagihan/)
# =====================================================================
def pay_pasca(sku, customer_no, ref_id, testing=None):
    """
    Melakukan pembayaran tagihan pascabayar yang telah di-inquiry sebelumnya.
    commands: 'pay-pasca'
    Signature: md5(username + key + ref_id)
    PERHATIAN: ref_id harus sama persis dengan ref_id saat inquiry_pasca pada hari yang sama.
    """
    from dotenv import load_dotenv
    load_dotenv(override=False)
    username = clean_str(os.getenv('DIGI_USER'))
    key = clean_str(os.getenv('DIGI_KEY'))
    base_url = clean_str(os.getenv('DIGI_URL', 'https://api.digiflazz.com/v1')).rstrip('/')
    url = f"{base_url}/transaction"

    if not username or not key:
        return False, {}, "Username atau API Key Digiflazz belum diatur di .env!"

    sign = hashlib.md5(f"{username}{key}{str(ref_id).strip()}".encode()).hexdigest()
    payload = {
        "commands": "pay-pasca",
        "username": username,
        "buyer_sku_code": str(sku).strip(),
        "customer_no": str(customer_no).strip(),
        "ref_id": str(ref_id).strip(),
        "sign": sign
    }
    if testing is not None:
        payload["testing"] = bool(testing)

    try:
        res = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=25)
        res_json = res.json() if res.status_code in [200, 400, 401, 403] else {}
        data = res_json.get('data', {}) if isinstance(res_json, dict) else {}
        rc = data.get('rc')

        if rc == '00':
            return True, data, "Pembayaran tagihan pascabayar sukses"
        elif rc == '03':
            return True, data, "Pembayaran tagihan sedang diproses (Pending)"
        else:
            auto_handle_product_disruption(sku, rc, data.get('message'))
            msg = data.get('message', get_rc_message(rc, f"Pembayaran tagihan gagal (RC: {rc})"))
            return False, data, f"RC {rc}: {msg}" if rc else msg
    except Exception as e:
        return False, {}, f"Gagal menghubungi server Digiflazz: {str(e)}"

# Alias fungsi pascabayar untuk kompatibilitas universal
inquiry_postpaid = inquiry_pasca
pay_postpaid = pay_pasca

# =====================================================================
# 7. CEK STATUS TRANSAKSI (https://developer.digiflazz.com/api/buyer/cek-status/)
# =====================================================================
def check_transaction_status(sku, customer_no, ref_id, is_pasca=False):
    """
    Mengecek status transaksi terakhir:
    - Prabayar: Re-submit payload transaksi awal dengan ref_id yang sama.
    - Pascabayar: commands 'status-pasca'.
    """
    from dotenv import load_dotenv
    load_dotenv(override=False)
    username = clean_str(os.getenv('DIGI_USER'))
    key = clean_str(os.getenv('DIGI_KEY'))
    base_url = clean_str(os.getenv('DIGI_URL', 'https://api.digiflazz.com/v1')).rstrip('/')
    url = f"{base_url}/transaction"

    if not username or not key:
        return False, {}, "Username atau API Key Digiflazz belum diatur di .env!"

    sign = hashlib.md5(f"{username}{key}{str(ref_id).strip()}".encode()).hexdigest()
    payload = {
        "username": username,
        "buyer_sku_code": str(sku).strip(),
        "customer_no": str(customer_no).strip(),
        "ref_id": str(ref_id).strip(),
        "sign": sign
    }
    if is_pasca:
        payload["commands"] = "status-pasca"

    try:
        res = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=20)
        res_json = res.json() if res.status_code in [200, 400, 401, 403] else {}
        data = res_json.get('data', {}) if isinstance(res_json, dict) else {}
        status = str(data.get('status', '')).capitalize()
        rc = data.get('rc')
        msg = data.get('message', get_rc_message(rc, f"Status: {status}"))
        return True, data, msg
    except Exception as e:
        return False, {}, f"Gagal memeriksa status: {str(e)}"

# =====================================================================
# 8. INQUIRY PLN (https://developer.digiflazz.com/api/buyer/inquiry-pln/)
# =====================================================================
def inquiry_pln(customer_no):
    """
    Inquiry data pelanggan PLN (Prabayar/Token & Pascabayar).
    Signature khusus PLN: md5(username + key + customer_no)
    Mengembalikan nama pelanggan, segmen daya/tarif, dan nomor meter.
    """
    from dotenv import load_dotenv
    load_dotenv(override=False)
    username = clean_str(os.getenv('DIGI_USER'))
    key = clean_str(os.getenv('DIGI_KEY'))
    base_url = clean_str(os.getenv('DIGI_URL', 'https://api.digiflazz.com/v1')).rstrip('/')
    url = f"{base_url}/inquiry-pln"

    cust_clean = str(customer_no).strip()
    if not username or not key:
        return False, {}, "Username atau API Key Digiflazz belum diatur di .env!"

    if not cust_clean:
        return False, {}, "Nomor meter / ID Pelanggan PLN tidak boleh kosong!"

    sign = hashlib.md5(f"{username}{key}{cust_clean}".encode()).hexdigest()
    payload = {
        "username": username,
        "customer_no": cust_clean,
        "sign": sign
    }

    try:
        res = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=20)
        res_json = res.json() if res.status_code in [200, 400, 401, 403] else {}
        data = res_json.get('data', {}) if isinstance(res_json, dict) else {}
        rc = data.get('rc')

        if rc == '00' or (res.status_code == 200 and 'name' in data):
            return True, data, f"Pelanggan PLN: {data.get('name', 'Terdaftar')}"
        else:
            msg = data.get('message', get_rc_message(rc, 'ID Pelanggan PLN tidak ditemukan'))
            return False, data, f"RC {rc}: {msg}" if rc else msg
    except Exception as e:
        return False, {}, f"Gagal menghubungi server Digiflazz: {str(e)}"

# =====================================================================
# 11. VERIFIKASI WEBHOOK SIGNATURE (https://developer.digiflazz.com/api/buyer/webhook/)
# =====================================================================
def verify_webhook_signature(raw_body_bytes, signature_header, secret=None):
    """
    Memvalidasi keaslian webhook Digiflazz menggunakan HMAC-SHA1 pada header X-Hub-Signature.
    Header format: 'sha1=<hexdigest>' atau '<hexdigest>'.
    Secret: webhook secret yang dikonfigurasi di Buyer Dashboard Digiflazz, atau fallback ke DIGI_KEY.
    """
    if not secret:
        secret = os.getenv('DIGI_WEBHOOK_SECRET', os.getenv('DIGI_KEY', '')).strip()

    if not signature_header or not secret or not raw_body_bytes:
        return False

    sig = str(signature_header).strip()
    if sig.lower().startswith('sha1='):
        sig = sig[5:]
    elif sig.lower().startswith('sha1:'):
        sig = sig[5:]

    try:
        computed = hmac.new(secret.encode('utf-8'), raw_body_bytes, hashlib.sha1).hexdigest()
        return hmac.compare_digest(sig.lower(), computed.lower())
    except Exception:
        return False

