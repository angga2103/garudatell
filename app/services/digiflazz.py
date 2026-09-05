import requests
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from app.extensions import db
from app.models.product import Product
from app.models.margin import MarginTier

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
    "55": "Produk pascabayar sedang gangguan"
}

def get_rc_message(rc, default_msg=None):
    """Mendapatkan pesan bahasa Indonesia berdasarkan Response Code resmi Digiflazz."""
    if rc is None or rc == '':
        return default_msg or "Status tidak diketahui"
    rc_str = str(rc).strip()
    return DIGIFLAZZ_RC.get(rc_str, default_msg or f"Respon kode {rc_str}")

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

def sync_products():
    """Sinkronisasi katalog produk dari Digiflazz (Prepaid & Pasca) ke database lokal."""
    from dotenv import load_dotenv
    load_dotenv(override=False)
    username = clean_str(os.getenv('DIGI_USER'))
    key = clean_str(os.getenv('DIGI_KEY'))

    if not username or not key:
        return False, "Gagal: Username atau API Key Digiflazz belum diatur di .env!"

    tiers = MarginTier.query.order_by(MarginTier.level.asc()).all()
    new_count = 0
    update_count = 0
    cmds = ["prepaid", "pasca"]

    for cmd in cmds:
        ok, items, msg = get_price_list(cmd=cmd)
        if not ok:
            return False, f"Digiflazz menolak ({cmd}): {msg}"

        for item in items:
            sku = item.get('buyer_sku_code')
            if not sku:
                continue

            product = Product.query.filter_by(sku_code=sku).first()
            product_active = item.get('buyer_product_status', True)
            price = item.get('price', item.get('admin', 0))
            sell_price_calc = calculate_sell_price(price, tiers)

            if not product:
                new_product = Product(
                    sku_code=sku,
                    name=item.get('product_name', sku),
                    category=item.get('category', 'Umum'),
                    brand=item.get('brand', 'Umum'),
                    base_price=price,
                    sell_price=sell_price_calc,
                    is_active=product_active,
                    is_manual_margin=False
                )
                db.session.add(new_product)
                new_count += 1
            else:
                if product.base_price != price:
                    product.base_price = price
                    if not product.is_manual_margin:
                        product.sell_price = sell_price_calc
                    update_count += 1
                product.is_active = product_active

    db.session.commit()
    return True, f"Sukses! {new_count} produk baru, {update_count} diperbarui (Prepaid & Pasca)."

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
        return res.json()
    except Exception as e:
        return {"data": {"status": "Gagal", "message": str(e), "rc": "46"}}

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
    """Format nama bank sesuai dokumentasi resmi Digiflazz (Flip/ShopeePay untuk Perorangan, BCA/MANDIRI/BRI/BNI untuk Perusahaan)."""
    b = str(bank).strip()
    if b.lower() == 'shopeepay':
        return 'ShopeePay'
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
            msg = data.get('message', get_rc_message(rc, f"Pembayaran tagihan gagal (RC: {rc})"))
            return False, data, f"RC {rc}: {msg}" if rc else msg
    except Exception as e:
        return False, {}, f"Gagal menghubungi server Digiflazz: {str(e)}"

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

