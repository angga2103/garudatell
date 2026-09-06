const express = require('express');
const { 
    default: makeWASocket, 
    useMultiFileAuthState, 
    fetchLatestBaileysVersion, 
    Browsers, 
    DisconnectReason 
} = require('@whiskeysockets/baileys');
const pino = require('pino');
const path = require('path');
const fs = require('fs');
const https = require('https');

const app = express();
app.use(express.json());

// Global Exception Prevention
process.on('uncaughtException', (err) => {
    console.error('[BAILEYS UNCAUGHT EXCEPTION]', err);
});
process.on('unhandledRejection', (reason, promise) => {
    console.error('[BAILEYS UNHANDLED REJECTION]', reason);
});

// State & Paths
let sock = null;
let connectionState = 'close';
let isConnecting = false;
let reconnectTimer = null;
const authFolder = path.join(__dirname, 'auth_info_baileys');

// Muat konfigurasi Telegram dari file .env root jika tersedia
function loadEnvConfig() {
    const envPath = path.resolve(__dirname, '..', '.env');
    const config = {};
    if (fs.existsSync(envPath)) {
        try {
            const content = fs.readFileSync(envPath, 'utf8');
            content.split('\n').forEach(line => {
                const match = line.match(/^\s*([\w.-]+)\s*=\s*(.*)?\s*$/);
                if (match) {
                    let val = (match[2] || '').trim();
                    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
                        val = val.slice(1, -1);
                    }
                    config[match[1]] = val;
                }
            });
        } catch (e) {}
    }
    return {
        telegramToken: process.env.BOT_ADMIN_TOKEN || config.BOT_ADMIN_TOKEN || process.env.BOT_CS_TOKEN || config.BOT_CS_TOKEN || '',
        telegramChatId: process.env.BOT_ADMIN_CHAT_ID || config.BOT_ADMIN_CHAT_ID || process.env.BOT_CS_CHAT_ID || config.BOT_CS_CHAT_ID || ''
    };
}

const envConfig = loadEnvConfig();

// Helper Kirim Pesan ke Telegram
function sendTelegram(endpoint, payload) {
    if (!envConfig.telegramToken) return Promise.resolve(null);
    return new Promise((resolve) => {
        try {
            const dataString = JSON.stringify(payload);
            const options = {
                hostname: 'api.telegram.org',
                port: 443,
                path: `/bot${envConfig.telegramToken}/${endpoint}`,
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Content-Length': Buffer.byteLength(dataString)
                },
                timeout: 10000
            };
            const req = https.request(options, (res) => {
                let resBody = '';
                res.on('data', chunk => { resBody += chunk; });
                res.on('end', () => {
                    try { resolve(JSON.parse(resBody)); } catch (e) { resolve(null); }
                });
            });
            req.on('error', () => resolve(null));
            req.on('timeout', () => { req.destroy(); resolve(null); });
            req.write(dataString);
            req.end();
        } catch (e) {
            resolve(null);
        }
    });
}

// Cek apakah sesi aktif sudah tersimpan
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

// Bersihkan folder sesi auth
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
        console.log('[WA BOT] Direktori auth_info_baileys telah dibersihkan.');
    } catch (err) {
        console.error('[WA BOT] Gagal membersihkan folder auth:', err);
    }
}

