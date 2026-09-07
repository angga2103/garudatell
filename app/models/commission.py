from datetime import datetime, timezone, timedelta
from app.extensions import db

def get_wib_datetime():
    return datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)

class CommissionLog(db.Model):
    __tablename__ = 'commission_logs'

    id = db.Column(db.Integer, primary_key=True)
    upline_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    downline_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transaction.id'), nullable=True, index=True)
    
    trx_amount = db.Column(db.Float, default=0.0)
    commission_amount = db.Column(db.Float, nullable=False, default=0.0)
    status = db.Column(db.String(20), default='earned', index=True) # 'earned', 'paid_out', 'cancelled'
    
    created_at = db.Column(db.DateTime, default=get_wib_datetime, index=True)
    payout_date = db.Column(db.DateTime, nullable=True)

    # Relasi
    upline = db.relationship('User', foreign_keys=[upline_id], backref='earned_commissions')
    downline = db.relationship('User', foreign_keys=[downline_id], backref='contributed_commissions')
    transaction = db.relationship('Transaction', backref='commission_entry')

    def __repr__(self):
        return f"<CommissionLog upline={self.upline_id} downline={self.downline_id} amount={self.commission_amount}>"
