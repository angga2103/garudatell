# ==============================================================================
# PASCABAYAR SERVICE - KATALOG & SEEDER PRODUK PASCABAYAR NASIONAL
# ==============================================================================
# Menjaga ketersediaan data produk tagihan PPOB (PDAM, BPJS, PLN Pasca, PBB, dll)
# di database lokal secara persisten dan terlindungi dari penghapusan sync pihak ketiga.
# ==============================================================================

import logging
from app.extensions import db
from app.models.product import Product

logger = logging.getLogger(__name__)

PASCABAYAR_CATALOG = [
    # --------------------------------------------------------------------------
    # 1. PDAM JAWA TIMUR
    # --------------------------------------------------------------------------
    {
        'sku_code': 'post685472',
        'name': 'PDAM Kabupaten Kediri',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_kotakediri',
        'name': 'PDAM Kota Kediri',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_surabaya',
        'name': 'PDAM Surya Sembada Kota Surabaya',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_sidoarjo',
        'name': 'PDAM Delta Tirta Kab Sidoarjo',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_malang',
        'name': 'PDAM Kota Malang (Tugu Tirta)',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_kabmalang',
        'name': 'PDAM Kabupaten Malang',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_gresik',
        'name': 'PDAM Giri Tirta Kab Gresik',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_jombang',
        'name': 'PDAM Tirta Kencana Kab Jombang',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_blitar',
        'name': 'PDAM Kota & Kab Blitar',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_tulungagung',
        'name': 'PDAM Tirta Cahya Agung Tulungagung',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_nganjuk',
        'name': 'PDAM Tirta Anjuk Ladang Nganjuk',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_mojokerto',
        'name': 'PDAM Kota & Kab Mojokerto',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_pasuruan',
        'name': 'PDAM Kota & Kab Pasuruan',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_madiun',
        'name': 'PDAM Tirta Asri Kab Madiun',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_banyuwangi',
        'name': 'PDAM Banyuwangi',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_jember',
        'name': 'PDAM Jember',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },

    # --------------------------------------------------------------------------
    # 2. PDAM DKI JAKARTA, JAWA BARAT & BANTEN
    # --------------------------------------------------------------------------
    {
        'sku_code': 'post_pdam_jakarta',
        'name': 'PAM JAYA / AETRA / PALYJA DKI Jakarta',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    },
    {
        'sku_code': 'post_pdam_bandung',
        'name': 'PDAM Tirtawening Kota Bandung',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_kabbandung',
        'name': 'PDAM Tirta Raharja Kab Bandung',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_bekasi',
        'name': 'PDAM Tirta Patriot Kota Bekasi',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_bogor',
        'name': 'PDAM Tirta Kahuripan Kab Bogor',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_depok',
        'name': 'PDAM Tirta Asasta Kota Depok',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_tangerang',
        'name': 'PDAM Tirta Benteng Kota Tangerang',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_tangsel',
        'name': 'PDAM Tangerang Selatan',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },

    # --------------------------------------------------------------------------
    # 3. PDAM JAWA TENGAH, DIY & LUAR JAWA
    # --------------------------------------------------------------------------
    {
        'sku_code': 'post_pdam_semarang',
        'name': 'PDAM Tirta Moedal Kota Semarang',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_solo',
        'name': 'PDAM Toya Wening Kota Solo / Surakarta',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_jogja',
        'name': 'PDAM Tirtamarta Kota Yogyakarta & Sleman',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_pdam_bali',
        'name': 'PDAM Kota Denpasar & Badung Bali',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    },
    {
        'sku_code': 'post_pdam_medan',
        'name': 'PDAM Tirtanadi Sumatera Utara (Medan)',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    },
    {
        'sku_code': 'post_pdam_makassar',
        'name': 'PDAM Kota Makassar',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    },
    {
        'sku_code': 'post_pdam_palembang',
        'name': 'PDAM Tirta Musi Kota Palembang',
        'brand': 'PDAM',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    },

    # --------------------------------------------------------------------------
    # 4. BPJS KESEHATAN & KETENAGAKERJAAN
    # --------------------------------------------------------------------------
    {
        'sku_code': 'post685476',
        'name': 'BPJS Kesehatan',
        'brand': 'BPJS KESEHATAN',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_bpjs_tk',
        'name': 'BPJS Ketenagakerjaan',
        'brand': 'BPJS KETENAGAKERJAAN',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    },
    {
        'sku_code': 'post_bpjs_denda',
        'name': 'BPJS Kesehatan Denda',
        'brand': 'BPJS KESEHATAN',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },

    # --------------------------------------------------------------------------
    # 5. PBB & PAJAK DAERAH
    # --------------------------------------------------------------------------
    {
        'sku_code': 'post685474',
        'name': 'PBB Kabupaten Kediri',
        'brand': 'PBB',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    },
    {
        'sku_code': 'post_pbb_kotakediri',
        'name': 'PBB Kota Kediri',
        'brand': 'PBB',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    },
    {
        'sku_code': 'post_pbb_surabaya',
        'name': 'PBB Kota Surabaya',
        'brand': 'PBB',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    },
    {
        'sku_code': 'post_pbb_sidoarjo',
        'name': 'PBB Kabupaten Sidoarjo',
        'brand': 'PBB',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    },
    {
        'sku_code': 'post_pbb_malang',
        'name': 'PBB Kota & Kab Malang',
        'brand': 'PBB',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    },
    {
        'sku_code': 'post_pbb_dki',
        'name': 'PBB DKI Jakarta',
        'brand': 'PBB',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    },
    {
        'sku_code': 'post_pbb_bandung',
        'name': 'PBB Kota Bandung',
        'brand': 'PBB',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    },
    {
        'sku_code': 'post_pbb_semarang',
        'name': 'PBB Kota Semarang',
        'brand': 'PBB',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    },
    {
        'sku_code': 'post_samsat_jatim',
        'name': 'e-Samsat Pajak Kendaraan Jawa Timur',
        'brand': 'PBB',
        'category': 'Pascabayar',
        'base_price': 3000.0,
        'sell_price': 3500.0
    },

    # --------------------------------------------------------------------------
    # 6. PLN PASCABAYAR & NONTAGLIS
    # --------------------------------------------------------------------------
    {
        'sku_code': 'post685486',
        'name': 'PLN Pascabayar',
        'brand': 'PLN PASCABAYAR',
        'category': 'Pascabayar',
        'base_price': 4000.0,
        'sell_price': 4200.0
    },
    {
        'sku_code': 'post685479',
        'name': 'PLN Nontaglis',
        'brand': 'PLN NONTAGLIS',
        'category': 'Pascabayar',
        'base_price': 4000.0,
        'sell_price': 4200.0
    },

    # --------------------------------------------------------------------------
    # 7. GAS & TELEKOMUNIKASI
    # --------------------------------------------------------------------------
    {
        'sku_code': 'post_gas_pgn',
        'name': 'Gas PGN / Pertagas',
        'brand': 'GAS',
        'category': 'Pascabayar',
        'base_price': 2000.0,
        'sell_price': 2500.0
    },
    {
        'sku_code': 'post_telkom_indihome',
        'name': 'Telkom / Indihome / Speedy',
        'brand': 'TELKOM',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    },

    # --------------------------------------------------------------------------
    # 8. MULTIFINANCE & CICILAN
    # --------------------------------------------------------------------------
    {
        'sku_code': 'post_fif',
        'name': 'FIF Group Multifinance',
        'brand': 'MULTIFINANCE',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    },
    {
        'sku_code': 'post_baf',
        'name': 'BAF (Bussan Auto Finance)',
        'brand': 'MULTIFINANCE',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    },
    {
        'sku_code': 'post_adira',
        'name': 'Adira Finance',
        'brand': 'MULTIFINANCE',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    },
    {
        'sku_code': 'post_wom',
        'name': 'WOM Finance',
        'brand': 'MULTIFINANCE',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    },
    {
        'sku_code': 'post_oto',
        'name': 'OTO Kredit Motor & Mobil',
        'brand': 'MULTIFINANCE',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    },
    {
        'sku_code': 'post_mega',
        'name': 'Mega Auto Finance (MAF)',
        'brand': 'MULTIFINANCE',
        'category': 'Pascabayar',
        'base_price': 2500.0,
        'sell_price': 3000.0
    }
]

