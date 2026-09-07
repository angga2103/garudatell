from datetime import datetime, timezone, timedelta
from flask_login import UserMixin
from app.extensions import db

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    pin_hash = db.Column(db.String(200), nullable=True)
    balance = db.Column(db.Float, default=0.0)
    points = db.Column(db.Integer, default=0)
    role = db.Column(db.String(20), default='user') # 'user', 'reseller', 'vip'
    role_expires_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    referral_code = db.Column(db.String(20), unique=True, nullable=True)
    
    # Kemitraan Downline & Komisi
    upline_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    commission_balance = db.Column(db.Float, default=0.0)
    last_reminded_at = db.Column(db.DateTime, nullable=True)

    # Relasi Self-Referential Downlines
    downlines = db.relationship('User', backref=db.backref('upline', remote_side=[id]), lazy='dynamic')

    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def is_vip_active(self):
        """Memeriksa apakah akun berstatus VIP dan masa aktif masih berlaku."""
        if self.role != 'vip':
            return False
        if not self.role_expires_at:
            return True # VIP manual oleh admin tanpa batas waktu
        wib_now = datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)
        return self.role_expires_at > wib_now

    def is_reseller_active(self):
        """Memeriksa apakah akun berstatus Reseller dan masa aktif masih berlaku."""
        if self.role != 'reseller':
            return False
        if not self.role_expires_at:
            return True # Reseller manual oleh admin tanpa batas waktu
        wib_now = datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)
        return self.role_expires_at > wib_now

    def get_effective_role(self):
        """Mengembalikan role aktif saat ini (memperhitungkan masa kedaluwarsa)."""
        if self.is_vip_active():
            return 'vip'
        elif self.is_reseller_active():
            return 'reseller'
        return 'user'

    def get_remaining_days(self):
        """Menghitung sisa hari masa aktif langganan."""
        if not self.role_expires_at or self.role not in ['reseller', 'vip']:
            return 0
        wib_now = datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)
        diff = self.role_expires_at - wib_now
        return max(0, diff.days)
