import requests
import re

s = requests.Session()
r_page = s.get("http://127.0.0.1:5000/admin/login")
csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', r_page.text).group(1)

r_login = s.post("http://127.0.0.1:5000/admin/login", data={"csrf_token": csrf_token, "password": "admin123"}, allow_redirects=True)
print("Login Status:", r_login.status_code, "URL:", r_login.url)

r_saldo = s.get("http://127.0.0.1:5000/admin/saldo")
print("Saldo Status:", r_saldo.status_code, "URL:", r_saldo.url)
print("Contains 'Saldo & Deposit Digiflazz':", "Saldo & Deposit Digiflazz" in r_saldo.text)
print("Contains 'Minta Tiket Deposit Digiflazz Baru':", "Minta Tiket Deposit Digiflazz Baru" in r_saldo.text)

