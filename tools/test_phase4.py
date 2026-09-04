import os
import sys
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from app import create_app
import re

app = create_app()
client = app.test_client()

# 1. Test CSRF on admin login
res_get = client.get('/admin/login')
token_match = re.search(r'name="csrf_token" value="([^"]+)"', res_get.text)
assert token_match, "CSRF token not found in admin login form!"
csrf_token = token_match.group(1)
print(f"[TEST 1 PASSED] CSRF token successfully rendered in form: {csrf_token[:15]}...")

# 2. Test Rate Limiter on admin login (limit is 5 per minute)
status_codes = []
for i in range(7):
    r = client.post('/admin/login', data={'username': 'attacker', 'password': 'wrong', 'csrf_token': csrf_token})
    status_codes.append(r.status_code)

print("Status codes from 7 rapid requests:", status_codes)
assert 429 in status_codes, f"Expected 429 in {status_codes}"
print("[TEST 2 PASSED] Rate limiter successfully returned HTTP 429 Too Many Requests!")

# 3. Test Webhooks CSRF exemption
r_digi = client.post('/trx/callback/digiflazz', json={'ref_id': 'DUMMY', 'status': 'Sukses'})
assert r_digi.status_code == 403, f"Expected 403 from signature check, got {r_digi.status_code}"
print("[TEST 3 PASSED] Webhook Digiflazz exempted from CSRF, validated signature!")

# 4. Test Logger file
import os
log_file = os.path.join('storage', 'logs', 'garudatel.log')
assert os.path.exists(os.path.dirname(log_file)), "storage/logs directory does not exist!"
print("[TEST 4 PASSED] Logging directory verified at storage/logs/")

print("\n=== ALL PHASE 4 AUTOMATED TESTS PASSED SUCCESSFULLY! ===")
