from app.extensions import db

class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)
    description = db.Column(db.String(100), nullable=True)

    def __repr__(self):
        return f"<Setting {self.key}>"
