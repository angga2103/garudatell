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

import re

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
    'parameter yang dikirim tidak lengkap',
    'digiflazz',
    'vip-reseller',
    'vip reseller',
    'tokovoucher',
    'apigames'
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

    # Filter dan hilangkan nama provider server dari pesan teks
    clean_msg = str(raw_message).strip()
    clean_msg = re.sub(r'(?i)\b(digiflazz|vip-reseller|vip reseller|tokovoucher|apigames)\b', 'operator', clean_msg)
    return clean_msg


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


def clean_raw_sn(raw_sn):
    if not raw_sn:
        return ''
    s = str(raw_sn).strip()
    s = re.sub(r'^(SN|Keterangan|KET)\s*:\s*', '', s, flags=re.I).strip()
    return s


def parse_sn_data(raw_sn, is_failed=False):
    """
    Memecah string SN kompleks (Cek Kuota Telkomsel, XL, PLN, Voucher, dll)
    menjadi dictionary data terstruktur.
    """
    s = clean_raw_sn(raw_sn)
    if not s:
        return {'type': 'empty', 'raw': ''}

    if is_failed:
        return {'type': 'failed', 'raw': s, 'message': s}

    # 1. PLN Token (20 Digit)
    pln_match = re.search(r'(?:^|\D)(\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4})(?:\D|$)', s)
    digits_token = re.sub(r'[-\s]', '', pln_match.group(1)) if pln_match else ''
    if pln_match and (
        any(k in s.lower() for k in ['kwh', 'pln', 'r1', 'b1', 'i1', 'va', 'stroom'])
        or len(digits_token) == 20
        or len(s.split('/')) >= 3
    ):
        raw_token = digits_token
        formatted_token = ' - '.join([raw_token[i:i+4] for i in range(0, 20, 4)])
        parts = [p.strip() for p in s.split('/') if p.strip() and re.sub(r'[-\s]', '', p) != raw_token]
        return {
            'type': 'pln_token',
            'raw': s,
            'raw_token': raw_token,
            'formatted_token': formatted_token,
            'info_parts': parts
        }

    # 2. Telkomsel Info / Cek Kuota
    if any(k in s for k in ['Masa Aktif Kartu', '-Status Registrasi', '-Info Paket Aktif', '-Status Jaringan']):
        parts = re.split(r'\s*-(?=(?:Status|Info|Masa)\b)', s)
        fields = {}
        for p in parts:
            p = p.strip().lstrip('-').strip()
            if ':' in p:
                k, v = p.split(':', 1)
                fields[k.strip().lower()] = v.strip()

        ma = fields.get('masa aktif kartu', '')
        if ma in ['-', '']:
            ma = ''

        reg = fields.get('status registrasi', '')
        net = fields.get('status jaringan', '')
        dev = fields.get('status perangkat', '')
        if dev in ['-', '']:
            dev = ''

        info_pkg = fields.get('info paket aktif', '')
        pkgs = []
        if info_pkg:
            raw_p = re.split(r'#\d+\s*-\s*', info_pkg)
            for rp in raw_p:
                rp = rp.strip()
                if not rp or rp == '-':
                    continue
                m_exp = re.search(r'\s*-\s*(aktif\s+hingga.*?)$', rp, re.I)
                if m_exp:
                    pname = rp[:m_exp.start()].strip()
                    pexp = m_exp.group(1).strip()
                    pkgs.append({'name': pname, 'expired': pexp})
                else:
                    pkgs.append({'name': rp, 'expired': ''})

        return {
            'type': 'telkomsel_info',
            'raw': s,
            'masa_aktif': ma,
            'registrasi': reg,
            'jaringan': net,
            'perangkat': dev,
            'packages': pkgs
        }

    # 3. XL Info / Cek Kuota
    if 'dukcapil=' in s.lower() or ('.expired:' in s.lower() and 'data' in s.lower()):
        parts = [p.strip() for p in s.split('/') if p.strip()]
        dukcapil = ''
        pkgs = []
        for p in parts:
            if 'dukcapil=' in p.lower():
                val = p.split('=', 1)[1].strip()
                dukcapil = 'Terdaftar (Dukcapil)' if val.lower() == 'registered' else f'{val} (Dukcapil)'
            else:
                m = re.match(r'^(?:\d+\.\s*)?(.*?)\.Expired:([^\s]+(?:\s+[^\s]+)?)\s*(?:DATA\s*(.*?))?$', p, re.I)
                if m:
                    pname = m.group(1).strip()
                    pexp = m.group(2).strip()
                    pdata = (m.group(3) or '').strip()
                    pkgs.append({'name': pname, 'expired': pexp, 'quota': pdata})
                else:
                    pkgs.append({'name': p, 'expired': '', 'quota': ''})

        return {
            'type': 'xl_info',
            'raw': s,
            'dukcapil': dukcapil,
            'packages': pkgs
        }

    # 4. Multi-Package Bertanda '*' atau 'sisa kuota'
    if '*' in s or 'sisa kuota' in s.lower():
        parts = [p.strip() for p in s.split('*') if p.strip()]
        pkgs = []
        pulsa_info = ''
        card_info = ''
        for p in parts:
            if p.lower().startswith('sisa pulsa'):
                pulsa_info = p
            elif not '/' in p and any(k in p.lower() for k in ['kartu', 'perdana', 'nomor', 'aktif']):
                card_info = p
            else:
                m = re.match(r'^(.*?)\s*/\s*(Sisa Kuota.*)$', p, re.I)
                if m:
                    title = m.group(1).strip()
                    details = m.group(2).strip()
                    sub_items = [it.strip() for it in re.split(r',\s*(?=\d+|Nelp|Sisa|Kuota|Bonus)', details, flags=re.I) if it.strip()]
                    pkgs.append({'title': title, 'items': sub_items})
                else:
                    pkgs.append({'title': p, 'items': []})

        return {
            'type': 'multi_quota',
            'raw': s,
            'card_info': card_info,
            'pulsa_info': pulsa_info,
            'packages': pkgs
        }

    # 5. Voucher Fisik
    if any(k in s.upper() for k in ['KODE VOUCHER', 'VOUCHER:', 'KODE:']):
        return {
            'type': 'voucher',
            'raw': s,
            'details': [p.strip() for p in s.split('/') if p.strip()]
        }

    return {
        'type': 'simple',
        'raw': s
    }


