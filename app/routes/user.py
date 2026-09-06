from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_required, current_user
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from app.models.product import Product
from app.extensions import db, csrf, limiter
from sqlalchemy import or_
import os

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

user_bp = Blueprint('user', __name__)

def get_user_notifications(user_id=None):
    from app.models.notification import Notification, NotificationRead
    if user_id:
        notifs = Notification.query.filter(
            or_(Notification.target_user_id == None, Notification.target_user_id == user_id)
        ).order_by(Notification.created_at.desc()).limit(25).all()
        read_ids = {r.notification_id for r in NotificationRead.query.filter_by(user_id=user_id).all()}
        unread_count = sum(1 for n in notifs if n.id not in read_ids)
        return notifs, unread_count, read_ids
    else:
        notifs = Notification.query.filter(
            Notification.target_user_id == None
        ).order_by(Notification.created_at.desc()).limit(25).all()
        return notifs, len(notifs), set()

@user_bp.route('/')
@user_bp.route('/dashboard')
def dashboard():
    raw_categories = db.session.query(Product.category).filter(Product.is_active==True).distinct().all()
    categories = [c[0] for c in raw_categories if c[0]]
    kategori_utama = [c for c in categories if c in ['Pulsa', 'Data', 'E-Money', 'PLN', 'Games']]
    kategori_lainnya = [c for c in categories if c not in kategori_utama]
    if not kategori_utama:
        kategori_utama = categories[:6]
        kategori_lainnya = categories[6:]

    user_id = current_user.id if current_user.is_authenticated else None
    notifications, unread_notif_count, read_ids = get_user_notifications(user_id)

    recent_transactions = []
    if current_user.is_authenticated:
        from app.models.transaction import Transaction
        recent_transactions = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.created_at.desc()).limit(15).all()

    return render_template('user/dashboard.html',
                           kategori_utama=kategori_utama,
                           kategori_lainnya=kategori_lainnya,
                           notifications=notifications,
                           unread_notif_count=unread_notif_count,
                           read_ids=read_ids,
                           recent_transactions=recent_transactions)

@user_bp.route('/login')
def login():
    """Arahkan akses /login langsung ke halaman profil & autentikasi pengguna."""
    if current_user.is_authenticated:
        return redirect(url_for('user.dashboard'))
    return redirect(url_for('user.profil'))

@user_bp.route('/register')
def register():
    """Arahkan akses /register langsung ke form pendaftaran di profil."""
    if current_user.is_authenticated:
        return redirect(url_for('user.dashboard'))
    return redirect('/profil?action=register')


# ==========================================
# RUTE KATEGORI (REWRITE - BERSIH & PRESISI)
# ==========================================
@user_bp.route('/kategori/tv')
def kategori_tv_index():
    kondisi_tv = (
        (
            Product.category.ilike('%tv%') | 
            Product.category.ilike('%parabola%') |
            Product.brand.ilike('%k-vision%') | 
            Product.brand.ilike('%kvision%') |
            Product.brand.ilike('%nex parabola%') | 
            Product.brand.ilike('%transvision%') | 
            Product.brand.ilike('%matrix%') | 
            Product.brand.ilike('%tanaka%') | 
            Product.brand.ilike('%orange tv%') |
            Product.brand.ilike('%vision plus%') |
            Product.brand.ilike('%wetv%')
        ) &
        ~Product.category.ilike('%game%') &
        ~Product.brand.ilike('%razer%') &
        ~Product.name.ilike('%ragnarok%')
    )
    
    db_products = Product.query.filter(kondisi_tv, Product.is_active == True).order_by(Product.sell_price.asc()).all()
    
    produk_final = []
    for prod in db_products:
        b = (prod.brand or '').replace('VIP-', '').strip().upper()
        if 'K-VISION' in b or 'KVISION' in b or 'GOL' in b:
            tag = 'K-VISION'
        elif 'NEX' in b:
            tag = 'NEX PARABOLA'
        elif 'TRANS' in b:
            tag = 'TRANSVISION'
        elif 'MATRIX' in b:
            tag = 'MATRIX'
        elif 'TANAKA' in b:
            tag = 'TANAKA'
        elif 'ORANGE' in b:
            tag = 'ORANGE TV'
        elif 'VISION' in b:
            tag = 'VISION+'
        elif 'WETV' in b:
            tag = 'WETV'
        else:
            tag = b if b else 'TV'

        produk_final.append({
            'kode_produk': prod.sku_code,
            'sku_code': prod.sku_code,
            'nama_produk': prod.name,
            'name': prod.name,
            'harga': prod.sell_price,
            'sell_price': prod.sell_price,
            'provider': tag,
            'brand': b,
            'is_active': prod.is_active
        })
        
    return render_template('user/tv_index.html', products=produk_final, title='TV BERLANGGANAN')

@user_bp.route('/kategori/tv/<provider_id>')
def kategori_tv_detail(provider_id):
    from flask import redirect
    return redirect('/kategori/tv')

