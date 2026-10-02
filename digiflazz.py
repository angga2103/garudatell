"""
Shim / Proxy module for root-level 'import digiflazz' compatibility.
Directly maps to app.services.digiflazz.
"""
from app.services.digiflazz import *
import app.services.digiflazz as _srv

# Ensure common function names are accessible
submit_transaction = getattr(_srv, 'submit_transaction', getattr(_srv, 'create_transaction', None))
create_transaction = getattr(_srv, 'create_transaction', None)
inquiry_postpaid = getattr(_srv, 'inquiry_postpaid', getattr(_srv, 'inquiry_pasca', None))
inquiry_pasca = getattr(_srv, 'inquiry_pasca', None)
pay_postpaid = getattr(_srv, 'pay_postpaid', getattr(_srv, 'pay_pasca', None))
pay_pasca = getattr(_srv, 'pay_pasca', None)
inquiry_pln = getattr(_srv, 'inquiry_pln', None)
is_pln_cutoff_time = getattr(_srv, 'is_pln_cutoff_time', None)
get_pln_cutoff_message = getattr(_srv, 'get_pln_cutoff_message', None)
check_transaction_status = getattr(_srv, 'check_transaction_status', None)
check_balance = getattr(_srv, 'check_balance', None)
verify_webhook_signature = getattr(_srv, 'verify_webhook_signature', None)
