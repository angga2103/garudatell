from app.extensions import db
from datetime import datetime
import json

class MuslimTrackRecord(db.Model):
    """
    Model penyimpanan rekaman harian Moeslem Daily Tracker terikat pada akun pengguna (user_id).
    Mendukung sinkronisasi awan (cloud sync) lintas perangkat dan riwayat permanen.
    """
    __tablename__ = 'muslim_track_records'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    date = db.Column(db.String(10), nullable=False, index=True) # Format: YYYY-MM-DD
    habits_data = db.Column(db.Text, default='{}')              # JSON String data checklist habits
    journal = db.Column(db.Text, default='')                   # Catatan harian / muhasabah
    score = db.Column(db.Integer, default=0)                   # Capaian produktivitas 0 - 100%
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'date', name='uq_user_date_muslimtrack'),
        db.Index('idx_muslimtrack_user_date', 'user_id', 'date'),
    )

    user = db.relationship('User', backref=db.backref('muslim_tracks', lazy='dynamic', cascade='all, delete-orphan'))

    def get_habits(self):
        """Mengembalikan data checklist habits dalam bentuk dictionary."""
        if not self.habits_data:
            return {}
        try:
            return json.loads(self.habits_data)
        except Exception:
            return {}

    def set_habits(self, data_dict):
        """Menyimpan data checklist habits ke bentuk JSON string."""
        if isinstance(data_dict, dict):
            self.habits_data = json.dumps(data_dict)
        elif isinstance(data_dict, str):
            self.habits_data = data_dict
        else:
            self.habits_data = '{}'

    def to_dict(self):
        """Representasi dictionary untuk respons REST API."""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'date': self.date,
            'habits': self.get_habits(),
            'journal': self.journal or '',
            'score': self.score or 0,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None,
        }
