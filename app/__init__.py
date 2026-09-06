from flask import Flask, request
from app.extensions import db, migrate, cache, csrf, limiter
from dotenv import load_dotenv
from sqlalchemy import event, inspect
from sqlalchemy.engine import Engine
import os
import secrets
import logging
from logging.handlers import RotatingFileHandler

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Mengaktifkan SQLite WAL (Write-Ahead Logging) mode & busy_timeout untuk mencegah database locked."""
    if hasattr(dbapi_connection, "cursor"):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=10000;")
        except Exception:
            pass
        finally:
            cursor.close()

def create_app():
    app = Flask(__name__)
    basedir = os.path.abspath(os.path.dirname(__file__))
    root_dir = os.path.dirname(basedir)
    load_dotenv(os.path.join(root_dir, '.env'))

    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'garudatel.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or secrets.token_hex(32)
    app.config['RATELIMIT_STORAGE_URI'] = 'memory://'
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    
    # Flask-Caching Configuration
    app.config['CACHE_TYPE'] = 'SimpleCache'
    app.config['CACHE_DEFAULT_TIMEOUT'] = 300
    app.config['CACHE_THRESHOLD'] = 1000
    
    cache.init_app(app)
    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    # Setup Structured Rotating File Logger
    log_dir = os.path.join(root_dir, 'storage', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    if not app.debug or os.getenv('WERKZEUG_RUN_MAIN') == 'true':
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, 'garudatel.log'),
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setFormatter(logging.Formatter(
            '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
        ))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
        app.logger.setLevel(logging.INFO)

    # Setup Flask-Login
    from flask_login import LoginManager
    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Silakan login terlebih dahulu.'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        from app.models.user import User
        return User.query.get(int(user_id))
        
    migrate.init_app(app, db)

    # Impor Blueprint
    from app.routes.user import user_bp
    from app.routes.admin import admin_bp
    from app.routes.auth import auth_bp
    from app.routes.transaction import trx_bp
    
    # Daftarkan Blueprint
    app.register_blueprint(user_bp) 
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(trx_bp, url_prefix='/trx')

    # Daftarkan Alias Route Webhook Callback (/api/callback/... & /callback/...)
    from app.routes.transaction import callback_digiflazz, callback_paymentkita, callback_pakasir, callback_vipreseller
    webhook_routes = [
        ('/api/callback/vipreseller', callback_vipreseller),
        ('/callback/vipreseller', callback_vipreseller),
        ('/api/callback/digiflazz', callback_digiflazz),
        ('/callback/digiflazz', callback_digiflazz),
        ('/api/callback/paymentkita', callback_paymentkita),
        ('/callback/paymentkita', callback_paymentkita),
        ('/api/callback/pakasir', callback_pakasir),
        ('/callback/pakasir', callback_pakasir),
    ]
    for path, handler in webhook_routes:
        endpoint_name = 'alias_' + path.replace('/', '_').strip('_')
        app.add_url_rule(path, endpoint=endpoint_name, view_func=handler, methods=['POST'])

    # Daftarkan Alias Route AJAX Auth (/api/auth_ajax & /api/check_wa_status)
    from app.routes.auth import auth_ajax, check_wa_status
    app.add_url_rule('/api/auth_ajax', endpoint='alias_api_auth_ajax', view_func=auth_ajax, methods=['POST'])
    app.add_url_rule('/api/check_wa_status', endpoint='alias_api_check_wa_status', view_func=check_wa_status, methods=['GET'])

    with app.app_context():
        db.create_all()
        try:
            inspector = inspect(db.engine)
            if 'otp_codes' in inspector.get_table_names():
                cols = [c['name'] for c in inspector.get_columns('otp_codes')]
                if 'attempts' not in cols:
                    with db.engine.connect() as conn:
                        conn.execute(db.text('ALTER TABLE otp_codes ADD COLUMN attempts INTEGER DEFAULT 0'))
                        conn.commit()
        except Exception as e:
            app.logger.warning(f"Auto-migration failed: {e}")

    # Pastikan direktori uploads untuk logo toko tersedia
    uploads_dir = os.path.join(basedir, 'static', 'uploads')
    os.makedirs(uploads_dir, exist_ok=True)

    # Global Context Processor: Injeksi Pengaturan Toko Dinamis ke Seluruh Template Jinja2
    @app.context_processor
    def inject_store():
        try:
            from app.services.setting_service import get_store_settings
            return dict(store=get_store_settings())
        except Exception:
            return dict(store={
                'name': 'GarudaTel',
                'tagline': 'Platform PPOB & Top Up Terpercaya',
                'whatsapp_group': '',
                'receipt_footer': 'Terima kasih atas kepercayaan Anda!',
                'logo': '',
                'logo_url': ''
            })

    # Endpoint Healthcheck untuk Uptime Monitoring
    @app.route('/health', methods=['GET'])
    @app.route('/api/health', methods=['GET'])
    @csrf.exempt
    def health_check():
        import time
        from flask import jsonify
        db_status = 'connected'
        http_status = 200
        try:
            db.session.execute(db.text('SELECT 1')).scalar()
        except Exception as e:
            db_status = f'error: {str(e)}'
            http_status = 503

        version = '2.0.0'
        version_file = os.path.join(root_dir, 'VERSION')
        if os.path.exists(version_file):
            try:
                with open(version_file, 'r') as vf:
                    version = vf.read().strip()
            except Exception:
                pass

        return jsonify({
            'status': 'healthy' if http_status == 200 else 'unhealthy',
            'database': db_status,
            'version': version,
            'timestamp': int(time.time()),
            'environment': 'production' if not app.debug else 'development'
        }), http_status

    # Dynamic Gzip Compression Middleware untuk transfer cepat & hemat bandwidth
    @app.after_request
    def compress_response(response):
        import gzip
        accept_encoding = request.headers.get('Accept-Encoding', '')
        if (response.status_code < 300 and 
            'gzip' in accept_encoding.lower() and 
            'Content-Encoding' not in response.headers):
            content_type = response.headers.get('Content-Type', '')
            if any(t in content_type for t in ['text/html', 'application/json', 'text/css', 'javascript']):
                response.direct_passthrough = False
                data = response.get_data()
                if len(data) > 1024:
                    compressed = gzip.compress(data, compresslevel=6)
                    response.set_data(compressed)
                    response.headers['Content-Encoding'] = 'gzip'
                    response.headers['Content-Length'] = len(compressed)
        return response

    return app