@user_bp.route('/kategori/<path:nama_kategori>')
def lihat_kategori(nama_kategori):
    kat = nama_kategori.lower().strip()
    
    # 1. Konfigurasi Template & Keyword Pencarian Database
    template_name = 'user/kategori.html'
    keywords = [kat]
    title = nama_kategori.upper()
    
    if kat == 'pulsa':
        db_products = Product.query.filter(
            Product.category.ilike('%pulsa%'),
            Product.is_active == True
        ).order_by(Product.sell_price.asc()).all()
        produk_final = []
        for prod in db_products:
            brand_clean = (prod.brand or '').replace('VIP-', '').strip().upper()
            if brand_clean == 'BY.U': brand_clean = 'BYU'
            produk_final.append({
                'kode_produk': prod.sku_code,
                'sku_code': prod.sku_code,
                'nama_produk': prod.name,
                'name': prod.name,
                'harga': prod.sell_price,
                'sell_price': prod.sell_price,
                'provider': brand_clean,
                'is_active': prod.is_active
            })
        return render_template('user/pulsa.html', products=produk_final, title='PULSA')

    elif kat == 'data':
        keywords = ['data', 'kuota', 'paket', 'internet', 'inject', 'internetmax']
        filters = [Product.category.ilike(f'%{kw}%') for kw in keywords]
        db_products = Product.query.filter(
            or_(*filters),
            Product.is_active == True
        ).order_by(Product.sell_price.asc()).all()
        produk_final = []
        for prod in db_products:
            brand_clean = (prod.brand or '').replace('VIP-', '').strip().upper()
            if brand_clean == 'BY.U': brand_clean = 'BYU'
            produk_final.append({
                'kode_produk': prod.sku_code,
                'sku_code': prod.sku_code,
                'nama_produk': prod.name,
                'name': prod.name,
                'harga': prod.sell_price,
                'sell_price': prod.sell_price,
                'provider': brand_clean,
                'is_active': prod.is_active
            })
        return render_template('user/data.html', products=produk_final, title='PAKET DATA')

    elif kat in ['tv', 'tv-berlangganan', 'tv berlangganan']:
        return kategori_tv_index()
    elif kat in ['games', 'voucher game', 'game', 'hiburan', 'voucher-game', 'streaming']:
        from app.models.product import Product as MProduct
        from flask import render_template as m_render, request
        
        # Kondisi dasar: Produk game & voucher VIP-Reseller
        kondisi_games = (
            (MProduct.category.ilike('%game%') | MProduct.category.ilike('%voucher%')) &
            MProduct.brand.ilike('VIP-%') &
            (MProduct.is_active == True)
        )
        
        # Ambil daftar unik seluruh 99 game brand untuk selector dropdown
        all_game_brands = [
            b[0].replace('VIP-', '').strip() 
            for b in MProduct.query.with_entities(MProduct.brand).filter(kondisi_games).distinct().order_by(MProduct.brand.asc()).all()
            if b[0]
        ]
        
        # Tangkap filter dari URL (default: ML / Mobile Legends)
        active_game = request.args.get('game', '').upper().strip()
        active_brand = request.args.get('brand', '').strip()
        search_query = request.args.get('search', '').strip()
        
        # Mapping preset game populer
        preset_map = {
            'ML': {'name': 'Mobile Legends', 'keywords': ['mobile legends'], 'dual': True},
            'FF': {'name': 'Free Fire', 'keywords': ['free fire'], 'dual': False},
            'PUBG': {'name': 'PUBG Mobile', 'keywords': ['pubg'], 'dual': False},
            'VALORANT': {'name': 'Valorant', 'keywords': ['valorant'], 'dual': False},
            'HOK': {'name': 'Honor of Kings', 'keywords': ['honor of kings'], 'dual': False},
            'STEAM': {'name': 'Steam Wallet', 'keywords': ['steam'], 'dual': False},
            'GENSHIN': {'name': 'Genshin / Honkai', 'keywords': ['genshin', 'honkai'], 'dual': True},
            'ROBLOX': {'name': 'Roblox / Garena', 'keywords': ['roblox', 'garena', 'undawn'], 'dual': False},
            'CODM': {'name': 'Call of Duty', 'keywords': ['call of duty', 'codm'], 'dual': False},
            'AOV': {'name': 'Arena of Valor', 'keywords': ['arena of valor', 'aov'], 'dual': False},
            'POINTBLANK': {'name': 'Point Blank', 'keywords': ['point blank', 'pb'], 'dual': False},
            'RAGNAROK': {'name': 'Ragnarok X', 'keywords': ['ragnarok'], 'dual': True},
            'BLOODSTRIKE': {'name': 'Blood Strike', 'keywords': ['blood strike'], 'dual': False},
            'METALSLUG': {'name': 'Metal Slug', 'keywords': ['metal slug'], 'dual': False},
            'UNDAWN': {'name': 'Undawn', 'keywords': ['undawn'], 'dual': False},
        }
        
        if not active_game and not active_brand and not search_query:
            active_game = 'ML' # Default Mobile Legends agar halaman super cepat dimuat
            
        base_query = MProduct.query.filter(kondisi_games)
        is_dual_input = False
        
        if active_brand:
            base_query = base_query.filter(MProduct.brand.ilike(f'%{active_brand}%'))
            if 'mobile legends' in active_brand.lower() or 'genshin' in active_brand.lower():
                is_dual_input = True
        elif active_game in preset_map:
            kw_filters = [MProduct.brand.ilike(f'%{kw}%') for kw in preset_map[active_game]['keywords']]
            base_query = base_query.filter(or_(*kw_filters))
            is_dual_input = preset_map[active_game]['dual']
        elif active_game == 'ALL':
            is_dual_input = False
        else:
            active_game = 'ML'
            base_query = base_query.filter(MProduct.brand.ilike('%mobile legends%'))
            is_dual_input = True

        if search_query:
            base_query = base_query.filter(
                MProduct.name.ilike(f'%{search_query}%') | MProduct.brand.ilike(f'%{search_query}%')
            )
            
        db_products = base_query.order_by(MProduct.sell_price.asc()).all()
        
        produk_final = []
        for prod in db_products:
            brand_clean = (prod.brand or '').replace('VIP-', '').strip().upper()
            produk_final.append({
                'kode_produk': prod.sku_code,
                'sku_code': prod.sku_code,
                'nama_produk': prod.name,
                'name': prod.name,
                'harga': prod.sell_price,
                'sell_price': prod.sell_price,
                'provider': brand_clean,
                'brand': brand_clean,
                'is_active': prod.is_active
            })
            
        return m_render('user/games.html', 
            products=produk_final,
            all_brands=all_game_brands,
            active_game=active_game,
            active_brand=active_brand,
            is_dual_input=is_dual_input,
            title='VOUCHER & TOP UP GAME',
            search_query=search_query
        )
        
    elif kat in ['emoney', 'e-money', 'e-wallet']:
        kondisi_emoney = (
            (
                Product.category.ilike('%e-money%') |
                Product.category.ilike('%emoney%') |
                Product.category.ilike('%wallet%') |
                Product.brand.in_(['DANA', 'OVO', 'SHOPEE PAY', 'GO PAY', 'E-MONEY', 'LINKAJA']) |
                Product.name.ilike('DANA %') |
                Product.name.ilike('% DANA %') |
                Product.name.ilike('%gopay%') |
                Product.name.ilike('%go pay%') |
                Product.name.ilike('%ovo%') |
                Product.name.ilike('%shopee%') |
                Product.name.ilike('%linkaja%')
            ) &
            ~Product.name.ilike('%perdana%') &
            ~Product.category.ilike('%perdana%')
        )
        db_products = Product.query.filter(
            kondisi_emoney,
            Product.is_active == True
        ).order_by(Product.sell_price.asc()).all()

        produk_final = []
        for prod in db_products:
            name_upper = (prod.name or '').upper()
            brand_upper = (prod.brand or '').replace('VIP-', '').strip().upper()
            
            if 'DANA' in brand_upper or 'DANA' in name_upper:
                provider_tag = 'DANA'
            elif 'GO PAY' in brand_upper or 'GOPAY' in brand_upper or 'GOPAY' in name_upper or 'GO PAY' in name_upper:
                provider_tag = 'GOPAY'
            elif 'OVO' in brand_upper or 'OVO' in name_upper:
                provider_tag = 'OVO'
            elif 'SHOPEE' in brand_upper or 'SHOPEE' in name_upper:
                provider_tag = 'SHOPEEPAY'
            elif 'LINKAJA' in brand_upper or 'LINKAJA' in name_upper:
                provider_tag = 'LINKAJA'
            else:
                provider_tag = brand_upper if brand_upper else 'E-MONEY'

            is_bebas = 'BEBAS' in name_upper
            sub_tag = 'Bebas Nominal' if is_bebas else 'Top Up'

            produk_final.append({
                'kode_produk': prod.sku_code,
                'sku_code': prod.sku_code,
                'nama_produk': prod.name,
                'name': prod.name,
                'harga': prod.sell_price,
                'sell_price': prod.sell_price,
                'provider': provider_tag,
                'sub_tag': sub_tag,
                'is_bebas': is_bebas,
                'brand': brand_upper,
                'is_active': prod.is_active
            })

        return render_template('user/emoney.html', products=produk_final, title='E-WALLET & E-MONEY')

    elif kat in ['pln', 'token pln', 'token-pln']:
        kondisi_pln = (
            Product.category.ilike('%pln%') |
            Product.category.ilike('%listrik%') |
            Product.name.ilike('%pln%')
        )
        db_products = Product.query.filter(
            kondisi_pln,
            Product.is_active == True
        ).order_by(Product.sell_price.asc()).all()
        produk_final = []
        for prod in db_products:
            brand_clean = (prod.brand or '').replace('VIP-', '').strip().upper()
            is_pasca = 'PASCA' in (prod.name or '').upper() or 'NONTAGLIS' in (prod.name or '').upper() or 'PASCA' in brand_clean
            kategori_tag = 'PASCABAYAR' if is_pasca else 'PRABAYAR'
            produk_final.append({
                'kode_produk': prod.sku_code,
                'sku_code': prod.sku_code,
                'nama_produk': prod.name,
                'name': prod.name,
                'harga': prod.sell_price,
                'sell_price': prod.sell_price,
                'provider': kategori_tag,
                'brand': brand_clean,
                'is_active': prod.is_active
            })
        from app.services.digiflazz import is_pln_cutoff_time
        return render_template('user/pln.html', products=produk_final, title='TOKEN PLN', is_cutoff=is_pln_cutoff_time())
        
    elif kat in ['telpsms', 'telp-sms', 'telp & sms']:
        keywords = ['telp', 'sms']
        filters = [Product.category.ilike(f'%{kw}%') for kw in keywords]
        db_products = Product.query.filter(
            or_(*filters),
            Product.is_active == True
        ).order_by(Product.sell_price.asc()).all()
        produk_final = []
        for prod in db_products:
            brand_clean = (prod.brand or '').replace('VIP-', '').strip().upper()
            produk_final.append({
                'kode_produk': prod.sku_code,
                'sku_code': prod.sku_code,
                'nama_produk': prod.name,
                'name': prod.name,
                'harga': prod.sell_price,
                'sell_price': prod.sell_price,
                'provider': brand_clean,
                'is_active': prod.is_active
            })
        return render_template('user/telpsms.html', products=produk_final, title='TELP & SMS')

    elif kat in ['masaaktif', 'masa aktif', 'masa-aktif']:
        kondisi_masaaktif = (
            Product.category.ilike('%masa aktif%') |
            (Product.name.ilike('%masa%') & Product.name.ilike('%aktif%'))
        )
        db_products = Product.query.filter(kondisi_masaaktif, Product.is_active == True).order_by(Product.sell_price.asc()).all()
        produk_final = []
        for prod in db_products:
            brand_clean = (prod.brand or '').replace('VIP-', '').strip().upper()
            produk_final.append({
                'kode_produk': prod.sku_code,
                'sku_code': prod.sku_code,
                'nama_produk': prod.name,
                'name': prod.name,
                'harga': prod.sell_price,
                'sell_price': prod.sell_price,
                'provider': brand_clean,
                'is_active': prod.is_active
            })
        return render_template('user/masaaktif.html', products=produk_final, title='MASA AKTIF')
        
    # 2. Tarik Data Database secara Presisi (Sesuai kolom app/models/product.py Anda)
    filters = [Product.category.ilike(f'%{kw}%') for kw in keywords]
    
    # Perbaikan Filter Mutlak: Jauhkan produk TV dari halaman Games
    base_query = Product.query.filter(or_(*filters), Product.is_active == True)
    
    if kat in ['games', 'voucher game', 'game', 'hiburan', 'voucher-game']:
        # Tolak semua produk yang kategori atau namanya mengandung unsur TV Berlangganan
        base_query = base_query.filter(
            ~Product.category.ilike('%tv%'),
            ~Product.category.ilike('%streaming%'),
            ~Product.brand.ilike('%vision%'),
            ~Product.brand.ilike('%nex%'),
            ~Product.brand.ilike('%parabola%')
        )
        
    db_products = base_query.all()
    
    # 3. Format Data untuk UI (Menerjemahkan Database ke Bahasa UI)
    produk_final = []
    for prod in db_products:
        produk_final.append({
            'kode_produk': prod.sku_code,
            'nama_produk': prod.name,
            'harga': prod.sell_price,
            'provider': prod.brand
        })
        
    # 4. Urutkan berdasarkan harga termurah
    produk_final.sort(key=lambda x: x['harga'])
        
    return render_template(template_name, products=produk_final, title=title)


