from app.extensions import db
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

class TrustedDevice(db.Model):
    __tablename__ = 'trusted_device'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    device_uuid = db.Column(db.String(64), nullable=False, index=True)
    device_name = db.Column(db.String(100), nullable=False)  # Contoh: "Cabang 1 - Pasar Baru"
    device_info = db.Column(db.String(255), nullable=True)   # Browser / OS info
    ip_address = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(20), default='pending', index=True)  # 'pending', 'approved', 'rejected', 'revoked'
    approval_token = db.Column(db.String(64), unique=True, nullable=True, index=True)
    approval_expires_at = db.Column(db.DateTime, nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime, nullable=True)

    # Kolom Baru untuk Mode Kasir Mandiri & Pembatasan
    pin_hash = db.Column(db.String(200), nullable=True)                # Hash PIN Kasir 4-6 digit
    daily_limit = db.Column(db.Float, default=0.0)                     # Limit belanja harian (0 = tanpa limit)
    operating_hours_start = db.Column(db.String(5), nullable=True)     # Contoh: "07:00" (WIB)
    operating_hours_end = db.Column(db.String(5), nullable=True)       # Contoh: "22:00" (WIB)
    activation_token = db.Column(db.String(64), unique=True, nullable=True, index=True) # Token aktivasi satu kali pakai
    activation_expires_at = db.Column(db.DateTime, nullable=True)      # Waktu kedaluwarsa tautan aktivasi (misal 2 jam)
    session_version = db.Column(db.Integer, default=1, nullable=False) # Nomor versi sesi (naik setiap re-aktivasi / revoke)
    active_session_token = db.Column(db.String(64), nullable=True)     # Token sesi tunggal aktif (mencegah login paralel/kloning)
    device_fingerprint = db.Column(db.String(128), nullable=True)      # Hash sidik jari hardware browser (anti-copy cookie)
    branch_balance = db.Column(db.Float, default=0.0)                  # Saldo deposit kasir cabang mandiri
    low_balance_alert = db.Column(db.Float, default=100000.0)          # Ambang batas alert saldo menipis ke WA Owner

    __table_args__ = (
        db.UniqueConstraint('user_id', 'device_uuid', name='uq_user_device'),
        db.Index('idx_user_dev_status', 'user_id', 'status'),
    )

    @property
    def created_at_wib(self):
        if self.created_at:
            wib = self.created_at + timedelta(hours=7)
            return wib.strftime('%d-%m-%Y %H:%M')
        return '-'

    @property
    def last_used_at_wib(self):
        if self.last_used_at:
            wib = self.last_used_at + timedelta(hours=7)
            return wib.strftime('%d-%m-%Y %H:%M')
        return 'Belum pernah'

    def is_token_expired(self):
        if not self.approval_expires_at:
            return True
        return datetime.utcnow() > self.approval_expires_at

    def is_activation_expired(self):
        """Memeriksa apakah tautan aktivasi cabang telah kedaluwarsa."""
        if not self.activation_expires_at:
            return False
        try:
            exp = self.activation_expires_at
            if isinstance(exp, str):
                exp = datetime.fromisoformat(exp)
            return datetime.utcnow() > exp
        except Exception:
            return False

    def revoke_active_sessions(self):
        """Memutus seketika seluruh sesi kasir yang sedang aktif di browser manapun."""
        self.session_version = (self.session_version or 0) + 1
        self.active_session_token = None

    def check_fingerprint(self, client_fp):
        """Validasi kecocokan sidik jari hardware browser."""
        if not self.device_fingerprint or not client_fp:
            return True  # Toleransi jika fingerprint belum terekam
        return str(self.device_fingerprint).strip() == str(client_fp).strip()

    def set_pin(self, pin):
        """Menyimpan hash PIN kasir."""
        if pin:
            self.pin_hash = generate_password_hash(str(pin).strip())
        else:
            self.pin_hash = None

    def check_pin(self, pin):
        """Memvalidasi PIN kasir."""
        if not self.pin_hash:
            return False
        return check_password_hash(self.pin_hash, str(pin).strip())

    @property
    def is_24_hours(self):
        """Cek apakah cabang beroperasi 24 jam nonstop."""
        if not self.operating_hours_start or not self.operating_hours_end:
            return True
        s = str(self.operating_hours_start).strip()
        e = str(self.operating_hours_end).strip()
        return not s or not e or (s == '00:00' and (e == '00:00' or e == '23:59'))

    @property
    def operating_hours_display(self):
        """Format tampilan jam operasional yang ramah pengguna."""
        if self.is_24_hours:
            return "24 Jam Nonstop"
        return f"{self.operating_hours_start} - {self.operating_hours_end} WIB"

    def is_within_operating_hours(self):
        """
        Memeriksa apakah saat ini berada dalam jam operasional kasir (WIB).
        Mendukung jam operasional reguler dan jam lintas tengah malam (misal: 18:00 - 04:00 WIB).
        """
        if self.is_24_hours:
            return True  # 24 jam jika tidak diatur atau 00:00 - 23:59
        
        start = str(self.operating_hours_start).strip()
        end = str(self.operating_hours_end).strip()

        try:
            wib_now = datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)
            cur_time_str = wib_now.strftime('%H:%M')
            if start == end:
                return True
            if start < end:
                # Shift reguler (misal: 07:00 s/d 22:00 WIB)
                return start <= cur_time_str <= end
            else:
                # Shift lintas tengah malam (misal: 18:00 s/d 04:00 WIB)
                return cur_time_str >= start or cur_time_str <= end
        except Exception:
            return True

    def get_today_spent(self):
        """Menghitung akumulasi pemakaian saldo cabang pada hari ini (WIB)."""
        from app.models.transaction import Transaction
        wib_now = datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)
        wib_today_start = wib_now.replace(hour=0, minute=0, second=0, microsecond=0)
        utc_today_start = wib_today_start - timedelta(hours=7)

        trxs = Transaction.query.filter(
            Transaction.user_id == self.user_id,
            Transaction.device_id == self.id,
            Transaction.payment_method == 'SALDO',
            Transaction.status.in_(['SUCCESS', 'PROCESSING', 'PENDING']),
            Transaction.created_at >= utc_today_start
        ).all()

        return sum(float(t.amount or 0.0) for t in trxs)

    def get_remaining_daily_limit(self):
        """Mengembalikan sisa limit harian kasir. Nilai -1 berarti tanpa limit (unlimited)."""
        if not self.daily_limit or self.daily_limit <= 0:
            return -1.0  # Unlimited
        spent = self.get_today_spent()
        return max(0.0, float(self.daily_limit) - spent)

    def is_low_balance(self):
        """Memeriksa apakah saldo cabang di bawah ambang batas peringatan."""
        threshold = self.low_balance_alert if self.low_balance_alert is not None else 100000.0
        return (self.branch_balance or 0.0) <= threshold
