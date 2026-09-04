import requests
import hashlib
import os
from app.extensions import db
from app.models.product import Product

def clean_str(val):
    if not val: return ''
    return str(val).replace("'", "").replace('"', '').strip(" \t\n\r")

from app.models.margin import MarginTier

def calculate_sell_price(base_price, tiers):
    """Hitung harga jual dinamis berdasarkan tabel MarginTier."""
    if not tiers:
        return base_price + 500
    for t in tiers:
        if t.min_price <= base_price <= t.max_price:
            return base_price + t.margin
    return base_price + tiers[-1].margin

def sync_products():
    url = clean_str(os.getenv('DIGI_URL', 'https://api.digiflazz.com/v1')) + '/price-list'
    username = clean_str(os.getenv('DIGI_USER'))
    key = clean_str(os.getenv('DIGI_KEY'))

    if not username or not key:
        return False, "Gagal: Username atau API Key Digiflazz belum diatur di .env!"

    # Ambil tabel MarginTier terurut dari level terendah ke tertinggi
    tiers = MarginTier.query.order_by(MarginTier.level.asc()).all()

    new_count = 0
    update_count = 0
    sign = hashlib.md5(f"{username}{key}pricelist".encode()).hexdigest()
    cmds = ["prepaid", "pasca"]

    for cmd in cmds:
        payload = {"cmd": cmd, "username": username, "sign": sign}
        try:
            response = requests.post(url, json=payload, timeout=12).json()
            if 'data' in response and isinstance(response['data'], list):
                for item in response['data']:
                    sku = item.get('buyer_sku_code')
                    if not sku: continue
                        
                    product = Product.query.filter_by(sku_code=sku).first()
                    product_active = item.get('buyer_product_status', True)
                    price = item.get('price', item.get('admin', 0))
                    sell_price_calc = calculate_sell_price(price, tiers)

                    if not product:
                        new_product = Product(
                            sku_code=sku, name=item['product_name'], category=item.get('category', 'Umum'),
                            brand=item.get('brand', 'Umum'), base_price=price, sell_price=sell_price_calc,
                            is_active=product_active, is_manual_margin=False
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
            else:
                error_msg = response.get('data', {}).get('message', 'Respons tidak valid dari server')
                return False, f"Digiflazz menolak ({cmd}): {error_msg}"
                
        except Exception as e:
            return False, f"Terjadi kesalahan sistem ({cmd}): {str(e)}"

    db.session.commit()
    return True, f"Sukses! {new_count} produk baru, {update_count} diperbarui (Prepaid & Pasca)."

def create_transaction(sku, tujuan, ref_id):
    import os, hashlib, requests
    username = os.getenv('DIGI_USER', '').strip()
    key = os.getenv('DIGI_KEY', '').strip()
    url = os.getenv('DIGI_URL', 'https://api.digiflazz.com/v1').strip() + '/transaction'
    sign = hashlib.md5(f"{username}{key}{ref_id}".encode()).hexdigest()
    payload = {"username": username, "buyer_sku_code": sku, "customer_no": str(tujuan), "ref_id": str(ref_id), "sign": sign}
    try:
        return requests.post(url, json=payload, timeout=20).json()
    except Exception as e:
        return {"data": {"status": "Gagal", "message": str(e)}}

def check_balance():
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
        data = res_json.get('data', {})
        if 'deposit' in data:
            return True, float(data['deposit']), "Berhasil mengambil saldo Digiflazz"
        else:
            msg = data.get('message', 'Gagal membaca respon saldo Digiflazz')
            return False, 0.0, msg
    except Exception as e:
        return False, 0.0, f"Gagal menghubungi server Digiflazz: {str(e)}"

def request_deposit(amount, bank, owner_name):
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

    sign = hashlib.md5(f"{username}{key}deposit".encode()).hexdigest()
    payload = {
        "username": username,
        "amount": amount_int,
        "Bank": str(bank).upper(),
        "owner_name": str(owner_name).strip(),
        "sign": sign
    }

    try:
        res = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=20)
        res_json = res.json()
        data = res_json.get('data', {})
        rc = data.get('rc')
        if rc == '00' or ('amount' in data and data.get('amount', 0) > 0):
            return True, data, "Tiket deposit berhasil dibuat!"
        else:
            msg = data.get('message', f"Digiflazz error (RC: {rc})")
            return False, data, msg
    except Exception as e:
        return False, {}, f"Gagal menghubungi server Digiflazz: {str(e)}"

