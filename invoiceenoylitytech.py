from flask import Flask, request, send_file, jsonify, Blueprint
from fpdf import FPDF
import os
import io
import random
import string
from datetime import datetime
from pymongo import ReturnDocument
from db import db  # ensure db.py provides a MongoDB client with the necessary collections

# Blueprint setup
enoylity_bp = Blueprint("enoylity", __name__, url_prefix="/enoylity")

# COLORS
BLACK      = (0, 0, 0)
LIGHT_BLUE = (235, 244, 250)
DARK_BLUE  = (39, 60, 117)

# Company info
COMPANY_INFO = {
    "name":       "Enoylity Media Creations LLC",
    "address":    "444 Alaska Avenue, Suite AVJ801",
    "city_state": "Torrance, California, 90503, USA",
    "phone":      "+15075561971",
    "youtube":    "youtube.com/@enoylitytech",
    "email":      "support@enoylity.com"
}

# Helper to get next invoice number from MongoDB
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
        # Set default font
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
        note           =data['note']
        items          = data.get('items', [])
        invoice_date   = data['invoice_date']      # format: "DD-MM-YYYY"
        due_date       = data['due_date']          # format: "DD-MM-YYYY"
        payment_method = data.get('payment_method', 0)  # 0 = PayPal, 1 = Bank

        # Get next invoice number from database
        inv_num = get_next_invoice_number()

        # Build PDF
        pdf = InvoicePDF()
        pdf.invoice_number = inv_num
        pdf.invoice_date   = invoice_date
        pdf.due_date       = due_date
        pdf.add_page()
        
        # Bill To section
        pdf.set_fill_color(*LIGHT_BLUE)
        pdf.set_text_color(*BLACK)
        pdf.set_font('Lexend', 'B', 12)
        pdf.cell(0, 8, 'Bill To:', ln=1, fill=True)
        pdf.set_font('Lexend', '', 11)
        for line in (bt_name, bt_addr, bt_city, bt_mail):
            pdf.cell(0, 6, line, ln=1, fill=True)
        pdf.ln(10)

        # Invoice Details
        pdf.set_fill_color(*LIGHT_BLUE)
        pdf.set_text_color(*BLACK)
        pdf.set_font('Lexend', 'B', 12)
        pdf.cell(0, 8, 'Invoice Details:', ln=1, fill=True)
        pdf.set_font('Lexend', '', 10)
        pdf.cell(0, 7, f"Invoice #: {inv_num}", ln=1, fill=True)
        pdf.cell(0, 7, f"Bill Date: {invoice_date}", ln=1, fill=True)
        pdf.cell(0, 7, f"Due Date:  {due_date}", ln=1, fill=True)
        pdf.ln(10)

        # Table header
        pdf.set_fill_color(*DARK_BLUE)
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
            pdf.cell(30, 8, f'${rate:.2f}', 0, 0, 'R')
            pdf.cell(20, 8, str(qty),       0, 0, 'C')
            pdf.cell(45, 8, f'${amt:.2f}',  0, 1, 'R')

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

        # Persist record in database
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

        # Output PDF
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
        return jsonify({"error": f"Missing field: {ke}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@enoylity_bp.route('/invoices', methods=['GET'])
def get_all_invoices():
    try:
        invoices = list(db.invoiceenoylity.find({}, {'_id': 0}))
        return jsonify(invoices), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
