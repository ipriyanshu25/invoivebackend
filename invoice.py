
# chant gt format 

from flask import Flask, request, send_file, jsonify,Blueprint;
from fpdf import FPDF
import os
import time
from datetime import datetime, timedelta
import io

invoice_bp = Blueprint("invoice", __name__, url_prefix="/invoice")

# COLORS
BLACK      = (0, 0, 0)
LIGHT_PINK = (255, 240, 245)
DARK_PINK  = (219, 112, 147)

# Company info
COMPANY_INFO = {
    "name":       "MHD Tech",
    "address":    "8825 Perimeter Park Blvd Ste 501",
    "city_state": "Jacksonville, Florida, USA",
    "phone":      "+15075561971",
    "youtube":    "youtube.com/@mhd_tech",
    "email":      "aria@mhdtechpro.com"
}

class InvoicePDF(FPDF):
    def header(self):
        # Logo top‑right, larger size
        logo_path = 'logomhd.png'
        if os.path.isfile(logo_path):
            self.image(logo_path, x=self.w - self.r_margin - 40, y=10, w=40)
        # Company info (left)
        self.set_xy(self.l_margin, 10)
        self.set_font('Arial', 'B', 18)
        self.set_text_color(*BLACK)
        self.cell(0, 10, COMPANY_INFO['name'], ln=1)
        self.set_font('Arial', '', 11)
        self.cell(0, 6, COMPANY_INFO['address'], ln=1)
        self.cell(0, 6, COMPANY_INFO['city_state'], ln=1)
        self.cell(0, 6, f"Phone: {COMPANY_INFO['phone']}", ln=1)
        # clickable YouTube URL
        self.set_text_color(0, 0, 255)
        self.cell(0, 6, COMPANY_INFO['youtube'], ln=1,
                  link=f"https://{COMPANY_INFO['youtube']}")
        # clickable email
        self.cell(0, 6, COMPANY_INFO['email'], ln=1,
                  link=f"mailto:{COMPANY_INFO['email']}")
        self.set_text_color(*BLACK)
        self.ln(12)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')


@invoice_bp.route('/generate-invoice', methods=['POST'])
def generate_invoice_endpoint():
    try:
        data = request.get_json()
        bt_name    = data['bill_to_name']
        bt_addr    = data['bill_to_address']
        bt_city    = data['bill_to_city']
        bt_mail    = data['bill_to_email']
        items      = data.get('items', [])
        invoice_date = data['invoice_date']      # "DD-MM-YYYY"
        payment_method = data.get('payment_method', 0)  # 0 = PayPal, 1 = Bank

        # Invoice counter
        counter_file = 'invoice_counter.txt'
        if not os.path.exists(counter_file):
            with open(counter_file, 'w') as f:
                f.write('0')
        with open(counter_file, 'r+') as f:
            idx = int(f.read().strip()) + 1
            f.seek(0)
            f.write(str(idx))
            f.truncate()
        inv_no = f"INV{idx:05d}"

        # Compute due date = bill date + 6 days
        bd = datetime.strptime(invoice_date, '%d-%m-%Y')
        due_date = (bd + timedelta(days=6)).strftime('%d-%m-%Y')

        # Build PDF in memory
        pdf = InvoicePDF()
        pdf.invoice_number = inv_no
        pdf.invoice_date   = invoice_date
        pdf.due_date       = due_date
        pdf.add_page()

        # ---- Bill To section (light-pink background) ----
        pdf.set_fill_color(*LIGHT_PINK)
        pdf.set_text_color(*BLACK)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 8, 'Bill To:', ln=1, fill=True)
        pdf.set_font('Arial', '', 11)
        for line in (bt_name, bt_addr, bt_city, bt_mail):
            pdf.cell(0, 6, line, ln=1, fill=True)
        pdf.ln(10)

        # ---- Invoice Details section (light-pink background) ----
        pdf.set_fill_color(*LIGHT_PINK)
        pdf.set_text_color(*BLACK)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 8, 'Invoice Details:', ln=1, fill=True)
        pdf.set_font('Arial', '', 11)
        pdf.cell(0, 7, f"Invoice #: {inv_no}", ln=1, fill=True)
        pdf.cell(0, 7, f"Bill Date: {invoice_date}", ln=1, fill=True)
        pdf.cell(0, 7, f"Due Date:  {due_date}", ln=1, fill=True)
        pdf.ln(10)

        # ---- Items table header ----
        pdf.set_fill_color(*DARK_PINK)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(90, 10, 'DESCRIPTION', 0, 0, 'C', fill=True)
        pdf.cell(30, 10, 'RATE',        0, 0, 'C', fill=True)
        pdf.cell(20, 10, 'QTY',         0, 0, 'C', fill=True)
        pdf.cell(45, 10, 'AMOUNT',      0, 1, 'C', fill=True)

        # ---- Items rows ----
        pdf.set_text_color(*BLACK)
        pdf.set_font('Arial', '', 11)
        subtotal = 0
        for it in items:
            desc = it.get('description', '')
            rate = it.get('price', 0.0)
            qty  = it.get('quantity', 1)
            amt  = rate * qty
            subtotal += amt

            pdf.cell(90, 8, desc, 0, 0, 'L')
            pdf.cell(30, 8, f'${rate:.2f}', 0, 0, 'R')
            pdf.cell(20, 8, str(qty),       0, 0, 'C')
            pdf.cell(45, 8, f'${amt:.2f}',  0, 1, 'R')

        # ---- PayPal fee logic ----
        if payment_method == 0:
            fee = subtotal * 0.053
            total = subtotal + fee
            pdf.ln(4)
            pdf.set_font('Arial', '', 11)
            pdf.cell(140, 8, 'PayPal Fee (5.3%)', 0, 0, 'R')
            pdf.cell(45, 8, f'${fee:.2f}', 0, 1, 'R')
        else:
            total = subtotal

        pdf.ln(8)
        # ---- Total ----
        pdf.set_font('Arial', 'B', 14)
        pdf.set_text_color(*BLACK)
        # bump first cell width from 130 ➔ 140
        pdf.cell(141, 10, 'TOTAL', 0, 0, 'R')
        pdf.cell(45, 10, f'USD ${total:.2f}', 0, 1, 'R')
        pdf.ln(10)


        # ---- Default note ----
        pdf.set_font('Arial', 'I', 12)
        pdf.set_text_color(*BLACK)
        pdf.multi_cell(0, 6, 'Note: Thank you for your business.', 0, 'L')

        # Stream PDF to client
        buffer = io.BytesIO()
        buffer.write(pdf.output(dest='S').encode('latin1'))
        buffer.seek(0)
        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"invoice_{inv_no}.pdf"
        )

    except KeyError as ke:
        return jsonify({"error": f"Missing field: {ke}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

