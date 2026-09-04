import os
import requests
import urllib.parse

class PakasirService:
    """
    Layanan integrasi Payment Gateway Pakasir untuk transaksi QRIS dan verifikasi pembayaran.
    Dokumentasi resmi: https://app.pakasir.com
    """

    def __init__(self, config=None):
        config = config or {}
        self.project = config.get('project') or os.getenv('PAKASIR_PROJECT', '').strip()
        self.api_key = config.get('api_key') or os.getenv('PAKASIR_API_KEY', '').strip()
        self.base_url = "https://app.pakasir.com/api"

    def create_qris(self, order_id, amount):
        """
        Membuat transaksi pembayaran QRIS via Pakasir API.
        Endpoint: POST https://app.pakasir.com/api/transactioncreate/qris
        Payload: { project, order_id, amount, api_key }
        """
        if not self.project or not self.api_key:
            return {
                "status": False,
                "error": "Kredensial Pakasir (PAKASIR_PROJECT atau PAKASIR_API_KEY) belum dikonfigurasi di .env!"
            }

        try:
            nominal_int = int(float(amount))
        except (ValueError, TypeError):
            return {"status": False, "error": "Nominal transaksi tidak valid"}

        payload = {
            "project": self.project,
            "order_id": str(order_id),
            "amount": nominal_int,
            "api_key": self.api_key
        }

        try:
            res = requests.post(
                f"{self.base_url}/transactioncreate/qris",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=15
            )
            
            try:
                res_json = res.json()
            except Exception:
                return {"status": False, "error": f"Respons server bukan JSON (HTTP {res.status_code}): {res.text[:100]}"}
            
            # Parsing respons Pakasir:
            # Sesuai dokumentasi Pakasir, respons berisi payment_number (QR string)
            payment_obj = res_json.get('payment') or res_json.get('transaction') or res_json.get('data') or res_json
            qr_string = (
                payment_obj.get('payment_number') or 
                res_json.get('payment_number') or 
                payment_obj.get('qris_string') or 
                payment_obj.get('qr_string')
            )
            expired_at = payment_obj.get('expired_at') or res_json.get('expired_at')
            
            # Jika ada URL gambar langsung atau QR string
            qr_url = payment_obj.get('qr_url') or payment_obj.get('pay_url') or res_json.get('qr_url')
            if not qr_url and qr_string:
                # Generate URL gambar QR instan menggunakan api.qrserver.com
                encoded_qr = urllib.parse.quote(qr_string)
                qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&margin=10&data={encoded_qr}"

            if qr_url or qr_string:
                return {
                    "status": True,
                    "qr_url": qr_url,
                    "qr_string": qr_string,
                    "expired_at": expired_at,
                    "raw_response": res_json
                }
            else:
                error_msg = res_json.get('message') or res_json.get('error') or "Gagal mendapatkan QRIS dari Pakasir"
                return {"status": False, "error": error_msg, "raw_response": res_json}

        except Exception as e:
            return {"status": False, "error": f"Koneksi ke Pakasir gagal: {str(e)}"}

    def check_transaction(self, order_id):
        """
        Mengecek status transaksi di Pakasir.
        """
        if not self.project or not self.api_key:
            return {"status": False, "error": "Kredensial belum lengkap"}

        try:
            res = requests.get(
                f"{self.base_url}/transactiondetail",
                params={
                    "project": self.project,
                    "order_id": str(order_id),
                    "api_key": self.api_key
                },
                timeout=10
            )
            return res.json()
        except Exception as e:
            return {"status": False, "error": str(e)}

    def test_connection(self):
        """
        Menguji apakah Project Slug dan API Key Pakasir valid.
        """
        if not self.project or not self.api_key:
            return False, "Project Slug dan API Key Pakasir belum diatur!"

        try:
            res = requests.get(
                f"{self.base_url}/transactiondetail",
                params={
                    "project": self.project,
                    "order_id": "TEST_CONN_PING",
                    "api_key": self.api_key
                },
                timeout=10
            )
            if res.status_code == 401:
                return False, "Otentikasi Gagal: API Key atau Project Slug Pakasir tidak valid!"
            elif res.status_code in [200, 400, 404]:
                return True, "Koneksi ke API Pakasir Berhasil! Kredensial Valid."
            else:
                return False, f"Server Pakasir merespons kode: {res.status_code}"
        except Exception as e:
            return False, f"Gagal menghubungi server Pakasir: {str(e)}"
