import io
import os
from datetime import datetime, timedelta
import calendar

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

INDONESIAN_MONTHS = {
    1: 'Januari', 2: 'Februari', 3: 'Maret', 4: 'April',
    5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Agustus',
    9: 'September', 10: 'Oktober', 11: 'November', 12: 'Desember'
}


class NumberedCanvas(canvas.Canvas):
    """Canvas yang menghitung total halaman secara otomatis (Page X of Y) dan mencetak footer resmi."""
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

        # Footer divider line
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(1.2 * cm, 1.4 * cm, A4[0] - 1.2 * cm, 1.4 * cm)

        # Footer Left: Disclaimer
        self.drawString(
            1.2 * cm, 
            1.0 * cm, 
            "Dokumen Rekening Koran Resmi iPay • Diterbitkan otomatis oleh sistem PT Garuda Digital Media • https://ipay.my.id"
        )

        # Footer Right: Page X of Y
        page_str = f"Halaman {self._pageNumber} dari {page_count}"
        self.drawRightString(A4[0] - 1.2 * cm, 1.0 * cm, page_str)

        self.restoreState()


def format_rupiah(val):
    try:
        f_val = float(val or 0.0)
        return f"Rp {f_val:,.0f}".replace(",", ".")
    except Exception:
        return "Rp 0"


