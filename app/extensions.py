from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_caching import Cache
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

db = SQLAlchemy()
migrate = Migrate()
cache = Cache()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=["1000 per day", "200 per hour"])
