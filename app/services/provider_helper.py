"""
Provider Helper Service
Menangani sanitasi respon error dari provider H2H (Digiflazz, VIP-Reseller, dll).

Tujuan Utama:
1. Mencegah kebocoran pesan teknis internal server (misal 'Saldo Anda tidak cukup untuk melakukan pemesanan ini',
   'Saldo Buyer tidak mencukupi', 'IP not allowed', dll) ke pengguna akhir.
2. Memberikan pesan notifikasi yang ramah, sopan, dan jelas bagi pengguna:
   - Pengguna tahu bahwa saldo mereka AMAN dan telah dikembalikan / tidak terpotong.
   - Menginformasikan bahwa kendala terjadi pada jalur operator/pemeliharaan sistem.
3. Memberikan peringatan khusus untuk Admin (misal via Telegram Notifikasi) bahwa saldo deposit
   akun provider (VIP-Reseller / Digiflazz) sedang kosong/kurang sehingga admin segera top up.
"""

# Kata kunci yang mengindikasikan saldo deposit admin di provider habis / kurang
PROVIDER_BALANCE_KEYWORDS = [
    'saldo anda tidak cukup',
    'saldo tidak cukup',
    'saldo tidak mencukupi',
    'saldo buyer tidak mencukupi',
    'saldo buyer tidak cukup',
    'saldo akun tidak cukup',
    'saldo kurang',
    'saldo habis',
    'insufficient balance',
    'balance is not enough',
    'balance not enough',
    'not enough balance'
]

# Kata kunci kebocoran teknis/kredensial lain yang tidak layak dilihat pengguna
PROVIDER_SYSTEM_KEYWORDS = [
    'whitelist',
    'api key',
    'api_key',
    'sign tidak valid',
    'signature',
    'ip 2001',
    'not permitted',
    'timeout dari provider',
    'parameter yang dikirim tidak lengkap'
]

USER_FRIENDLY_SN_MSG = "Jalur operator sedang gangguan sementara. Saldo aman & telah direfund."
USER_FRIENDLY_POPUP_MSG = (
    "Pemesanan belum dapat diproses karena jalur operator sedang mengalami antrean padat "
    "atau gangguan sementara. Saldo Anda aman dan telah dikembalikan utuh ke akun Anda. "
    "Silakan coba beberapa saat lagi atau hubungi Layanan Pelanggan (CS)."
)


def is_provider_balance_error(raw_message, rc=None):
    """
    Mengecek apakah suatu pesan error atau response code mengindikasikan saldo deposit provider kosong/kurang.
    - Digiflazz: RC 01 (Saldo Tidak Cukup) atau RC 52 (Saldo Buyer tidak mencukupi)
    - VIP-Reseller: Pesan 'Saldo Anda tidak cukup untuk melakukan pemesanan ini [1].'
    """
    rc_str = str(rc or '').strip()
    if rc_str in ['01', '52', '1']:
        return True

    if not raw_message:
        return False

    msg_lower = str(raw_message).lower()
    for kw in PROVIDER_BALANCE_KEYWORDS:
        if kw in msg_lower:
            return True
    return False


def sanitize_public_sn_message(raw_message, rc=None, default_msg=None):
    """
    Mengubah pesan error provider menjadi pesan SN/Keterangan yang ramah di sisi user.
    """
    if is_provider_balance_error(raw_message, rc=rc):
        return USER_FRIENDLY_SN_MSG

    if not raw_message:
        return default_msg or USER_FRIENDLY_SN_MSG

    msg_lower = str(raw_message).lower()
    for kw in PROVIDER_SYSTEM_KEYWORDS:
        if kw in msg_lower:
            return "Gangguan sistem operator sementara. Silakan coba kembali nanti."

    # Jika nomor salah atau format salah, biarkan pesan wajar
    return str(raw_message).strip()


def sanitize_public_popup_message(raw_message, rc=None):
    """
    Menghasilkan pesan popup/modal saat user melakukan checkout / order.
    """
    if is_provider_balance_error(raw_message, rc=rc):
        return USER_FRIENDLY_POPUP_MSG

    cleaned_sn = sanitize_public_sn_message(raw_message, rc=rc)
    return f"Gagal: {cleaned_sn}"


def format_display_sn(sn_val, status=None):
    """
    Helper filter template Jinja2 untuk membersihkan pesan SN pada tampilan web.
    Dapat mendeteksi record lama di database yang terlanjur menyimpan pesan saldo provider habis.
    """
    if not sn_val:
        return sn_val

    # Jika mengandung pola saldo habis, ubah ke pesan ramah
    if is_provider_balance_error(sn_val):
        return USER_FRIENDLY_SN_MSG

    return sn_val