# Set of all protected pascabayar brands and SKUs
PASCABAYAR_BRANDS = {
    'PDAM', 'BPJS KESEHATAN', 'BPJS KETENAGAKERJAAN', 'PBB',
    'PLN PASCABAYAR', 'PLN NONTAGLIS', 'GAS', 'TELKOM', 'MULTIFINANCE'
}
PASCABAYAR_SKUS = {item['sku_code'] for item in PASCABAYAR_CATALOG}

def seed_pascabayar_products():
    """
    Menyinkronkan dan memastikan seluruh produk pascabayar nasional tersedia di database.
    Aman dipanggil berulang kali tanpa menduplikasi data.
    """
    inserted = 0
    updated = 0

    try:
        for item in PASCABAYAR_CATALOG:
            sku = item['sku_code']
            prod = Product.query.filter_by(sku_code=sku).first()
            if not prod:
                new_p = Product(
                    sku_code=sku,
                    name=item['name'],
                    category=item['category'],
                    brand=item['brand'],
                    base_price=item['base_price'],
                    sell_price=item['sell_price'],
                    is_active=True,
                    is_manual_margin=False
                )
                db.session.add(new_p)
                inserted += 1
            else:
                # Pastikan produk aktif dan data kategori/brand sesuai
                changed = False
                if not prod.is_active:
                    prod.is_active = True
                    changed = True
                if prod.category != item['category']:
                    prod.category = item['category']
                    changed = True
                if prod.brand != item['brand']:
                    prod.brand = item['brand']
                    changed = True
                if not prod.sell_price or prod.sell_price <= 0:
                    prod.sell_price = item['sell_price']
                    changed = True
                if changed:
                    updated += 1

        db.session.commit()
        logger.info(f"[PASCABAYAR SEEDER] Selesai: {inserted} baru, {updated} diperbarui.")
        return inserted, updated
    except Exception as e:
        db.session.rollback()
        logger.error(f"[PASCABAYAR SEEDER] Gagal melakukan seeding: {e}")
        return 0, 0

