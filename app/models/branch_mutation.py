from app.extensions import db
from datetime import datetime, timezone, timedelta

class BranchMutation(db.Model):
    __tablename__ = 'branch_mutation'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('trusted_device.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    type = db.Column(db.String(30), nullable=False, index=True)  # 'TOPUP_FROM_OWNER', 'WITHDRAW_TO_OWNER', 'SALE', 'REFUND'
    amount = db.Column(db.Float, nullable=False)
    balance_before = db.Column(db.Float, default=0.0)
    balance_after = db.Column(db.Float, default=0.0)
    description = db.Column(db.String(255), nullable=True)
    shift_name = db.Column(db.String(100), nullable=True, default='Kasir')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        db.Index('idx_bmut_dev_created', 'device_id', 'created_at'),
        db.Index('idx_bmut_user_created', 'user_id', 'created_at'),
    )

    @property
    def created_at_wib(self):
        if self.created_at:
            wib = self.created_at + timedelta(hours=7)
            return wib.strftime('%d-%m-%Y %H:%M')
        return '-'

    @property
    def date_wib(self):
        if self.created_at:
            wib = self.created_at + timedelta(hours=7)
            return wib.strftime('%d-%m-%Y')
        return '-'

    @property
    def time_wib(self):
        if self.created_at:
            wib = self.created_at + timedelta(hours=7)
            return wib.strftime('%H:%M')
        return '-'

    device = db.relationship('TrustedDevice', backref=db.backref('mutations', lazy='dynamic', cascade='all, delete-orphan'))
    user = db.relationship('User', backref=db.backref('branch_mutations', lazy='dynamic'))

