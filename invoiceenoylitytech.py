from flask import Flask, request, send_file, Blueprint
from fpdf import FPDF
import os
import io
import random
import string
from datetime import datetime
from pymongo import ReturnDocument
from db import db  # ensure db.py provides a MongoDB client with the necessary collections
from utils import format_response  # centralized formatter
import math

# Blueprint setup
enoylity_bp = Blueprint("enoylity", __name__, url_prefix="/invoice")

# COLORS
BLACK      = (0, 0, 0)
LIGHT_PINK = (255, 228, 241)
DARK_PINK  = (199, 21, 133)

# Company info
COMPANY_INFO = {
    "name":       "Enoylity Media Creations LLC",
    "address":    "444 Alaska Avenue, Suite AVJ801",
    "city_state": "Torrance, California, 90503, USA",
    "phone":      "+15075561971",
    "youtube":    "youtube.com/@enoylitytech",
    "email":      "support@enoylity.com"
}

def get_next_invoice_number():
    counter = db.invoice_counters.find_one_and_update(
        {"_id": "Enoylity Tech counter"},
        {"$inc": {"sequence_value": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    seq = counter.get("sequence_value", 1)
    return f"INV{seq:05d}"

class InvoicePDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Register Lexend fonts (ensure .ttf files are in 'static/fonts/' directory)
        self.add_font('Lexend', '', os.path.join('static', 'Lexend-Regular.ttf'), uni=True)
        self.add_font('Lexend', 'B', os.path.join('static', 'Lexend-Bold.ttf'), uni=True)
        self.set_font('Lexend', '', 11)

    def header(self):
        logo_path = 'enoylitytechlogo.png'
        if os.path.isfile(logo_path):
            self.image(logo_path, x=self.l_margin, y=10, w=40)
        self.set_xy(self.l_margin, 10)
        self.set_font('Lexend', 'B', 18)
        self.set_text_color(*BLACK)
        self.cell(0, 10, COMPANY_INFO['name'], ln=1, align='R')
        self.set_font('Lexend', '', 11)
        self.cell(0, 6, COMPANY_INFO['address'], ln=1, align='R')
        self.cell(0, 6, COMPANY_INFO['city_state'], ln=1, align='R')
        self.cell(0, 6, f"Phone: {COMPANY_INFO['phone']}", ln=1, align='R')
        self.cell(0, 6, COMPANY_INFO['youtube'], ln=1, align='R')
        self.cell(0, 6, COMPANY_INFO['email'], ln=1, align='R')
        self.ln(12)

    def footer(self):
        self.set_y(-15)
        self.set_font('Lexend', '', 8)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

@enoylity_bp.route('/invoice', methods=['POST'])
def generate_invoice_endpoint():
    try:
        data = request.get_json()
        bt_name        = data['bill_to_name']
        bt_addr        = data['bill_to_address']
        bt_city        = data['bill_to_city']
        bt_mail        = data['bill_to_email']
        note           = data['note']
        items          = data.get('items', [])
        invoice_date   = data['invoice_date']
        due_date       = data['due_date']
        payment_method = data.get('payment_method', 0)

        inv_num = get_next_invoice_number()
        pdf = InvoicePDF()
        pdf.invoice_number = inv_num
        pdf.invoice_date   = invoice_date
        pdf.due_date       = due_date
        pdf.add_page()
        
      # Bill To section
        lines    = [bt_name, bt_addr, bt_city, bt_mail]
        x, y     = pdf.l_margin, pdf.get_y()
        width    = pdf.w - pdf.l_margin - pdf.r_margin
        header_h = 13
        line_h   = 7
        indent   = 4
        padding  = 6

        block_h = header_h + len(lines) * line_h + padding

        # Draw one seamless pink block
        pdf.set_fill_color(*LIGHT_PINK)
        pdf.rect(x, y, width, block_h, style='F')

        # Header
        pdf.set_xy(x + indent, y + indent)
        pdf.set_text_color(*BLACK)
        pdf.set_font('Lexend', 'B', 12)
        pdf.cell(0, header_h, 'Bill To:', border=0, ln=1)

        # Lines, each indented under the header
        pdf.set_font('Lexend', '', 11)
        for line in lines:
            pdf.set_x(x + indent)
            pdf.cell(0, line_h, line, border=0, ln=1)

        pdf.ln(padding)


        # Invoice Details section
        details = [
            f"Invoice #: {inv_num}",
            f"Bill Date: {invoice_date}",
            f"Due Date:  {due_date}"
        ]
        y2      = pdf.get_y()
        block_h2 = header_h + len(details) * line_h + padding

        pdf.set_fill_color(*LIGHT_PINK)
        pdf.rect(x, y2, width, block_h2, style='F')

        # Header
        pdf.set_xy(x + indent, y2 + indent)
        pdf.set_font('Lexend', 'B', 12)
        pdf.cell(0, header_h, 'Invoice Details:', border=0, ln=1)

        # Detail lines, same indent and slightly tighter spacing
        pdf.set_font('Lexend', '', 10)
        for d in details:
            pdf.set_x(x + indent)
            pdf.cell(0, line_h, d, border=0, ln=1)

        pdf.ln(padding)




        # Table header
        pdf.set_fill_color(*DARK_PINK)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('Lexend', 'B', 12)
        pdf.cell(90, 10, 'DESCRIPTION', 0, 0, 'C', fill=True)
        pdf.cell(30, 10, 'RATE',        0, 0, 'C', fill=True)
        pdf.cell(20, 10, 'QTY',         0, 0, 'C', fill=True)
        pdf.cell(45, 10, 'AMOUNT',      0, 1, 'C', fill=True)

        pdf.set_text_color(*BLACK)
        pdf.set_font('Lexend', '', 11)
        subtotal = 0
        for it in items:
            desc = it.get('description', '')
            rate = float(it.get('price', 0.0))
            qty  = int(it.get('quantity', 1))
            amt  = rate * qty
            subtotal += amt
            pdf.cell(90, 8, desc, 0, 0, 'L')
            pdf.cell(30, 8, f'${rate:.2f}', 0, 0, 'C')
            pdf.cell(20, 8, str(qty),       0, 0, 'C')
            pdf.cell(45, 8, f'${amt:.2f}',  0, 1, 'C')

        # PayPal fee
        if payment_method == 0:
            fee   = subtotal * 0.055
            total = subtotal + fee
            pdf.ln(4)
            pdf.set_font('Lexend', '', 11)
            pdf.cell(140, 8, 'PayPal Fee', 0, 0, 'R')
            pdf.cell(45, 8, f'${fee:.2f}', 0, 1, 'R')
        else:
            total = subtotal

        pdf.ln(8)
        pdf.set_font('Lexend', 'B', 14)
        pdf.set_text_color(*BLACK)
        pdf.cell(141, 10, 'TOTAL', 0, 0, 'R')
        pdf.cell(45, 10, f'USD ${total:.2f}', 0, 1, 'R')
        pdf.ln(10)

        pdf.set_font('Lexend', '', 12)
        pdf.multi_cell(0, 6, 'Note: '+ note , 0, 'L')

        # Generate 16-digit unique invoice enoylity ID
        invoice_enoylity_id = ''.join(random.choices(string.digits, k=16))
        record = {
            'invoiceenoylityId': invoice_enoylity_id,
            'invoice_number':     inv_num,
            'invoice_date':       invoice_date,
            'due_date':           due_date,
            'bill_to': {
                'name':    bt_name,
                'address': bt_addr,
                'city':    bt_city,
                'email':   bt_mail,
            },
            'items':            items,
            'payment_method':   payment_method,
            'subtotal':         subtotal,
            'total':            total,
            'created_at':       datetime.utcnow()
        }
        db.invoiceenoylity.insert_one(record)

        buffer = io.BytesIO()
        buffer.write(pdf.output(dest='S').encode('latin1'))
        buffer.seek(0)
        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"invoice_{inv_num}.pdf"
        )

    except KeyError as ke:
        return format_response(False, f"Missing field: {ke}", None, 400)
    except Exception as e:
        return format_response(False, str(e), None, 500)

@enoylity_bp.route('/invoices', methods=['GET'])
def get_all_invoices():
    try:
        invoices = list(db.invoiceenoylity.find({}, {'_id': 0}))
        return format_response(True, "Invoices retrieved successfully.", invoices, 200)
    except Exception as e:
        return format_response(False, str(e), None, 500)

@enoylity_bp.route('/getlist', methods=['POST'])
def search_invoices():
    body = request.get_json() or {}
    search     = body.get('search', '').strip()
    page       = max(int(body.get('page', 1)), 1)
    per_page   = max(int(body.get('per_page', 10)), 1)
    filters = {}

    if search:
        filters['$or'] = [
            {'invoice_number': {'$regex': search, '$options': 'i'}},
            {'bill_to.name':    {'$regex': search, '$options': 'i'}},
            {'bill_to.email':   {'$regex': search, '$options': 'i'}},
        ]

    start_str = body.get('start_date')
    end_str   = body.get('end_date')
    if start_str and end_str:
        try:
            start_dt = datetime.strptime(start_str, '%d-%m-%Y')
            end_dt   = datetime.strptime(end_str,   '%d-%m-%Y')
            filters['created_at'] = {'$gte': start_dt, '$lte': end_dt}
        except ValueError:
            return format_response(False, "Dates must be in DD-MM-YYYY format", None, 400)

    total_items = db.invoiceenoylity.count_documents(filters)
    cursor = (db.invoiceenoylity
              .find(filters, {'_id': 0})
              .sort('created_at', -1)
              .skip((page - 1) * per_page)
              .limit(per_page))
    invoices   = list(cursor)
    total_pages = math.ceil(total_items / per_page) if per_page else 0

    payload = {
        "setlist":     invoices,
        "page":        page,
        "per_page":    per_page,
        "total_items": total_items,
        "total_pages": total_pages
    }
    return format_response(True, "Search results returned.", payload, 200)