// ==============================================================================
// 1. KONFIGURASI SOCKET (MUTLAK SESUAI ARSITEKTUR BOT-KASIR)
// ==============================================================================
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

        const { state, saveCreds } = await useMultiFileAuthState(authFolder);
        const { version } = await fetchLatestBaileysVersion();

        if (sock) {
            try { sock.ev.removeAllListeners(); } catch (e) {}
            try { sock.end(); } catch (e) {}
            sock = null;
        }

        connectionState = 'connecting';
        console.log(`[WA BOT] Menghubungkan Baileys v${version.join('.')}...`);

        sock = makeWASocket({
            version,
            logger: pino({ level: 'silent' }),
            printQRInTerminal: false, // Kita matikan QR, ganti ke Pairing
            auth: state,
            browser: Browsers.ubuntu('Chrome'),
            markOnlineOnConnect: true,
            connectTimeoutMs: 60000,
            keepAliveIntervalMs: 10000
        });
        global.sock = sock;

        sock.ev.on('creds.update', saveCreds);

        sock.ev.on('connection.update', (update) => {
            const { connection, lastDisconnect } = update;
            if (connection) {
                connectionState = connection;
            }

            if (connection === 'close') {
                const statusCode = (lastDisconnect?.error)?.output?.statusCode;
                const shouldReconnect = statusCode !== DisconnectReason.loggedOut;

                console.log(`[WA BOT] ⚠️ Koneksi terputus. Status Code: ${statusCode}. Reconnect: ${shouldReconnect}`);

                // JIKA BENAR-BENAR LOGGED OUT / TERHAPUS
                if (!shouldReconnect) {
                    console.log('🚨 [SYSTEM FATAL] Sesi WhatsApp Terhapus / Suspend!');
                    cleanAuthFolder();

                    // Kirim Notifikasi Alarm ke Telegram dengan Tombol Pairing Ulang
                    if (envConfig.telegramChatId) {
                        sendTelegram('sendMessage', {
                            chat_id: envConfig.telegramChatId,
                            text: `🚨 *WHATSAPP LOGGED OUT / TERHAPUS* 🚨\n\nSistem mendeteksi sesi WhatsApp bot telah hilang/ter-suspend.\n\nSilakan klik tombol di bawah untuk menautkan ulang:`,
                            parse_mode: 'Markdown',
                            reply_markup: {
                                inline_keyboard: [[{ text: '📱 TAUTKAN NOMOR BARU', callback_data: 'cmd_pair_new' }]]
                            }
                        });
                    }
                }

                if (shouldReconnect) {
                    const delay = (statusCode === DisconnectReason.restartRequired || statusCode === 515) ? 1000 : 5000;
                    console.log(`🔄 Mencoba menyambung kembali dalam ${delay / 1000} detik...`);
                    if (reconnectTimer) clearTimeout(reconnectTimer);
                    reconnectTimer = setTimeout(() => {
                        isConnecting = false;
                        connectToWhatsApp();
                    }, delay);
                }
            } else if (connection === 'open') {
                console.log('✅ BOT WHATSAPP SUKSES TERSAMBUNG KE META!');
                isConnecting = false;
                if (envConfig.telegramChatId) {
                    sendTelegram('sendMessage', {
                        chat_id: envConfig.telegramChatId,
                        text: `✅ *BOT WHATSAPP TERHUBUNG!*\n\nNomor: \`${sock.user?.id?.split(':')[0] || 'Aktif'}\`\nStatus: Online & Siap Kirim OTP / Notifikasi.`,
                        parse_mode: 'Markdown'
                    });
                }
            }
        });

    } catch (err) {
        console.error('[WA BOT] Gagal inisialisasi socket:', err);
    } finally {
        isConnecting = false;
    }
}

connectToWhatsApp();

// ==============================================================================
// 2 & 3. EKSEKUSI PAIRING CODE (STABILIZER 3000ms & REGEX FORMAT)
// ==============================================================================
async function generatePairingCode(phoneNumber) {
    if (!phoneNumber) throw new Error('Nomor WhatsApp tidak boleh kosong');
    const cleanNumber = phoneNumber.toString().replace(/[^0-9]/g, '').trim();

    if (!sock) {
        await connectToWhatsApp();
    }

    console.log(`[WA BOT] ⏳ Menunggu 3000ms untuk memastikan koneksi soket sudah stabil (${cleanNumber})...`);
    await new Promise(resolve => setTimeout(resolve, 3000));

    if (!sock) {
        throw new Error('Socket WhatsApp gagal diinisialisasi');
    }

    console.log(`[WA BOT] Mengirim requestPairingCode ke Meta untuk ${cleanNumber}...`);
    const code = await sock.requestPairingCode(cleanNumber);
    const formattedCode = code?.match(/.{1,4}/g)?.join('-') || code;
    console.log(`\n🔗 KODE PAIRING: ${formattedCode}\n`);
    return formattedCode;
}

// ==============================================================================
// 2. ALUR TELEGRAM (BOT TELEGRAM CS / ADMIN INTERACTION)
// ==============================================================================
const telegramUserState = {}; // Simpan state user yang sedang diminta nomor