# =====================================================================
# RUTE RIWAYAT (DITAMBAHKAN SECARA AMAN)
# =====================================================================
@user_bp.route('/riwayat')
def riwayat():
    try:
        from app.models.transaction import Transaction
        from flask_login import current_user
        from flask import render_template, request
        from datetime import datetime
        
        if not current_user.is_authenticated:
            return render_template('user/riwayat.html', transactions=[], count_sukses=0, count_antri=0, count_proses=0, count_gagal=0, title='Riwayat (Harap Login)')
            
        query = Transaction.query.filter_by(user_id=current_user.id)
        
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        if start_date:
            try:
                sd = datetime.strptime(start_date, '%Y-%m-%d')
                query = query.filter(Transaction.created_at >= sd)
            except: pass
            
        if end_date:
            try:
                ed = datetime.strptime(end_date + ' 23:59:59', '%Y-%m-%d %H:%M:%S')
                query = query.filter(Transaction.created_at <= ed)
            except: pass

        # AUTO-SYNC: Cek status terkini transaksi aktif yang masih PROCESSING ke provider (Digiflazz/VIP)
        try:
            from app.routes.transaction import sync_single_transaction
            pending_trxs = Transaction.query.filter(
                Transaction.user_id == current_user.id,
                Transaction.status.in_(['PROCESSING', 'PENDING', 'PROSES']),
                Transaction.payment_status == 'PAID'
            ).order_by(Transaction.created_at.desc()).limit(3).all()

            for pt in pending_trxs:
                sync_single_transaction(pt)
        except Exception as sync_err:
            print(f"[AUTO-SYNC RIWAYAT WARNING]: {sync_err}")

        transactions = query.order_by(Transaction.created_at.desc()).all()
        
        count_sukses = sum(1 for t in transactions if getattr(t, 'status', '') == 'SUCCESS')
        count_antri = sum(1 for t in transactions if getattr(t, 'status', '') in ['PENDING', 'UNPAID'])
        count_proses = sum(1 for t in transactions if getattr(t, 'status', '') == 'PROCESSING')
        count_gagal = sum(1 for t in transactions if getattr(t, 'status', '') in ['FAILED', 'CANCELLED'])
        
        return render_template('user/riwayat.html',
                               transactions=transactions,
                               count_sukses=count_sukses,
                               count_antri=count_antri,
                               count_proses=count_proses,
                               count_gagal=count_gagal,
                               title='Riwayat Transaksi')
    except Exception as e:
        import traceback
        return f"<h3>🚨 ERROR RIWAYAT:</h3><p>{str(e)}</p><pre>{traceback.format_exc()}</pre>", 500




