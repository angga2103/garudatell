# ==============================================================================
# PRICING SERVICE - MESIN PENETAPAN HARGA OTOMATIS & MARGIN CERDAS
# ==============================================================================
# Mengimplementasikan:
# 1. Aturan Margin Khusus Kategori (Pulsa, Token PLN, Data, E-Wallet, Game, Pascabayar)
# 2. Auto-Tier 5 Level sebagai Default Fallback
# 3. Safety Guard Anti-Rugi untuk Produk Kunci Manual (Anti-Jebakan Modal Naik)
# ==============================================================================

import logging
from app.models.margin import MarginTier

logger = logging.getLogger(__name__)

# Margin Fallback Default jika tidak terdefinisi di database
DEFAULT_TIER_RULES = [
    {'level': 1, 'min_price': 0.0, 'max_price': 12000.0, 'margin': 400.0},
    {'level': 2, 'min_price': 12000.01, 'max_price': 50000.0, 'margin': 700.0},
    {'level': 3, 'min_price': 50000.01, 'max_price': 100000.0, 'margin': 1100.0},
    {'level': 4, 'min_price': 100000.01, 'max_price': 500000.0, 'margin': 1800.0},
    {'level': 5, 'min_price': 500000.01, 'max_price': 99999999.0, 'margin': 3000.0},
]


def calculate_smart_price(product_or_dict, tiers=None):
    """
    Menghitung harga jual cerdas dan optimal untuk iPay.my.id.
    Menerapkan hirarki cerdas:
    1. Kategori Pascabayar (Tagihan PDAM, PLN Pasca, BPJS, Multi, PBB) -> Margin Rp 1.500, Min Admin Rp 3.500
    2. Token PLN Prabayar -> Margin Flat Rp 250 (daya saing maksimal konter)
    3. Pulsa Reguler -> Margin Rp 250 / 450 / 750 (menjaga volume & traffic konter)
    4. Paket Data -> Margin Rp 600 / 1.000 / 1.500 (margin sehat)
    5. E-Wallet -> Margin Rp 400 / 700 / 1.200 (sangat kompetitif vs minimarket)
    6. Games -> Margin Rp 500 / 1.000 / 2.000 (margin tebal produk hiburan)
    7. Default Fallback -> Mengikuti 5 Level Auto-Tier Umum
    """
    if hasattr(product_or_dict, 'base_price'):
        base = float(product_or_dict.base_price or 0.0)
        category = str(product_or_dict.category or '')
        brand = str(product_or_dict.brand or '')
        name = str(product_or_dict.name or '')
        sku = str(product_or_dict.sku_code or '')
    elif isinstance(product_or_dict, dict):
        base = float(product_or_dict.get('base_price') or product_or_dict.get('price') or 0.0)
        category = str(product_or_dict.get('category') or '')
        brand = str(product_or_dict.get('brand') or '')
        name = str(product_or_dict.get('name') or product_or_dict.get('product_name') or '')
        sku = str(product_or_dict.get('sku_code') or product_or_dict.get('code') or '')
    else:
        base = float(product_or_dict or 0.0)
        category, brand, name, sku = '', '', '', ''

    if base <= 0:
        return 0.0

    cat_l = category.lower().strip()
    brand_l = brand.lower().strip()
    name_l = name.lower().strip()
    sku_l = sku.lower().strip()

    # --------------------------------------------------------------------------
    # 1. PASCABAYAR (PDAM, PLN Pasca, BPJS, Multifinance, PBB, Gas, Telkom)
    # --------------------------------------------------------------------------
    # Pada pascabayar, base_price adalah biaya admin provider (misal Rp 2.000 - Rp 2.500).
    # Margin Rp 1.500 dengan floor biaya admin minimal Rp 3.500 melindungi server
    # dari defisit biaya pembayaran QRIS MDR 0.7% pada tagihan besar.
    if ('pascabayar' in cat_l or 'tagihan' in cat_l or sku_l.startswith('post') or
            'pdam' in brand_l or 'bpjs' in brand_l or 'multifinance' in brand_l):
        return round(max(3500.0, base + 1500.0), 2)

    # --------------------------------------------------------------------------
    # 2. TOKEN PLN (Prabayar)
    # --------------------------------------------------------------------------
    # Margin flat Rp 250 untuk semua nominal (20k, 50k, 100k, 200k, 500k, 1jt)
    # Konter sangat sensitif pada token PLN; harga mepet nominal adalah kunci loyalitas.
    if ('pln' in cat_l or 'pln' in brand_l or ('token' in name_l and 'pln' in name_l)):
        return round(base + 250.0, 2)

    # --------------------------------------------------------------------------
    # 3. PULSA REGULER
    # --------------------------------------------------------------------------
    if ('pulsa' in cat_l and 'data' not in cat_l and 'kuota' not in cat_l and 'paket' not in cat_l):
        if base <= 12000.0:
            return round(base + 250.0, 2)
        elif base <= 50000.0:
            return round(base + 450.0, 2)
        else:
            return round(base + 750.0, 2)

    # --------------------------------------------------------------------------
    # 4. PAKET DATA / INTERNET
    # --------------------------------------------------------------------------
    if ('data' in cat_l or 'kuota' in cat_l or 'internet' in cat_l or
            'data' in name_l or 'kuota' in name_l or 'paket internet' in name_l):
        if base <= 25000.0:
            return round(base + 600.0, 2)
        elif base <= 75000.0:
            return round(base + 1000.0, 2)
        else:
            return round(base + 1500.0, 2)

    # --------------------------------------------------------------------------
    # 5. E-WALLET / E-MONEY
    # --------------------------------------------------------------------------
    if ('emoney' in cat_l or 'e-money' in cat_l or 'wallet' in cat_l or
            any(w in brand_l for w in ['dana', 'gopay', 'ovo', 'shopeepay', 'linkaja', 'kaspro'])):
        if base <= 25000.0:
            return round(base + 400.0, 2)
        elif base <= 100000.0:
            return round(base + 700.0, 2)
        else:
            return round(base + 1200.0, 2)

    # --------------------------------------------------------------------------
    # 6. GAMES & VOUCHER
    # --------------------------------------------------------------------------
    if ('game' in cat_l or 'voucher' in cat_l or
            any(w in brand_l for w in ['free fire', 'mobile legends', 'mlbb', 'pubg', 'genshin', 'roblox', 'valorant', 'honkai'])):
        if base <= 25000.0:
            return round(base + 500.0, 2)
        elif base <= 100000.0:
            return round(base + 1000.0, 2)
        else:
            return round(base + 2000.0, 2)

    # --------------------------------------------------------------------------
    # 7. DEFAULT / FALLBACK (Auto-Tier Umum)
    # --------------------------------------------------------------------------
    if tiers:
        for t in tiers:
            # Gunakan toleransi batas kontinu untuk mencegah celah pecahan desimal
            t_min = float(t.min_price or 0.0)
            t_max = float(t.max_price or 99999999.0)
            t_margin = float(t.margin or 0.0)
            if t_min <= base <= t_max or (base >= t_min and t_max >= 99000000.0):
                return round(base + t_margin, 2)

    # Fallback default hardcoded jika tabel margin_tiers kosong
    if base <= 12000.0:
        return round(base + 400.0, 2)
    elif base <= 50000.0:
        return round(base + 700.0, 2)
    elif base <= 100000.0:
        return round(base + 1100.0, 2)
    elif base <= 500000.0:
        return round(base + 1800.0, 2)
    else:
        return round(base + 3000.0, 2)


