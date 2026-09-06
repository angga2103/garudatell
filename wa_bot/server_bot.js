const express = require('express');
const { 
    default: makeWASocket, 
    useMultiFileAuthState, 
    fetchLatestBaileysVersion, 
    fetchLatestWaWebVersion, 
    Browsers, 
    DisconnectReason 
} = require('@whiskeysockets/baileys');
const pino = require('pino');
const path = require('path');
const fs = require('fs');
const QRCode = require('qrcode');

const app = express();
app.use(express.json());

// Global error prevention agar Node.js / PM2 tidak crash mendadak
process.on('uncaughtException', (err) => {
    console.error('[BAILEYS UNCAUGHT EXCEPTION]', err);
});
process.on('unhandledRejection', (reason, promise) => {
    console.error('[BAILEYS UNHANDLED REJECTION]', reason);
});

let sock = null;
let isConnecting = false;
let connectionState = 'close'; // 'close' | 'connecting' | 'open'
let reconnectTimer = null;
let currentQrCode = null; // Base64 Data URL untuk QR Code
const authFolder = path.join(__dirname, 'auth_info_baileys');

// Fungsi pembantu untuk cek apakah auth directory memiliki sesi aktif yang sudah terdaftar
function isSessionRegistered() {
    try {
        const credsPath = path.join(authFolder, 'creds.json');
        if (fs.existsSync(credsPath)) {
            const creds = JSON.parse(fs.readFileSync(credsPath, 'utf8'));
            return !!(creds.registered && creds.me);
        }
    } catch (e) {}
    return false;
}

// Membersihkan creds.me yang unverified agar saat reconnect tidak memicu "401 Connection Failure"
function sanitizeUnverifiedCreds() {
    try {
        const credsPath = path.join(authFolder, 'creds.json');
        if (fs.existsSync(credsPath)) {
            const creds = JSON.parse(fs.readFileSync(credsPath, 'utf8'));
            if (!creds.registered && creds.me) {
                console.log('[WA BOT] Membersihkan creds.me yang belum terdaftar sebelum menghubungkan ke Meta...');
                delete creds.me;
                delete creds.pairingCode;
                fs.writeFileSync(credsPath, JSON.stringify(creds, null, 2));
            }
        }
    } catch (e) {
        console.error('[WA BOT] Gagal sanitize unverified creds:', e);
    }
}

// Membersihkan sesi
function cleanAuthFolder() {
    try {
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
        if (sock) {
            try { sock.ev.removeAllListeners(); } catch (e) {}
            try { sock.end(); } catch (e) {}
            sock = null;
        }
        if (fs.existsSync(authFolder)) {
            fs.rmSync(authFolder, { recursive: true, force: true });
        }
        connectionState = 'close';
        currentQrCode = null;
        console.log('[WA BOT] Direktori auth_info_baileys telah dibersihkan.');
    } catch (err) {
        console.error('[WA BOT] Gagal membersihkan folder auth:', err);
    }
}

async function getValidWaVersion() {
    // 1. Coba ambil versi WA Web aktif langsung dari Meta
    try {
        const webVer = await fetchLatestWaWebVersion();
        if (webVer?.version && Array.isArray(webVer.version)) {
            return webVer.version;
        }
    } catch (e) {}

    // 2. Fallback ke Baileys release version
    try {
        const baileysVer = await fetchLatestBaileysVersion();
        if (baileysVer?.version && Array.isArray(baileysVer.version)) {
            return baileysVer.version;
        }
    } catch (e) {}

    // 3. Fallback ke verified stable WA Web version
    return [2, 3000, 1046911082];
}