def generate_monthly_statement_pdf(user, month, year, statement_data):
    """
    Menghasilkan file PDF Rekening Koran bulanan profesional dan bank-grade
    menggunakan ReportLab Platypus.

    :param user: Objek User
    :param month: int (1-12)
    :param year: int (e.g. 2026)
    :param statement_data: dict berisi:
        - mutations: list of dict event mutasi (kronologis terlama -> terbaru)
        - starting_balance: float
        - ending_balance: float
        - total_pemasukan: float
        - total_pengeluaran: float
        - total_refund: float
    :return: BytesIO buffer berisi PDF
    """
    buffer = io.BytesIO()

    # Setup Dokumen A4 Portrait dengan Margin Bersih
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.8 * cm
    )

    # Stylesheet & Custom Styles
    base_styles = getSampleStyleSheet()
    
    style_company_title = ParagraphStyle(
        'CompanyTitle',
        parent=base_styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=14,
        textColor=colors.HexColor("#00877A")
    )
    
    style_company_sub = ParagraphStyle(
        'CompanySub',
        parent=base_styles['Normal'],
        fontName='Helvetica',
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#475569")
    )

    style_stmt_title = ParagraphStyle(
        'StatementTitle',
        parent=base_styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=15,
        alignment=2, # Right aligned
        textColor=colors.HexColor("#0F172A")
    )

    style_stmt_sub = ParagraphStyle(
        'StatementSub',
        parent=base_styles['Normal'],
        fontName='Helvetica',
        fontSize=7.5,
        leading=10,
        alignment=2, # Right aligned
        textColor=colors.HexColor("#64748B")
    )

    style_box_label = ParagraphStyle(
        'BoxLabel',
        parent=base_styles['Normal'],
        fontName='Helvetica',
        fontSize=7,
        leading=8.5,
        textColor=colors.HexColor("#64748B")
    )

    style_box_value = ParagraphStyle(
        'BoxValue',
        parent=base_styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=10.5,
        textColor=colors.HexColor("#0F172A")
    )

    style_table_th = ParagraphStyle(
        'TableTH',
        parent=base_styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7.5,
        leading=9,
        textColor=colors.white,
        alignment=1 # Center
    )

    style_cell_normal = ParagraphStyle(
        'CellNormal',
        parent=base_styles['Normal'],
        fontName='Helvetica',
        fontSize=7,
        leading=8.5,
        textColor=colors.HexColor("#1E293B")
    )

    style_cell_center = ParagraphStyle(
        'CellCenter',
        parent=base_styles['Normal'],
        fontName='Helvetica',
        fontSize=7,
        leading=8.5,
        alignment=1,
        textColor=colors.HexColor("#334155")
    )

    style_cell_bold = ParagraphStyle(
        'CellBold',
        parent=base_styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7,
        leading=8.5,
        textColor=colors.HexColor("#0F172A")
    )

    style_cell_green = ParagraphStyle(
        'CellGreen',
        parent=base_styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7,
        leading=8.5,
        alignment=2, # Right
        textColor=colors.HexColor("#16A34A")
    )

    style_cell_red = ParagraphStyle(
        'CellRed',
        parent=base_styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7,
        leading=8.5,
        alignment=2, # Right
        textColor=colors.HexColor("#DC2626")
    )

    style_cell_balance = ParagraphStyle(
        'CellBalance',
        parent=base_styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7,
        leading=8.5,
        alignment=2, # Right
        textColor=colors.HexColor("#0F172A")
    )

    story = []

    # 1. HEADER PERUSAHAAN & STATEMENT TITLE
    # Cek Logo
    logo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static', 'img', 'icons', 'icon-192x192.png'))
    logo_cell = None
    if os.path.exists(logo_path):
        try:
            logo_img = Image(logo_path, width=36, height=36)
            logo_cell = logo_img
        except Exception:
            logo_cell = None

    month_name = INDONESIAN_MONTHS.get(int(month), f"Bulan {month}")
    last_day = calendar.monthrange(int(year), int(month))[1]
    period_str = f"01 {month_name} {year} - {last_day:02d} {month_name} {year}"
    wib_now = datetime.utcnow() + timedelta(hours=7)
    print_date_str = wib_now.strftime("%d/%m/%Y %H:%M:%S") + " WIB"
    stmt_code = f"STMT-{year}{int(month):02d}-{user.id}"

    header_left = []
    if logo_cell:
        header_table_left_data = [[
            logo_cell,
            [
                Paragraph("<b>PT GARUDA DIGITAL MEDIA</b>", style_company_title),
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
            Paragraph("<b>PT GARUDA DIGITAL MEDIA</b>", style_company_title),
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

    # Teal Horizontal Line Divider
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#00877A"), spaceAfter=8, spaceBefore=4))

    # 2. METADATA PENGGUNA & PERIODE
    user_name = (getattr(user, 'name', '') or getattr(user, 'username', '') or f"Pengguna #{user.id}").strip()
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
            Paragraph(": PT Garuda Digital Media (iPay)", style_box_value),
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

    # 3. REKAP SALDO BULANAN (SUMMARY FINANCIAL TILES)
    starting_bal = statement_data.get('starting_balance', 0.0)
    ending_bal = statement_data.get('ending_balance', 0.0)
    tot_in = statement_data.get('total_pemasukan', 0.0)
    tot_out = statement_data.get('total_pengeluaran', 0.0)
    tot_ref = statement_data.get('total_refund', 0.0)
    # Total kredit mencakup pemasukan dan refund
    tot_kredit = tot_in + tot_ref

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

    # 4. TABEL RINCIAN MUTASI (RUNNING LEDGER)
    # Kolom: No (22), Tanggal & Jam (68), Uraian Transaksi (162), No. Ref (70), Debit (-) (65), Kredit (+) (65), Saldo Akhir (68) -> Total 520pt
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
        # Urutkan kronologis dari awal bulan sampai akhir bulan agar alur rekening koran rapi dan runut
        # (atau jika sudah urut, pastikan)
        sorted_mutations = sorted(mutations, key=lambda x: x.get('date_str', ''))

        for idx, m in enumerate(sorted_mutations, start=1):
            m_type = m.get('type', '')
            direction = m.get('direction', '')
            amount = float(m.get('amount', 0.0) or 0.0)
            bal_after = float(m.get('balance_after', 0.0) or 0.0)

            # Format Tanggal & Jam
            # m['date_str'] format: 'YYYY-MM-DD HH:MM:SS'
            raw_date = m.get('date_str', '-')
            display_date = raw_date
            try:
                dt_obj = datetime.strptime(raw_date, '%Y-%m-%d %H:%M:%S')
                display_date = dt_obj.strftime('%d/%m/%Y\n%H:%M')
            except Exception:
                pass

            # Uraian & Target
            p_name = m.get('product_name') or m.get('title') or 'Transaksi'
            target = m.get('target', '-')
            sn_val = m.get('sn', '-')
            
            desc_parts = [f"<b>{p_name}</b>"]
            if target and target != '-':
                desc_parts.append(f"<font color='#475569'>Tujuan: {target}</font>")
            if sn_val and sn_val != '-' and len(sn_val) > 2:
                # Batasi panjang SN agar tidak merusak tabel
                short_sn = sn_val if len(sn_val) <= 24 else (sn_val[:22] + '..')
                desc_parts.append(f"<font color='#64748B'>SN: {short_sn}</font>")

            desc_paragraph = Paragraph("<br/>".join(desc_parts), style_cell_normal)
            ref_paragraph = Paragraph(f"<font color='#00877A'><b>{m.get('ref_id', '-')}</b></font>", style_cell_center)

            # Debit / Kredit
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

    # Styling Ledger Table
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

    # Zebra Striping
    for r in range(1, len(table_data)):
        if r % 2 == 0:
            table_style_commands.append(('BACKGROUND', (0, r), (-1, r), colors.HexColor("#F8FAFC")))

    ledger_table.setStyle(TableStyle(table_style_commands))
    story.append(ledger_table)
    story.append(Spacer(1, 12))

    # 5. CATATAN PENGESAHAN ELEKTRONIK & VERIFIKASI (KEEP TOGETHER)
    notice_text = (
        "<b>PERNYATAAN RESMI:</b><br/>"
        "1. Dokumen Rekening Koran ini sah dan diterbitkan secara digital oleh sistem otomatisasi iPay (PT Garuda Digital Media).<br/>"
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

    # Bangun PDF dengan NumberedCanvas
    doc.build(story, canvasmaker=NumberedCanvas)

    buffer.seek(0)
    return buffer