# =====================================================================
# RUTE PROFIL & LOGIN WHATSAPP (SIAP UNTUK BOT OTP)
# =====================================================================
@user_bp.route('/profil', methods=['GET', 'POST'])
@csrf.exempt
def profil():
    from app.models.user import User
    from flask_login import login_user, logout_user, current_user
    from flask import render_template, request, redirect, url_for, flash
    from werkzeug.security import generate_password_hash, check_password_hash
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        # LOGIKA LOGOUT
        if action == 'logout':
            logout_user()
            flash('Anda telah berhasil keluar.', 'success')
            return redirect(url_for('user.dashboard'))
            
        # LOGIKA LOGIN (Via Password)
        elif action == 'login':
            identifier = request.form.get('username') # Bisa diisi Username atau No WA
            password = request.form.get('password')
            
            # Cari berdasarkan username
            user = User.query.filter_by(name=identifier).first()
            
            # Jika tidak ketemu, cari berdasarkan nama atau nomor WA
            if not user:
                if hasattr(User, 'name'):
                    user = User.query.filter_by(name=identifier).first()
                if not user and hasattr(User, 'phone'):
                    user = User.query.filter_by(phone=identifier).first()
                    
            if user:
                # Validasi Password (Mendukung hash atau plain text sementara)
                password_match = False
                try:
                    if hasattr(user, 'check_password'):
                        password_match = user.check_password(password)
                    elif hasattr(user, 'password_hash'):
                        password_match = check_password_hash(user.password_hash, password)
                    elif hasattr(user, 'password'):
                        # Jika password belum di hash di database lama
                        password_match = check_password_hash(user.password, password) if user.password.startswith('pbkdf2') else (user.password == password)
                except:
                    # Fallback darurat
                    password_match = (getattr(user, 'password', '') == password)

                if password_match:
                    login_user(user, remember=True)
                    flash('Berhasil masuk! Selamat datang kembali.', 'success')
                    return redirect(url_for('user.profil'))
                else:
                    flash('Gagal! Password yang Anda masukkan salah.', 'danger')
            else:
                flash('Gagal! Akun tidak ditemukan di sistem.', 'danger')
                
        # LOGIKA PENDAFTARAN OTP (SUNTIKAN ANTI-PATAH)
        elif action == 'request_otp_baru':
            from flask import jsonify
            from app.models.user import User
            from app.wa_helper import kirim_wa_otp
            from app.services.otp_service import create_otp
            
            new_username = request.form.get('new_username')
            new_whatsapp = request.form.get('new_whatsapp')
            new_password = request.form.get('new_password')
            
            if not new_username or not new_whatsapp or not new_password:
                return jsonify({'status': 'error', 'message': 'Semua field wajib diisi.'})

            # Cek apakah username / WA sudah dipakai
            cek_user = None
            if hasattr(User, 'username'):
                cek_user = User.query.filter((User.username==new_username) | (User.phone==new_whatsapp)).first()
            elif hasattr(User, 'name'):
                cek_user = User.query.filter((User.name==new_username) | (User.phone==new_whatsapp)).first()
            else:
                cek_user = User.query.filter_by(phone=new_whatsapp).first()
            if cek_user: return jsonify({'status': 'error', 'message': 'Username atau No WhatsApp sudah terdaftar.'})
            
            # Simpan OTP ke tabel database OtpCode (dengan password ter-hash)
            p_hash = generate_password_hash(new_password)
            otp_kode = create_otp(new_whatsapp, action='register', username=new_username, password_hash=p_hash)
            
            # Panggil kirim_wa_otp dengan kode 6 digit
            kirim_wa_otp(new_whatsapp, otp_kode)
            return jsonify({'status': 'success', 'message': 'Kode OTP dikirim ke WhatsApp!'})

        elif action == 'verify_otp_baru':
            from flask import jsonify
            from app.models.user import User
            from app.extensions import db
            from flask_login import login_user
            from app.services.otp_service import verify_otp
            
            new_whatsapp = request.form.get('new_whatsapp')
            otp_input = request.form.get('otp')
            
            is_valid, msg, user_data = verify_otp(new_whatsapp, otp_input, action='register')
            if not is_valid:
                return jsonify({'status': 'error', 'message': msg})
                
            # Daftar sukses
            password_hash_final = user_data.get('password_hash')
            user_kwargs = {
                'phone': new_whatsapp,
                'password_hash': password_hash_final,
                'role': 'user',
                'balance': 0.0,
                'is_active': True
            }
            uname = user_data.get('username') or new_whatsapp
            if hasattr(User, 'username'): user_kwargs['username'] = uname
            if hasattr(User, 'name'): user_kwargs['name'] = uname
            
            new_user = User(**user_kwargs)
            if hasattr(User, 'name'): new_user.name = uname
            db.session.add(new_user)
            db.session.commit()
            
            login_user(new_user)
            return jsonify({'status': 'success', 'message': 'Pendaftaran Berhasil'})

        elif action == 'request_emergency_otp':
            from flask import jsonify
            from app.services.otp_service import create_otp
            from app.services.telegram_service import send_emergency_otp_request

            phone = request.form.get('phone') or request.form.get('new_whatsapp')
            user_name = request.form.get('name') or request.form.get('new_username') or None
            purpose = request.form.get('purpose', 'Pendaftaran Akun Baru')

            if not phone:
                return jsonify({'status': 'error', 'message': 'Nomor WhatsApp wajib diisi.'})

            clean_num = ''.join(filter(str.isdigit, str(phone)))
            if clean_num.startswith('0'):
                clean_num = '62' + clean_num[1:]

            otp_kode = create_otp(clean_num, action='manual', username=user_name, expiry_seconds=600)
            tele_ok, tele_msg, wa_link = send_emergency_otp_request(
                phone=clean_num,
                otp_code=otp_kode,
                user_name=user_name,
                action_type=purpose,
                expiry_minutes=10
            )

            return jsonify({
                'status': 'success',
                'message': 'Permintaan bantuan OTP Darurat telah diteruskan ke Tim CS Telegram kami. Tim CS akan segera menghubungi atau mengirimkan kode ke WhatsApp Anda (berlaku 10 menit).',
                'wa_direct_link': wa_link,
                'telegram_notified': tele_ok
            })
            
    return render_template('user/profil.html', title='Profil Akun')


