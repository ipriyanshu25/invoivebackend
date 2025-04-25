from flask import Blueprint, request, send_file
import io
import os
import logging
from datetime import datetime
from fpdf import FPDF
from pymongo import ReturnDocument

from utils import format_response
from db import db

# Import helper to fetch editable fields
from settings import get_current_settings

# Configure logging
logging.basicConfig(level=logging.ERROR)

invoice_bp = Blueprint("invoice", __name__, url_prefix="/invoiceMHD")

# Default settings for invoice template
DEFAULT_SETTINGS = {
    "_id": "default",
    "logo_path": "logomhd.png",
    "fonts": {
        "regular": os.path.join('static', 'Lexend-Regular.ttf'),
        "bold":    os.path.join('static', 'Lexend-Bold.ttf')
    },
    "colors": {
        "black":      [0, 0, 0],
        "light_pink": [244, 225, 230],
        "dark_pink":  [91, 17, 44]
    },
    "company_info": {
        "name":       "MHD Tech",
        "address":    "8825 Perimeter Park Blvd Ste 501",
        "city_state": "Jacksonville, Florida, USA",
        "phone":      "+15075561971",
        "youtube":    "youtube.com/@mhd_tech",
        "email":      "aria@mhdtechpro.com"
    }
}

# PDF generator using dynamic settings
class InvoicePDF(FPDF):
    def __init__(self, settings, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.settings = settings
        self.add_font('Lexend', '', settings['fonts']['regular'], uni=True)
        self.add_font('Lexend', 'B', settings['fonts']['bold'], uni=True)

    def header(self):
        logo = self.settings['logo_path']
        if os.path.isfile(logo):
            self.image(logo, x=self.w - self.r_margin - 40, y=10, w=40)
        self.set_xy(self.l_margin, 10)
        self.set_font('Lexend', 'B', 28)
        self.set_text_color(*self.settings['colors']['black'])
        self.cell(0, 10, self.settings['company_info']['name'], ln=1)
        self.set_font('Lexend', '', 11)
        ci = self.settings['company_info']
        self.cell(0, 6, ci['address'], ln=1)
        self.cell(0, 6, ci['city_state'], ln=1)
        self.cell(0, 6, f"Phone: {ci['phone']}", ln=1)
        self.cell(0, 6, ci.get('youtube', ''), ln=1)
        self.cell(0, 6, ci['email'], ln=1)
        self.ln(12)

    def footer(self):
        self.set_y(-15)
        self.set_font('Lexend', '', 8)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

# Invoice number generator
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
        # 1️⃣ Fetch editable fields for the "MHD" invoice type
        raw = db.settings_invoice.find_one({"invoice_type": "MHD Tech"}) or {}
        editable = raw.get("editable_fields", {})
        print(editable)
        # 2️⃣ Merge into defaults (without mutating them)
        import copy
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        for key, val in editable.items():
            if isinstance(val, dict) and key in settings:
                settings[key].update(val)
            else:
                settings[key] = val

        # 4️⃣ Validate payload
        data = request.get_json() or {}
        phone = data.get('bill_to_phone')
        if phone:
            if not phone.isdigit() or len(phone) != 10:
                return format_response(False, "Phone number must be exactly 10 digits if provided", status=400)
        
        required_fields = {
            "bill_to_name":     "Billing name is required",
            "bill_to_address":  "Billing address is required",
            "bill_to_email":    "Billing email is required",
            "invoice_date":     "Invoice date is required",
            "due_date":         "Due date is required"
        }

        for field, error_msg in required_fields.items():
            if not data.get(field):
                return format_response(False, error_msg, status=400)


        # 5️⃣ Parse fields
        bt_name = data['bill_to_name']
        bt_addr = data['bill_to_address']
        bt_phone = data['bill_to_phone']
        bt_mail = data['bill_to_email']
        note    = data['notes']
        items   = data.get('items', [])
        payment_method = int(data.get('payment_method', 0))

        inv_no = get_next_invoice_number()
        # Validate dates
        try:
            datetime.strptime(data['invoice_date'], '%d-%m-%Y')
            datetime.strptime(data['due_date'],   '%d-%m-%Y')
        except ValueError:
            return format_response(False, "Invalid date format. Use DD-MM-YYYY", status=400)

        # 6️⃣ Build PDF
        pdf = InvoicePDF(settings)
        pdf.invoice_number = inv_no
        pdf.invoice_date   = data['invoice_date']
        pdf.due_date       = data['due_date']
        pdf.add_page()

        # Bill To block
        lines = ["Bill To:"] + [bt_name, bt_addr, bt_phone, bt_mail]
        heights = [8] + [6]*(len(lines)-1)
        block_w = pdf.w - pdf.l_margin - pdf.r_margin
        x, y = pdf.get_x(), pdf.get_y()
        pdf.set_fill_color(*settings['colors']['light_pink'])
        pdf.rect(x, y, block_w, sum(heights), 'F')
        pdf.set_text_color(*settings['colors']['black'])
        for h, txt, style in zip(heights, lines, ['B'] + ['']*(len(lines)-1)):
            pdf.set_font('Lexend', style, 12 if style=='B' else 11)
            pdf.set_xy(x, y)
            pdf.cell(0, h, txt, ln=1)
            y += h
        pdf.ln(4)

        # Invoice Details block
        details = [
            "Invoice Details:",
            f"Invoice #: {inv_no}",
            f"Bill Date: {data['invoice_date']}",
            f"Due Date: {data['due_date']}"
        ]
        d_heights = [8] + [7]*(len(details)-1)
        x, y = pdf.get_x(), pdf.get_y()
        pdf.set_fill_color(*settings['colors']['light_pink'])
        pdf.rect(x, y, block_w, sum(d_heights), 'F')
        pdf.set_text_color(*settings['colors']['black'])
        for h, txt, style in zip(d_heights, details, ['B'] + ['']*(len(details)-1)):
            pdf.set_font('Lexend', style, 12 if style=='B' else 11)
            pdf.set_xy(x, y)
            pdf.cell(0, h, txt, ln=1)
            y += h
        pdf.ln(10)

        # Items table header
        pdf.set_fill_color(*settings['colors']['dark_pink'])
        pdf.set_text_color(255,255,255)
        pdf.set_font('Lexend','B',12)
        pdf.cell(90,10,'DESCRIPTION',0,0,'C',fill=True)
        pdf.cell(30,10,'RATE',0,0,'C',fill=True)
        pdf.cell(20,10,'QTY',0,0,'C',fill=True)
        pdf.cell(45,10,'AMOUNT',0,1,'C',fill=True)

        # Items rows
        pdf.set_text_color(*settings['colors']['black'])
        pdf.set_font('Lexend','',11)
        subtotal = 0
        for it in items:
            desc = it.get('description','')
            rate = float(it.get('price',0))
            qty  = int(it.get('quantity',1))
            amt  = rate * qty
            subtotal += amt
            pdf.cell(90,8,desc,0,0,'L')
            pdf.cell(30,8,f'${rate:.2f}',0,0,'C')
            pdf.cell(20,8,str(qty),0,0,'C')
            pdf.cell(45,8,f'${amt:.2f}',0,1,'C')

        # PayPal fee if applicable
        if payment_method == 0:
            fee = round(subtotal * 0.055, 2)
            total = subtotal + fee
            pdf.ln(4)
            pdf.set_font('Lexend','',11)
            pdf.cell(140,8,'PayPal Fee',0,0,'R')
            pdf.cell(45,8,f'${fee:.2f}',0,1,'R')
        else:
            total = subtotal

        # Total
        pdf.ln(8)
        pdf.set_font('Lexend','B',14)
        pdf.set_text_color(*settings['colors']['black'])
        pdf.cell(141,10,'TOTAL',0,0,'R')
        pdf.cell(45,10,f'USD ${total:.2f}',0,1,'R')
        pdf.ln(10)

        # Notes
        pdf.set_font('Lexend','',12)
        pdf.set_text_color(*settings['colors']['black'])
        pdf.multi_cell(0,6,'Note: ' + note,0,'L')

        # Save record
        db.invoiceMHD.insert_one({
            'invoice_number': inv_no,
            'bill_to': {
                'name': bt_name,
                'address': bt_addr,
                'phone': bt_phone,
                'email': bt_mail
            },
            'items': items,
            'invoice_date': data['invoice_date'],
            'due_date': data['due_date'],
            'notes': note,
            'total_amount': total,
            'payment_method': payment_method
        })

        # Stream PDF back to client
        buf = io.BytesIO(pdf.output(dest='S').encode('latin1'))
        buf.seek(0)
        return send_file(
            buf,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"invoice_{inv_no}.pdf"
        )

    except Exception:
        logging.exception("Error generating invoice")
        return format_response(False, "Internal server error", status=500)


@invoice_bp.route('/getlist', methods=['POST'])
def get_invoice_list():
    try:
        data = request.get_json() or {}
        page     = int(data.get('page', 1))
        per_page = int(data.get('per_page', 10))
        search   = (data.get('search') or '').strip()

        criteria = {}
        if search:
            regex = {'$regex': search, '$options': 'i'}
            criteria = {'$or': [
                {'invoice_number': regex},
                {'bill_to.name':  regex},
                {'invoice_date':  regex},
                {'due_date':      regex}
            ]}

        skip    = (page - 1) * per_page
        cursor  = db.invoiceMHD.find(criteria).skip(skip).limit(per_page)
        invoices = [{**inv, '_id': str(inv['_id'])} for inv in cursor]
        total    = db.invoiceMHD.count_documents(criteria)

        return format_response(
            True,
            'Invoice list retrieved',
            data={
                'invoices': invoices,
                'total': total,
                'page': page,
                'per_page': per_page
            }
        )
    except Exception:
        return format_response(False, 'Internal server error', status=500)
