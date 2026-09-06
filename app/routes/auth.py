from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from app.models.user import User
from app.extensions import db, csrf, limiter
from app.wa_helper import kirim_wa_otp
import random
import time
import json
import os

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/api/check_wa_status', methods=['GET'])
@csrf.exempt
def check_wa_status():
    from app.wa_helper import is_wa_bot_connected
    return jsonify({'connected': is_wa_bot_connected()})

@auth_bp.route('/api/auth_ajax', methods=['POST'])
@csrf.exempt
@limiter.limit("30 per minute")
def auth_ajax():
    try:
        data = request.get_json() or {}
        action = data.get('action')
        phone = data.get('phone')
        password = data.get('password')

        if action == 'check_wa_status':
            from app.wa_helper import is_wa_bot_connected
            return jsonify({'status': 'success', 'connected': is_wa_bot_connected()})
        if action == 'request_otp_register':
            from app.services.otp_service import create_otp
            name = data.get('name')
            if not name:
                return jsonify({'status': 'error', 'message': 'Nama lengkap wajib diisi!'})
                
            existing_user = User.query.filter_by(phone=phone).first()
            if existing_user:
                return jsonify({'status': 'error', 'message': 'Nomor WhatsApp sudah terdaftar! Silakan Masuk.'})
            
            # Generate OTP & Simpan ke DB dengan password ter-hash
            p_hash = generate_password_hash(password)
            otp_kode = create_otp(phone, action='register', username=name, password_hash=p_hash)
                
            # Kirim Pesan via Bot WA
            berhasil = kirim_wa_otp(phone, otp_kode)
            if berhasil:
                return jsonify({'status': 'otp_sent', 'message': 'OTP berhasil dikirim ke WhatsApp Anda!'})
            else:
                return jsonify({'status': 'error', 'message': 'Gagal mengirim OTP. Pastikan Bot WhatsApp admin aktif.'})

        # ==========================================
        # LOGIKA VERIFIKASI OTP & DAFTAR
        # ==========================================
        elif action == 'verify_otp_register':
            from app.services.otp_service import verify_otp
            name = data.get('name')
            otp_input = data.get('otp')
            
            if not otp_input:
                return jsonify({'status': 'error', 'message': 'Masukkan kode OTP!'})
                
            is_valid, msg, user_data = verify_otp(phone, otp_input, action='register')
            if not is_valid:
                return jsonify({'status': 'error', 'message': msg})
                
            # Mendaftarkan User
            hashed_password = user_data.get('password_hash') or generate_password_hash(password)
            new_user = User(
                name=name,
                phone=phone,
                password_hash=hashed_password,
                role='user',
                balance=0.0,
                is_active=True
            )
            db.session.add(new_user)
            db.session.commit()
            
            login_user(new_user)
            return jsonify({'status': 'success', 'message': 'Verifikasi berhasil! Mengalihkan...'})
            
        # ==========================================
        # LOGIKA MINTA OTP LUPA PASSWORD
        # ==========================================
        elif action == 'request_otp_reset':
            from app.services.otp_service import create_otp
            user = User.query.filter_by(phone=phone).first()
            if not user:
                return jsonify({'status': 'error', 'message': 'Nomor WhatsApp tidak terdaftar di sistem kami.'})
            
            otp_kode = create_otp(phone, action='reset_password')
                
            berhasil = kirim_wa_otp(phone, otp_kode)
            if berhasil:
                return jsonify({'status': 'otp_sent', 'message': 'OTP Reset Password telah dikirim ke WhatsApp Anda!'})
            else:
                return jsonify({'status': 'error', 'message': 'Gagal mengirim pesan OTP.'})

        # ==========================================
        # LOGIKA VERIFIKASI OTP & UBAH PASSWORD
        # ==========================================
        elif action == 'verify_otp_reset':
            from app.services.otp_service import verify_otp
            otp_input = data.get('otp')
            new_password = data.get('new_password')
            
            if not otp_input or not new_password:
                return jsonify({'status': 'error', 'message': 'Isi kode OTP dan Password Baru!'})
                
            is_valid, msg, _ = verify_otp(phone, otp_input, action='reset_password')
            if not is_valid:
                return jsonify({'status': 'error', 'message': msg})
                
            user = User.query.filter_by(phone=phone).first()
            if user:
                user.password_hash = generate_password_hash(new_password)
                db.session.commit()
                return jsonify({'status': 'success', 'message': 'Password berhasil diubah! Silakan Masuk.'})
            else:
                return jsonify({'status': 'error', 'message': 'Akun tidak ditemukan.'})

        # ==========================================
        # LOGIKA PERMINTAAN BANTUAN OTP DARURAT KE CS TELEGRAM
        # ==========================================
        # ==========================================
        # LOGIKA PERMINTAAN BANTUAN OTP MANUAL (PERSETUJUAN ADMIN & CS)
        # ==========================================
        elif action in ['request_manual_otp', 'request_emergency_otp']:
            from app.models.otp_manual import OtpManualRequest
            from app.services.telegram_service import send_emergency_otp_request
            from app.services.otp_service import get_phone_variants
            import json

            user_name = data.get('name') or None
            purpose = data.get('action_type') or data.get('purpose', 'Pendaftaran / Masuk Akun')
            temp_data_raw = data.get('temp_data') or None

            clean_num = ''.join(filter(str.isdigit, str(phone)))
            variants = get_phone_variants(clean_num)

            # Cek status penolakan
            latest_rejection = OtpManualRequest.query.filter(
                OtpManualRequest.phone.in_(variants),
                OtpManualRequest.status == 'REJECTED'
            ).order_by(OtpManualRequest.id.desc()).first()

            if latest_rejection:
                reason = latest_rejection.rejection_reason or 'Permintaan ditolak oleh Administrator'
                return jsonify({
                    'status': 'rejected',
                    'rejection_reason': reason,
                    'message': f"Permintaan OTP manual untuk nomor ini sebelumnya telah DITOLAK oleh Admin/CS.\nAlasan: \"{reason}\".\nSilakan hubungi CS jika Anda merasa ini adalah kekeliruan."
                })

            # Cek jika ada request PENDING yang masih berjalan
            pending_req = OtpManualRequest.query.filter(
                OtpManualRequest.phone.in_(variants),
                OtpManualRequest.status == 'PENDING'
            ).order_by(OtpManualRequest.id.desc()).first()

            if pending_req:
                return jsonify({
                    'status': 'pending_approval',
                    'request_id': pending_req.id,
                    'message': 'Permintaan bantuan Anda sedang menunggu persetujuan Admin/CS.'
                })

            # Buat record baru
            temp_str = json.dumps(temp_data_raw) if isinstance(temp_data_raw, dict) else (temp_data_raw or None)
            new_req = OtpManualRequest(
                phone=clean_num,
                name=user_name,
                action=purpose,
                temp_data=temp_str,
                status='PENDING',
                ip_address=request.remote_addr
            )
            db.session.add(new_req)
            db.session.commit()

            # Kirim notifikasi ke Bot CS Telegram
            send_emergency_otp_request(
                phone=clean_num,
                otp_code=None,
                user_name=user_name,
                action_type=purpose,
                request_id=new_req.id,
                status='PENDING'
            )

            return jsonify({
                'status': 'pending_approval',
                'request_id': new_req.id,
                'message': 'Permintaan bantuan OTP Manual telah diteruskan ke Admin & CS Telegram kami. Mohon menunggu persetujuan Admin...'
            })

        elif action == 'check_manual_otp_status':
            from app.models.otp_manual import OtpManualRequest
            from app.services.otp_service import get_phone_variants

            req_id = data.get('request_id')
            manual_req = None
            if req_id:
                manual_req = OtpManualRequest.query.get(req_id)
            elif phone:
                clean_num = ''.join(filter(str.isdigit, str(phone)))
                variants = get_phone_variants(clean_num)
                manual_req = OtpManualRequest.query.filter(OtpManualRequest.phone.in_(variants)).order_by(OtpManualRequest.id.desc()).first()

            if not manual_req:
                return jsonify({'status': 'not_found', 'message': 'Permintaan tidak ditemukan.'})

            return jsonify({
                'status': manual_req.status,
                'rejection_reason': manual_req.rejection_reason,
                'is_expired': manual_req.is_expired()
            })

        # ==========================================
        # LOGIKA DAFTAR BARU (REGISTER)
        # ==========================================
        if action == 'register':
            name = data.get('name')
            if not name:
                return jsonify({'status': 'error', 'message': 'Nama lengkap wajib diisi!'})
                
            # Cek apakah nomor HP sudah ada di database
            existing_user = User.query.filter_by(phone=phone).first()
            if existing_user:
                return jsonify({'status': 'error', 'message': 'Nomor WhatsApp sudah terdaftar! Silakan Masuk.'})
            
            # Buat user baru (menyesuaikan field database yang valid)
            hashed_password = generate_password_hash(password)
            new_user = User(
                name=name,
                phone=phone,
                password_hash=hashed_password,
                role='user',
                balance=0.0,
                is_active=True
            )
            db.session.add(new_user)
            db.session.commit()
            
            # Langsung otomatis login setelah daftar
            login_user(new_user)
            return jsonify({'status': 'success', 'message': 'Pendaftaran berhasil! Mengalihkan...'})

        # ==========================================
        # LOGIKA MASUK (LOGIN)
        # ==========================================
        elif action == 'login':
            user = User.query.filter_by(phone=phone).first()
            
            # Verifikasi user dan cocokkan kata sandi (menggunakan password_hash)
            if user and check_password_hash(user.password_hash, password):
                if not user.is_active:
                    return jsonify({'status': 'error', 'message': 'Akun Anda dinonaktifkan. Hubungi Admin.'})
                
                login_user(user)
                return jsonify({'status': 'success', 'message': 'Login berhasil! Mengalihkan...'})
            else:
                return jsonify({'status': 'error', 'message': 'Nomor WhatsApp atau Kata Sandi salah!'})

        return jsonify({'status': 'error', 'message': 'Aksi tidak valid!'})

    except Exception as e:
        print(f"Error pada auth_ajax: {e}")
        return jsonify({'status': 'error', 'message': 'Terjadi kesalahan pada server.'})

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('user.dashboard'))

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    from flask import redirect
    if current_user.is_authenticated:
        return redirect('/')
    return redirect('/profil')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    from flask import redirect
    if current_user.is_authenticated:
        return redirect('/')
    return redirect('/profil?action=register')