# --- INJEKSI ROUTE KHUSUS KEAMANAN ---
@user_bp.route('/update_security', methods=['POST'])
@csrf.exempt
@login_required
def update_security():
    from werkzeug.security import check_password_hash, generate_password_hash
    from flask import request, flash, redirect, url_for
    from app.extensions import db
    from app.models.user import User

    action = request.form.get('action')
    user_db = User.query.get(current_user.id)

    if not user_db:
        flash('Sesi tidak valid!', 'error')
        return redirect('/profil')

    if action == 'change_password':
        old_pass = request.form.get('old_password')
        new_pass = request.form.get('new_password')
        if not check_password_hash(user_db.password_hash, old_pass):
            flash('Password lama salah!', 'error')
        else:
            user_db.password_hash = generate_password_hash(new_pass)
            db.session.add(user_db)
            db.session.commit()
            flash('Password berhasil diubah!', 'success')

    elif action == 'change_pin':
        old_pin = request.form.get('old_pin')
        new_pin = request.form.get('new_pin')
        if user_db.pin_hash and not check_password_hash(user_db.pin_hash, old_pin):
            flash('PIN lama salah!', 'error')
        else:
            user_db.pin_hash = generate_password_hash(new_pin)
            db.session.add(user_db)
            db.session.commit()
            flash('PIN Transaksi berhasil diatur!', 'success')

    return redirect('/profil')
# -------------------------------------


@user_bp.route('/informasi')
@login_required
def informasi():
    mutasi_data = []
    try:
        from app.models.transaction import Transaction
        # Mengambil 50 transaksi terakhir dari user yang login
        mutasi_data = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.id.desc()).limit(50).all()
    except Exception as e:
        print(f"Error mengambil mutasi: {e}")
        
    return render_template('user/informasi.html', mutasi_data=mutasi_data)



# --- ROUTE PRODUK CUAN DINAMIS ---
@user_bp.route('/cuan/<provider>')
@login_required
def produk_cuan(provider):
    providers = {
        'telkomsel': {'title': 'TELKOMSEL CUAN', 'logo': 'T', 'color': '#E11D48', 'placeholder': '08123456789', 'label': 'Telkomsel'},
        'xl': {'title': 'XL & AXIS CUAN', 'logo': 'XL', 'color': '#10B981', 'placeholder': '081912345678', 'label': 'XL/AXIS'},
        'isat': {'title': 'INDOSAT CUAN', 'logo': 'im3', 'color': '#F59E0B', 'placeholder': '085712345678', 'label': 'Indosat'},
        'tri': {'title': 'TRI CUAN', 'logo': '3', 'color': '#EF4444', 'placeholder': '089612345678', 'label': 'Tri'},
        'byu': {'title': 'BY.U CUAN', 'logo': 'by.U', 'color': '#3B82F6', 'placeholder': '085112345678', 'label': 'by.U'}
    }
    data = providers.get(provider)
    if not data:
        from flask import flash, redirect, url_for
        flash('Provider tidak ditemukan!', 'error')
        return redirect(url_for('user.dashboard'))
    return render_template('user/cuan.html', data=data)
# ---------------------------------


























# --- API PENCARIAN PRODUK CUAN ---
@user_bp.route('/api/search_cuan_live/<provider>/<nohp>', methods=['GET'])
def api_search_cuan_live(provider, nohp):
    import random
    from flask import jsonify
    from app.models.product import Product
    
    # 1. VALIDASI PANJANG NOMOR (Anti-Spam / Nomor Asal)
    if not nohp.isdigit() or len(nohp) < 10 or len(nohp) > 15:
        return jsonify({'status': 'error', 'message': 'Format nomor HP tidak valid.'})

    provider = provider.lower()
    prefix = nohp[:4]
    
    # Kumpulan Prefix Lengkap Operator Indonesia
    prefix_tsel = ['0811','0812','0813','0821','0822','0823','0852','0853','0851']
    prefix_xl = ['0817','0818','0819','0859','0877','0878']
    prefix_axis = ['0831','0832','0833','0838']
    prefix_isat = ['0814','0815','0816','0855','0856','0857','0858']
    prefix_tri = ['0895','0896','0897','0898','0899']

    target_brands = []
    
    # 2. GERBANG VALIDASI KETAT (CROSS-BLOCKING LOGIC)
    if provider == 'telkomsel':
        if prefix not in prefix_tsel:
            return jsonify({'status': 'error', 'message': 'Gagal: Nomor yang dimasukkan bukan nomor Telkomsel.'})
        target_brands = ['TELKOMSEL', 'TSEL']
        
    elif provider == 'byu':
        if prefix not in prefix_tsel: # By.u menggunakan blok 0851 Telkomsel
            return jsonify({'status': 'error', 'message': 'Gagal: Nomor yang dimasukkan bukan nomor By.U.'})
        target_brands = ['BY.U', 'BYU']
        
    elif provider == 'xl':
        # Halaman XL & Axis digabung, izinkan kedua prefix tersebut
        if prefix in prefix_xl:
            target_brands = ['XL']
        elif prefix in prefix_axis:
            target_brands = ['AXIS']
        else:
            return jsonify({'status': 'error', 'message': 'Gagal: Nomor yang dimasukkan bukan nomor XL atau AXIS.'})
            
    elif provider == 'isat':
        if prefix not in prefix_isat:
            return jsonify({'status': 'error', 'message': 'Gagal: Nomor yang dimasukkan bukan nomor Indosat.'})
        target_brands = ['INDOSAT', 'ISAT']
        
    elif provider == 'tri':
        if prefix not in prefix_tri:
            return jsonify({'status': 'error', 'message': 'Gagal: Nomor yang dimasukkan bukan nomor Tri (3).'})
        target_brands = ['THREE', 'TRI']
        
    else:
        return jsonify({'status': 'error', 'message': 'Provider tidak dikenali sistem.'})

    # 3. PROSES PENGAMBILAN DATA (Aman dari kebocoran nomor silang)
    try:
        all_products = Product.query.filter(Product.is_active == True).all()
        valid_products = []
        
        for p in all_products:
            brand = str(p.brand).upper()
            name = str(p.name).upper()
            
            if any(b in brand for b in target_brands) or any(b in name for b in target_brands):
                
                # Filter tambahan untuk memastikan XL dan Axis tidak tertukar di database
                if 'XL' in target_brands and 'AXIS' not in target_brands and 'AXIS' in name: continue
                if 'AXIS' in target_brands and 'XL' not in target_brands and 'XL' in name: continue
                if 'TELKOMSEL' in target_brands and ('BY.U' in name or 'BYU' in name): continue
                if ('BY.U' in target_brands or 'BYU' in target_brands) and 'TELKOMSEL' in name and 'BY.U' not in name: continue
                
                # Buang fitur cek, pulsa biasa, masa aktif
                if any(x in name for x in ['CEK', 'PULSA', 'MASA AKTIF', 'INFO', 'INQUIRY', 'TRANSFER']):
                    continue
                
                # Ambil rentang harga menengah (10rb - 75rb)
                if 10000 <= p.sell_price <= 75000:
                    valid_products.append(p)
                    
        # Fallback cadangan
        if len(valid_products) < 5:
            valid_products = [p for p in all_products if (any(b in str(p.brand).upper() for b in target_brands) or any(b in str(p.name).upper() for b in target_brands)) and not any(x in str(p.name).upper() for x in ['CEK', 'PULSA', 'MASA AKTIF'])]

        selected = random.sample(valid_products, min(len(valid_products), 6))
        selected = sorted(selected, key=lambda x: x.sell_price)
        
        result = []
        for p in selected:
            cat = 'PROMO SPESIAL'
            if 'DATA' in str(p.category).upper() or 'DATA' in str(p.name).upper(): cat = 'PAKET DATA'
            elif 'VOUCHER' in str(p.category).upper() or 'VOUCHER' in str(p.name).upper(): cat = 'VOUCHER'
            elif 'AKRAB' in str(p.name).upper(): cat = 'PAKET AKRAB'
            
            result.append({
                'sku': p.sku_code,
                'name': p.name,
                'price': p.sell_price,
                'category': cat,
                'type': 'prepaid',
                'desc': getattr(p, 'description', 'Deskripsi tidak tersedia untuk paket ini.')
            })
            
        if not result:
            return jsonify({'status': 'error', 'message': 'Promo sedang tidak tersedia untuk nomor ini.'})
            
        return jsonify({'status': 'success', 'data': result})
    except Exception as e:
        return jsonify({'status': 'error', 'message': 'Terjadi kesalahan sistem.'})

