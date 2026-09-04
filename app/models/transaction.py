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

    __table_args__ = (
        db.Index('idx_trx_user_created', 'user_id', 'created_at'),
        db.Index('idx_trx_status_created', 'status', 'created_at'),
    )

    @property
    def created_at_wib(self):
        from datetime import timedelta
        if self.created_at:
            wib = self.created_at + timedelta(hours=7)
            return wib.strftime('%d-%m-%Y %H:%M')
        return 'Baru Saja'

    @property
    def target(self):
        return self.target_number

    @property
    def price(self):
        return self.amount


    # Relasi ke User
    user = db.relationship('User', backref=db.backref('transactions', lazy=True))
