from app.extensions import db
from datetime import datetime

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ref_id = db.Column(db.String(100), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    sku_code = db.Column(db.String(50), nullable=False)
    product_name = db.Column(db.String(150), nullable=False)
    target_number = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(20), nullable=False)
    payment_status = db.Column(db.String(20), default='UNPAID', index=True)
    status = db.Column(db.String(20), default='PENDING', index=True)
    sn = db.Column(db.String(255), nullable=True)
    provider_ref = db.Column(db.String(100), nullable=True)
    is_prepaid = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Identifikasi Perangkat Kasir / Cabang Toko (Eksklusif VIP)
    device_id = db.Column(db.Integer, db.ForeignKey('trusted_device.id'), nullable=True, index=True)
    device_name = db.Column(db.String(100), nullable=True, index=True)

    # Informasi Seller / Biller Provider (Digiflazz / VIP-Reseller)
    seller_name = db.Column(db.String(100), nullable=True, index=True)
    seller_tele = db.Column(db.String(100), nullable=True)
    seller_wa = db.Column(db.String(50), nullable=True)
    base_price = db.Column(db.Float, nullable=True)

    __table_args__ = (
        db.Index('idx_trx_user_created', 'user_id', 'created_at'),
        db.Index('idx_trx_status_created', 'status', 'created_at'),
        db.Index('idx_trx_user_device', 'user_id', 'device_name'),
    )

    @property
    def created_at_wib(self):
        from datetime import timedelta
        if self.created_at:
            wib = self.created_at + timedelta(hours=7)
            return wib.strftime('%d-%m-%Y %H:%M')
        return 'Baru Saja'

    @property
    def created_at_digiflazz_fmt(self):
        """Format waktu YYYY-MM-DD HH:MM:SS WIB sesuai standar komplain Digiflazz ke Seller."""
        from datetime import timedelta
        if self.created_at:
            wib = self.created_at + timedelta(hours=7)
            return wib.strftime('%Y-%m-%d %H:%M:%S')
        wib_now = datetime.utcnow() + timedelta(hours=7)
        return wib_now.strftime('%Y-%m-%d %H:%M:%S')

    @property
    def resolved_seller_name(self):
        """Mengembalikan nama seller transaksi, atau fallback dari katalog Product jika transaksi lama."""
        if self.seller_name and self.seller_name.strip():
            return self.seller_name.strip()
        if self.sku_code in ['DEPOSIT_SALDO', 'DEPOSIT_MANUAL', 'MANUAL_DEDUCTION', 'COMMISSION_PAYOUT']:
            return None
        try:
            from app.models.product import Product
            with db.session.no_autoflush:
                prod = Product.query.filter_by(sku_code=self.sku_code).first()
            if prod and prod.seller_name:
                return prod.seller_name.strip()
            if prod and (str(prod.brand or '').startswith('VIP-') or '[VIP]' in str(prod.name or '')):
                return 'VIP-Reseller'
        except Exception:
            pass
        if str(self.ref_id or '').startswith(('VIP-', 'VP')):
            return 'VIP-Reseller'
        return None

    def format_digiflazz_complaint(self, mode=None):
        """
        Merakit teks komplain standar Digiflazz ke Seller:
        - Pending: SDJT2D5.085143842997, 2026-10-12 11:55:04 ref Id: GT-..., pending
        - Sukses belum masuk: IN5.085648361007, 2026-09-22 15:18:07 ref Id: GT-..., Sukses, tapi belum masuk ke customernya
        - Gagal: TDJT33.085385876405, 2026-10-06 14:02:59 ref Id: GT-..., gagal, bisa dibantu infokan alasan gagalnya?
        """
        sku = (self.sku_code or 'PRODUK').strip()
        dest = (self.target_number or '').strip()
        dt_str = self.created_at_digiflazz_fmt
        ref_val = (self.provider_ref if (self.provider_ref and not str(self.provider_ref).startswith('IPAY')) else None) or self.ref_id

        st = (mode or self.status or 'PENDING').upper()
        if st in ['SUCCESS', 'SUKSES', 'SUKSES_BELUM_MASUK', 'BELUM_MASUK']:
            return f"{sku}.{dest}, {dt_str} ref Id: {ref_val}, Sukses, tapi belum masuk ke customernya"
        elif st in ['FAILED', 'GAGAL', 'ERROR', 'CANCELLED']:
            return f"{sku}.{dest}, {dt_str} ref Id: {ref_val}, gagal, bisa dibantu infokan alasan gagalnya?"
        else:
            return f"{sku}.{dest}, {dt_str} ref Id: {ref_val}, pending"

    @property
    def target(self):
        return self.target_number

    @property
    def price(self):
        return self.amount


    # Relasi ke User & Perangkat Kasir
    user = db.relationship('User', backref=db.backref('transactions', lazy=True))
    device = db.relationship('TrustedDevice', backref=db.backref('transactions', lazy=True))