async function connectToWhatsApp() {
    if (isConnecting) return;
    isConnecting = true;
    if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
    }

    try {
        if (!fs.existsSync(authFolder)) {
            fs.mkdirSync(authFolder, { recursive: true });
        }

        // Cegah Baileys login premature dengan nomor unverified yang memicu 401
        if (!isSessionRegistered()) {
            sanitizeUnverifiedCreds();
        }

        const waVersion = await getValidWaVersion();
        console.log(`[WA BOT] Menggunakan WhatsApp Web Version: ${waVersion.join('.')}`);

        const { state, saveCreds } = await useMultiFileAuthState(authFolder);

        // Hentikan listener socket lama jika ada
        if (sock) {
            try { sock.ev.removeAllListeners(); } catch (e) {}
            try { sock.end(); } catch (e) {}
            sock = null;
        }

        connectionState = 'connecting';

        sock = makeWASocket({
            version: waVersion,
            logger: pino({ level: 'info' }),
            printQRInTerminal: false,
            auth: state,
            browser: Browsers.macOS('Desktop'), // Browser macOS Desktop memiliki trust level tertinggi di Meta Multi-Device
            qrTimeout: 300000, // 5 menit per siklus QR agar tidak cepat timeout 408
            markOnlineOnConnect: false,
            generateHighQualityLinkPreview: false,
            syncFullHistory: false
        });

        sock.ev.on('creds.update', saveCreds);

        sock.ev.on('connection.update', async (update) => {
            const { connection, lastDisconnect, qr } = update;
            if (connection) {
                connectionState = connection;
            }

            if (qr) {
                try {
                    currentQrCode = await QRCode.toDataURL(qr, { margin: 2, scale: 6 });
                    console.log('[WA BOT] 📲 Kode QR baru siap discan di Admin Panel!');
                } catch (err) {
                    console.error('[WA BOT] Gagal render QR Code:', err);
                }
            }

            if (connection === 'close') {
                const statusCode = lastDisconnect?.error?.output?.statusCode;
                const isLoggedOut = (statusCode === DisconnectReason.loggedOut || statusCode === 401) && isSessionRegistered();
                console.log(`[WA BOT] ⚠️ Koneksi terputus. Status Code: ${statusCode} (${lastDisconnect?.error?.message || 'Tanpa pesan'}). Sesi Keluar: ${isLoggedOut}`);

                if (isLoggedOut) {
                    console.log('[WA BOT] 🚨 Sesi WhatsApp telah Logout / Dikeluarkan dari HP. Membersihkan memori sesi...');
                    cleanAuthFolder();
                } else if (statusCode === DisconnectReason.restartRequired || statusCode === 515) {
                    // KODE 515: WhatsApp Companion Registration Handshake meminta restart koneksi segera
                    console.log('[WA BOT] 🔄 Status 515 (restartRequired): Handshake pairing berhasil diverifikasi Meta! Melakukan reconnect instan...');
                    if (reconnectTimer) clearTimeout(reconnectTimer);
                    reconnectTimer = setTimeout(() => {
                        isConnecting = false;
                        connectToWhatsApp();
                    }, 500);
                } else {
                    console.log('[WA BOT] ⏳ Menghubungkan ulang dalam 3 detik...');
                    if (reconnectTimer) clearTimeout(reconnectTimer);
                    reconnectTimer = setTimeout(() => {
                        isConnecting = false;
                        connectToWhatsApp();
                    }, 3000);
                }
            } else if (connection === 'open') {
                console.log('✅ BOT WHATSAPP SUKSES TERSAMBUNG KE META!');
                currentQrCode = null;
                isConnecting = false;
            }
        });
    } catch (err) {
        console.error('[WA BOT] Gagal menginisialisasi socket:', err);
    } finally {
        isConnecting = false;
    }
}

connectToWhatsApp();

// Endpoint Status
app.get('/api/status', (req, res) => {
    const isRegistered = isSessionRegistered() || !!(sock?.authState?.creds?.registered && sock?.user);
    const isConnected = (connectionState === 'open') && isRegistered;
    res.json({
        status: 'ok',
        connected: isConnected,
        state: connectionState,
        registered: isRegistered,
        qr: isConnected ? null : currentQrCode,
        user: isConnected ? (sock?.user || null) : null
    });
});

// Endpoint Health
app.get('/api/health', (req, res) => {
    const isRegistered = isSessionRegistered() || !!(sock?.authState?.creds?.registered && sock?.user);
    const isConnected = (connectionState === 'open') && isRegistered;
    res.json({
        status: 'ok',
        connected: isConnected,
        state: connectionState,
        registered: isRegistered,
        qr: isConnected ? null : currentQrCode,
        uptime: process.uptime(),
        user: isConnected ? (sock?.user || null) : null
    });
});

