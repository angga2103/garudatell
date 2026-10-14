import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import unittest
import re

from app.services.provider_helper import (
    parse_sn_data,
    format_clean_sn_text,
    format_display_sn
)

class TestSnFormatter(unittest.TestCase):
    def test_telkomsel_with_package(self):
        sn = "Masa Aktif Kartu : 24 Oktober 2026 -Status Registrasi : Terdaftar -Status Jaringan : 4G -Status Perangkat : - -Info Paket Aktif : #1 - kuota belajar/ilmupedia 7 Hari (11.00 GB / 11.00 GB) - Aktif hingga 12 Oktober 2026"
        data = parse_sn_data(sn)
        self.assertEqual(data['type'], 'telkomsel_info')
        self.assertEqual(data['masa_aktif'], '24 Oktober 2026')
        self.assertEqual(data['registrasi'], 'Terdaftar')
        self.assertEqual(data['jaringan'], '4G')
        self.assertEqual(data['perangkat'], '')
        self.assertEqual(len(data['packages']), 1)
        self.assertIn('kuota belajar/ilmupedia', data['packages'][0]['name'])
        self.assertIn('12 Oktober 2026', data['packages'][0]['expired'])

        formatted = format_clean_sn_text(sn)
        self.assertIn("Masa Aktif : 24 Oktober 2026", formatted)
        self.assertIn("Registrasi : Terdaftar", formatted)
        self.assertIn("kuota belajar/ilmupedia", formatted)

    def test_telkomsel_without_package(self):
        sn = "Masa Aktif Kartu : 13 Juni 2027 -Status Registrasi : Terdaftar -Status Jaringan : 4G -Status Perangkat : 4G -Info Paket Aktif : #1 -"
        data = parse_sn_data(sn)
        self.assertEqual(data['type'], 'telkomsel_info')
        self.assertEqual(data['masa_aktif'], '13 Juni 2027')
        self.assertEqual(data['registrasi'], 'Terdaftar')
        self.assertEqual(data['jaringan'], '4G')
        self.assertEqual(data['perangkat'], '4G')
        self.assertEqual(len(data['packages']), 0)

        formatted = format_clean_sn_text(sn)
        self.assertIn("Masa Aktif : 13 Juni 2027", formatted)
        self.assertIn("Tidak ada paket aktif", formatted)

    def test_telkomsel_empty_expiry(self):
        sn = "Masa Aktif Kartu : - -Status Registrasi : Terdaftar -Status Jaringan : 4G -Status Perangkat : - -Info Paket Aktif : #1 -"
        data = parse_sn_data(sn)
        self.assertEqual(data['type'], 'telkomsel_info')
        self.assertEqual(data['masa_aktif'], '')
        self.assertEqual(data['registrasi'], 'Terdaftar')
        self.assertEqual(len(data['packages']), 0)

        formatted = format_clean_sn_text(sn)
        self.assertNotIn("Masa Aktif : -", formatted)
        self.assertIn("Registrasi : Terdaftar", formatted)

    def test_xl_quota(self):
        sn = "Dukcapil=Registered / 1.Xtra Edukasi 15GB, 7hr.Expired:14-Oct-26 23:59:59 DATA Xtra Edukasi 24jam di 2G3G4G 6.22 GB"
        data = parse_sn_data(sn)
        self.assertEqual(data['type'], 'xl_info')
        self.assertEqual(data['dukcapil'], 'Terdaftar (Dukcapil)')
        self.assertEqual(len(data['packages']), 1)
        self.assertIn("Xtra Edukasi 15GB, 7hr", data['packages'][0]['name'])
        self.assertIn("14-Oct-26 23:59:59", data['packages'][0]['expired'])
        self.assertIn("6.22 GB", data['packages'][0]['quota'])

        formatted = format_clean_sn_text(sn)
        self.assertIn("Dukcapil", formatted)
        self.assertIn("Xtra Edukasi", formatted)
        self.assertIn("14-Oct-26", formatted)

    def test_pln_token(self):
        sn = "1234-5678-9012-3456-7890 / NUR HAYATI / R1 / 900VA / 54.2KWH"
        data = parse_sn_data(sn)
        self.assertEqual(data['type'], 'pln_token')
        self.assertEqual(data['raw_token'], '12345678901234567890')
        self.assertEqual(data['formatted_token'], '1234 - 5678 - 9012 - 3456 - 7890')

        formatted = format_clean_sn_text(sn)
        self.assertIn("1234 - 5678 - 9012 - 3456 - 7890", formatted)
        self.assertIn("NUR HAYATI", formatted)

    def test_regular_sn(self):
        sn = "0214087997076300006722"
        data = parse_sn_data(sn)
        self.assertEqual(data['type'], 'simple')
        formatted = format_clean_sn_text(sn)
        self.assertEqual(formatted, "0214087997076300006722")

    def test_failed_transaction(self):
        sn = "Nomor tujuan salah atau tidak aktif"
        data = parse_sn_data(sn, is_failed=True)
        self.assertEqual(data['type'], 'failed')
        formatted = format_clean_sn_text(sn, is_failed=True)
        self.assertEqual(formatted, "Nomor tujuan salah atau tidak aktif")

if __name__ == '__main__':
    unittest.main()
