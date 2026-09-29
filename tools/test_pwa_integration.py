#!/usr/bin/env python3
"""
================================================================================
TEST SUITE INTEGRASI PWA (PROGRESSIVE WEB APP) iPay GARUDATEL
================================================================================
Menguji seluruh komponen PWA:
1. Endpoint /manifest.json (MIME type, valid JSON, nama 'iPay', icons, shortcuts)
2. Endpoint /sw.js (MIME type, Service-Worker-Allowed: /, Cache-Control, skema cache)
3. Ketersediaan seluruh aset ikon multi-resolusi di disk dan HTTP static
4. Endpoint /offline (Tampilan fallback ramah saat jaringan terputus)
5. Integrasi template base.html (Tag manifest, meta iOS, PWA banner, SW registration)
================================================================================
"""

import os
import sys
import json

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app

def run_pwa_tests():
    app = create_app()
    client = app.test_client()

    print("==================================================================")
    print("      MEMULAI PENGUJIAN INTEGRASI PWA (PROGRESSIVE WEB APP)       ")
    print("==================================================================")

    with app.app_context():
        # --- TEST 1: ENDPOINT /manifest.json ---
        print("\n[TEST 1] Menguji endpoint /manifest.json ...")
        res_manifest = client.get('/manifest.json')
        assert res_manifest.status_code == 200, f"Expected 200, got {res_manifest.status_code}"
        assert 'application/manifest+json' in res_manifest.content_type, f"Content-Type salah: {res_manifest.content_type}"
        
        manifest_data = json.loads(res_manifest.data.decode('utf-8'))
        assert manifest_data.get('short_name') == 'iPay', "short_name harus 'iPay'"
        assert 'iPay' in manifest_data.get('name', ''), "name harus memuat 'iPay'"
        assert manifest_data.get('display') == 'standalone', "display mode harus 'standalone'"
        assert manifest_data.get('theme_color') == '#008779', "theme_color harus '#008779'"
        assert len(manifest_data.get('icons', [])) >= 4, "Minimal harus ada 4 varian icon"
        
        # Validasi tujuan maskable dan any
        purposes = [ic.get('purpose') for ic in manifest_data.get('icons', [])]
        assert 'maskable' in purposes, "Harus menyertakan icon maskable untuk Android"
        assert 'any' in purposes, "Harus menyertakan icon standar (any)"
        
        print(f"  [PASS] Manifest valid! Nama: '{manifest_data['name']}', Display: '{manifest_data['display']}'")
        print(f"  [PASS] Jumlah Icon: {len(manifest_data['icons'])}, Shortcuts: {len(manifest_data.get('shortcuts', []))}")

        # --- TEST 2: ENDPOINT /sw.js ---
        print("\n[TEST 2] Menguji Service Worker /sw.js ...")
        res_sw = client.get('/sw.js')
        assert res_sw.status_code == 200, f"Expected 200, got {res_sw.status_code}"
        assert 'javascript' in res_sw.content_type, f"Content-Type SW harus javascript: {res_sw.content_type}"
        assert res_sw.headers.get('Service-Worker-Allowed') == '/', "Header Service-Worker-Allowed harus '/'"
        assert 'no-cache' in res_sw.headers.get('Cache-Control', ''), "SW harus no-cache agar selalu terupdate"
        
        sw_code = res_sw.data.decode('utf-8')
        assert 'CACHE_NAME' in sw_code, "SW harus mendefinisikan CACHE_NAME"
        assert '/offline' in sw_code, "SW harus memuat precache /offline"
        assert 'isSensitiveRoute' in sw_code, "SW harus memiliki proteksi Network-Only untuk transaksi"
        assert '/admin' in sw_code and '/api' in sw_code, "SW harus mengecualikan /admin dan /api dari cache"
        
        print("  [PASS] Service Worker aktif dengan scope '/' & proteksi Network-Only untuk rute finansial!")

        # --- TEST 3: VALIDASI FILE IKON DI DISK & HTTP STATIC ---
        print("\n[TEST 3] Menguji ketersediaan file ikon iPay ...")
        icon_files = [
            'icon-192x192.png',
            'icon-512x512.png',
            'icon-maskable-192x192.png',
            'icon-maskable-512x512.png',
            'apple-touch-icon.png',
            'favicon-32x32.png',
            'favicon-16x16.png',
            'icon.svg'
        ]
        icons_dir = os.path.join(app.static_folder, 'img', 'icons')
        
        for icon_name in icon_files:
            file_path = os.path.join(icons_dir, icon_name)
            assert os.path.exists(file_path), f"File icon tidak ditemukan di disk: {file_path}"
            file_size = os.path.getsize(file_path)
            assert file_size > 0, f"Ukuran file {icon_name} kosong"
            
            # Cek akses HTTP
            res_icon = client.get(f'/static/img/icons/{icon_name}')
            assert res_icon.status_code == 200, f"Gagal akses HTTP static: /static/img/icons/{icon_name}"
            print(f"  [PASS] Icon '{icon_name}' ({file_size} bytes) -> HTTP 200 OK")

        # --- TEST 4: ENDPOINT /offline ---
        print("\n[TEST 4] Menguji halaman fallback /offline ...")
        res_offline = client.get('/offline')
        assert res_offline.status_code == 200, f"Expected 200, got {res_offline.status_code}"
        html_offline = res_offline.data.decode('utf-8')
        assert 'Koneksi Internet Terputus' in html_offline
        assert 'Coba Muat Ulang' in html_offline
        assert 'iPay GarudaTel' in html_offline
        print("  [PASS] Halaman fallback /offline ter-render sempurna dengan tombol auto-reconnect!")

        # --- TEST 5: INTEGRASI TEMPLATE base.html ---
        print("\n[TEST 5] Menguji integrasi meta tag & PWA banner di base.html ...")
        res_home = client.get('/')
        assert res_home.status_code in [200, 302], f"Status home: {res_home.status_code}"
        
        # Ambil konten halaman home (atau bantuan jika redirect)
        html_home = res_home.data.decode('utf-8') if res_home.status_code == 200 else client.get('/bantuan').data.decode('utf-8')
        assert '<link rel="manifest" href="/manifest.json">' in html_home, "Manifest tag harus ada di base.html"
        assert '<meta name="theme-color" content="#008779">' in html_home, "theme-color harus ada"
        assert 'apple-mobile-web-app-capable' in html_home, "Tag Apple PWA harus ada"
        assert 'id="pwa-install-banner"' in html_home, "Komponen banner PWA harus ada di DOM"
        assert 'pwa-btn-install' in html_home, "Tombol pasang PWA harus ada"
        assert 'navigator.serviceWorker.register' in html_home, "Script registrasi SW harus ada di base.html"
        print("  [PASS] Meta tag PWA, Apple touch icon, banner instalasi, dan registrasi SW aktif di base.html!")

    print("\n==================================================================")
    print("       SELURUH PENGUJIAN PWA iPay GARUDATEL LULUS 100%!           ")
    print("==================================================================")

if __name__ == '__main__':
    run_pwa_tests()
