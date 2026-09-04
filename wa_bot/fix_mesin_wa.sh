#!/bin/bash
echo "============================================================"
echo "🛠️ MENYEMBUHKAN MESIN BAILEYS (ARSITEKTUR ANTI-TABRAKAN)"
echo "============================================================"

# 1. Matikan proses bot
pm2 stop garudatel-wa-bot

# 2. Hapus memori sesi yang macet
echo "[*] Membersihkan memori sesi lama..."
rm -rf auth_info_baileys

# 3. Merakit ulang otak Baileys (Singleton Pattern)
echo "[*] Menulis ulang server_bot.js..."
cat << 'NODE_EOF' > server_bot.js
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

// Langsung nyalakan 1 koneksi permanen
connectToWhatsApp();

app.post('/api/pair', async (req, res) => {
    let { number } = req.body;
    if (!number) return res.status(400).json({ status: 'error', message: 'Nomor kosong' });
    
    number = number.replace(/[^0-9]/g, '');

    try {
        if (sock?.authState?.creds?.registered) {
            return res.json({ status: 'error', message: 'Bot sudah terdaftar! Hapus sesi di server untuk ganti nomor.' });
        }
        const code = await sock.requestPairingCode(number);
        const formattedCode = code?.match(/.{1,4}/g)?.join('-') || code;
        res.json({ status: 'success', code: formattedCode });
    } catch (err) {
        res.json({ status: 'error', message: 'Gagal meminta kode dari Meta. Coba sesaat lagi.' });
    }
});

app.listen(3000, () => console.log('🚀 Mesin Baileys V2 Aktif'));
NODE_EOF

# 4. Nyalakan kembali
echo "[*] Menyalakan ulang PM2..."
pm2 start server_bot.js --name garudatel-wa-bot
pm2 save

echo "[V] TAHAP 1 SELESAI: Mesin Node.js Sehat!"
