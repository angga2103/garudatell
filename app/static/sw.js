/**
 * iPay GarudaTel - Progressive Web App Service Worker
 * Versi Cache: ipay-pwa-v1.0.0
 * 
 * Strategi:
 * 1. Aset Statis (CSS, JS, Fonts, Images, Icons) -> Cache-First / Stale-While-Revalidate (Super Cepat)
 * 2. Halaman HTML Navigasi -> Network-First dengan Fallback ke /offline jika tanpa sinyal
 * 3. Transaksi Finansial, Saldo, Callback, dan Admin -> NETWORK-ONLY (Keamanan 100% Bebas Stale Data)
 */

const CACHE_NAME = 'ipay-pwa-v1.0.0';

// Aset Inti yang di-precache saat instalasi
const PRECACHE_ASSETS = [
  '/',
  '/offline',
  '/manifest.json',
  '/static/img/icons/icon-192x192.png',
  '/static/img/icons/icon-512x512.png',
  '/static/img/icons/icon-maskable-192x192.png',
  '/static/img/icons/apple-touch-icon.png',
  '/static/img/icons/icon.svg',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css',
  'https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800;900&display=swap'
];

// 1. INSTALL EVENT: Pre-cache aset inti
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        // Coba cache satu per satu agar jika salah satu resource eksternal gagal, worker tetap aktif
        return Promise.allSettled(
          PRECACHE_ASSETS.map((url) =>
            fetch(url, { mode: url.startsWith('http') && !url.includes(self.location.hostname) ? 'cors' : 'no-cors' })
              .then((response) => {
                if (response.status === 200 || response.type === 'opaque') {
                  return cache.put(url, response);
                }
              })
              .catch((err) => console.warn('[PWA] Gagal precache URL:', url, err))
          )
        );
      })
      .then(() => self.skipWaiting())
  );
});

// 2. ACTIVATE EVENT: Bersihkan cache versi lama
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((name) => {
          if (name !== CACHE_NAME) {
            console.log('[PWA] Menghapus cache versi lama:', name);
            return caches.delete(name);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// 3. FETCH EVENT: Intersepsi request dengan strategi aman
self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // A. Abaikan request non-GET (POST, PUT, DELETE mutlak Network-Only)
  if (request.method !== 'GET') {
    return;
  }

  // B. RUTE KRUSIAL FINANSIAL & ADMIN: Mutlak NETWORK-ONLY
  // Jangan pernah cache transaksi checkout, deposit saldo, callback provider, atau panel admin!
  const isSensitiveRoute = (
    url.pathname.startsWith('/admin') ||
    url.pathname.startsWith('/api') ||
    url.pathname.startsWith('/callback') ||
    url.pathname.startsWith('/trx') ||
    url.pathname.startsWith('/deposit') ||
    url.pathname.startsWith('/logout') ||
    url.pathname.includes('checkout') ||
    url.pathname.includes('payment')
  );

  if (isSensitiveRoute) {
    // Biarkan browser langsung memanggil network tanpa menyentuh cache
    return;
  }

  // C. Halaman Navigasi HTML: Network-First dengan Fallback ke Offline Page
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((networkResponse) => {
          // Jika respons sukses, update cache halaman ini di background
          if (networkResponse && networkResponse.status === 200) {
            const responseClone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(request, responseClone);
            });
          }
          return networkResponse;
        })
        .catch(async () => {
          // Jaringan terputus / offline:
          // 1. Coba cari di cache halaman yang sebelumnya pernah dibuka
          const cachedResponse = await caches.match(request);
          if (cachedResponse) {
            return cachedResponse;
          }
          // 2. Jika tidak ada di cache, tampilkan halaman offline resmi
          const offlinePage = await caches.match('/offline');
          return offlinePage || new Response(
            '<h1>Koneksi Terputus</h1><p>Silakan periksa koneksi internet Anda dan muat ulang halaman.</p>',
            { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
          );
        })
    );
    return;
  }

  // D. Aset Statis (CSS, JS, Fonts, Images): Cache-First / Stale-While-Revalidate
  const isStaticAsset = (
    url.pathname.startsWith('/static/') ||
    url.hostname.includes('fonts.googleapis.com') ||
    url.hostname.includes('fonts.gstatic.com') ||
    url.hostname.includes('cdnjs.cloudflare.com') ||
    url.hostname.includes('cdn.jsdelivr.net')
  );

  if (isStaticAsset) {
    event.respondWith(
      caches.match(request).then((cachedResponse) => {
        // Jika ada di cache, sajikan instan (Satset UI)
        if (cachedResponse) {
          // Tetap lakukan fetch di background untuk update cache selanjutnya jika ada perubahan
          fetch(request).then((networkResponse) => {
            if (networkResponse && networkResponse.status === 200) {
              caches.open(CACHE_NAME).then((cache) => cache.put(request, networkResponse));
            }
          }).catch(() => {});
          return cachedResponse;
        }

        // Jika belum ada di cache, ambil dari network dan simpan
        return fetch(request).then((networkResponse) => {
          if (!networkResponse || networkResponse.status !== 200 || networkResponse.type === 'opaque') {
            return networkResponse;
          }
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(request, responseToCache);
          });
          return networkResponse;
        });
      })
    );
    return;
  }

  // E. Fallback default
  event.respondWith(
    caches.match(request).then((cachedResponse) => {
      return cachedResponse || fetch(request);
    })
  );
});
