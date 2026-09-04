from datetime import datetime, timedelta
from app.extensions import db

class DigiDepositTicket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount_requested = db.Column(db.Float, nullable=False)
    amount_transfer = db.Column(db.Float, nullable=False)
    bank = db.Column(db.String(30), nullable=False)
    owner_name = db.Column(db.String(100), nullable=False)
    account_number = db.Column(db.String(50), nullable=True)
    account_name = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    rc = db.Column(db.String(20), nullable=True)
    status = db.Column(db.String(20), default='PENDING')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def created_at_wib(self):
        wib = self.created_at + timedelta(hours=7)
        return wib.strftime("%d/%m/%Y %H:%M WIB")

    def __repr__(self):
        return f"<DigiDepositTicket #{self.id} {self.bank} Rp {self.amount_transfer}>"

