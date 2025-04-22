from flask import Blueprint, request, send_file
import io
import os
import logging
from datetime import datetime
from fpdf import FPDF
from pymongo import ReturnDocument

from utils import format_response
from db import db

# Configure logging
logging.basicConfig(level=logging.ERROR)

invoice_bp = Blueprint("invoice", __name__, url_prefix="/invoice")

# COLORS
BLACK      = (0, 0, 0)
LIGHT_PINK = (244, 225, 230)
DARK_PINK  = (91, 17, 44)

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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Register Lexend fonts (ensure .ttf files are in 'fonts/' directory)
        self.add_font('Lexend', '', os.path.join('static', 'Lexend-Regular.ttf'), uni=True)
        self.add_font('Lexend', 'B', os.path.join('static', 'Lexend-Bold.ttf'), uni=True)

    def header(self):
        logo_path = 'logomhd.png'
        if os.path.isfile(logo_path):
            self.image(logo_path, x=self.w - self.r_margin - 40, y=10, w=40)
        self.set_xy(self.l_margin, 10)
        # Company name in Lexend Bold
        self.set_font('Lexend', 'B', 28)
        self.set_text_color(*BLACK)
        self.cell(0, 10, COMPANY_INFO['name'], ln=1)
        # Company info in Lexend Regular
        self.set_font('Lexend', '', 11)
        self.cell(0, 6, COMPANY_INFO['address'], ln=1)
        self.cell(0, 6, COMPANY_INFO['city_state'], ln=1)
        self.cell(0, 6, f"Phone: {COMPANY_INFO['phone']}", ln=1)
        self.cell(0, 6, COMPANY_INFO['youtube'], ln=1)
        self.cell(0, 6, COMPANY_INFO['email'], ln=1)
        self.ln(12)

    def footer(self):
        self.set_y(-15)
        # Footer in Lexend Regular
        self.set_font('Lexend', '', 8)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')