def format_clean_sn_text(raw_sn, is_failed=False):
    """
    Format string SN menjadi teks berbaris rapi untuk disalin (Clipboard),
    dikirim ke WhatsApp (Struk WA), atau struk printer.
    """
    data = parse_sn_data(raw_sn, is_failed=is_failed)
    stype = data.get('type')

    if stype == 'empty':
        return '-'

    if stype == 'failed':
        return data.get('message', '')

    if stype == 'pln_token':
        lines = [f"TOKEN PLN : {data['formatted_token']}"]
        if data.get('info_parts'):
            lines.append("Info      : " + " / ".join(data['info_parts']))
        return "\n".join(lines)

    if stype == 'telkomsel_info':
        lines = []
        if data.get('masa_aktif'):
            lines.append(f"Masa Aktif : {data['masa_aktif']}")
        if data.get('registrasi'):
            lines.append(f"Registrasi : {data['registrasi']}")
        if data.get('jaringan'):
            net = data['jaringan']
            if data.get('perangkat'):
                net += f" (Perangkat: {data['perangkat']})"
            lines.append(f"Jaringan   : {net}")

        pkgs = data.get('packages', [])
        if pkgs:
            lines.append("Paket Aktif:")
            for p in pkgs:
                lines.append(f"• {p['name']}")
                if p.get('expired'):
                    lines.append(f"  ({p['expired']})")
        else:
            lines.append("Paket Aktif: Tidak ada paket aktif")

        return "\n".join(lines)

    if stype == 'xl_info':
        lines = []
        if data.get('dukcapil'):
            lines.append(f"Registrasi : {data['dukcapil']}")

        pkgs = data.get('packages', [])
        if pkgs:
            lines.append("Paket Aktif:")
            for p in pkgs:
                lines.append(f"• {p['name']}")
                if p.get('expired'):
                    lines.append(f"  Masa Aktif : {p['expired']}")
                if p.get('quota'):
                    lines.append(f"  Sisa Kuota : {p['quota']}")

        return "\n".join(lines)

    if stype == 'multi_quota':
        lines = []
        if data.get('card_info'):
            lines.append(f"Kartu : {data['card_info']}")
        if data.get('pulsa_info'):
            lines.append(f"Pulsa : {data['pulsa_info']}")

        pkgs = data.get('packages', [])
        if pkgs:
            lines.append("Paket & Kuota:")
            for p in pkgs:
                lines.append(f"• {p['title']}")
                for it in p.get('items', []):
                    lines.append(f"  - {it}")

        return "\n".join(lines)

    if stype == 'voucher':
        return "\n".join(data.get('details', [data['raw']]))

    return data.get('raw', '')

