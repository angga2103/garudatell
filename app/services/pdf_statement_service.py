import io
import os
import calendar
from datetime import datetime, timedelta

INDONESIAN_MONTHS = {
    1: 'Januari', 2: 'Februari', 3: 'Maret', 4: 'April',
    5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Agustus',
    9: 'September', 10: 'Oktober', 11: 'November', 12: 'Desember'
}


def format_rupiah(val):
    try:
        f_val = float(val or 0.0)
        return f"Rp {f_val:,.0f}".replace(",", ".")
    except Exception:
        return "Rp 0"


def _extract_statement_summary(statement_data):
    """
    Mengekstrak data ringkasan finansial (Saldo Awal, Saldo Akhir, Total Masuk, Total Keluar, Refund)
    secara presisi baik dari dict `stats`, key level-root, maupun kalkulasi langsung dari `mutations`.
    """
    stats = statement_data.get('stats') if isinstance(statement_data.get('stats'), dict) else {}
    mutations = statement_data.get('mutations', [])

    starting_bal = stats.get('starting_balance')
    ending_bal = stats.get('ending_balance')
    tot_in = stats.get('total_pemasukan')
    tot_out = stats.get('total_pengeluaran')
    tot_ref = stats.get('total_refund')

    if starting_bal is None:
        starting_bal = statement_data.get('starting_balance')
    if ending_bal is None:
        ending_bal = statement_data.get('ending_balance')
    if tot_in is None:
        tot_in = statement_data.get('total_pemasukan')
    if tot_out is None:
        tot_out = statement_data.get('total_pengeluaran')
    if tot_ref is None:
        tot_ref = statement_data.get('total_refund')

    # Jika stats 0 atau kosong padahal ada data mutasi di tabel, hitung langsung dari mutations
    if mutations:
        sorted_m = sorted(mutations, key=lambda x: x.get('date_str', ''))
        calc_starting = sorted_m[0].get('balance_before', 0.0)
        calc_ending = sorted_m[-1].get('balance_after', 0.0)
        calc_in = sum(float(m.get('amount', 0.0) or 0.0) for m in sorted_m if m.get('type') == 'pemasukan')
        calc_out = sum(float(m.get('amount', 0.0) or 0.0) for m in sorted_m if m.get('type') == 'pengeluaran')
        calc_ref = sum(float(m.get('amount', 0.0) or 0.0) for m in sorted_m if m.get('type') == 'refund')

        if starting_bal is None or (starting_bal == 0.0 and ending_bal == 0.0 and (calc_ending != 0.0 or calc_in != 0.0 or calc_out != 0.0)):
            starting_bal = calc_starting
        if ending_bal is None or (ending_bal == 0.0 and calc_ending != 0.0):
            ending_bal = calc_ending
        if tot_in is None or (tot_in == 0.0 and calc_in != 0.0):
            tot_in = calc_in
        if tot_out is None or (tot_out == 0.0 and calc_out != 0.0):
            tot_out = calc_out
        if tot_ref is None or (tot_ref == 0.0 and calc_ref != 0.0):
            tot_ref = calc_ref

    starting_bal = float(starting_bal or 0.0)
    ending_bal = float(ending_bal or 0.0)
    tot_in = float(tot_in or 0.0)
    tot_out = float(tot_out or 0.0)
    tot_ref = float(tot_ref or 0.0)
    tot_kredit = tot_in + tot_ref

    return {
        'starting_bal': starting_bal,
        'ending_bal': ending_bal,
        'tot_in': tot_in,
        'tot_out': tot_out,
        'tot_ref': tot_ref,
        'tot_kredit': tot_kredit,
        'mutations': mutations
    }