# ==========================================
# FITUR POIN MEMBER & KLAIM TAHUNAN
# ==========================================
def _render_rules_markdown(md_text):
    """Konversi sederhana dan aman format teks/markdown aturan ke HTML."""
    if not md_text:
        return "<p>Belum ada aturan poin yang ditetapkan.</p>"
    import html
    import re
    
    lines = md_text.strip().split('\n')
    html_lines = []
    in_list = False
    
    for line in lines:
        line_str = line.strip()
        if not line_str:
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            continue
            
        # Heading ### atau ##
        if line_str.startswith('###'):
            if in_list: html_lines.append('</ul>'); in_list = False
            title = html.escape(line_str.replace('###', '').strip())
            html_lines.append(f'<h4 style="margin: 14px 0 8px 0; color: #1e293b; font-weight: 800; font-size: 13px;">{title}</h4>')
        elif line_str.startswith('##'):
            if in_list: html_lines.append('</ul>'); in_list = False
            title = html.escape(line_str.replace('##', '').strip())
            html_lines.append(f'<h3 style="margin: 16px 0 10px 0; color: #00877a; font-weight: 900; font-size: 14px;">{title}</h3>')
        # List bullet '-' atau '*'
        elif line_str.startswith('-') or line_str.startswith('*'):
            if not in_list:
                html_lines.append('<ul style="padding-left: 18px; margin-bottom: 10px;">')
                in_list = True
            content = line_str[1:].strip()
            # Parse bold **text**
            content = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', html.escape(content))
            html_lines.append(f'<li style="margin-bottom: 6px;">{content}</li>')
        # Numbered list '1.'
        elif re.match(r'^\d+\.', line_str):
            if in_list: html_lines.append('</ul>'); in_list = False
            content = re.sub(r'^\d+\.\s*', '', line_str)
            content = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', html.escape(content))
            html_lines.append(f'<p style="margin-bottom: 8px; font-weight: 700; color: #1e293b;">{line_str[:3]} {content}</p>')
        else:
            if in_list: html_lines.append('</ul>'); in_list = False
            content = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', html.escape(line_str))
            html_lines.append(f'<p style="margin-bottom: 8px;">{content}</p>')
            
    if in_list:
        html_lines.append('</ul>')
        
    return '\n'.join(html_lines)


@user_bp.route('/poin')
def poin_member():
    """Halaman Informasi & Klaim Poin Member."""
    from flask import redirect, url_for, flash
    from datetime import datetime
    from app.models.setting import Setting
    from app.models.point_log import PointLog

    if not current_user.is_authenticated:
        flash('Silakan masuk terlebih dahulu untuk melihat poin Anda.', 'info')
        return redirect(url_for('auth.login'))

    # 1. Parameter Poin dari Database Setting
    rate_set = Setting.query.filter_by(key='point_rate').first()
    point_rate = float(rate_set.value) if rate_set and rate_set.value else 1.0

    start_set = Setting.query.filter_by(key='point_claim_start_day').first()
    start_day = int(start_set.value) if start_set and start_set.value and start_set.value.isdigit() else 1

    end_set = Setting.query.filter_by(key='point_claim_end_day').first()
    end_day = int(end_set.value) if end_set and end_set.value and end_set.value.isdigit() else 7

    force_set = Setting.query.filter_by(key='point_claim_force_open').first()
    force_open = (force_set.value == '1') if force_set else False

    rules_set = Setting.query.filter_by(key='point_rules_content').first()
    raw_rules = rules_set.value if rules_set and rules_set.value else ''
    rules_content = _render_rules_markdown(raw_rules)

    # 2. Cek Periode Klaim (1 s/d 7 Januari setiap tahun)
    now = datetime.now()
    is_january_window = (now.month == 1 and start_day <= now.day <= end_day)
    is_claim_active = is_january_window or force_open

    # 3. Keterangan Periode Klaim Berikutnya
    if now.month == 1 and now.day < start_day:
        next_claim_text = f"{start_day} - {end_day} Januari {now.year}"
    elif now.month == 1 and now.day <= end_day:
        next_claim_text = f"Sedang Berlangsung ({start_day} - {end_day} Januari {now.year})"
    else:
        next_claim_text = f"{start_day} - {end_day} Januari {now.year + 1}"

    user_points = int(current_user.points or 0)
    estimated_balance = user_points * point_rate

    # 4. Ambil Riwayat Poin Member
    point_logs = PointLog.query.filter_by(user_id=current_user.id).order_by(PointLog.created_at.desc()).limit(25).all()

    return render_template('user/poin.html',
                           user_points=user_points,
                           point_rate=int(point_rate) if point_rate.is_integer() else point_rate,
                           estimated_balance=estimated_balance,
                           is_claim_active=is_claim_active,
                           next_claim_text=next_claim_text,
                           rules_content=rules_content,
                           point_logs=point_logs)