def get_next_invoice_number():
    counter = db.invoice_counters.find_one_and_update(
        {"_id": "MHD Tech counter"},
        {"$inc": {"sequence_value": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    seq = counter.get("sequence_value", 1)
    return f"INV{seq:05d}"

@invoice_bp.route('/generate-invoice', methods=['POST'])
def generate_invoice_endpoint():
    try:
        data = request.get_json() or {}
        for field in ("bill_to_name", "bill_to_address", "bill_to_city", "bill_to_email", "invoice_date", "due_date"):  # noqa
            if field not in data:
                return format_response(False, f"Missing required field: {field}", status=400)

        bt_name = data['bill_to_name']
        bt_addr = data['bill_to_address']
        bt_city = data['bill_to_city']
        bt_mail = data['bill_to_email']
        note = data['notes']
        items = data.get('items', [])
        payment_method = int(data.get('payment_method', 0))

        inv_no = get_next_invoice_number()

        try:
            bd = datetime.strptime(data['invoice_date'], '%d-%m-%Y')
            due_date = datetime.strptime(data['due_date'], '%d-%m-%Y')
        except ValueError:
            return format_response(False, "Invalid date format. Use DD-MM-YYYY", status=400)

        pdf = InvoicePDF()
        pdf.invoice_number = inv_no
        pdf.invoice_date = data['invoice_date']
        pdf.due_date = data['due_date']
        pdf.add_page()

        # ---- Bill To section with full background ----
        lines = ["Bill To:"] + [bt_name, bt_addr, bt_city, bt_mail]
        line_heights = [8] + [6] * (len(lines) - 1)
        block_height = sum(line_heights)
        block_width = pdf.w - pdf.l_margin - pdf.r_margin
        start_x, start_y = pdf.get_x(), pdf.get_y()
        pdf.set_fill_color(*LIGHT_PINK)
        pdf.rect(start_x, start_y, block_width, block_height, 'F')
        pdf.set_text_color(*BLACK)
        # Write each line without individual fill
        for height, text, style in zip(line_heights, lines, ['B'] + [''] * (len(lines) - 1)):
            pdf.set_font('Lexend', style, 12 if style == 'B' else 11)
            pdf.set_xy(start_x, start_y)
            pdf.cell(0, height, text, ln=1)
            start_y += height
        pdf.ln(4)

        # ---- Invoice Details section with full background ----
        lines = ["Invoice Details:", f"Invoice #: {inv_no}", f"Bill Date: {data['invoice_date']}", f"Due Date: {data['due_date']}"]
        line_heights = [8] + [7] * (len(lines) - 1)
        block_height = sum(line_heights)
        start_x, start_y = pdf.get_x(), pdf.get_y()
        pdf.set_fill_color(*LIGHT_PINK)
        pdf.rect(start_x, start_y, block_width, block_height, 'F')
        pdf.set_text_color(*BLACK)
        for height, text, style in zip(line_heights, lines, ['B'] + [''] * (len(lines) - 1)):
            pdf.set_font('Lexend', style, 12 if style == 'B' else 11)
            pdf.set_xy(start_x, start_y)
            pdf.cell(0, height, text, ln=1)
            start_y += height
        pdf.ln(10)

        # ---- Items Table ----
        pdf.set_fill_color(*DARK_PINK)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('Lexend', 'B', 12)
        pdf.cell(90, 10, 'DESCRIPTION', 0, 0, 'C', fill=True)
        pdf.cell(30, 10, 'RATE', 0, 0, 'C', fill=True)
        pdf.cell(20, 10, 'QTY', 0, 0, 'C', fill=True)
        pdf.cell(45, 10, 'AMOUNT', 0, 1, 'C', fill=True)

        pdf.set_text_color(*BLACK)
        pdf.set_font('Lexend', '', 11)
        subtotal = 0
        for it in items:
            desc = it.get('description', '')
            rate = float(it.get('price', 0))
            qty = int(it.get('quantity', 1))
            amt = rate * qty
            subtotal += amt

            pdf.cell(90, 8, desc, 0, 0, 'L')
            pdf.cell(30, 8, f'${rate:.2f}', 0, 0, 'C')
            pdf.cell(20, 8, str(qty), 0, 0, 'C')
            pdf.cell(45, 8, f'${amt:.2f}', 0, 1, 'C')

        # ---- PayPal Fee ----
        if payment_method == 0:
            fee = round(subtotal * 0.055, 2)
            total = subtotal + fee
            pdf.ln(4)
            pdf.set_font('Lexend', '', 11)
            pdf.cell(140, 8, 'PayPal Fee', 0, 0, 'R')
            pdf.cell(45, 8, f'${fee:.2f}', 0, 1, 'R')
        else:
            total = subtotal

        pdf.ln(8)
        # ---- Total ----
        pdf.set_font('Lexend', 'B', 14)
        pdf.set_text_color(*BLACK)
        pdf.cell(141, 10, 'TOTAL', 0, 0, 'R')
        pdf.cell(45, 10, f'USD ${total:.2f}', 0, 1, 'R')
        pdf.ln(10)

        # ---- Note ----
        pdf.set_font('Lexend', '', 12)
        pdf.set_text_color(*BLACK)
        pdf.multi_cell(0, 6, "Note: " + note, 0, 'L')

        # Save record
        invoice_record = {
            'invoice_number': inv_no,
            'bill_to': {'name': bt_name, 'address': bt_addr, 'city': bt_city, 'email': bt_mail},
            'items': items,
            'invoice_date': data['invoice_date'],
            'due_date': data['due_date'],
            'total_amount': total,
            'payment_method': payment_method
        }
        db.mhdinvoice.insert_one(invoice_record)

        buf = io.BytesIO(pdf.output(dest='S').encode('latin1'))
        buf.seek(0)
        return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=f"invoice_{inv_no}.pdf")

    except KeyError as ke:
        return format_response(False, f"Missing field: {ke}", status=400)
    except Exception:
        logging.exception("Error generating invoice")
        return format_response(False, "Internal server error", status=500)

@invoice_bp.route('/getlist', methods=['POST'])
def get_invoice_list():
    try:
        data = request.get_json() or {}
        page = int(data.get('page', 1))
        per_page = int(data.get('per_page', 10))
        search = (data.get('search') or '').strip()

        filter_criteria = {}
        if search:
            regex = {'$regex': search, '$options': 'i'}
            filter_criteria = {'$or': [{'invoice_number': regex}, {'bill_to.name': regex}, {'invoice_date': regex}, {'due_date': regex}]}

        skip = (page - 1) * per_page
        cursor = db.mhdinvoice.find(filter_criteria).skip(skip).limit(per_page)
        invoices = []
        for inv in cursor:
            inv['_id'] = str(inv['_id'])
            invoices.append(inv)

        total = db.mhdinvoice.count_documents(filter_criteria)
        payload = {'invoices': invoices, 'total': total, 'page': page, 'per_page': per_page}
        return format_response(True, 'Invoice list retrieved successfully', data=payload)

    except Exception:
        return format_response(False, 'Internal server error', status=500)