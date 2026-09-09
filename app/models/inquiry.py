from app.extensions import db
from datetime import datetime

class PostpaidInquiry(db.Model):
    __tablename__ = 'postpaid_inquiry'

    id = db.Column(db.Integer, primary_key=True)
    ref_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    sku_code = db.Column(db.String(50), nullable=False)
    customer_no = db.Column(db.String(50), nullable=False)
    customer_name = db.Column(db.String(150), nullable=True)
    tarif = db.Column(db.String(50), nullable=True)
    daya = db.Column(db.String(50), nullable=True)
    lembar_tagihan = db.Column(db.Integer, default=1)
    tagihan_pokok = db.Column(db.Float, default=0.0)
    denda = db.Column(db.Float, default=0.0)
    admin_fee = db.Column(db.Float, default=0.0)
    total_amount = db.Column(db.Float, nullable=False)
    is_paid = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)

    user = db.relationship('User', backref=db.backref('inquiries', lazy=True))
