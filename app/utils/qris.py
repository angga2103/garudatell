import os
import re
import logging

logger = logging.getLogger(__name__)

DEFAULT_DANA_QRIS_STRING = (
    "00020101021240560011ID.DANA.WWW01189360091531433862600215ANGGA DIAN PRAT"
    "5204482953033605405101205802ID5924ANGGA DIAN PRATAMA PUTRA6011Kota Bekasi"
    "61051279062460804DMCT9934000200012428101201202610205004486663049B67"
)


def crc16_ccitt(data: str) -> str:
    """
    Menghitung CRC16-CCITT standar EMVCo QRIS:
    Polynomial: 0x1021, Initial value: 0xFFFF.
    Hasil berupa 4 karakter heksadesimal huruf besar (contoh: '9B67').
    """
    crc = 0xFFFF
    for ch in data:
        crc ^= ord(ch) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def parse_emvco_qris(qris_str: str) -> list:
    """
    Mem-parsing payload EMVCo QRIS menjadi list pasangan (tag, value).
    Mengabaikan Tag 63 (CRC) jika ada di bagian akhir.
    """
    clean_str = (qris_str or "").strip()
    # Jika ada tag 63 di 10 karakter terakhir, potong
    pos_63 = clean_str.rfind("6304")
    if pos_63 != -1 and pos_63 >= len(clean_str) - 8:
        clean_str = clean_str[:pos_63]

    tags = []
    idx = 0
    total_len = len(clean_str)

    while idx < total_len:
        if idx + 4 > total_len:
            break
        tag = clean_str[idx : idx + 2]
        try:
            length = int(clean_str[idx + 2 : idx + 4])
        except ValueError:
            break
        val_start = idx + 4
        val_end = val_start + length
        if val_end > total_len:
            break
        val = clean_str[val_start:val_end]
        tags.append((tag, val))
        idx = val_end

    return tags


def generate_dynamic_qris(base_qris: str, amount: int) -> str:
    """
    Mengubah QRIS Statis/Dinamis menjadi QRIS Dinamis spesifik nominal:
    1. Mengatur Tag 01 (Point of Initiation Method) menjadi '12' (Dinamis).
    2. Menyisipkan/mengganti Tag 54 (Transaction Amount) dengan nominal uang bulat.
    3. Menghitung ulang checksum CRC16-CCITT pada Tag 63.
    """
    if not base_qris:
        base_qris = get_base_qris_string()

    amount_int = int(amount)
    if amount_int <= 0:
        raise ValueError(f"Nominal pembayaran QRIS harus lebih besar dari 0 (diberikan: {amount})")

    tags = parse_emvco_qris(base_qris)
    if not tags:
        raise ValueError("Format base QRIS tidak valid atau kosong.")

    amt_str = str(amount_int)
    amt_tag = ("54", amt_str)

    new_tags = []
    has_amount = False

    for tag, val in tags:
        if tag == "01":
            # Tag 01: 11 = Statis, 12 = Dinamis (dengan nominal terkunci)
            new_tags.append(("01", "12"))
        elif tag == "54":
            new_tags.append(amt_tag)
            has_amount = True
        elif tag in ["58", "59"] and not has_amount:
            # Standar EMVCo: Tag 54 diletakkan sebelum Tag 58 (Country Code) / 59 (Merchant Name)
            new_tags.append(amt_tag)
            has_amount = True
            new_tags.append((tag, val))
        else:
            new_tags.append((tag, val))

    if not has_amount:
        new_tags.append(amt_tag)

    # Susun ulang string TLV
    payload = ""
    for tag, val in new_tags:
        payload += f"{tag}{len(val):02d}{val}"

    # Tambahkan header Tag 63 dengan panjang 04
    payload += "6304"

    # Hitung CRC16-CCITT
    crc = crc16_ccitt(payload)
    return payload + crc


def validate_qris(qris_str: str) -> tuple:
    """
    Memvalidasi integritas data QRIS berdasarkan spesifikasi EMVCo dan checksum CRC16.
    Mengembalikan (is_valid: bool, message: str).
    """
    if not qris_str or len(qris_str) < 20:
        return False, "Payload QRIS terlalu pendek atau kosong"

    pos_63 = qris_str.rfind("6304")
    if pos_63 == -1 or len(qris_str) != pos_63 + 8:
        return False, "Tag 63 (CRC16) tidak ditemukan di akhir payload"

    payload_without_crc = qris_str[: pos_63 + 4]
    expected_crc = qris_str[pos_63 + 4 :].upper()
    calculated_crc = crc16_ccitt(payload_without_crc)

    if calculated_crc != expected_crc:
        return False, f"CRC mismatch: dihitung {calculated_crc}, ada {expected_crc}"

    return True, "QRIS valid"


def get_base_qris_string() -> str:
    """
    Mengambil string template QRIS DANA dari tabel Setting atau fallback ke default user.
    """
    try:
        from app.services.setting_service import get_setting_value

        val = get_setting_value("dana_qris_string", DEFAULT_DANA_QRIS_STRING)
        if val and len(val.strip()) > 30:
            return val.strip()
    except Exception as e:
        logger.warning(f"Gagal mengambil dana_qris_string dari Setting: {e}")

    return DEFAULT_DANA_QRIS_STRING
