from datetime import datetime, timedelta
import random
from app.extensions import db

class SupportTicket(db.Model):
    __tablename__ = 'support_tickets'

    id = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(30), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user_name = db.Column(db.String(100), nullable=False)
    user_phone = db.Column(db.String(30), nullable=False)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transaction.id'), nullable=True)
    category = db.Column(db.String(60), nullable=False, default='Transaksi Bermasalah')
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='OPEN')  # 'OPEN', 'PROCESS', 'RESOLVED', 'CLOSED'
    telegram_sent = db.Column(db.Boolean, default=False)
    telegram_response = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('support_tickets', lazy=True))
    transaction = db.relationship('Transaction', backref=db.backref('support_tickets', lazy=True))

    @staticmethod
    def generate_ticket_number():
        """Menghasilkan nomor tiket unik format CS-YYYYMMDD-XXXX."""
        now_str = datetime.utcnow().strftime("%Y%m%d")
        rand_num = random.randint(1000, 9999)
        return f"CS-{now_str}-{rand_num}"

    @property
    def created_at_wib(self):
        wib = self.created_at + timedelta(hours=7)
        return wib.strftime("%d %b %Y, %H:%M WIB")

    @property
    def clean_phone_for_wa(self):
        raw = self.user_phone or ""
        clean = "".join([c for c in raw if c.isdigit()])
        if clean.startswith("0"):
            clean = "62" + clean[1:]
        elif not clean.startswith("62") and clean:
            clean = "62" + clean
        return clean

    def __repr__(self):
        return f"<SupportTicket {self.ticket_number} [{self.status}] {self.category}>"