async function startTelegramPolling() {
    if (!envConfig.telegramToken) return;

    let offset = 0;
    console.log('[TELEGRAM] Menjalankan listener Telegram untuk Pairing Code & Alarm...');

    while (true) {
        try {
            const res = await sendTelegram('getUpdates', {
                offset: offset,
                timeout: 20,
                allowed_updates: ['message', 'callback_query']
            });

            if (res && res.ok && Array.isArray(res.result)) {
                for (const update of res.result) {
                    offset = update.update_id + 1;

                    // A. Listener Callback Query (Tombol 'cmd_pair_new')
                    if (update.callback_query) {
                        const cb = update.callback_query;
                        const chatId = cb.message?.chat?.id;
                        const data = cb.data;

                        if (data === 'cmd_pair_new' && chatId) {
                            telegramUserState[chatId] = { awaitingNumber: true };
                            sendTelegram('answerCallbackQuery', {
                                callback_query_id: cb.id,
                                text: 'Silakan masukkan nomor WhatsApp bot'
                            });
                            sendTelegram('sendMessage', {
                                chat_id: chatId,
                                text: `📲 *INPUT NOMOR WHATSAPP BOT*\n\nSilakan ketik dan kirim nomor WhatsApp yang akan ditautkan ke chat ini.\n\nContoh: \`6281234567890\``,
                                parse_mode: 'Markdown'
                            });
                        }
                    }

                    // B. Listener Message (Tangkap balasan nomor diawali '62')
                    if (update.message && update.message.text) {
                        const msg = update.message;
                        const chatId = msg.chat?.id;
                        const text = msg.text.trim();

                        const isAwaiting = telegramUserState[chatId]?.awaitingNumber;
                        const isPhoneFormat = text.startsWith('62') && text.length >= 10 && text.length <= 16 && /^\d+$/.test(text);

                        if (isAwaiting || isPhoneFormat) {
                            delete telegramUserState[chatId];

                            sendTelegram('sendMessage', {
                                chat_id: chatId,
                                text: `⏳ *Memproses Pairing Code untuk nomor ${text}...*\n_Menunggu kestabilan soket 3 detik..._`,
                                parse_mode: 'Markdown'
                            });

                            try {
                                const formattedCode = await generatePairingCode(text);
                                sendTelegram('sendMessage', {
                                    chat_id: chatId,
                                    text: `🔗 *KODE PAIRING WHATSAPP:*\n\n\`${formattedCode}\`\n\n📌 *Langkah Tautkan:*\n1. Buka WhatsApp di HP\n2. Buka menu titik tiga / *Perangkat Tertaut*\n3. Pilih *Tautkan Perangkat* -> *Tautkan dengan nomor telepon saja*\n4. Masukkan kode 8 digit di atas.`,
                                    parse_mode: 'Markdown'
                                });
                            } catch (err) {
                                sendTelegram('sendMessage', {
                                    chat_id: chatId,
                                    text: `🚨 *Gagal meminta kode pairing:* ${err.message || 'Terjadi kendala soket'}`,
                                    parse_mode: 'Markdown'
                                });
                            }
                        }
                    }
                }
            } else if (res && res.error_code === 409) {
                // Jika token sedang di-polling oleh Bot Python (run_bot_admin.py), mundur 60 detik tanpa crash
                await new Promise(r => setTimeout(r, 60000));
            } else {
                await new Promise(r => setTimeout(r, 3000));
            }
        } catch (e) {
            await new Promise(r => setTimeout(r, 5000));
        }
    }
}

// Jalankan Telegram Listener secara background jika token ada
if (envConfig.telegramToken) {
    startTelegramPolling();
}

// ==============================================================================
// 4. REST API HTTP UNTUK DASHBOARD PANEL ADMIN GARUDATEL (FLASK)
// ==============================================================================

// Endpoint Status
app.get('/api/status', (req, res) => {
    const isRegistered = isSessionRegistered() || !!(sock?.authState?.creds?.registered && sock?.user);
    const isConnected = (connectionState === 'open') && isRegistered;
    res.json({
        status: 'ok',
        connected: isConnected,
        state: connectionState,
        registered: isRegistered,
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
        uptime: process.uptime(),
        user: isConnected ? (sock?.user || null) : null
    });
});

// Endpoint Minta Kode Pairing via Web Admin Panel
app.post('/api/pair', async (req, res) => {
    let { number } = req.body;
    if (!number) return res.status(400).json({ status: 'error', message: 'Nomor tidak boleh kosong' });

    number = number.toString().replace(/[^0-9]/g, '').trim();
    if (!number.startsWith('62')) {
        return res.json({ status: 'error', message: 'Nomor WhatsApp harus berawalan kode 62 (contoh: 628xxx)' });
    }

    try {
        const formattedCode = await generatePairingCode(number);
        res.json({ status: 'success', code: formattedCode });
    } catch (err) {
        console.error('[PAIR ERROR]', err);
        res.json({ status: 'error', message: err.message || 'Gagal meminta kode pairing dari Meta' });
    }
});

// Endpoint Kirim Pesan (OTP & Notifikasi Transaksi)
app.post('/api/send', async (req, res) => {
    try {
        let { number, message } = req.body;
        const isRegistered = isSessionRegistered() || !!(sock?.authState?.creds?.registered && sock?.user);
        if (!sock || connectionState !== 'open' || !isRegistered) {
            return res.json({ status: 'error', message: 'Mesin WhatsApp belum terhubung / offline' });
        }
        if (!number || !message) {
            return res.json({ status: 'error', message: 'Nomor dan pesan tidak boleh kosong' });
        }

        const jid = number.toString().replace(/[^0-9]/g, '') + '@s.whatsapp.net';
        await sock.sendMessage(jid, { text: message });
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
app.listen(PORT, HOST, () => console.log(`🚀 Mesin Baileys Berjalan di http://${HOST}:${PORT}`));