@user_bp.route('/poin/claim', methods=['POST'])
@csrf.exempt
def claim_poin_action():
    """Memproses klaim poin member menjadi saldo akun (Hanya 1-7 Januari / Testing Mode)."""
    from flask import jsonify
    from datetime import datetime
    from app.models.setting import Setting
    from app.models.point_log import PointLog
    from app.models.user import User

    if not current_user.is_authenticated:
        return jsonify({'status': 'error', 'message': 'Sesi login telah berakhir. Silakan login kembali.'}), 401

    # 1. Verifikasi Periode Klaim
    start_set = Setting.query.filter_by(key='point_claim_start_day').first()
    start_day = int(start_set.value) if start_set and start_set.value and start_set.value.isdigit() else 1

    end_set = Setting.query.filter_by(key='point_claim_end_day').first()
    end_day = int(end_set.value) if end_set and end_set.value and end_set.value.isdigit() else 7

    force_set = Setting.query.filter_by(key='point_claim_force_open').first()
    force_open = (force_set.value == '1') if force_set else False

    now = datetime.now()
    is_january_window = (now.month == 1 and start_day <= now.day <= end_day)
    is_claim_active = is_january_window or force_open

    if not is_claim_active:
        return jsonify({
            'status': 'error',
            'message': f'Klaim poin hanya dapat dilakukan pada 1 minggu pertama bulan Januari ({start_day} - {end_day} Januari). Poin Anda aman dan otomatis terakumulasi untuk tahun depan!'
        }), 400

    # 2. Cek Saldo Poin Member dengan Locking Baris DB
    try:
        user = User.query.filter_by(id=current_user.id).with_for_update().first()
        current_pts = int(user.points or 0)
        
        if current_pts <= 0:
            return jsonify({'status': 'error', 'message': 'Anda belum memiliki poin untuk diklaim.'}), 400

        rate_set = Setting.query.filter_by(key='point_rate').first()
        point_rate = float(rate_set.value) if rate_set and rate_set.value else 1.0

        saldo_didapat = current_pts * point_rate
        
        # 3. Update Saldo Utama & Reset Poin
        user.balance = (user.balance or 0.0) + saldo_didapat
        user.points = 0

        # 4. Catat Mutasi Log Poin
        log = PointLog(
            user_id=user.id,
            type='CLAIM_TO_SALDO',
            points=-current_pts,
            balance_added=saldo_didapat,
            description=f'Klaim {current_pts:,} Poin menjadi Saldo Utama Rp {saldo_didapat:,.0f}'
        )
        db.session.add(log)
        db.session.commit()

        return jsonify({
            'status': 'success',
            'message': f'Selamat! {current_pts:,} Poin berhasil diklaim dan saldo Anda bertambah Rp {saldo_didapat:,.0f}.'
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': f'Gagal memproses klaim: {str(e)}'}), 500


# ==========================================
# PUSAT DEPOSIT SALDO (QRIS & MANUAL E-WALLET)
# ==========================================
@user_bp.route('/deposit')
def deposit():
    """Halaman pengisian saldo dengan pilihan QRIS otomatis & Transfer Manual E-Wallet."""
    if not current_user.is_authenticated:
        from flask import flash, redirect, url_for
        flash('Silakan login terlebih dahulu untuk melakukan deposit.', 'warning')
        return redirect(url_for('user.dashboard'))

    from app.models.transaction import Transaction
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
    active_pg = os.getenv('ACTIVE_PAYMENT_GATEWAY', 'paymentkita').lower().strip()
    gateway_name = 'Pakasir QRIS (Instan 24 Jam)' if active_pg == 'pakasir' else 'PaymentKita QRIS (Instan 24 Jam)'

    # Ambil 5 riwayat deposit terakhir milik user
    recent_deposits = Transaction.query.filter(
        Transaction.user_id == current_user.id,
        Transaction.sku_code.in_(['DEPOSIT_SALDO', 'DEPOSIT_MANUAL'])
    ).order_by(Transaction.id.desc()).limit(5).all()

    return render_template('user/deposit.html',
                           active_pg=active_pg,
                           gateway_name=gateway_name,
                           recent_deposits=recent_deposits)


@user_bp.route('/deposit/manual', methods=['POST'])
@csrf.exempt
def deposit_manual_action():
    """Memproses pengajuan deposit transfer manual E-Wallet dengan kode unik 01-99."""
    from flask import jsonify, request
    import random
    import time
    from urllib.parse import quote
    from app.models.transaction import Transaction

    if not current_user.is_authenticated:
        return jsonify({'status': 'error', 'message': 'Silakan login terlebih dahulu.'}), 401

    data = request.get_json(silent=True) or request.form.to_dict() or {}
    nominal_raw = data.get('nominal') or data.get('amount')
    ewallet_type = (data.get('ewallet_type') or 'DANA').upper().strip()

    try:
        nominal = int(float(nominal_raw))
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': 'Nominal tidak valid.'}), 400

    if nominal < 10000:
        return jsonify({'status': 'error', 'message': 'Minimal deposit manual adalah Rp 10.000.'}), 400

    # Generate 2 digit kode unik acak 01 s/d 99
    unique_code = random.randint(1, 99)
    total_transfer = nominal + unique_code

    ref_id = f"DEP-MANUAL-{int(time.time())}{random.randint(100, 999)}"

    ewallet_dest = "081775700114"
    ewallet_owner = "GarudaTel"

    # Simpan ke tabel Transaksi
    trx = Transaction(
        ref_id=ref_id,
        user_id=current_user.id,
        sku_code='DEPOSIT_MANUAL',
        product_name=f'Deposit Manual {ewallet_type}',
        target_number=getattr(current_user, 'phone', None) or ewallet_dest,
        amount=nominal,
        payment_method='manual_ewallet',
        payment_status='UNPAID',
        status='PENDING',
        is_prepaid=True,
        sn=f'Kode Unik: {unique_code:02d} | Total: Rp {total_transfer:,} | Rek: {ewallet_dest} ({ewallet_type})'
    )
    db.session.add(trx)
    db.session.commit()

    from app.services.telegram_service import async_send_trx_notification
    async_send_trx_notification(trx, title="PENGAJUAN DEPOSIT MANUAL")

    # Format URL WhatsApp konfirmasi
    user_name = getattr(current_user, 'name', 'Member')
    user_phone = getattr(current_user, 'phone', '-')
    
    wa_message = (
        f"Halo Admin GarudaTel, saya ingin konfirmasi deposit manual E-Wallet:\n\n"
        f"• Nama Akun: {user_name}\n"
        f"• No. WhatsApp: {user_phone}\n"
        f"• Nominal Saldo: Rp {nominal:,.0f}\n"
        f"• Kode Unik: {unique_code:02d}\n"
        f"• TOTAL TRANSFER: Rp {total_transfer:,.0f}\n"
        f"• Metode / Tujuan: {ewallet_type} ({ewallet_dest} a.n {ewallet_owner})\n"
        f"• Ref ID: {ref_id}\n\n"
        f"Saya sudah mentransfer sesuai jumlah total di atas. Mohon segera dicek dan disetujui. Terima kasih!"
    )
    # Format URL WhatsApp konfirmasi dengan skema langsung whatsapp://
    wa_url = f"whatsapp://send?phone=6281775700114&text={quote(wa_message)}"
    wa_web_url = f"https://wa.me/6281775700114?text={quote(wa_message)}"

    return jsonify({
        'status': 'success',
        'ref_id': ref_id,
        'nominal': nominal,
        'unique_code': f"{unique_code:02d}",
        'total_transfer': total_transfer,
        'ewallet_type': ewallet_type,
        'ewallet_dest': ewallet_dest,
        'ewallet_owner': ewallet_owner,
        'wa_url': wa_url,
        'wa_web_url': wa_web_url,
        'message': 'Pengajuan deposit manual berhasil dibuat.'
    }), 200


@user_bp.route('/muslimtrack')
@user_bp.route('/scan')
@user_bp.route('/dailytracker')
@user_bp.route('/tracker')
def muslimtrack():
    """Halaman Moeslim Daily Tracker Pro (Native In-App Super-App)"""
    return render_template('muslimtrack/index.html')


# ==========================================
# RUTE NOTIFIKASI & PENGUMUMAN USER
# ==========================================
@user_bp.route('/notifikasi')
def notifikasi():
    """Halaman Pusat Notifikasi Pengguna"""
    user_id = current_user.id if current_user.is_authenticated else None
    notifs, unread_count, read_ids = get_user_notifications(user_id)
    return render_template('user/notifikasi.html',
                           notifications=notifs,
                           unread_count=unread_count,
                           read_ids=read_ids)


@user_bp.route('/api/notifikasi/read-all', methods=['POST'])
@csrf.exempt
def notifikasi_read_all():
    """Menandai semua notifikasi telah dibaca untuk menghilangkan titik merah."""
    if not current_user.is_authenticated:
        return jsonify({'success': True, 'unread_count': 0})

    from app.models.notification import Notification, NotificationRead
    notifs = Notification.query.filter(
        or_(Notification.target_user_id == None, Notification.target_user_id == current_user.id)
    ).all()
    existing_reads = {r.notification_id for r in NotificationRead.query.filter_by(user_id=current_user.id).all()}

    for n in notifs:
        if n.id not in existing_reads:
            nr = NotificationRead(user_id=current_user.id, notification_id=n.id)
            db.session.add(nr)

    db.session.commit()
    return jsonify({'success': True, 'unread_count': 0})


@user_bp.route('/api/notifikasi/<int:id>/read', methods=['POST'])
@csrf.exempt
def notifikasi_read_single(id):
    """Menandai satu notifikasi spesifik telah dibaca."""
    if not current_user.is_authenticated:
        return jsonify({'success': True})

    from app.models.notification import NotificationRead
    exists = NotificationRead.query.filter_by(user_id=current_user.id, notification_id=id).first()
    if not exists:
        nr = NotificationRead(user_id=current_user.id, notification_id=id)
        db.session.add(nr)
        db.session.commit()

    _, unread_count, _ = get_user_notifications(current_user.id)
    return jsonify({'success': True, 'unread_count': unread_count})


# ==========================================
# RUTE TIKET CS TELEGRAM (BOT 1 CS)
# ==========================================
@user_bp.route('/tiket')
@user_bp.route('/bantuan')
@user_bp.route('/cs')
def bantuan():
    """Halaman Tiket Bantuan & CS Pengguna"""
    selected_ref = request.args.get('ref', '').strip()
    recent_trxs = []
    selected_trx = None

    if current_user.is_authenticated:
        from app.models.transaction import Transaction
        recent_trxs = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.created_at.desc()).limit(20).all()
        if selected_ref:
            selected_trx = Transaction.query.filter_by(user_id=current_user.id, ref_id=selected_ref).first()

    return render_template('user/bantuan.html',
                           recent_trxs=recent_trxs,
                           selected_ref=selected_ref,
                           selected_trx=selected_trx)


@user_bp.route('/api/user/recent-transactions')
def api_recent_transactions():
    """Mengambil riwayat transaksi user untuk pemilih dropdown tiket CS."""
    if not current_user.is_authenticated:
        return jsonify({'transactions': []})

    from app.models.transaction import Transaction
    trxs = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.created_at.desc()).limit(20).all()
    data = [{
        'id': t.id,
        'ref_id': t.ref_id,
        'product_name': t.product_name or 'Produk',
        'target_number': t.target_number or '-',
        'status': t.status,
        'amount': t.amount,
        'date': t.created_at.strftime('%d/%m/%Y %H:%M') if t.created_at else '-'
    } for t in trxs]

    return jsonify({'transactions': data})


