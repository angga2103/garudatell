function cleanRawSn(rawSn) {
    if (!rawSn) return '';
    return String(rawSn).trim().replace(/^(SN|Keterangan|KET)\s*:\s*/i, '').trim();
}

function parseSnData(rawSn, isFailed = false) {
    const s = cleanRawSn(rawSn);
    if (!s) return { type: 'empty', raw: '' };
    if (isFailed) return { type: 'failed', raw: s, message: s };

    // 1. PLN Token (20 Digit)
    const plnMatch = s.match(/(?:^|\D)(\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4})(?:\D|$)/);
    const digitsToken = plnMatch ? plnMatch[1].replace(/[-\s]/g, '') : '';
    if (plnMatch && (
        /kwh|pln|r1|b1|i1|va|stroom/i.test(s) ||
        digitsToken.length === 20 ||
        s.split('/').length >= 3
    )) {
        const rawToken = digitsToken;
        const formattedToken = rawToken.match(/.{1,4}/g).join(' - ');
        const parts = s.split('/').map(p => p.trim()).filter(p => p && p.replace(/[-\s]/g, '') !== rawToken);
        return {
            type: 'pln_token',
            raw: s,
            rawToken: rawToken,
            formattedToken: formattedToken,
            infoParts: parts
        };
    }

    // 2. Telkomsel Info / Cek Kuota
    if (/Masa Aktif Kartu|-Status Registrasi|-Info Paket Aktif|-Status Jaringan/i.test(s)) {
        const parts = s.split(/\s*-(?=(?:Status|Info|Masa)\b)/i);
        const fields = {};
        parts.forEach(p => {
            const cleanP = p.trim().replace(/^-+/, '').trim();
            const idx = cleanP.indexOf(':');
            if (idx !== -1) {
                const k = cleanP.slice(0, idx).trim().toLowerCase();
                const v = cleanP.slice(idx + 1).trim();
                fields[k] = v;
            }
        });

        let ma = fields['masa aktif kartu'] || '';
        if (ma === '-' || ma === '') ma = '';

        const reg = fields['status registrasi'] || '';
        const net = fields['status jaringan'] || '';
        let dev = fields['status perangkat'] || '';
        if (dev === '-' || dev === '') dev = '';

        const infoPkg = fields['info paket aktif'] || '';
        const pkgs = [];
        if (infoPkg) {
            const rawP = infoPkg.split(/#\d+\s*-\s*/);
            rawP.forEach(rp => {
                const item = rp.trim();
                if (!item || item === '-') return;
                const mExp = item.match(/\s*-\s*(aktif\s+hingga.*?)$/i);
                if (mExp) {
                    const pname = item.slice(0, mExp.index).trim();
                    const pexp = mExp[1].trim();
                    pkgs.push({ name: pname, expired: pexp });
                } else {
                    pkgs.push({ name: item, expired: '' });
                }
            });
        }

        return {
            type: 'telkomsel_info',
            raw: s,
            masaAktif: ma,
            registrasi: reg,
            jaringan: net,
            perangkat: dev,
            packages: pkgs
        };
    }

    // 3. XL Info / Cek Kuota
    if (/dukcapil=/i.test(s) || (/\.expired:/i.test(s) && /data/i.test(s))) {
        const parts = s.split('/').map(p => p.trim()).filter(Boolean);
        let dukcapil = '';
        const pkgs = [];
        parts.forEach(p => {
            if (/dukcapil=/i.test(p)) {
                const val = p.split('=')[1].trim();
                dukcapil = (val.toLowerCase() === 'registered') ? 'Terdaftar (Dukcapil)' : val + ' (Dukcapil)';
            } else {
                const m = p.match(/^(?:\d+\.\s*)?(.*?)\.Expired:([^\s]+(?:\s+[^\s]+)?)\s*(?:DATA\s*(.*?))?$/i);
                if (m) {
                    pkgs.push({
                        name: m[1].trim(),
                        expired: m[2].trim(),
                        quota: (m[3] || '').trim()
                    });
                } else {
                    pkgs.push({ name: p, expired: '', quota: '' });
                }
            }
        });

        return {
            type: 'xl_info',
            raw: s,
            dukcapil: dukcapil,
            packages: pkgs
        };
    }

    // 4. Multi-Package Bertanda '*' atau 'sisa kuota'
    if (s.includes('*') || /sisa kuota/i.test(s)) {
        const parts = s.split('*').map(p => p.trim()).filter(Boolean);
        const pkgs = [];
        let pulsaInfo = '';
        let cardInfo = '';
        parts.forEach(p => {
            if (p.toLowerCase().startsWith('sisa pulsa')) {
                pulsaInfo = p;
            } else if (!p.includes('/') && /kartu|perdana|nomor|aktif/i.test(p)) {
                cardInfo = p;
            } else {
                const m = p.match(/^(.*?)\s*\/\s*(Sisa Kuota.*)$/i);
                if (m) {
                    const title = m[1].trim();
                    const details = m[2].trim();
                    const subItems = details.split(/,\s*(?=\d+|Nelp|Sisa|Kuota|Bonus)/i).map(it => it.trim()).filter(Boolean);
                    pkgs.push({ title, items: subItems });
                } else {
                    pkgs.push({ title: p, items: [] });
                }
            }
        });

        return {
            type: 'multi_quota',
            raw: s,
            cardInfo,
            pulsaInfo,
            packages: pkgs
        };
    }

    // 5. Voucher
    if (/KODE VOUCHER|VOUCHER:|KODE:/i.test(s)) {
        return {
            type: 'voucher',
            raw: s,
            details: s.split('/').map(p => p.trim()).filter(Boolean)
        };
    }

    return {
        type: 'simple',
        raw: s
    };
}