def enforce_manual_price_safety_guard(product, new_base_price):
    """
    SAFETY GUARD ANTI-RUGI UNTUK PRODUK KUNCI MANUAL:
    Memeriksa apakah kenaikan harga modal baru dari provider melampaui harga jual manual.
    Jika modal > harga jual:
    - Otomatis menaikkan harga jual menjadi (modal baru + Rp 100) sebagai Safety Floor.
    - Mengembalikan True dan pesan peringatan untuk dikirim ke bot / log.
    Jika modal <= harga jual:
    - Mempertahankan harga jual manual apa adanya (Aman).
    """
    if not product or not getattr(product, 'is_manual_margin', False):
        return False, None

    new_base = float(new_base_price or 0.0)
    current_sell = float(product.sell_price or 0.0)

    if new_base > current_sell:
        old_sell = current_sell
        safety_sell = round(new_base + 100.0, 2)
        product.sell_price = safety_sell
        msg = (
            f"⚠️ [SAFETY GUARD ALERT] SKU '{product.sku_code}' ({product.name}) terkunci manual di Rp {old_sell:,.0f}, "
            f"namun harga modal Digiflazz naik menjadi Rp {new_base:,.0f}! "
            f"Sistem otomatis menaikkan harga jual ke Safety Floor Rp {safety_sell:,.0f} demi mencegah transaksi rugi."
        )
        logger.warning(msg)
        return True, msg

    return False, None
