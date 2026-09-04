from datetime import datetime
from app.extensions import db

class BroadcastLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    target_type = db.Column(db.String(50), default='all')  # 'all', 'custom'
    recipient_count = db.Column(db.Integer, default=0)
    success_count = db.Column(db.Integer, default=0)
    failed_count = db.Column(db.Integer, default=0)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def created_at_wib(self):
        from datetime import timedelta
        wib = self.created_at + timedelta(hours=7)
        return wib.strftime("%d/%m/%Y %H:%M WIB")

    def __repr__(self):
        return f"<BroadcastLog #{self.id} {self.target_type}>"

