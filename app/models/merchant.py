from datetime import datetime, timezone, timedelta
from app.extensions import db

def get_wib_datetime():
    return datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)

class MerchantApiKey(db.Model):
    __tablename__ = 'merchant_api_keys'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    merchant_id = db.Column(db.String(32), unique=True, nullable=False, index=True)
    api_key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    secret_key = db.Column(db.String(64), nullable=False)
    name = db.Column(db.String(100), default='Kasir Utama', nullable=False)
    webhook_url = db.Column(db.String(255), nullable=True)
    ip_whitelist = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    tenant_id = db.Column(db.String(64), nullable=True, index=True)
    master_recovery_key = db.Column(db.String(32), nullable=True)
    created_at = db.Column(db.DateTime, default=get_wib_datetime, index=True)
    last_used_at = db.Column(db.DateTime, nullable=True)

    # Relasi ke User
    user = db.relationship('User', backref=db.backref('merchant_api_keys', lazy=True, cascade='all, delete-orphan'))

    def get_tenant_id(self):
        """Mendapatkan ID Toko (tenant slug) untuk sinkronisasi POS IPAY"""
        if getattr(self, 'tenant_id', None) and self.tenant_id:
            return self.tenant_id.strip()
        if self.webhook_url and 'tenant_id=' in self.webhook_url:
            import urllib.parse
            try:
                parsed = urllib.parse.urlparse(self.webhook_url)
                qs = urllib.parse.parse_qs(parsed.query)
                if 'tenant_id' in qs and qs['tenant_id']:
                    return qs['tenant_id'][0].strip()
            except Exception:
                pass
        import re
        clean = re.sub(r'[^a-zA-Z0-9]+', '-', (self.name or '').lower()).strip('-')
        clean = clean.replace('pos-', '').strip('-')
        return clean or f"store-{self.id}"

    @property
    def formatted_last_used_at(self):
        if not self.last_used_at:
            return "Belum pernah digunakan"
        if hasattr(self.last_used_at, 'strftime'):
            try:
                return self.last_used_at.strftime('%d/%m/%Y %H:%M WIB')
            except Exception:
                pass
        return str(self.last_used_at)

    @property
    def formatted_created_at(self):
        if not self.created_at:
            return "-"
        if hasattr(self.created_at, 'strftime'):
            try:
                return self.created_at.strftime('%d/%m/%Y %H:%M WIB')
            except Exception:
                pass
        return str(self.created_at)

    def __repr__(self):
        return f"<MerchantApiKey {self.merchant_id} user_id={self.user_id} active={self.is_active}>"


class MerchantProvisionRequest(db.Model):
    __tablename__ = 'merchant_provision_requests'

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    store_name = db.Column(db.String(120), nullable=False)
    owner_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), nullable=False, index=True)
    tenant_id = db.Column(db.String(100), nullable=True, index=True)
    webhook_url = db.Column(db.String(255), nullable=True)
    callback_url = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), default='PENDING', nullable=False, index=True)  # PENDING, APPROVED, REJECTED
    rejection_reason = db.Column(db.String(255), nullable=True)
    user_id = db.Column(db.Integer, nullable=True)
    merchant_id = db.Column(db.String(32), nullable=True)
    api_key = db.Column(db.String(64), nullable=True)
    secret_key = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=get_wib_datetime, index=True)
    updated_at = db.Column(db.DateTime, default=get_wib_datetime, onupdate=get_wib_datetime)


    @property
    def formatted_created_at(self):
        if not self.created_at:
            return "-"
        if hasattr(self.created_at, 'strftime'):
            try:
                return self.created_at.strftime('%d/%m/%Y %H:%M WIB')
            except Exception:
                pass
        return str(self.created_at)


class PosBroadcast(db.Model):
    __tablename__ = 'pos_broadcasts'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    level = db.Column(db.String(30), default='info', nullable=False)  # info, warning, promo, urgent
    target_merchant_id = db.Column(db.String(32), nullable=True, index=True)  # None / 'ALL' = semua kasir POS
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=get_wib_datetime, index=True)

    @property
    def formatted_created_at(self):
        if not self.created_at:
            return "-"
        if hasattr(self.created_at, 'strftime'):
            try:
                return self.created_at.strftime('%d/%m/%Y %H:%M WIB')
            except Exception:
                pass
        return str(self.created_at)


def ensure_merchant_provision_table():
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        if 'merchant_provision_requests' not in tables:
            MerchantProvisionRequest.__table__.create(db.engine)
        if 'pos_broadcasts' not in tables:
            PosBroadcast.__table__.create(db.engine)
    except Exception:
        pass


