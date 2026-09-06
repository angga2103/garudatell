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

@auth_bp.route('/api/auth_ajax', methods=['POST'])
@csrf.exempt
@limiter.limit("20 per minute")
def auth_ajax():
    try:
        data = request.get_json() or {}
        action = data.get('action')
        phone = data.get('phone')
        password = data.get('password')

        if not phone:
            return jsonify({'status': 'error', 'message': 'Nomor WhatsApp wajib diisi!'})

        if action != 'request_emergency_otp' and not password:
            return jsonify({'status': 'error', 'message': 'Data tidak lengkap!'})


        # ==========================================
        # LOGIKA MINTA OTP DAFTAR BARU
        # ==========================================
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
        elif action == 'request_emergency_otp':
            from app.services.otp_service import create_otp
            from app.services.telegram_service import send_emergency_otp_request
            
            user_name = data.get('name') or None
            purpose = data.get('purpose', 'Pendaftaran / Masuk Akun')
            
            # Buat OTP darurat 10 menit (600 detik) dengan action 'manual'
            otp_kode = create_otp(phone, action='manual', username=user_name, expiry_seconds=600)
            
            # Kirim notifikasi ke Bot Telegram CS
            clean_num = ''.join(filter(str.isdigit, str(phone)))
            if clean_num.startswith('0'):
                clean_num = '62' + clean_num[1:]
                
            tele_ok, tele_msg, wa_direct_link = send_emergency_otp_request(
                phone=clean_num,
                otp_code=otp_kode,
                user_name=user_name,
                action_type=purpose,
                expiry_minutes=10
            )

            # Link WhatsApp menuju ke nomor CS
            import urllib.parse
            cs_phone = ''.join(filter(str.isdigit, os.getenv('ADMIN_PHONE') or '6281234567890'))
            if cs_phone.startswith('0'):
                cs_phone = '62' + cs_phone[1:]
            cs_text = urllib.parse.quote(
                f"Halo CS GarudaTel, saya ({user_name or clean_num}) memohon bantuan verifikasi OTP darurat untuk nomor {clean_num}. Terima kasih."
            )
            cs_wa_url = f"https://wa.me/{cs_phone}?text={cs_text}"
            
            return jsonify({
                'status': 'success',
                'message': 'Permintaan bantuan OTP Darurat telah berhasil diteruskan ke Tim CS Telegram kami! Tim CS akan segera menghubungi Anda via WhatsApp. Kode OTP ini berlaku selama 10 menit.',
                'wa_direct_link': wa_direct_link,
                'cs_wa_url': cs_wa_url,
                'telegram_notified': tele_ok
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