# =====================================================================
# ENGINE 1: REPORTLAB (PRIMARY ENGINE BILA LIBRARY TERPASANG)
# =====================================================================
def _generate_with_reportlab(user, month, year, statement_data):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, HRFlowable
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.pdfgen import canvas

    class NumberedCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super(NumberedCanvas, self).__init__(*args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            num_pages = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self.draw_page_decorations(num_pages)
                super(NumberedCanvas, self).showPage()
            super(NumberedCanvas, self).save()

        def draw_page_decorations(self, page_count):
            self.saveState()
            self.setFont("Helvetica", 7.5)
            self.setFillColor(colors.HexColor("#64748B"))
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.5)
            self.line(1.2 * cm, 1.4 * cm, A4[0] - 1.2 * cm, 1.4 * cm)
            self.drawString(
                1.2 * cm, 
                1.0 * cm, 
                "Dokumen Rekening Koran Resmi iPay • Diterbitkan otomatis oleh sistem Garuda Digital Media • https://ipay.my.id"
            )
            page_str = f"Halaman {self._pageNumber} dari {page_count}"
            self.drawRightString(A4[0] - 1.2 * cm, 1.0 * cm, page_str)
            self.restoreState()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.8 * cm
    )

    base_styles = getSampleStyleSheet()
    style_company_title = ParagraphStyle(
        'CompanyTitle', parent=base_styles['Normal'],
        fontName='Helvetica-Bold', fontSize=12, leading=14, textColor=colors.HexColor("#00877A")
    )
    style_company_sub = ParagraphStyle(
        'CompanySub', parent=base_styles['Normal'],
        fontName='Helvetica', fontSize=7.5, leading=9.5, textColor=colors.HexColor("#475569")
    )
    style_stmt_title = ParagraphStyle(
        'StatementTitle', parent=base_styles['Normal'],
        fontName='Helvetica-Bold', fontSize=13, leading=15, alignment=2, textColor=colors.HexColor("#0F172A")
    )
    style_stmt_sub = ParagraphStyle(
        'StatementSub', parent=base_styles['Normal'],
        fontName='Helvetica', fontSize=7.5, leading=10, alignment=2, textColor=colors.HexColor("#64748B")
    )
    style_box_label = ParagraphStyle(
        'BoxLabel', parent=base_styles['Normal'],
        fontName='Helvetica', fontSize=7, leading=8.5, textColor=colors.HexColor("#64748B")
    )
    style_box_value = ParagraphStyle(
        'BoxValue', parent=base_styles['Normal'],
        fontName='Helvetica-Bold', fontSize=8.5, leading=10.5, textColor=colors.HexColor("#0F172A")
    )
    style_table_th = ParagraphStyle(
        'TableTH', parent=base_styles['Normal'],
        fontName='Helvetica-Bold', fontSize=7.5, leading=9, textColor=colors.white, alignment=1
    )
    style_cell_normal = ParagraphStyle(
        'CellNormal', parent=base_styles['Normal'],
        fontName='Helvetica', fontSize=7, leading=8.5, textColor=colors.HexColor("#1E293B")
    )
    style_cell_center = ParagraphStyle(
        'CellCenter', parent=base_styles['Normal'],
        fontName='Helvetica', fontSize=7, leading=8.5, alignment=1, textColor=colors.HexColor("#334155")
    )
    style_cell_green = ParagraphStyle(
        'CellGreen', parent=base_styles['Normal'],
        fontName='Helvetica-Bold', fontSize=7, leading=8.5, alignment=2, textColor=colors.HexColor("#16A34A")
    )
    style_cell_red = ParagraphStyle(
        'CellRed', parent=base_styles['Normal'],
        fontName='Helvetica-Bold', fontSize=7, leading=8.5, alignment=2, textColor=colors.HexColor("#DC2626")
    )
    style_cell_balance = ParagraphStyle(
        'CellBalance', parent=base_styles['Normal'],
        fontName='Helvetica-Bold', fontSize=7, leading=8.5, alignment=2, textColor=colors.HexColor("#0F172A")
    )

    story = []

    # Logo (Safe with fallback if Pillow not installed)
    logo_cell = None
    try:
        from reportlab.platypus import Image as RLImage
        logo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static', 'img', 'icons', 'icon-192x192.png'))
        if os.path.exists(logo_path):
            logo_img = RLImage(logo_path, width=36, height=36)
            logo_cell = logo_img
    except Exception:
        logo_cell = None

    month_name = INDONESIAN_MONTHS.get(int(month), f"Bulan {month}")
    last_day = calendar.monthrange(int(year), int(month))[1]
    period_str = f"01 {month_name} {year} - {last_day:02d} {month_name} {year}"
    wib_now = datetime.utcnow() + timedelta(hours=7)
    print_date_str = wib_now.strftime("%d/%m/%Y %H:%M:%S") + " WIB"
    stmt_code = f"STMT-{year}{int(month):02d}-{user.id}"

    if logo_cell:
        header_table_left_data = [[
            logo_cell,
            [
                Paragraph("<b>GARUDA DIGITAL MEDIA</b>", style_company_title),
                Paragraph("<b>iPay Platform</b> • Layanan Distribusi Pulsa & PPOB Terpercaya", style_company_sub),
                Paragraph("Website: https://ipay.my.id • Layanan CS: 08:00 - 23:00 WIB", style_company_sub)
            ]
        ]]
        header_left = Table(header_table_left_data, colWidths=[42, 230])
        header_left.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
    else:
        header_left = [
            Paragraph("<b>GARUDA DIGITAL MEDIA</b>", style_company_title),
            Paragraph("<b>iPay Platform</b> • Layanan Distribusi Pulsa & PPOB Terpercaya", style_company_sub),
            Paragraph("Website: https://ipay.my.id • Layanan CS: 08:00 - 23:00 WIB", style_company_sub)
        ]

    header_right = [
        Paragraph("<b>REKENING KORAN ELEKTRONIK</b>", style_stmt_title),
        Paragraph("<font color='#00877a'><b>ELECTRONIC ACCOUNT STATEMENT</b></font>", style_stmt_sub),
        Spacer(1, 2),
        Paragraph(f"No. Dokumen: <b>{stmt_code}</b>", style_stmt_sub),
        Paragraph(f"Waktu Cetak: {print_date_str}", style_stmt_sub)
    ]

    header_table = Table([[header_left, header_right]], colWidths=[280, 240])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#00877A"), spaceAfter=8, spaceBefore=4))

    # Metadata
    user_name = (getattr(user, 'name', '') or f"Pengguna #{user.id}").strip()
    user_phone = getattr(user, 'phone', '-') or '-'
    user_role = (getattr(user, 'role', 'MEMBER') or 'MEMBER').upper()

    meta_data = [
        [
            Paragraph("NAMA PEMILIK AKUN", style_box_label),
            Paragraph(f": <b>{user_name.upper()}</b>", style_box_value),
            Paragraph("PERIODE MUTASI", style_box_label),
            Paragraph(f": <b>{period_str}</b>", style_box_value),
        ],
        [
            Paragraph("NO. TELEPON / ID", style_box_label),
            Paragraph(f": {user_phone} (ID: #{user.id})", style_box_value),
            Paragraph("MATA UANG", style_box_label),
            Paragraph(": <b>IDR (Rupiah Indonesia)</b>", style_box_value),
        ],
        [
            Paragraph("TIPE / STATUS AKUN", style_box_label),
            Paragraph(f": <font color='#00877A'><b>{user_role}</b></font> • AKTIF", style_box_value),
            Paragraph("LEMBAGA PENYEDIA", style_box_label),
            Paragraph(": Garuda Digital Media (iPay)", style_box_value),
        ]
    ]

    meta_table = Table(meta_data, colWidths=[95, 165, 95, 165])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#E2E8F0")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#F1F5F9")),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 8))

    # Financial Summary Box
    summary_info = _extract_statement_summary(statement_data)
    starting_bal = summary_info['starting_bal']
    ending_bal = summary_info['ending_bal']
    tot_in = summary_info['tot_in']
    tot_out = summary_info['tot_out']
    tot_ref = summary_info['tot_ref']
    tot_kredit = summary_info['tot_kredit']
    mutations = summary_info['mutations']

    summary_cells = [
        [
            Paragraph("<b>SALDO AWAL</b>", style_box_label),
            Paragraph("<b>TOTAL KREDIT (+)</b>", style_box_label),
            Paragraph("<b>TOTAL DEBIT (-)</b>", style_box_label),
            Paragraph("<b>SALDO AKHIR</b>", style_box_label)
        ],
        [
            Paragraph(f"<b>{format_rupiah(starting_bal)}</b>", ParagraphStyle('BalSt', parent=style_box_value, fontSize=10, textColor=colors.HexColor("#1E293B"))),
            Paragraph(f"<b>+ {format_rupiah(tot_kredit)}</b>", ParagraphStyle('BalIn', parent=style_box_value, fontSize=10, textColor=colors.HexColor("#16A34A"))),
            Paragraph(f"<b>- {format_rupiah(tot_out)}</b>", ParagraphStyle('BalOut', parent=style_box_value, fontSize=10, textColor=colors.HexColor("#DC2626"))),
            Paragraph(f"<b>{format_rupiah(ending_bal)}</b>", ParagraphStyle('BalEnd', parent=style_box_value, fontSize=10, textColor=colors.HexColor("#00877A"))),
        ],
        [
            Paragraph("<font size='6' color='#64748B'>Per 01 bulan berjalan</font>", base_styles['Normal']),
            Paragraph(f"<font size='6' color='#16A34A'>Topup: {format_rupiah(tot_in)} | Ref: {format_rupiah(tot_ref)}</font>", base_styles['Normal']),
            Paragraph("<font size='6' color='#DC2626'>Pembelian & penyesuaian</font>", base_styles['Normal']),
            Paragraph("<font size='6' color='#00877A'>Posisi per akhir periode</font>", base_styles['Normal']),
        ]
    ]

    summary_table = Table(summary_cells, colWidths=[130, 130, 130, 130])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F0FDF4")),
        ('BACKGROUND', (2, 0), (2, -1), colors.HexColor("#FEF2F2")),
        ('BACKGROUND', (3, 0), (3, -1), colors.HexColor("#E6F7F5")),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#99F6E4")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 10))

    # Table Ledger
    headers = [
        Paragraph("NO", style_table_th),
        Paragraph("TANGGAL & WAKTU", style_table_th),
        Paragraph("URAIAN / KETERANGAN TRANSAKSI", ParagraphStyle('THL', parent=style_table_th, alignment=0)),
        Paragraph("NO. REFERENSI", style_table_th),
        Paragraph("DEBIT (-)", ParagraphStyle('THR', parent=style_table_th, alignment=2)),
        Paragraph("KREDIT (+)", ParagraphStyle('THR', parent=style_table_th, alignment=2)),
        Paragraph("SALDO AKHIR", ParagraphStyle('THR', parent=style_table_th, alignment=2))
    ]

    table_data = [headers]
    mutations = statement_data.get('mutations', [])

    if not mutations:
        no_data_row = [
            Paragraph("-", style_cell_center),
            Paragraph("-", style_cell_center),
            Paragraph("<i>Tidak ada catatan mutasi transaksi pada periode bulan ini.</i>", style_cell_normal),
            Paragraph("-", style_cell_center),
            Paragraph("-", style_cell_center),
            Paragraph("-", style_cell_center),
            Paragraph(format_rupiah(ending_bal), style_cell_balance)
        ]
        table_data.append(no_data_row)
    else:
        sorted_mutations = sorted(mutations, key=lambda x: x.get('date_str', ''))

        for idx, m in enumerate(sorted_mutations, start=1):
            m_type = m.get('type', '')
            direction = m.get('direction', '')
            amount = float(m.get('amount', 0.0) or 0.0)
            bal_after = float(m.get('balance_after', 0.0) or 0.0)

            raw_date = m.get('date_str', '-')
            display_date = raw_date
            try:
                dt_obj = datetime.strptime(raw_date, '%Y-%m-%d %H:%M:%S')
                display_date = dt_obj.strftime('%d/%m/%Y\n%H:%M')
            except Exception:
                pass

            p_name = m.get('product_name') or m.get('title') or 'Transaksi'
            target = m.get('target', '-')
            sn_val = m.get('sn', '-')
            
            desc_parts = [f"<b>{p_name}</b>"]
            if target and target != '-':
                desc_parts.append(f"<font color='#475569'>Tujuan: {target}</font>")
            if sn_val and sn_val != '-' and len(sn_val) > 2:
                short_sn = sn_val if len(sn_val) <= 24 else (sn_val[:22] + '..')
                desc_parts.append(f"<font color='#64748B'>SN: {short_sn}</font>")

            desc_paragraph = Paragraph("<br/>".join(desc_parts), style_cell_normal)
            ref_paragraph = Paragraph(f"<font color='#00877A'><b>{m.get('ref_id', '-')}</b></font>", style_cell_center)

            if direction == '-' or m_type == 'pengeluaran':
                debit_cell = Paragraph(f"- {format_rupiah(amount)}", style_cell_red)
                credit_cell = Paragraph("-", style_cell_center)
            else:
                debit_cell = Paragraph("-", style_cell_center)
                credit_cell = Paragraph(f"+ {format_rupiah(amount)}", style_cell_green)

            bal_cell = Paragraph(f"<b>{format_rupiah(bal_after)}</b>", style_cell_balance)

            row = [
                Paragraph(str(idx), style_cell_center),
                Paragraph(display_date, style_cell_center),
                desc_paragraph,
                ref_paragraph,
                debit_cell,
                credit_cell,
                bal_cell
            ]
            table_data.append(row)

    col_widths = [22, 68, 162, 70, 65, 65, 68]
    ledger_table = Table(table_data, colWidths=col_widths, repeatRows=1)

    table_style_commands = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#00877A")),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E1")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
    ]

    for r in range(1, len(table_data)):
        if r % 2 == 0:
            table_style_commands.append(('BACKGROUND', (0, r), (-1, r), colors.HexColor("#F8FAFC")))

    ledger_table.setStyle(TableStyle(table_style_commands))
    story.append(ledger_table)
    story.append(Spacer(1, 12))

    notice_text = (
        "<b>PERNYATAAN RESMI:</b><br/>"
        "1. Dokumen Rekening Koran ini sah dan diterbitkan secara digital oleh sistem otomatisasi iPay (Garuda Digital Media).<br/>"
        "2. Seluruh catatan mutasi dan saldo di atas adalah final sesuai dengan database transaksi terverifikasi pada saat tanggal cetak.<br/>"
        "3. Apabila terdapat perbedaan atau pertanyaan terkait mutasi, silakan hubungi Layanan Pelanggan (CS) resmi iPay melalui menu Bantuan di aplikasi atau WhatsApp resmi dalam waktu maksimal 7 (tujuh) hari kerja kalender sejak tanggal terbit dokumen ini."
    )
    notice_p = Paragraph(notice_text, ParagraphStyle('NoticeP', parent=base_styles['Normal'], fontName='Helvetica', fontSize=6.8, leading=8.5, textColor=colors.HexColor("#475569")))
    notice_box = Table([[notice_p]], colWidths=[520])
    notice_box.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
        ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(KeepTogether([notice_box]))

    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer


# =====================================================================
# ENGINE 2: ZERO-DEPENDENCY PURE PYTHON ENGINE (100% STANDALONE)
# Digunakan secara mulus bila ReportLab / Pillow belum terpasang di server
# =====================================================================
class _PurePdfEngine:
    """PDF 1.4 compiler murni Python tanpa external dependency apa pun."""
    def __init__(self):
        self.pages = []

    def new_page(self):
        self.pages.append([])

    def draw_rect(self, x, y, w, h, fill_rgb=None, stroke_rgb=None, stroke_width=1.0):
        cmds = ['q']
        if stroke_rgb:
            cmds.append(f'{stroke_rgb[0]:.3f} {stroke_rgb[1]:.3f} {stroke_rgb[2]:.3f} RG')
            cmds.append(f'{stroke_width:.2f} w')
        if fill_rgb:
            cmds.append(f'{fill_rgb[0]:.3f} {fill_rgb[1]:.3f} {fill_rgb[2]:.3f} rg')
        cmds.append(f'{x:.2f} {y:.2f} {w:.2f} {h:.2f} re')
        if fill_rgb and stroke_rgb:
            cmds.append('B')
        elif fill_rgb:
            cmds.append('f')
        else:
            cmds.append('S')
        cmds.append('Q')
        self.pages[-1].append(' '.join(cmds))

    def draw_line(self, x1, y1, x2, y2, stroke_rgb=(0,0,0), stroke_width=1.0):
        cmds = [
            'q',
            f'{stroke_rgb[0]:.3f} {stroke_rgb[1]:.3f} {stroke_rgb[2]:.3f} RG',
            f'{stroke_width:.2f} w',
            f'{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S',
            'Q'
        ]
        self.pages[-1].append(' '.join(cmds))

    def draw_text(self, text, x, y, font='F1', size=10, rgb=(0,0,0), align='left'):
        clean = str(text or '').replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        approx_w = len(clean) * size * 0.52
        if align == 'right':
            x = x - approx_w
        elif align == 'center':
            x = x - (approx_w / 2.0)
        cmds = [
            'BT',
            f'/{font} {size:.2f} Tf',
            f'{rgb[0]:.3f} {rgb[1]:.3f} {rgb[2]:.3f} rg',
            f'1 0 0 1 {x:.2f} {y:.2f} Tm',
            f'({clean}) Tj',
            'ET'
        ]
        self.pages[-1].append(' '.join(cmds))

    def compile(self):
        num_pages = len(self.pages)
        objects = []
        page_obj_ids = []
        content_obj_ids = []
        
        cur_obj = 5
        for i in range(num_pages):
            page_obj_ids.append(cur_obj)
            cur_obj += 1
            content_obj_ids.append(cur_obj)
            cur_obj += 1

        cat = '<< /Type /Catalog /Pages 2 0 R >>'
        kids_str = ' '.join(f'{pid} 0 R' for pid in page_obj_ids)
        pages_root = f'<< /Type /Pages /Kids [ {kids_str} ] /Count {num_pages} >>'
        f1 = '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>'
        f2 = '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>'

        objects.append(cat.encode('latin1'))
        objects.append(pages_root.encode('latin1'))
        objects.append(f1.encode('latin1'))
        objects.append(f2.encode('latin1'))

        for i in range(num_pages):
            p_obj = f'<< /Type /Page /Parent 2 0 R /MediaBox [ 0 0 595.28 841.89 ] /Contents {content_obj_ids[i]} 0 R /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>'
            objects.append(p_obj.encode('latin1'))
            stream_body = '\n'.join(self.pages[i]).encode('latin1', errors='replace')
            c_obj = f'<< /Length {len(stream_body)} >>\nstream\n'.encode('latin1') + stream_body + b'\nendstream'
            objects.append(c_obj)

        buf = io.BytesIO()
        buf.write(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
        offsets = []
        for idx, obj in enumerate(objects, 1):
            offsets.append(buf.tell())
            buf.write(f'{idx} 0 obj\n'.encode('latin1'))
            buf.write(obj)
            buf.write(b'\nendobj\n')

        xref_offset = buf.tell()
        buf.write(f'xref\n0 {len(objects) + 1}\n'.encode('latin1'))
        buf.write(b'0000000000 65535 f \n')
        for off in offsets:
            buf.write(f'{off:010d} 00000 n \n'.encode('latin1'))

        buf.write(f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n'.encode('latin1'))
        buf.write(f'startxref\n{xref_offset}\n%%EOF\n'.encode('latin1'))
        buf.seek(0)
        return buf


def _generate_with_pure_python(user, month, year, statement_data):
    """Fallback generator tanpa library eksternal, menghasilkan PDF standar perbankan yang elegan."""
    pdf = _PurePdfEngine()

    month_name = INDONESIAN_MONTHS.get(int(month), f"Bulan {month}")
    last_day = calendar.monthrange(int(year), int(month))[1]
    period_str = f"01 {month_name} {year} - {last_day:02d} {month_name} {year}"
    wib_now = datetime.utcnow() + timedelta(hours=7)
    print_date_str = wib_now.strftime("%d/%m/%Y %H:%M:%S") + " WIB"
    stmt_code = f"STMT-{year}{int(month):02d}-{user.id}"

    user_name = (getattr(user, 'name', '') or f"Pengguna #{user.id}").strip()
    user_phone = getattr(user, 'phone', '-') or '-'
    user_role = (getattr(user, 'role', 'MEMBER') or 'MEMBER').upper()

    summary_info = _extract_statement_summary(statement_data)
    starting_bal = summary_info['starting_bal']
    ending_bal = summary_info['ending_bal']
    tot_in = summary_info['tot_in']
    tot_out = summary_info['tot_out']
    tot_ref = summary_info['tot_ref']
    tot_kredit = summary_info['tot_kredit']
    mutations = summary_info['mutations']

    PAGE_W = 595.28
    PAGE_H = 841.89
    MARGIN = 36.0 # 0.5 in
    CONTENT_W = PAGE_W - (MARGIN * 2)

    def draw_page_header_and_meta():
        pdf.new_page()
        # Top Header Brand
        pdf.draw_text("GARUDA DIGITAL MEDIA", MARGIN, 808, font='F2', size=11, rgb=(0, 0.529, 0.478))
        pdf.draw_text("iPay Platform - Layanan Distribusi Pulsa & PPOB Terpercaya", MARGIN, 796, font='F1', size=7.5, rgb=(0.28, 0.33, 0.41))
        pdf.draw_text("Website: https://ipay.my.id - Layanan CS: 08:00 - 23:00 WIB", MARGIN, 786, font='F1', size=7, rgb=(0.39, 0.45, 0.55))

        pdf.draw_text("REKENING KORAN ELEKTRONIK", PAGE_W - MARGIN, 808, font='F2', size=11, rgb=(0.06, 0.09, 0.16), align='right')
        pdf.draw_text("ELECTRONIC ACCOUNT STATEMENT", PAGE_W - MARGIN, 796, font='F2', size=7.5, rgb=(0, 0.529, 0.478), align='right')
        pdf.draw_text(f"No: {stmt_code} | Cetak: {print_date_str}", PAGE_W - MARGIN, 786, font='F1', size=7, rgb=(0.39, 0.45, 0.55), align='right')

        # Teal Line
        pdf.draw_rect(MARGIN, 778, CONTENT_W, 2, fill_rgb=(0, 0.529, 0.478))

        # Metadata Box
        box_y = 726
        box_h = 46
        pdf.draw_rect(MARGIN, box_y, CONTENT_W, box_h, fill_rgb=(0.97, 0.98, 0.99), stroke_rgb=(0.88, 0.91, 0.94), stroke_width=0.8)
        
        pdf.draw_text("NAMA PEMILIK AKUN", MARGIN + 8, box_y + 32, font='F1', size=6.5, rgb=(0.39, 0.45, 0.55))
        pdf.draw_text(f": {user_name.upper()}", MARGIN + 105, box_y + 32, font='F2', size=7.5, rgb=(0.06, 0.09, 0.16))

        pdf.draw_text("PERIODE MUTASI", MARGIN + 280, box_y + 32, font='F1', size=6.5, rgb=(0.39, 0.45, 0.55))
        pdf.draw_text(f": {period_str}", MARGIN + 365, box_y + 32, font='F2', size=7.5, rgb=(0.06, 0.09, 0.16))

        pdf.draw_text("NO. TELEPON / ID", MARGIN + 8, box_y + 19, font='F1', size=6.5, rgb=(0.39, 0.45, 0.55))
        pdf.draw_text(f": {user_phone} (ID #{user.id})", MARGIN + 105, box_y + 19, font='F2', size=7.5, rgb=(0.06, 0.09, 0.16))

        pdf.draw_text("MATA UANG", MARGIN + 280, box_y + 19, font='F1', size=6.5, rgb=(0.39, 0.45, 0.55))
        pdf.draw_text(": IDR (Rupiah Indonesia)", MARGIN + 365, box_y + 19, font='F2', size=7.5, rgb=(0.06, 0.09, 0.16))

        pdf.draw_text("STATUS / TIPE AKUN", MARGIN + 8, box_y + 6, font='F1', size=6.5, rgb=(0.39, 0.45, 0.55))
        pdf.draw_text(f": {user_role} - AKTIF", MARGIN + 105, box_y + 6, font='F2', size=7.5, rgb=(0, 0.529, 0.478))

        pdf.draw_text("LEMBAGA PENYEDIA", MARGIN + 280, box_y + 6, font='F1', size=6.5, rgb=(0.39, 0.45, 0.55))
        pdf.draw_text(": Garuda Digital Media (iPay)", MARGIN + 365, box_y + 6, font='F2', size=7.5, rgb=(0.06, 0.09, 0.16))

        # Financial Summary Box (4 Columns)
        sum_y = 675
        sum_h = 42
        col_w = CONTENT_W / 4.0
        pdf.draw_rect(MARGIN, sum_y, CONTENT_W, sum_h, fill_rgb=(0.95, 0.99, 0.98), stroke_rgb=(0.6, 0.96, 0.89), stroke_width=1)

        # Saldo Awal
        pdf.draw_text("SALDO AWAL", MARGIN + 10, sum_y + 28, font='F2', size=7, rgb=(0.39, 0.45, 0.55))
        pdf.draw_text(format_rupiah(starting_bal), MARGIN + 10, sum_y + 14, font='F2', size=9, rgb=(0.1, 0.1, 0.1))
        pdf.draw_text("Per 01 bulan ini", MARGIN + 10, sum_y + 4, font='F1', size=6, rgb=(0.5, 0.5, 0.5))

        # Total Kredit
        pdf.draw_line(MARGIN + col_w, sum_y, MARGIN + col_w, sum_y + sum_h, stroke_rgb=(0.8, 0.85, 0.9), stroke_width=0.5)
        pdf.draw_text("TOTAL KREDIT (+)", MARGIN + col_w + 10, sum_y + 28, font='F2', size=7, rgb=(0.09, 0.64, 0.29))
        pdf.draw_text(f"+ {format_rupiah(tot_kredit)}", MARGIN + col_w + 10, sum_y + 14, font='F2', size=9, rgb=(0.09, 0.64, 0.29))
        sub_kredit = f"Topup: {format_rupiah(tot_in)}" if tot_ref == 0.0 else f"Topup: {format_rupiah(tot_in)} | Ref: {format_rupiah(tot_ref)}"
        pdf.draw_text(sub_kredit, MARGIN + col_w + 10, sum_y + 4, font='F1', size=6, rgb=(0.09, 0.64, 0.29))

        # Total Debit
        pdf.draw_line(MARGIN + col_w * 2, sum_y, MARGIN + col_w * 2, sum_y + sum_h, stroke_rgb=(0.8, 0.85, 0.9), stroke_width=0.5)
        pdf.draw_text("TOTAL DEBIT (-)", MARGIN + col_w * 2 + 10, sum_y + 28, font='F2', size=7, rgb=(0.86, 0.15, 0.15))
        pdf.draw_text(f"- {format_rupiah(tot_out)}", MARGIN + col_w * 2 + 10, sum_y + 14, font='F2', size=9, rgb=(0.86, 0.15, 0.15))
        pdf.draw_text("Pembelian & penyesuaian", MARGIN + col_w * 2 + 10, sum_y + 4, font='F1', size=6, rgb=(0.86, 0.15, 0.15))

        # Saldo Akhir
        pdf.draw_line(MARGIN + col_w * 3, sum_y, MARGIN + col_w * 3, sum_y + sum_h, stroke_rgb=(0.8, 0.85, 0.9), stroke_width=0.5)
        pdf.draw_text("SALDO AKHIR", MARGIN + col_w * 3 + 10, sum_y + 28, font='F2', size=7, rgb=(0, 0.529, 0.478))
        pdf.draw_text(format_rupiah(ending_bal), MARGIN + col_w * 3 + 10, sum_y + 14, font='F2', size=9, rgb=(0, 0.529, 0.478))
        pdf.draw_text("Posisi per akhir periode", MARGIN + col_w * 3 + 10, sum_y + 4, font='F1', size=6, rgb=(0, 0.529, 0.478))

    def draw_table_header(y):
        th_h = 16
        pdf.draw_rect(MARGIN, y - th_h, CONTENT_W, th_h, fill_rgb=(0, 0.529, 0.478))
        pdf.draw_text("NO", MARGIN + 10, y - 11, font='F2', size=7, rgb=(1, 1, 1), align='center')
        pdf.draw_text("WAKTU (WIB)", MARGIN + 55, y - 11, font='F2', size=7, rgb=(1, 1, 1), align='center')
        pdf.draw_text("URAIAN / KETERANGAN TRANSAKSI", MARGIN + 95, y - 11, font='F2', size=7, rgb=(1, 1, 1))
        pdf.draw_text("REF ID", MARGIN + 295, y - 11, font='F2', size=7, rgb=(1, 1, 1), align='center')
        pdf.draw_text("DEBIT (-)", MARGIN + 380, y - 11, font='F2', size=7, rgb=(1, 1, 1), align='right')
        pdf.draw_text("KREDIT (+)", MARGIN + 450, y - 11, font='F2', size=7, rgb=(1, 1, 1), align='right')
        pdf.draw_text("SALDO AKHIR", MARGIN + 520, y - 11, font='F2', size=7, rgb=(1, 1, 1), align='right')
        return y - th_h

    def draw_page_footer(cur_page, total_pages):
        pdf.draw_line(MARGIN, 34, PAGE_W - MARGIN, 34, stroke_rgb=(0.8, 0.85, 0.9), stroke_width=0.5)
        pdf.draw_text("Dokumen Rekening Koran Resmi iPay - Garuda Digital Media - https://ipay.my.id", MARGIN, 24, font='F1', size=6.5, rgb=(0.39, 0.45, 0.55))
        pdf.draw_text(f"Halaman {cur_page} dari {total_pages}", PAGE_W - MARGIN, 24, font='F1', size=6.5, rgb=(0.39, 0.45, 0.55), align='right')

    # Draw First Page
    draw_page_header_and_meta()
    cur_y = 665
    cur_y = draw_table_header(cur_y)

    sorted_muts = sorted(mutations, key=lambda x: x.get('date_str', ''))

    if not sorted_muts:
        row_h = 24
        pdf.draw_rect(MARGIN, cur_y - row_h, CONTENT_W, row_h, fill_rgb=(1, 1, 1), stroke_rgb=(0.88, 0.91, 0.94), stroke_width=0.5)
        pdf.draw_text("Tidak ada catatan transaksi pada periode bulan ini.", MARGIN + (CONTENT_W / 2), cur_y - 15, font='F1', size=8, rgb=(0.5, 0.5, 0.5), align='center')
        cur_y -= row_h
    else:
        for idx, m in enumerate(sorted_muts, 1):
            row_h = 24
            if cur_y - row_h < 75:
                # Need new page
                pdf.new_page()
                # Mini Header on next pages
                pdf.draw_text("GARUDA DIGITAL MEDIA - REKENING KORAN", MARGIN, 810, font='F2', size=8.5, rgb=(0, 0.529, 0.478))
                pdf.draw_text(f"Periode: {period_str} | ID #{user.id}", PAGE_W - MARGIN, 810, font='F1', size=7.5, rgb=(0.39, 0.45, 0.55), align='right')
                pdf.draw_rect(MARGIN, 804, CONTENT_W, 1, fill_rgb=(0, 0.529, 0.478))
                cur_y = draw_table_header(800)

            # Draw Row
            bg_col = (0.97, 0.98, 0.99) if idx % 2 == 0 else (1, 1, 1)
            pdf.draw_rect(MARGIN, cur_y - row_h, CONTENT_W, row_h, fill_rgb=bg_col, stroke_rgb=(0.88, 0.91, 0.94), stroke_width=0.4)

            # Date
            raw_date = m.get('date_str', '-')
            date_p1 = raw_date[:10] if len(raw_date) >= 10 else raw_date
            date_p2 = raw_date[11:16] if len(raw_date) >= 16 else ''

            # Product & Target
            p_name = m.get('product_name') or m.get('title') or 'Transaksi'
            target = m.get('target', '-')
            p_display = p_name if len(p_name) <= 32 else (p_name[:30] + '..')
            sub_display = f"Tujuan: {target}" if target and target != '-' else (m.get('sn', '-')[:30] if m.get('sn', '-') != '-' else '')

            amount = float(m.get('amount', 0.0) or 0.0)
            bal_after = float(m.get('balance_after', 0.0) or 0.0)
            direction = m.get('direction', '')
            m_type = m.get('type', '')

            pdf.draw_text(str(idx), MARGIN + 10, cur_y - 14, font='F1', size=7, rgb=(0.2, 0.2, 0.2), align='center')
            pdf.draw_text(date_p1, MARGIN + 55, cur_y - 10, font='F1', size=6.5, rgb=(0.2, 0.2, 0.2), align='center')
            pdf.draw_text(date_p2, MARGIN + 55, cur_y - 18, font='F1', size=6, rgb=(0.5, 0.5, 0.5), align='center')

            pdf.draw_text(p_display, MARGIN + 95, cur_y - 10, font='F2', size=7, rgb=(0.1, 0.1, 0.1))
            pdf.draw_text(sub_display, MARGIN + 95, cur_y - 18, font='F1', size=6, rgb=(0.4, 0.45, 0.5))

            ref_id = str(m.get('ref_id', '-'))
            ref_short = ref_id if len(ref_id) <= 15 else (ref_id[:13] + '..')
            pdf.draw_text(ref_short, MARGIN + 295, cur_y - 14, font='F2', size=6.5, rgb=(0, 0.529, 0.478), align='center')

            if direction == '-' or m_type == 'pengeluaran':
                pdf.draw_text(f"- {format_rupiah(amount)}", MARGIN + 380, cur_y - 14, font='F2', size=7, rgb=(0.86, 0.15, 0.15), align='right')
                pdf.draw_text("-", MARGIN + 450, cur_y - 14, font='F1', size=7, rgb=(0.5, 0.5, 0.5), align='right')
            else:
                pdf.draw_text("-", MARGIN + 380, cur_y - 14, font='F1', size=7, rgb=(0.5, 0.5, 0.5), align='right')
                pdf.draw_text(f"+ {format_rupiah(amount)}", MARGIN + 450, cur_y - 14, font='F2', size=7, rgb=(0.09, 0.64, 0.29), align='right')

            pdf.draw_text(format_rupiah(bal_after), MARGIN + 520, cur_y - 14, font='F2', size=7, rgb=(0.1, 0.1, 0.1), align='right')
            cur_y -= row_h

    # Notice / Disclaimer at end
    if cur_y - 45 < 45:
        pdf.new_page()
        cur_y = 800

    notice_y = cur_y - 42
    pdf.draw_rect(MARGIN, notice_y, CONTENT_W, 36, fill_rgb=(0.95, 0.96, 0.98), stroke_rgb=(0.8, 0.85, 0.9), stroke_width=0.6)
    pdf.draw_text("PERNYATAAN RESMI:", MARGIN + 8, notice_y + 26, font='F2', size=6.5, rgb=(0.2, 0.25, 0.3))
    pdf.draw_text("1. Dokumen Rekening Koran ini sah dan diterbitkan secara digital oleh sistem otomatisasi iPay (Garuda Digital Media).", MARGIN + 8, notice_y + 17, font='F1', size=5.8, rgb=(0.3, 0.35, 0.4))
    pdf.draw_text("2. Catatan mutasi di atas final sesuai database transaksi pada tanggal cetak. Pertanyaan dapat disampaikan ke CS iPay.", MARGIN + 8, notice_y + 8, font='F1', size=5.8, rgb=(0.3, 0.35, 0.4))

    # Add Footers to all pages
    total_pages = len(pdf.pages)
    for p_idx in range(total_pages):
        # We need to temporarily set active page
        pdf.pages[p_idx].append(f'q 0.8 0.85 0.9 RG 0.5 w {MARGIN:.2f} 34 m {PAGE_W - MARGIN:.2f} 34 l S Q')
        pdf.pages[p_idx].append(f'BT /F1 6.5 Tf 0.39 0.45 0.55 rg 1 0 0 1 {MARGIN:.2f} 24 Tm (Dokumen Rekening Koran Resmi iPay - Garuda Digital Media - https://ipay.my.id) Tj ET')
        page_str = f"Halaman {p_idx + 1} dari {total_pages}"
        x_page = (PAGE_W - MARGIN) - (len(page_str) * 6.5 * 0.52)
        pdf.pages[p_idx].append(f'BT /F1 6.5 Tf 0.39 0.45 0.55 rg 1 0 0 1 {x_page:.2f} 24 Tm ({page_str}) Tj ET')

    return pdf.compile()


# =====================================================================
# ENTRY POINT DENGAN AUTO-FALLBACK & EXCEPTION SHIELD
# =====================================================================
def generate_monthly_statement_pdf(user, month, year, statement_data):
    """
    Menghasilkan file PDF Rekening Koran bulanan profesional dan bank-grade.
    Secara otomatis menggunakan ReportLab Platypus bila tersedia, dan
    otomatis beralih ke PurePython Engine bila ReportLab/Pillow tidak terpasang.
    Dijamin 100% tidak akan pernah melempar ModuleNotFoundError!
    """
    try:
        # Coba jalankan dengan ReportLab Platypus
        import reportlab
        return _generate_with_reportlab(user, month, year, statement_data)
    except Exception as e:
        print(f"[PDF_STATEMENT_SERVICE] ReportLab engine unavailable or failed ({e}). Using pure Python engine.")
        try:
            return _generate_with_pure_python(user, month, year, statement_data)
        except Exception as err2:
            print(f"[PDF_STATEMENT_SERVICE FATAL]: Pure Python engine also failed: {err2}")
            import traceback
            traceback.print_exc()
            raise err2
