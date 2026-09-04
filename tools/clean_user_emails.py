import os
import sys

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User

app = create_app()
with app.app_context():
    users = User.query.all()
    count = 0
    for u in users:
        val = str(u.email).strip() if u.email is not None else ""
        if val in ("", "''", '""', "None", "none", "null"):
            u.email = None
            count += 1
    db.session.commit()
    print(f"Pembersihan selesai: {count} user email diperbaiki menjadi NULL/None.")
    for u in User.query.all():
        print(f"ID: {u.id} | Nama: {u.name} | Phone: {u.phone} | Email: {repr(u.email)} | Aktif: {u.is_active}")

