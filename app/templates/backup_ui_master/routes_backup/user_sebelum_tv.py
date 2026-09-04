from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_required, current_user
from flask import Blueprint, render_template
from app.models.product import Product
from app.extensions import db

user_bp = Blueprint('user', __name__)

@user_bp.route('/')
def dashboard():
    raw_categories = db.session.query(Product.category).filter(Product.is_active==True).distinct().all()
    categories = [c[0] for c in raw_categories if c[0]]
    kategori_utama = [c for c in categories if c in ['Pulsa', 'Data', 'E-Money', 'PLN', 'Games']]
    kategori_lainnya = [c for c in categories if c not in kategori_utama]
    if not kategori_utama:
        kategori_utama = categories[:6]
        kategori_lainnya = categories[6:]
    return render_template('user/dashboard.html',
                           kategori_utama=kategori_utama,
                           kategori_lainnya=kategori_lainnya)

# Rute Khusus Pulsa (Harus di atas rute dinamis)
@user_bp.route('/kategori/Pulsa')
@user_bp.route('/kategori/pulsa')
def kategori_pulsa_spesifik():
    # MENGGUNAKAN sell_price SESUAI MODEL DATABASE
    produk_pulsa = Product.query.filter(Product.category.ilike('%pulsa%')).order_by(Product.sell_price.asc()).all()
    return render_template('user/pulsa.html', products=produk_pulsa, title="PULSA")


# Rute Khusus Paket Data
@user_bp.route('/kategori/Data')
@user_bp.route('/kategori/data')
def kategori_data_spesifik():
    # Menarik data produk khusus kategori Data
    produk_data = Product.query.filter(Product.category.ilike('%data%')).order_by(Product.sell_price.asc()).all()
    return render_template('user/data.html', products=produk_data, title="PAKET DATA")

# Rute Khusus E-Money
@user_bp.route('/kategori/E-Money')
@user_bp.route('/kategori/e-money')
@user_bp.route('/kategori/Emoney')
@user_bp.route('/kategori/emoney')
def kategori_emoney_spesifik():
    from sqlalchemy import or_
    # Tarik data dari database yang kategorinya mengandung unsur e-wallet
    produk_emoney = Product.query.filter(
        or_(
            Product.category.ilike('%money%'),
            Product.category.ilike('%wallet%'),
            Product.category.ilike('%saldo%'),
            Product.category.ilike('%dana%'),
            Product.category.ilike('%ovo%'),
            Product.category.ilike('%gopay%'),
            Product.category.ilike('%pay%'),
            Product.category.ilike('%shopee%'),
            Product.category.ilike('%link%'),
            Product.category.ilike('%grab%'),
            Product.category.ilike('%gojek%'),
            Product.category.ilike('%doku%'),
            Product.category.ilike('%kaspro%')
        )
    ).order_by(Product.sell_price.asc()).all()
    return render_template('user/emoney.html', products=produk_emoney, title="E-MONEY")

@user_bp.route('/kategori/telpsms')
@user_bp.route('/kategori/Telpsms')
def kategori_telpsms():
    return render_template('user/telpsms.html', title='TELP & SMS')

@user_bp.route('/kategori/pln')
@user_bp.route('/kategori/PLN')
def kategori_pln():
    return render_template('user/pln.html', title='TOKEN PLN')

@user_bp.route('/kategori/MasaAktif')
@user_bp.route('/kategori/masaaktif')
def kategori_masaaktif():
    return render_template('user/masaaktif.html', title='MASA AKTIF')

@user_bp.route('/kategori/<nama_kategori>')
def lihat_kategori(nama_kategori):
    from app.models.product import Product
    
    # Jika kategori adalah Games, buka jalurnya!
    if nama_kategori.lower() == 'games':
        produk_games = Product.query.filter(Product.category.ilike('%game%')).order_by(Product.sell_price.asc()).all()
        brands = sorted(list(set([p.brand for p in produk_games if p.brand])))
        return render_template('user/games.html', products=produk_games, brands=brands, title="TOPUP GAME")
        
    elif nama_kategori.lower() == 'pln':
        produk_pln = Product.query.filter(
            Product.category.ilike('%pln%') | Product.brand.ilike('%pln%')
        ).order_by(Product.sell_price.asc()).all()
        return render_template('user/pln.html', products=produk_pln, title="TOKEN PLN")

    return f"Halaman untuk kategori {nama_kategori} sedang dibangun!"

@user_bp.route('/profil')
def profil():
    if current_user.is_authenticated and not current_user.referral_code:
        import random, string
        chars = string.ascii_uppercase + string.digits
        current_user.referral_code = 'GT-' + ''.join(random.choice(chars) for _ in range(6))
        db.session.commit()
    return render_template('user/profil.html')

@user_bp.route('/riwayat')
@login_required
def riwayat():
    from app.models.transaction import Transaction
    
    # Ambil semua transaksi milik user ini, urutkan dari yang paling baru
    transactions = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.created_at.desc()).all()
    
    # Menghitung statistik untuk kotak di atas
    count_sukses = sum(1 for t in transactions if t.status == 'SUCCESS')
    count_antri = sum(1 for t in transactions if t.status in ['PENDING', 'UNPAID'])
    count_proses = sum(1 for t in transactions if t.status == 'PROCESSING')
    count_gagal = sum(1 for t in transactions if t.status in ['FAILED', 'CANCELLED'])
    
    return render_template('user/riwayat.html', 
                           transactions=transactions,
                           count_sukses=count_sukses,
                           count_antri=count_antri,
                           count_proses=count_proses,
                           count_gagal=count_gagal)


@user_bp.route('/informasi')
def informasi():
    return render_template('user/informasi.html')

@user_bp.route('/topup')
@login_required
def topup():
    return render_template('user/topup.html')

@user_bp.route('/edit-profil', methods=['GET', 'POST'])
@login_required
def edit_profil():
    if request.method == 'POST':
        current_user.name = request.form.get('name')
        current_user.email = request.form.get('email')
        db.session.commit()
        flash('Profil berhasil diperbarui!', 'success')
        return redirect(url_for('user.profil'))
    return render_template('user/edit_profil.html')

@user_bp.route('/ubah-password', methods=['GET', 'POST'])
@login_required
def ubah_password():
    if request.method == 'POST':
        old_pw = request.form.get('old_password')
        new_pw = request.form.get('new_password')
        if check_password_hash(current_user.password_hash, old_pw):
            current_user.password_hash = generate_password_hash(new_pw)
            db.session.commit()
            flash('Password berhasil diubah!', 'success')
            return redirect(url_for('user.profil'))
        else:
            flash('Password lama tidak sesuai!', 'error')
    return render_template('user/ubah_password.html')

@user_bp.route('/ubah-pin', methods=['GET', 'POST'])
@login_required
def ubah_pin():
    if request.method == 'POST':
        new_pin = request.form.get('new_pin')
        if new_pin and len(new_pin) >= 4:
            current_user.pin_hash = generate_password_hash(new_pin)
            db.session.commit()
            flash('PIN Keamanan berhasil diatur!', 'success')
            return redirect(url_for('user.profil'))
        else:
            flash('PIN minimal 4 digit!', 'warning')
    return render_template('user/ubah_pin.html')
