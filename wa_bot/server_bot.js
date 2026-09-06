const express = require('express');
const { default: makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion } = require('@whiskeysockets/baileys');
const pino = require('pino');
const path = require('path');
const fs = require('fs');

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
const authFolder = path.join(__dirname, 'auth_info_baileys');

async function connectToWhatsApp() {
    if (isConnecting) return;
    isConnecting = true;
    try {
        if (!fs.existsSync(authFolder)) {
            fs.mkdirSync(authFolder, { recursive: true });
        }
        const { state, saveCreds } = await useMultiFileAuthState(authFolder);
        const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: [2, 3000, 1015901307] }));

        sock = makeWASocket({
            version,
            logger: pino({ level: 'silent' }),
            printQRInTerminal: false,
            auth: state,
            browser: ['Ubuntu', 'Chrome', '20.0.04']
        });

        sock.ev.on('creds.update', saveCreds);

        sock.ev.on('connection.update', (update) => {
            const { connection, lastDisconnect } = update;
            if (connection === 'close') {
                const statusCode = lastDisconnect?.error?.output?.statusCode;
                const shouldReconnect = statusCode !== 401;
                console.log(`[WA BOT] Koneksi terputus (Status: ${statusCode}). Reconnect: ${shouldReconnect}`);
                if (shouldReconnect) {
                    setTimeout(() => {
                        isConnecting = false;
                        connectToWhatsApp();
                    }, 3000);
                } else {
                    console.log('[WA BOT] Sesi tidak valid (401). Silakan lakukan reset sesi.');
                    isConnecting = false;
                }
            } else if (connection === 'open') {
                console.log('✅ BOT TERSAMBUNG KE META!');
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

// Endpoint Status (Indikator paling akurat: sock.user)
app.get('/api/status', (req, res) => {
    const isConnected = !!sock?.user;
    res.json({
        status: 'ok',
        connected: isConnected,
        user: sock?.user || null
    });
});

// Endpoint Health
app.get('/api/health', (req, res) => {
    res.json({
        status: 'ok',
        connected: !!sock?.user,
        uptime: process.uptime(),
        user: sock?.user || null
    });
});

// Endpoint Minta Kode Pairing
app.post('/api/pair', async (req, res) => {
    let { number } = req.body;
    if (!number) return res.status(400).json({ status: 'error', message: 'Nomor tidak boleh kosong' });
    number = number.replace(/[^0-9]/g, '');

    try {
        if (!sock) {
            await connectToWhatsApp();
            await new Promise((resolve) => setTimeout(resolve, 1500));
        }
        if (sock?.user) {
            return res.json({ status: 'error', message: 'Bot sudah terhubung! Reset sesi terlebih dahulu jika ingin mengganti nomor.' });
        }
        if (!sock || typeof sock.requestPairingCode !== 'function') {
            return res.json({ status: 'error', message: 'Mesin socket belum siap. Silakan coba kembali dalam beberapa detik.' });
        }

        const code = await sock.requestPairingCode(number);
        const formattedCode = code?.match(/.{1,4}/g)?.join('-') || code;
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
        if (!sock?.user) return res.json({ status: 'error', message: 'Mesin WA Disconnected' });
        if (!number || !message) return res.json({ status: 'error', message: 'Data tidak lengkap' });

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
        if (sock) {
            try { sock.end(); } catch (e) {}
            sock = null;
        }
        if (fs.existsSync(authFolder)) {
            fs.rmSync(authFolder, { recursive: true, force: true });
        }
        setTimeout(() => connectToWhatsApp(), 1000);
        res.json({ status: 'success', message: 'Sesi WhatsApp berhasil dibersihkan & mesin siap pairing baru.' });
    } catch (err) {
        console.error('[RESET ERROR]', err);
        res.json({ status: 'error', message: err.message || 'Gagal mereset sesi WhatsApp' });
    }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`🚀 Mesin Baileys V2.2 Aktif di port ${PORT}`));