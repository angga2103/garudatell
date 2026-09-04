from datetime import datetime
from app.extensions import db

class PointLog(db.Model):
    __tablename__ = 'point_log'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    type = db.Column(db.String(30), nullable=False)  # EARN_TRX, CLAIM_TO_SALDO, ADMIN_ADJUST, RESET
    points = db.Column(db.Integer, nullable=False)   # +1, -150, etc.
    balance_added = db.Column(db.Float, default=0.0) # Saldo bertambah saat klaim
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship('User', backref=db.backref('point_logs', lazy='dynamic', order_by='PointLog.created_at.desc()'))

    def __repr__(self):
        return f"<PointLog {self.user_id} {self.type} {self.points}>"