function formatSnForCopy(rawSn, isFailed = false) {
    const data = parseSnData(rawSn, isFailed);
    if (data.type === 'empty') return '-';
    if (data.type === 'failed') return data.message || '';

    if (data.type === 'pln_token') {
        const lines = ['TOKEN PLN : ' + data.formattedToken];
        if (data.infoParts && data.infoParts.length > 0) {
            lines.push('Info      : ' + data.infoParts.join(' / '));
        }
        return lines.join('\n');
    }

    if (data.type === 'telkomsel_info') {
        const lines = [];
        if (data.masaAktif) lines.push('Masa Aktif : ' + data.masaAktif);
        if (data.registrasi) lines.push('Registrasi : ' + data.registrasi);
        if (data.jaringan) {
            let net = data.jaringan;
            if (data.perangkat) net += ' (Perangkat: ' + data.perangkat + ')';
            lines.push('Jaringan   : ' + net);
        }
        if (data.packages && data.packages.length > 0) {
            lines.push('Paket Aktif:');
            data.packages.forEach(p => {
                lines.push('• ' + p.name);
                if (p.expired) lines.push('  (' + p.expired + ')');
            });
        } else {
            lines.push('Paket Aktif: Tidak ada paket aktif');
        }
        return lines.join('\n');
    }

    if (data.type === 'xl_info') {
        const lines = [];
        if (data.dukcapil) lines.push('Registrasi : ' + data.dukcapil);
        if (data.packages && data.packages.length > 0) {
            lines.push('Paket Aktif:');
            data.packages.forEach(p => {
                lines.push('• ' + p.name);
                if (p.expired) lines.push('  Masa Aktif : ' + p.expired);
                if (p.quota) lines.push('  Sisa Kuota : ' + p.quota);
            });
        }
        return lines.join('\n');
    }

    if (data.type === 'multi_quota') {
        const lines = [];
        if (data.cardInfo) lines.push('Kartu : ' + data.cardInfo);
        if (data.pulsaInfo) lines.push('Pulsa : ' + data.pulsaInfo);
        if (data.packages && data.packages.length > 0) {
            lines.push('Paket & Kuota:');
            data.packages.forEach(p => {
                lines.push('• ' + p.title);
                (p.items || []).forEach(it => lines.push('  - ' + it));
            });
        }
        return lines.join('\n');
    }

    if (data.type === 'voucher') {
        return (data.details || [data.raw]).join('\n');
    }

    return data.raw;
}

const tests = [
    'Masa Aktif Kartu : 13 Juni 2027 -Status Registrasi : Terdaftar -Status Jaringan : 4G -Status Perangkat : 4G -Info Paket Aktif : #1 -',
    'Masa Aktif Kartu : - -Status Registrasi : Terdaftar -Status Jaringan : 4G -Status Perangkat : - -Info Paket Aktif : #1 -',
    'Masa Aktif Kartu : 24 Oktober 2026 -Status Registrasi : Terdaftar -Status Jaringan : 4G -Status Perangkat : - -Info Paket Aktif : #1 - kuota belajar/ilmupedia 7 Hari (11.00 GB / 11.00 GB) - Aktif hingga 12 Oktober 2026',
    'Dukcapil=Registered / 1.Xtra Edukasi 15GB, 7hr.Expired:14-Oct-26 23:59:59 DATA Xtra Edukasi 24jam di 2G3G4G 6.22 GB',
    '1234-5678-9012-3456-7890 / NUR HAYATI / R1 / 900VA / 54.2KWH',
    '0214087997076300006722'
];

tests.forEach((t, i) => {
    console.log(`\n=== TEST ${i+1} ===`);
    console.log(formatSnForCopy(t));
});