@user_bp.route('/tiket/kirim', methods=['POST'])
@csrf.exempt
def kirim_tiket():
    """Menerima keluhan pengguna, mencatat tiket, dan mengirim ke Bot 1 CS Telegram."""
    from app.models.support_ticket import SupportTicket
    from app.models.transaction import Transaction
    from app.services.telegram_service import send_cs_ticket

    user_name = request.form.get('user_name', '').strip()
    user_phone = request.form.get('user_phone', '').strip()
    category = request.form.get('category', 'Transaksi Bermasalah').strip()
    message = request.form.get('message', '').strip()
    transaction_ref = request.form.get('transaction_ref', '').strip()

    if current_user.is_authenticated:
        if not user_name:
            user_name = current_user.name
        if not user_phone:
            user_phone = current_user.phone

    if not user_name or not user_phone or not message:
        flash('Mohon lengkapi nama, nomor telepon, dan detail pesan keluhan Anda.', 'warning')
        return redirect(request.referrer or url_for('user.bantuan'))

    trx = None
    if transaction_ref and transaction_ref != 'NONE':
        trx = Transaction.query.filter_by(ref_id=transaction_ref).first()
        if not trx and transaction_ref.isdigit():
            trx = Transaction.query.get(int(transaction_ref))

    ticket_num = SupportTicket.generate_ticket_number()
    ticket = SupportTicket(
        ticket_number=ticket_num,
        user_id=current_user.id if current_user.is_authenticated else None,
        user_name=user_name,
        user_phone=user_phone,
        transaction_id=trx.id if trx else None,
        category=category,
        message=message,
        status='OPEN'
    )
    db.session.add(ticket)
    db.session.commit()

    # Kirim langsung ke Bot 1 : CS & Balas Inbox di Telegram
    sent_ok, tg_msg = send_cs_ticket(ticket, trx)
    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return jsonify({
            'success': True,
            'ticket_number': ticket.ticket_number,
            'telegram_sent': sent_ok,
            'message': 'Tiket berhasil dikirim ke Tim CS!'
        })

    flash(f'✅ Tiket bantuan #{ticket.ticket_number} berhasil dikirim ke CS. Kami akan segera menghubungi Anda!', 'success')
    return redirect(url_for('user.bantuan', ticket_success=ticket.ticket_number))


@user_bp.route('/inquiry/pln', methods=['POST'])
@user_bp.route('/api/inquiry/pln', methods=['POST'])
@csrf.exempt
def inquiry_pln_route():
    """Endpoint pengecekan nama pelanggan PLN Token / Tagihan secara online."""
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    customer_no = data.get('customer_no') or data.get('id_pelanggan') or data.get('nomor') or ''
    if not customer_no:
        return jsonify({'status': 'error', 'message': 'ID Pelanggan / Nomor Meter PLN wajib diisi'}), 400

    from app.services.digiflazz import inquiry_pln, is_pln_cutoff_time, get_pln_cutoff_message
    if is_pln_cutoff_time():
        return jsonify({
            'status': 'error',
            'success': False,
            'is_cutoff': True,
            'message': get_pln_cutoff_message()
        }), 400

    ok, res_data, msg = inquiry_pln(customer_no)
    if ok:
        return jsonify({
            'status': 'success',
            'success': True,
            'name': res_data.get('name'),
            'segment_power': res_data.get('segment_power'),
            'subscriber_id': res_data.get('subscriber_id'),
            'data': res_data,
            'message': msg
        }), 200
    else:
        return jsonify({
            'status': 'error',
            'success': False,
            'data': res_data,
            'message': msg
        }), 400



