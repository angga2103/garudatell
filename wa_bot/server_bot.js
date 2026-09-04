const express = require('express');
const { default: makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion } = require('@whiskeysockets/baileys');
const pino = require('pino');

const app = express();
app.use(express.json());

let sock;

async function connectToWhatsApp() {
    const { state, saveCreds } = await useMultiFileAuthState('auth_info_baileys');
    const { version } = await fetchLatestBaileysVersion();

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
            const shouldReconnect = lastDisconnect?.error?.output?.statusCode !== 401;
            if (shouldReconnect) connectToWhatsApp();
        } else if (connection === 'open') {
            console.log('✅ BOT TERSAMBUNG KE META!');
        }
    });
}

connectToWhatsApp();

// Endpoint Status (Indikator paling akurat: sock.user)
app.get('/api/status', (req, res) => {
    const isConnected = !!sock?.user;
    res.json({ connected: isConnected });
});

app.post('/api/pair', async (req, res) => {
    let { number } = req.body;
    if (!number) return res.status(400).json({ status: 'error', message: 'Nomor kosong' });
    number = number.replace(/[^0-9]/g, '');
    try {
        if (sock?.user) return res.json({ status: 'error', message: 'Bot sudah terhubung!' });
        const code = await sock.requestPairingCode(number);
        const formattedCode = code?.match(/.{1,4}/g)?.join('-') || code;
        res.json({ status: 'success', code: formattedCode });
    } catch (err) {
        res.json({ status: 'error', message: err.message });
    }
});

// Endpoint BARU: Kirim Pesan Tes
app.post('/api/send', async (req, res) => {
    try {
        let { number, message } = req.body;
        if (!sock?.user) return res.json({ status: 'error', message: 'Mesin WA Disconnected' });
        if (!number || !message) return res.json({ status: 'error', message: 'Data tidak lengkap' });
        
        number = number.replace(/[^0-9]/g, '') + '@s.whatsapp.net';
        await sock.sendMessage(number, { text: message });
        res.json({ status: 'success' });
    } catch (err) {
        res.json({ status: 'error', message: err.message });
    }
});

app.listen(3000, () => console.log('🚀 Mesin Baileys V2.1 Aktif'));