def get_or_create_pascabayar_product(sku_code):
    """
    Mencari atau langsung membuat produk pascabayar sesuai katalog jika belum tercatat di database.
    """
    if not sku_code:
        return None
        
    prod = Product.query.filter_by(sku_code=sku_code).first()
    if prod:
        return prod

    # Cari di katalog statis
    item = next((x for x in PASCABAYAR_CATALOG if x['sku_code'] == sku_code), None)
    if not item:
        # Fallback pencocokan SKU standar
        sku_clean = str(sku_code).lower()
        if 'pdam' in sku_clean or sku_code == 'post685472':
            item = PASCABAYAR_CATALOG[0]
        elif 'bpjs' in sku_clean or sku_code == 'post685476':
            item = next(x for x in PASCABAYAR_CATALOG if x['sku_code'] == 'post685476')
        elif 'pln' in sku_clean or sku_code == 'post685486':
            item = next(x for x in PASCABAYAR_CATALOG if x['sku_code'] == 'post685486')
        elif 'pbb' in sku_clean or sku_code == 'post685474':
            item = next(x for x in PASCABAYAR_CATALOG if x['sku_code'] == 'post685474')

    if item:
        try:
            prod = Product(
                sku_code=item['sku_code'],
                name=item['name'],
                category=item['category'],
                brand=item['brand'],
                base_price=item['base_price'],
                sell_price=item['sell_price'],
                is_active=True,
                is_manual_margin=False
            )
            db.session.add(prod)
            db.session.commit()
            return prod
        except Exception as e:
            db.session.rollback()
            logger.error(f"[PASCABAYAR] Gagal auto-create produk {sku_code}: {e}")
            return None

    return None
