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

def create_app(test_config=None):
    app = Flask(__name__)
    basedir = os.path.abspath(os.path.dirname(__file__))
    root_dir = os.path.dirname(basedir)
    load_dotenv(os.path.join(root_dir, '.env'))

    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'garudatel.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': 30,
        'max_overflow': 50,
        'pool_timeout': 30,
        'pool_recycle': 1800
    }
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or secrets.token_hex(32)
    app.config['RATELIMIT_STORAGE_URI'] = os.getenv('RATELIMIT_STORAGE_URI', 'memory://')
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    
    # Flask-Caching Configuration
    app.config['CACHE_TYPE'] = 'SimpleCache'
    app.config['CACHE_DEFAULT_TIMEOUT'] = 300
    app.config['CACHE_THRESHOLD'] = 1000

    if test_config:
        app.config.update(test_config)
    
    # In-memory SQLite uses StaticPool which does not accept pool_size/max_overflow/pool_timeout
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if ':memory:' in db_uri or db_uri == 'sqlite://':
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {}
    
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
        try:
            return User.query.get(int(user_id))
        except (ValueError, TypeError):
            return None
    migrate.init_app(app, db)
    app.jinja_env.globals['hasattr'] = hasattr

    # Auto-migration ringan untuk kolom cs_reply pada support_tickets
    with app.app_context():
        try:
            from sqlalchemy import inspect, text
            inspector = inspect(db.engine)
            if 'support_tickets' in inspector.get_table_names():
                existing_cols = [c['name'] for c in inspector.get_columns('support_tickets')]
                if 'cs_reply' not in existing_cols:
                    db.session.execute(text('ALTER TABLE support_tickets ADD COLUMN cs_reply TEXT'))
                if 'cs_replied_at' not in existing_cols:
                    db.session.execute(text('ALTER TABLE support_tickets ADD COLUMN cs_replied_at DATETIME'))
                if 'admin_reply' not in existing_cols:
                    db.session.execute(text('ALTER TABLE support_tickets ADD COLUMN admin_reply TEXT'))
                if 'admin_replied_at' not in existing_cols:
                    db.session.execute(text('ALTER TABLE support_tickets ADD COLUMN admin_replied_at DATETIME'))
                if 'admin_name' not in existing_cols:
                    db.session.execute(text('ALTER TABLE support_tickets ADD COLUMN admin_name VARCHAR(100)'))
                db.session.commit()
        except Exception:
            pass

    # Impor Blueprint
    from app.routes.user import user_bp
    from app.routes.admin import admin_bp
    from app.routes.auth import auth_bp
    from app.routes.transaction import trx_bp
    from app.routes.kasir import kasir_bp
    from app.routes.admin_provider import admin_provider_bp
    from app.routes.merchant_api import merchant_api_bp
    
    # Daftarkan Blueprint
    app.register_blueprint(user_bp) 
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(admin_provider_bp, url_prefix='/admin')
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(trx_bp, url_prefix='/trx')
    app.register_blueprint(kasir_bp, url_prefix='/kasir')
    app.register_blueprint(merchant_api_bp, url_prefix='/api/v1')

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

    # Daftarkan Alias Route Cron Job Otomatis (/api/cron/sync-products & /api/cron/check-low-balance)
    from app.routes.admin import cron_sync_products, cron_check_low_balance
    app.add_url_rule('/api/cron/sync-products', endpoint='alias_api_cron_sync_products', view_func=cron_sync_products, methods=['GET', 'POST'])
    app.add_url_rule('/api/cron/check-low-balance', endpoint='alias_api_cron_check_low_balance', view_func=cron_check_low_balance, methods=['GET', 'POST'])

    # Daftarkan Alias Route AJAX Auth (/api/auth_ajax & /api/check_wa_status)
    from app.routes.auth import auth_ajax, check_wa_status
    app.add_url_rule('/api/auth_ajax', endpoint='alias_api_auth_ajax', view_func=auth_ajax, methods=['POST'])
    app.add_url_rule('/api/check_wa_status', endpoint='alias_api_check_wa_status', view_func=check_wa_status, methods=['GET'])

    @app.cli.command("sync-digiflazz")
    def cli_sync_digiflazz():
        """Sinkronisasi katalog Digiflazz via terminal CLI VPS."""
        from app.services.digiflazz import sync_products
        ok, msg = sync_products(force=True)
        print(f"[{'SUCCESS' if ok else 'FAILED'}] {msg}")

    with app.app_context():
        from app.models import CommissionLog, TrustedDevice, PostpaidInquiry, DeviceSessionLog, MerchantApiKey  # Pastikan seluruh model terdaftar di metadata SQLAlchemy
        db.create_all()
        try:
            inspector = inspect(db.engine)

            # Auto-migrate kolom baru tabel user jika belum ada (Self-Healing)
            if 'user' in inspector.get_table_names():
                user_cols = [c['name'] for c in inspector.get_columns('user')]
                new_user_cols = [
                    ('role_expires_at', 'DATETIME'),
                    ('upline_id', 'INTEGER REFERENCES user(id)'),
                    ('commission_balance', 'REAL DEFAULT 0.0'),
                    ('last_reminded_at', 'DATETIME'),
                    ('referral_code', 'VARCHAR(20)'),
                    ('is_device_lock_enabled', 'BOOLEAN DEFAULT 0'),
                    ('last_low_balance_notified_at', 'DATETIME'),
                    ('current_session_token', 'VARCHAR(64)'),
                    ('last_active_at', 'DATETIME'),
                    ('active_device_name', 'VARCHAR(150)'),
                    ('active_device_ip', 'VARCHAR(50)'),
                    ('active_device_uuid', 'VARCHAR(64)')
                ]
                with db.engine.connect() as conn:
                    for c_name, c_type in new_user_cols:
                        if c_name not in user_cols:
                            try:
                                conn.execute(db.text(f'ALTER TABLE user ADD COLUMN {c_name} {c_type}'))
                                app.logger.info(f"[AUTO-MIGRATE] Kolom user.{c_name} berhasil ditambahkan ke database.")
                            except Exception as ex_col:
                                app.logger.warning(f"Gagal tambah kolom user.{c_name}: {ex_col}")
                    conn.commit()

            # Auto-migrate kolom baru tabel transaction jika belum ada
            if 'transaction' in inspector.get_table_names():
                trx_cols = [c['name'] for c in inspector.get_columns('transaction')]
                new_trx_cols = [
                    ('device_id', 'INTEGER REFERENCES trusted_device(id)'),
                    ('device_name', 'VARCHAR(100)')
                ]
                with db.engine.connect() as conn:
                    for c_name, c_type in new_trx_cols:
                        if c_name not in trx_cols:
                            try:
                                conn.execute(db.text(f'ALTER TABLE `transaction` ADD COLUMN {c_name} {c_type}'))
                                app.logger.info(f"[AUTO-MIGRATE] Kolom transaction.{c_name} berhasil ditambahkan ke database.")
                            except Exception as ex_col:
                                app.logger.warning(f"Gagal tambah kolom transaction.{c_name}: {ex_col}")
                    conn.commit()

            # Auto-migrate kolom baru tabel trusted_device jika belum ada
            if 'trusted_device' in inspector.get_table_names():
                dev_cols = [c['name'] for c in inspector.get_columns('trusted_device')]
                new_dev_cols = [
                    ('pin_hash', 'VARCHAR(200)'),
                    ('daily_limit', 'REAL DEFAULT 0.0'),
                    ('operating_hours_start', 'VARCHAR(5)'),
                    ('operating_hours_end', 'VARCHAR(5)'),
                    ('activation_token', 'VARCHAR(64)'),
                    ('activation_expires_at', 'DATETIME'),
                    ('session_version', 'INTEGER DEFAULT 1'),
                    ('active_session_token', 'VARCHAR(64)'),
                    ('device_fingerprint', 'VARCHAR(128)'),
                    ('branch_balance', 'REAL DEFAULT 0.0'),
                    ('low_balance_alert', 'REAL DEFAULT 100000.0')
                ]
                with db.engine.connect() as conn:
                    for c_name, c_type in new_dev_cols:
                        if c_name not in dev_cols:
                            try:
                                conn.execute(db.text(f'ALTER TABLE trusted_device ADD COLUMN {c_name} {c_type}'))
                                app.logger.info(f"[AUTO-MIGRATE] Kolom trusted_device.{c_name} berhasil ditambahkan ke database.")
                            except Exception as ex_col:
                                app.logger.warning(f"Gagal tambah kolom trusted_device.{c_name}: {ex_col}")
                    conn.commit()

            # Pastikan tabel branch_mutation terbuat jika belum ada
            if 'branch_mutation' not in inspector.get_table_names():
                try:
                    from app.models.branch_mutation import BranchMutation
                    BranchMutation.__table__.create(db.engine)
                    app.logger.info("[AUTO-MIGRATE] Tabel branch_mutation berhasil dibuat.")
                except Exception as ex_tbl:
                    app.logger.warning(f"Gagal buat tabel branch_mutation: {ex_tbl}")

            # Pastikan tabel merchant_api_keys terbuat jika belum ada (Self-Healing)
            if 'merchant_api_keys' not in inspector.get_table_names():
                try:
                    from app.models.merchant import MerchantApiKey
                    MerchantApiKey.__table__.create(db.engine, checkfirst=True)
                    app.logger.info("[AUTO-MIGRATE] Tabel merchant_api_keys berhasil dibuat.")
                except Exception as ex_tbl:
                    app.logger.warning(f"Gagal buat tabel merchant_api_keys: {ex_tbl}")

            # Auto-migrate kolom baru tabel product jika belum ada (description & is_manual_desc)
            if 'product' in inspector.get_table_names():
                prod_cols = [c['name'] for c in inspector.get_columns('product')]
                new_prod_cols = [
                    ('description', 'TEXT'),
                    ('is_manual_desc', 'BOOLEAN DEFAULT 0')
                ]
                with db.engine.connect() as conn:
                    for c_name, c_type in new_prod_cols:
                        if c_name not in prod_cols:
                            try:
                                conn.execute(db.text(f'ALTER TABLE product ADD COLUMN {c_name} {c_type}'))
                                app.logger.info(f"[AUTO-MIGRATE] Kolom product.{c_name} berhasil ditambahkan ke database.")
                            except Exception as ex_col:
                                app.logger.warning(f"Gagal tambah kolom product.{c_name}: {ex_col}")
                    conn.commit()

            if 'otp_codes' in inspector.get_table_names():
                cols = [c['name'] for c in inspector.get_columns('otp_codes')]
                if 'attempts' not in cols:
                    with db.engine.connect() as conn:
                        conn.execute(db.text('ALTER TABLE otp_codes ADD COLUMN attempts INTEGER DEFAULT 0'))
                        conn.commit()

            # Perbaiki catatan transaksi lama di database yang terlanjur menyimpan pesan saldo provider habis
            if 'transaction' in inspector.get_table_names():
                from app.models.transaction import Transaction
                from app.services.provider_helper import USER_FRIENDLY_SN_MSG, PROVIDER_BALANCE_KEYWORDS
                from sqlalchemy import or_
                filters = [Transaction.sn.ilike(f'%{kw}%') for kw in PROVIDER_BALANCE_KEYWORDS]
                old_trxs = Transaction.query.filter(
                    Transaction.status.in_(['FAILED', 'GAGAL', 'CANCELLED']),
                    or_(*filters)
                ).all()
                if old_trxs:
                    for ot in old_trxs:
                        ot.sn = USER_FRIENDLY_SN_MSG
                    db.session.commit()
                    app.logger.info(f"[AUTO-CLEAN] Berhasil membersihkan {len(old_trxs)} data transaksi lama.")

            # Bersihkan produk Bebas Nominal yang telah dihapus di Digiflazz
            if 'product' in inspector.get_table_names():
                from app.models.product import Product
                bebas_deleted_skus = ['post685480', 'post685481', 'post685482', 'post685483', 'post685485', 'post706873']
                deleted_bebas = Product.query.filter(Product.sku_code.in_(bebas_deleted_skus)).delete(synchronize_session=False)
                if deleted_bebas:
                    db.session.commit()
                    app.logger.info(f"[AUTO-CLEAN] Berhasil membersihkan {deleted_bebas} produk Bebas Nominal yang telah dihapus di Digiflazz.")
        except Exception as e:
            app.logger.warning(f"Auto-migration / cleanup failed: {e}")

    # Pastikan direktori uploads untuk logo toko tersedia
    uploads_dir = os.path.join(basedir, 'static', 'uploads')
    os.makedirs(uploads_dir, exist_ok=True)

    # Middleware: Validasi 1 Akun 1 Login Aktif & Inaktivitas 23 Jam
    @app.before_request
    def validate_single_session():
        # Jangan proses jika request asset statis, health check, webhook callback
        if not request.endpoint or request.endpoint == 'static' or request.path.startswith('/static') or request.path in ['/health', '/api/health'] or request.path.startswith('/callback') or request.path.startswith('/api/callback'):
            return

        from flask_login import current_user, logout_user
        from flask import session, jsonify, redirect, flash
        from datetime import datetime
        from app.services.session_service import adopt_session_gracefully, is_session_expired_inactivity, log_session_event

        # Hanya proses untuk akun pengguna (bukan Admin panel)
        if current_user and current_user.is_authenticated and hasattr(current_user, 'current_session_token'):
            # 1. ADOPSI SESI MULUS (Zero Disruption untuk akun yang sedang login di produksi)
            if not current_user.current_session_token:
                adopt_session_gracefully(current_user, request, session)
                return

            client_token = session.get('session_token')
            
            # Jika cookie session belum memiliki token (misal login aktif sebelum update), sinkronkan
            if not client_token and current_user.current_session_token:
                session['session_token'] = current_user.current_session_token
                client_token = current_user.current_session_token

            # 2. CEK KECOCOKAN TOKEN SESI (Apakah sesi telah diputus oleh Admin atau Perangkat Baru)
            if client_token and client_token != current_user.current_session_token:
                logout_user()
                session.pop('session_token', None)
                if request.is_json or request.path.startswith('/api/') or request.path.startswith('/trx/'):
                    return jsonify({
                        'status': 'session_expired',
                        'message': 'Sesi Anda telah berakhir karena akun telah dipindahkan ke perangkat lain.'
                    }), 401
                flash('Sesi Anda telah berakhir karena akun Anda aktif di perangkat lain.', 'warning')
                return redirect('/profil')

            # 3. CEK KEDALUWARSA INAKTIVITAS 23 JAM
            if is_session_expired_inactivity(current_user, timeout_hours=23):
                old_dev = current_user.active_device_name
                old_ip = current_user.active_device_ip
                log_session_event(
                    user_id=current_user.id,
                    phone=current_user.phone,
                    event_type='AUTO_EXPIRED',
                    device_name=old_dev,
                    ip_address=old_ip,
                    details='Sesi otomatis kedaluwarsa setelah 23 jam tanpa aktivitas'
                )
                current_user.current_session_token = None
                current_user.last_active_at = None
                current_user.active_device_uuid = None
                db.session.commit()
                logout_user()
                session.pop('session_token', None)
                if request.is_json or request.path.startswith('/api/') or request.path.startswith('/trx/'):
                    return jsonify({
                        'status': 'session_expired',
                        'message': 'Sesi Anda telah berakhir setelah 23 jam tidak aktif.'
                    }), 401
                flash('Sesi Anda telah berakhir setelah 23 jam tidak aktif. Silakan masuk kembali.', 'info')
                return redirect('/profil')

            # 4. THROTTLED TIMESTAMP UPDATE (Update last_active_at maksimal 1x per 60 detik)
            now = datetime.utcnow()
            if not current_user.last_active_at or (now - current_user.last_active_at).total_seconds() > 60:
                current_user.last_active_at = now
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()

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

    # Template Filter: Format SN / Keterangan Bersih untuk Pengguna
    @app.template_filter('format_sn')
    def format_sn(sn_val, status=None):
        from app.services.provider_helper import format_display_sn
        return format_display_sn(sn_val, status)

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

    # Security Headers & Dynamic Gzip Compression Middleware
    @app.after_request
    def apply_security_and_compression(response):
        # Security Headers Produksi (OWASP Core Security Principles)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'

        # Cache-Control untuk Aset Statis Lokal (Browser Caching)
        if request.path.startswith('/static/') and response.status_code == 200:
            response.headers['Cache-Control'] = 'public, max-age=86400'

        # Gzip compression
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
