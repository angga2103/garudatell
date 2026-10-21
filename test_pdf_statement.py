import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import create_app
from app.models.user import User
from app.services.pdf_statement_service import (
    generate_monthly_statement_pdf,
    _generate_with_pure_python,
    _generate_with_reportlab,
    _extract_statement_summary
)

class TestPdfStatement(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app_context = self.app.app_context()
        self.app_context.push()

        self.user = User(
            id=3,
            name="ANGGA",
            phone="081775700114",
            email="angga@example.com",
            balance=45484.0,
            role="VIP"
        )

    def tearDown(self):
        self.app_context.pop()

    def test_extract_statement_summary_with_stats_dict(self):
        statement_data = {
            'mutations': [
                {'date_str': '2026-10-02 00:42:00', 'type': 'refund', 'direction': '+', 'amount': 511.0, 'balance_before': 33853.0, 'balance_after': 34364.0, 'ref_id': 'REF-1', 'product_name': 'Refund XL'},
                {'date_str': '2026-10-21 13:20:00', 'type': 'pengeluaran', 'direction': '-', 'amount': 511.0, 'balance_before': 45995.0, 'balance_after': 45484.0, 'ref_id': 'REF-2', 'product_name': 'XL Cek Sisa'}
            ],
            'stats': {
                'starting_balance': 33853.0,
                'ending_balance': 45484.0,
                'total_pemasukan': 100000.0,
                'total_pengeluaran': 88880.0,
                'total_refund': 511.0,
                'count': 2
            }
        }
        res = _extract_statement_summary(statement_data)
        self.assertEqual(res['starting_bal'], 33853.0)
        self.assertEqual(res['ending_bal'], 45484.0)
        self.assertEqual(res['tot_in'], 100000.0)
        self.assertEqual(res['tot_out'], 88880.0)
        self.assertEqual(res['tot_ref'], 511.0)
        self.assertEqual(res['tot_kredit'], 100511.0)

    def test_extract_statement_summary_fallback_from_mutations(self):
        statement_data = {
            'mutations': [
                {'date_str': '2026-10-02 00:42:00', 'type': 'refund', 'direction': '+', 'amount': 511.0, 'balance_before': 33853.0, 'balance_after': 34364.0, 'ref_id': 'REF-1', 'product_name': 'Refund XL'},
                {'date_str': '2026-10-21 13:20:00', 'type': 'pengeluaran', 'direction': '-', 'amount': 511.0, 'balance_before': 45995.0, 'balance_after': 45484.0, 'ref_id': 'REF-2', 'product_name': 'XL Cek Sisa'}
            ]
        }
        res = _extract_statement_summary(statement_data)
        self.assertEqual(res['starting_bal'], 33853.0)
        self.assertEqual(res['ending_bal'], 45484.0)
        self.assertEqual(res['tot_out'], 511.0)
        self.assertEqual(res['tot_ref'], 511.0)
        self.assertEqual(res['tot_kredit'], 511.0)

    def test_pure_python_pdf_renders_correct_summary_numbers(self):
        statement_data = {
            'mutations': [
                {'date_str': '2026-10-02 00:42:00', 'type': 'refund', 'direction': '+', 'amount': 511.0, 'balance_before': 33853.0, 'balance_after': 34364.0, 'ref_id': 'REF-1', 'product_name': 'Refund XL'},
                {'date_str': '2026-10-21 13:20:00', 'type': 'pengeluaran', 'direction': '-', 'amount': 511.0, 'balance_before': 45995.0, 'balance_after': 45484.0, 'ref_id': 'REF-2', 'product_name': 'XL Cek Sisa'}
            ],
            'stats': {
                'starting_balance': 33853.0,
                'ending_balance': 45484.0,
                'total_pemasukan': 100000.0,
                'total_pengeluaran': 88880.0,
                'total_refund': 511.0,
                'count': 2
            }
        }
        pdf = _generate_with_pure_python(self.user, 10, 2026, statement_data)
        raw_text = pdf.getvalue().decode('latin1')
        self.assertIn("33.853", raw_text)
        self.assertIn("45.484", raw_text)
        self.assertIn("100.511", raw_text)
        self.assertIn("88.880", raw_text)

    def test_reportlab_pdf_renders_correct_summary(self):
        statement_data = {
            'mutations': [
                {'date_str': '2026-10-02 00:42:00', 'type': 'refund', 'direction': '+', 'amount': 511.0, 'balance_before': 33853.0, 'balance_after': 34364.0, 'ref_id': 'REF-1', 'product_name': 'Refund XL'},
                {'date_str': '2026-10-21 13:20:00', 'type': 'pengeluaran', 'direction': '-', 'amount': 511.0, 'balance_before': 45995.0, 'balance_after': 45484.0, 'ref_id': 'REF-2', 'product_name': 'XL Cek Sisa'}
            ],
            'stats': {
                'starting_balance': 33853.0,
                'ending_balance': 45484.0,
                'total_pemasukan': 100000.0,
                'total_pengeluaran': 88880.0,
                'total_refund': 511.0,
                'count': 2
            }
        }
        pdf = _generate_with_reportlab(self.user, 10, 2026, statement_data)
        self.assertGreater(len(pdf.getvalue()), 1000)

if __name__ == '__main__':
    unittest.main()
