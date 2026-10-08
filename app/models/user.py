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
    last_low_balance_notified_at = db.Column(db.DateTime, nullable=True)

    # Proteksi Kasir & Kunci Perangkat (Eksklusif VIP)
    is_device_lock_enabled = db.Column(db.Boolean, default=False)

    # 1 Akun 1 Login Aktif (Single Active Session & Anti-Dual Login)
    current_session_token = db.Column(db.String(64), nullable=True, index=True)
    last_active_at = db.Column(db.DateTime, nullable=True)
    active_device_name = db.Column(db.String(150), nullable=True)
    active_device_ip = db.Column(db.String(50), nullable=True)
    active_device_uuid = db.Column(db.String(64), nullable=True)

    # Relasi Self-Referential Downlines
    downlines = db.relationship('User', backref=db.backref('upline', remote_side=[id]), lazy='dynamic')
    
    # Relasi Perangkat Kasir Terpercaya
    trusted_devices = db.relationship('TrustedDevice', backref='owner', lazy='dynamic', cascade='all, delete-orphan')

    def is_session_active(self, timeout_hours=23):
        """Memeriksa apakah sesi akun sedang aktif dalam batas inaktivitas (default 23 jam)."""
        if not self.current_session_token or not self.last_active_at:
            return False
        delta = datetime.utcnow() - self.last_active_at
        return delta.total_seconds() < timeout_hours * 3600

    @property
    def last_active_at_wib(self):
        if self.last_active_at:
            if hasattr(self.last_active_at, 'strftime'):
                wib = self.last_active_at + timedelta(hours=7)
                return wib.strftime('%d-%m-%Y %H:%M WIB')
            return str(self.last_active_at)
        return '-'

    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def set_pin(self, pin):
        from werkzeug.security import generate_password_hash
        if pin:
            self.pin_hash = generate_password_hash(str(pin).strip())
        else:
            self.pin_hash = None

    def check_pin(self, pin):
        from werkzeug.security import check_password_hash
        if not self.pin_hash:
            return False
        return check_password_hash(self.pin_hash, str(pin).strip())

    def _parse_role_expires_at(self):
        """Helper aman untuk mengonversi role_expires_at baik berupa datetime maupun string SQLite."""
        if not self.role_expires_at:
            return None
        if isinstance(self.role_expires_at, datetime):
            return self.role_expires_at
        if isinstance(self.role_expires_at, str):
            val = self.role_expires_at.strip()
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
                try:
                    return datetime.strptime(val[:19], fmt)
                except Exception:
                    pass
            try:
                return datetime.fromisoformat(val.replace('Z', ''))
            except Exception:
                pass
        return None

    def is_vip_active(self):
        """Memeriksa apakah akun berstatus VIP dan masa aktif masih berlaku."""
        if getattr(self, 'role', '') != 'vip':
            return False
        if not getattr(self, 'role_expires_at', None):
            return True # VIP manual oleh admin tanpa batas waktu
        try:
            exp = self._parse_role_expires_at()
            if not exp:
                return True
            wib_now = datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)
            return exp > wib_now
        except Exception:
            return True

    def is_reseller_active(self):
        """Memeriksa apakah akun berstatus Reseller dan masa aktif masih berlaku."""
        if getattr(self, 'role', '') != 'reseller':
            return False
        if not getattr(self, 'role_expires_at', None):
            return True # Reseller manual oleh admin tanpa batas waktu
        try:
            exp = self._parse_role_expires_at()
            if not exp:
                return True
            wib_now = datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)
            return exp > wib_now
        except Exception:
            return True

    def get_effective_role(self):
        """Mengembalikan role aktif saat ini (memperhitungkan masa kedaluwarsa)."""
        try:
            if self.is_vip_active():
                return 'vip'
            elif self.is_reseller_active():
                return 'reseller'
        except Exception:
            pass
        return getattr(self, 'role', 'user') or 'user'

    def get_remaining_days(self):
        """Menghitung sisa hari masa aktif langganan."""
        if not getattr(self, 'role_expires_at', None) or getattr(self, 'role', '') not in ['reseller', 'vip']:
            return 0
        try:
            exp = self._parse_role_expires_at()
            if not exp:
                return 0
            wib_now = datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)
            diff = exp - wib_now
            return max(0, diff.days)
        except Exception:
            return 0

    @property
    def total_branch_balance(self):
        """Menghitung total saldo aktif dari seluruh cabang kasir milik user."""
        try:
            return sum(float(d.branch_balance or 0.0) for d in self.trusted_devices.filter_by(status='approved').all())
        except Exception:
            return 0.0

    @property
    def total_asset_balance(self):
        """Menghitung total aset saldo (Saldo Utama + Total Saldo Seluruh Cabang)."""
        return float(self.balance or 0.0) + self.total_branch_balance

    @property
    def active_branches_count(self):
        """Menghitung jumlah cabang kasir yang berstatus disetujui/aktif."""
        try:
            return self.trusted_devices.filter_by(status='approved').count()
        except Exception:
            return 0

    @property
    def has_branches(self):
        """Memeriksa apakah pengguna memiliki cabang kasir terdaftar."""
        try:
            return self.trusted_devices.count() > 0
        except Exception:
            return False

