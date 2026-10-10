/**
 * iPay GarudaTel - Progressive Web App Service Worker
 * Versi Cache: ipay-pwa-v1.0.0
 * 
 * Strategi:
 * 1. Aset Statis (CSS, JS, Fonts, Images, Icons) -> Cache-First / Stale-While-Revalidate (Super Cepat)
 * 2. Halaman HTML Navigasi -> Network-First dengan Fallback ke /offline jika tanpa sinyal
 * 3. Transaksi Finansial, Saldo, Callback, dan Admin -> NETWORK-ONLY (Keamanan 100% Bebas Stale Data)
 */

const CACHE_NAME = 'ipay-pwa-v1.1.0';

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

// ==========================================
// 4. APP BADGING & PUSH NOTIFICATION HANDLER
// ==========================================

async function setWorkerBadge(count) {
  try {
    if ('setAppBadge' in navigator) {
      if (count && count > 0) {
        await navigator.setAppBadge(count);
      } else {
        await navigator.clearAppBadge();
      }
    }
  } catch (err) {
    console.warn('[SW Badging] Gagal update badge:', err);
  }
}

async function clearWorkerBadge() {
  try {
    if ('clearAppBadge' in navigator) {
      await navigator.clearAppBadge();
    }
    const notifs = await self.registration.getNotifications();
    notifs.forEach((n) => n.close());
  } catch (err) {
    console.warn('[SW Badging] Gagal bersihkan badge & notifikasi:', err);
  }
}

// Listener Push Notification dari Server
self.addEventListener('push', (event) => {
  let payload = {};
  if (event.data) {
    try {
      payload = event.data.json();
    } catch (e) {
      payload = { title: 'iPay GarudaTel', message: event.data.text() };
    }
  }

  const title = payload.title || 'iPay GarudaTel';
  const options = {
    body: payload.message || payload.body || 'Ada notifikasi terbaru untuk Anda.',
    icon: '/static/img/icons/icon-192x192.png',
    badge: '/static/img/icons/icon-maskable-192x192.png',
    vibrate: [120, 80, 120],
    data: {
      url: payload.link || payload.url || '/notifikasi',
      id: payload.id || null
    },
    tag: payload.tag || ('ipay-notif-' + (payload.id || Date.now())),
    renotify: true
  };

  const count = typeof payload.unread_count === 'number' ? payload.unread_count : 1;

  event.waitUntil(
    Promise.all([
      self.registration.showNotification(title, options),
      setWorkerBadge(count)
    ])
  );
});

// Listener Klik pada Notifikasi Sistem Android/Desktop
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || '/notifikasi';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          client.navigate(targetUrl);
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
    })
  );
});

// Listener Pesan Sinkronisasi dari Halaman Client (base.html / dashboard / notifikasi)
self.addEventListener('message', (event) => {
  if (!event.data) return;

  if (event.data.action === 'SYNC_BADGE') {
    const count = parseInt(event.data.count, 10) || 0;
    event.waitUntil(setWorkerBadge(count));
  } else if (event.data.action === 'CLEAR_BADGE') {
    event.waitUntil(clearWorkerBadge());
  } else if (event.data.action === 'SHOW_LOCAL_NOTIF') {
    const item = event.data.item;
    if (item) {
      const title = item.title || 'Info iPay';
      const options = {
        body: item.message || 'Pemberitahuan baru',
        icon: '/static/img/icons/icon-192x192.png',
        badge: '/static/img/icons/icon-maskable-192x192.png',
        vibrate: [100, 50, 100],
        tag: 'ipay-notif-' + item.id,
        data: { url: item.link || '/notifikasi', id: item.id }
      };
      event.waitUntil(
        Promise.all([
          self.registration.showNotification(title, options),
          setWorkerBadge(event.data.count || 1)
        ])
      );
    }
  }
});

