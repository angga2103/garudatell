from app import db

class Provider(db.Model):
    __tablename__ = "providers"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(100), nullable=False)

    # CORE DRIVER SYSTEM (SINGLE SOURCE)
    driver = db.Column(db.String(50), default="paymentkita")

    provider_type = db.Column(db.String(50), default="payment")

    config = db.Column(db.JSON, nullable=True)

    enabled = db.Column(db.Boolean, default=True)

    active = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, server_default=db.func.now())