// Endpoint QR Code langsung
app.get('/api/qr', (req, res) => {
    res.json({
        status: 'ok',
        qr: currentQrCode,
        connected: (connectionState === 'open') && isSessionRegistered()
    });
});

// Endpoint Minta Kode Pairing
app.post('/api/pair', async (req, res) => {
    let { number } = req.body;
    if (!number) return res.status(400).json({ status: 'error', message: 'Nomor tidak boleh kosong' });
    number = number.replace(/[^0-9]/g, '');

    try {
        const isRegistered = isSessionRegistered() || !!(sock?.authState?.creds?.registered && sock?.user);
        if (isRegistered && connectionState === 'open') {
            return res.json({ 
                status: 'error', 
                message: 'Bot sudah terhubung dan aktif! Silakan klik tombol "Reset Sesi" terlebih dahulu jika ingin mengganti nomor.' 
            });
        }

        console.log(`[WA BOT] Menerima permintaan kode pairing untuk nomor: ${number}. Menyiapkan sesi baru...`);

        // Bersihkan sesi unverified untuk memastikan pairingEphemeralKeyPair & noiseKey 100% fresh dan sinkron
        if (!isRegistered) {
            cleanAuthFolder();
            await connectToWhatsApp();
        }

        if (!sock) {
            return res.json({ status: 'error', message: 'Gagal menginisialisasi socket WhatsApp. Coba lagi dalam beberapa detik.' });
        }

        // Tunggu hingga WebSocket ke gateway Meta terbuka (maks 10 detik)
        let attempts = 0;
        while ((!sock.ws || !sock.ws.isOpen) && attempts < 20) {
            await new Promise(r => setTimeout(r, 500));
            attempts++;
        }

        if (!sock.ws || !sock.ws.isOpen) {
            return res.json({ status: 'error', message: 'Mesin socket belum terhubung ke gateway Meta. Silakan ulangi sesaat lagi.' });
        }

        // Jeda 1.5 detik agar socket handshake stabil sebelum mengirim permintaan pairing code
        await new Promise(r => setTimeout(r, 1500));

        console.log(`[WA BOT] Mengirim requestPairingCode ke Meta untuk ${number}...`);
        const code = await sock.requestPairingCode(number);
        const formattedCode = code?.match(/.{1,4}/g)?.join('-') || code;
        console.log(`[WA BOT] ✅ Sukses! Kode pairing dari Meta: ${formattedCode}`);

        res.json({ status: 'success', code: formattedCode });
    } catch (err) {
        console.error('[PAIR ERROR]', err);
        res.json({ status: 'error', message: err.message || 'Gagal meminta kode pairing dari Meta' });
    }
});

// Endpoint Kirim Pesan
app.post('/api/send', async (req, res) => {
    try {
        let { number, message } = req.body;
        const isRegistered = isSessionRegistered() || !!(sock?.authState?.creds?.registered && sock?.user);
        if (!sock || connectionState !== 'open' || !isRegistered) {
            return res.json({ status: 'error', message: 'Mesin WA Disconnected / Belum Terhubung' });
        }
        if (!number || !message) {
            return res.json({ status: 'error', message: 'Data tidak lengkap' });
        }

        number = number.replace(/[^0-9]/g, '') + '@s.whatsapp.net';
        await sock.sendMessage(number, { text: message });
        res.json({ status: 'success' });
    } catch (err) {
        console.error('[SEND ERROR]', err);
        res.json({ status: 'error', message: err.message || 'Gagal mengirim pesan via WhatsApp' });
    }
});

// Endpoint Reset Sesi
app.post('/api/reset', async (req, res) => {
    try {
        console.log('[WA BOT] Melakukan reset sesi WhatsApp...');
        cleanAuthFolder();
        setTimeout(() => connectToWhatsApp(), 1000);
        res.json({ status: 'success', message: 'Sesi WhatsApp berhasil dibersihkan & mesin siap pairing baru.' });
    } catch (err) {
        console.error('[RESET ERROR]', err);
        res.json({ status: 'error', message: err.message || 'Gagal mereset sesi WhatsApp' });
    }
});

const PORT = process.env.PORT || 3000;
const HOST = process.env.HOST || '0.0.0.0';
app.listen(PORT, HOST, () => console.log(`🚀 Mesin Baileys V2.3 Aktif di http://${HOST}:${PORT}`));