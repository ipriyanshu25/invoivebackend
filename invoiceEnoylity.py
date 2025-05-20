import logging
from flask import Blueprint, request, send_file
import io
import os
import datetime
import requests
from fpdf import FPDF
from pymongo import ReturnDocument
from bson import ObjectId
from utils import format_response
from db import db
from settings import get_current_settings  # dynamic settings fetch

invoice_enoylity_bp = Blueprint("invoiceEnoylity", __name__, url_prefix="/invoiceEnoylity")

# Static fallback defaults (used only if no settings are found)
DEFAULT_SETTINGS = {
    'company_name': 'Enoylity Studio',
    'company_tagline': 'Enoylity Media Creations Private Limited',
    'company_address': (
        'Ekam Enclave II, 301A, Ramai Nagar, near Kapil Nagar Square\n'
        'Nari Road, Nagpur, Maharashtra, India 440026'
    ),
    'company_email': 'support@enoylity.com',
    'company_phone': '+919284290181',
    'website': 'https://www.enoylitystudio.com/',
    'bank_details': {
        'account_name':        'Enoylity Media Creations LLC',
        'account_number':      '8489753859',
        'ach_routing_number':  '026073150',
        'fedwire_routing_no':  '026073008',
        'swift_code':          'CMFGUS33',
        'account_location':    'United States',
        'bank_name':           'Community Federal Savings Bank',
        'bank_address':        '89-16 Jamaica Ave, Woodhaven, NY, United States, 11421',
        'account_type':        'Checking'
    }
}

# Logo handling
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
LOGO_URL = 'https://www.enoylitystudio.com/wp-content/uploads/2024/02/enoylity-final-logo.png'
LOGO_FILENAME = 'enoylity-final-logo.png'
LOGO_PATH = os.path.join(ASSETS_DIR, LOGO_FILENAME)
os.makedirs(ASSETS_DIR, exist_ok=True)
if not os.path.isfile(LOGO_PATH):
    try:
        resp = requests.get(LOGO_URL, timeout=5)
        resp.raise_for_status()
        with open(LOGO_PATH, 'wb') as f:
            f.write(resp.content)
    except Exception as e:
        print(f"Warning: could not fetch logo – {e}")

class InvoicePDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_font('Lexend', '', os.path.join('static', 'Lexend-Regular.ttf'), uni=True)
        self.add_font('Lexend', 'B', os.path.join('static', 'Lexend-Bold.ttf'), uni=True)
        self.invoice_data = None
        self.logo_path = LOGO_PATH if os.path.isfile(LOGO_PATH) else None
        self.light_blue = (235, 244, 255)
        self.dark_blue = (39, 60, 117)
        self.medium_blue = (100, 149, 237)

    def header(self):
        if self.page_no() > 1 and self.logo_path:
            logo_w = 20
            x = self.w - self.r_margin - logo_w
            try:
                self.image(self.logo_path, x=x, y=8, w=logo_w)
            except Exception as e:
                print(f"Failed to add logo to header: {e}")
        if self.invoice_data:
            self.set_font('Lexend', 'B', 10)
            self.set_text_color(*self.dark_blue)
            self.cell(0, 10, f"Invoice #{self.invoice_data['invoice_number']} (Continued)", 0, 1, 'R')

    def footer(self):
        self.set_y(-20)
        self.set_font('Lexend', '', 8)
        self.set_text_color(100, 100, 100)
        if self.invoice_data:
            contact = (
                f"{self.invoice_data['company_email']} | "
                f"{self.invoice_data['company_phone']} | "
                f"{self.invoice_data['website']}"
            )
            self.cell(0, 4, contact, 0, 1, 'C')


def create_invoice(invoice_data):
    pdf = InvoicePDF()
    pdf.invoice_data = invoice_data
    pdf.add_page()

    # First-page header
    pdf.set_fill_color(*pdf.light_blue)
    pdf.rect(10, 10, 190, 50, 'F')
    if pdf.logo_path:
        try:
            pdf.image(pdf.logo_path, x=0, y=22, w=90)
        except Exception:
            pass

    pdf.set_xy(65, 15)
    pdf.set_font('Lexend', 'B', 20)
    pdf.set_text_color(*pdf.dark_blue)
    pdf.cell(130, 12, invoice_data['company_name'], align='R')

    pdf.set_xy(65, 27)
    pdf.set_font('Lexend', '', 12)
    pdf.cell(130, 8, invoice_data['company_tagline'], align='R')

    pdf.set_xy(65, 35)
    pdf.set_font('Lexend', '', 8)
    pdf.multi_cell(130, 4, invoice_data['company_address'], align='R')

    # Client & Invoice Details
    y = 70
    pdf.set_fill_color(*pdf.light_blue)
    pdf.rect(10, y, 95, 52, 'F')
    pdf.set_xy(15, y + 5)
    pdf.set_font('Lexend', 'B', 11)
    pdf.set_text_color(*pdf.dark_blue)
    pdf.cell(85, 6, 'Bill To', ln=1)

    pdf.set_font('Lexend', '', 10)
    pdf.set_xy(15, y + 13)
    pdf.multi_cell(75, 5, "\n".join([
        invoice_data['client_name'],
        invoice_data['client_address'],
        invoice_data.get('client_email', ''),
        invoice_data.get('client_phone', '')
    ]))

    pdf.rect(115, y, 85, 52, 'F')
    pdf.set_xy(120, y + 5)
    pdf.set_font('Lexend', 'B', 11)
    pdf.set_text_color(*pdf.dark_blue)
    pdf.cell(75, 6, 'Invoice Details', ln=1)

    pdf.set_font('Lexend', '', 10)
    for i, (label, key) in enumerate([
        ("Invoice Number:", 'invoice_number'),
        ("Bill Date:", 'invoice_date'),
        ("Due Date:", 'due_date'),
        ("Payment Method:", 'payment_method_text')
    ]):
        pdf.set_xy(120, y + 13 + i*6)
        pdf.cell(40, 6, label, 0, 0)
        pdf.cell(35, 6, invoice_data[key], 0, 1)

    # Items table header
    y = 130
    pdf.set_fill_color(*pdf.light_blue)
    pdf.rect(10, y, 190, 12, 'F')

    pdf.set_xy(15, y + 3)
    pdf.set_font('Lexend', 'B', 10)
    pdf.set_text_color(*pdf.dark_blue)
    pdf.cell(90, 6, 'ITEM DESCRIPTION', 0, 0, 'L')
    pdf.cell(25, 6, 'QTY', 0, 0, 'C')
    pdf.cell(30, 6, 'PRICE', 0, 0, 'R')
    pdf.cell(30, 6, 'TOTAL', 0, 1, 'R')

    # Iterate items
    y = 145
    bottom_limit = pdf.h - 60
    pdf.set_font('Lexend', '', 10)
    pdf.set_text_color(80, 80, 80)
    running_sub = 0

    for item in invoice_data['items']:
        if y > bottom_limit:
            pdf.add_page()
            y = 35
        desc = item['description']
        if len(desc) > 50:
            desc = desc[:50] + '…'
        total = item['quantity'] * item['price']
        running_sub += total

        pdf.set_xy(15, y)
        pdf.cell(90, 6, desc, 0, 0, 'L')
        pdf.cell(25, 6, str(item['quantity']), 0, 0, 'C')
        pdf.cell(30, 6, f"${item['price']:.2f}", 0, 0, 'R')
        pdf.cell(30, 6, f"${total:.2f}", 0, 1, 'R')

        y += 8
        pdf.set_draw_color(*pdf.medium_blue)
        pdf.line(15, y, 190, y)
        y += 4

    # Summary
    if y > bottom_limit:
        pdf.add_page()
        y = 35
    y += 10
    pdf.set_xy(120, y)
    pdf.set_font('Lexend', '', 10)
    pdf.set_text_color(*pdf.dark_blue)
    pdf.cell(40, 8, 'Sub Total', 0, 0)
    pdf.cell(30, 8, f"${invoice_data['subtotal']:.2f}", 0, 1, 'R')

    if invoice_data.get('paypal_fee', 0) > 0:
        y += 8
        pdf.set_xy(120, y)
        pdf.cell(40, 8, 'PayPal Fee', 0, 0)
        pdf.cell(30, 8, f"${invoice_data['paypal_fee']:.2f}", 0, 1, 'R')

    line_y = y + (16 if invoice_data.get('paypal_fee',0)>0 else 8)
    pdf.set_draw_color(*pdf.medium_blue)
    pdf.line(120, line_y, 190, line_y)

    y = line_y + (8 if invoice_data.get('paypal_fee',0)>0 else 8)
    pdf.set_xy(120, y)
    pdf.set_font('Lexend', 'B', 12)
    pdf.cell(40, 8, 'Grand Total', 0, 0)
    pdf.cell(30, 8, f"${invoice_data['total']:.2f}", 0, 1, 'R')

    # Bank Details & Notes
    y += 20
    if y > bottom_limit:
        pdf.add_page()
        y = 35

    pdf.set_xy(10, y)
    pdf.set_font('Lexend', 'B', 10)
    pdf.set_text_color(*pdf.dark_blue)
    pdf.cell(85, 6, 'BANK DETAILS', ln=1)

    bank = invoice_data['bank_details']
    bank_lines = [
        f"Account name: {bank['account_name']}",
        f"Account Number: {bank['account_number']}",
        f"ACH routing number: {bank['ach_routing_number']}",
        f"Fedwire routing number: {bank['fedwire_routing_no']}",
        f"SWIFT code: {bank['swift_code']}",
        f"Account location: {bank['account_location']}",
        f"Bank name: {bank['bank_name']}",
        f"Bank address: {bank['bank_address']}",
        f"Account Type: {bank['account_type']}"
    ]
    pdf.set_font('Lexend', '', 9)
    pdf.set_text_color(80, 80, 80)
    pdf.multi_cell(85, 5, "\n".join(bank_lines))

    pdf.set_xy(115, y)
    pdf.set_font('Lexend', 'B', 10)
    pdf.set_text_color(*pdf.dark_blue)
    pdf.cell(75, 6, 'NOTES', ln=1)

    y = pdf.get_y()
    pdf.set_xy(115, y)
    pdf.set_font('Lexend', '', 9)
    pdf.set_text_color(80, 80, 80)
    pdf.multi_cell(90, 9, invoice_data.get('notes', ''))

    return pdf.output(dest='S').encode('latin1')


def get_next_invoice_number():
    counter = db.invoice_counters.find_one_and_update(
        {"_id": "Enoylity Studio counter"},
        {"$inc": {"sequence_value": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    seq = counter.get('sequence_value', 1)
    return f"INV{seq:05d}"


@invoice_enoylity_bp.route('/generate-invoice', methods=['POST'])
def generate_invoice_route():
    try:
        data = request.get_json() or {}

        # ✅ Required fields with custom messages
        required_fields = {
            'invoice_date':    "Invoice date is required.",
            'due_date':        "Due date is required.",
            'client_name':     "Client name is required.",
            'client_address':  "Client address is required."
        }

        for field, error_msg in required_fields.items():
            if not data.get(field):
                return format_response(False, error_msg, status=400)

        # ✅ Validate and format dates
        try:
            inv_date = datetime.datetime.strptime(data['invoice_date'], '%d-%m-%Y')
            due_date = datetime.datetime.strptime(data['due_date'], '%d-%m-%Y')
        except ValueError:
            return format_response(False, "Invalid date format. Use DD-MM-YYYY", status=400)

        # ✅ Optional phone validation
        client_phone = data.get('client_phone')
        if client_phone:
            if not client_phone.isdigit() or len(client_phone) != 10:
                return format_response(False, "Client phone must be exactly 10 digits if provided", status=400)

        # ✅ Assign invoice number
        data['invoice_number'] = get_next_invoice_number()

        # ✅ Item calculations
        items = data.get('items', [])
        subtotal = sum(i['quantity'] * i['price'] for i in items)
        data['subtotal'] = subtotal
        pm = int(data.get('payment_method', 0))
        paypal_fee = subtotal * 0.056 if pm == 0 else 0.0
        data['paypal_fee'] = paypal_fee
        data['total'] = subtotal + paypal_fee
        data['payment_method_text'] = {0: "PayPal", 1: "Bank Transfer"}.get(pm, "Other")

        # ✅ Format address
        data['client_address'] = data['client_address'].replace(', ', '\n')

        # ✅ Merge settings
        settings = get_current_settings("Enoylity Studio") or {}

        company_defaults = {
            'company_name':    DEFAULT_SETTINGS['company_name'],
            'company_tagline': DEFAULT_SETTINGS['company_tagline'],
            'company_address': DEFAULT_SETTINGS['company_address'],
            'company_email':   DEFAULT_SETTINGS['company_email'],
            'company_phone':   DEFAULT_SETTINGS['company_phone'],
            'website':         DEFAULT_SETTINGS['website'],
        }
        raw = settings.get('company_info', {}) or {}
        company_info = {**company_defaults, **raw}

        bank_defaults = DEFAULT_SETTINGS['bank_details']
        raw_bank = settings.get('bank_details', {}) or {}
        bank_details = {**bank_defaults, **raw_bank}

        invoice_data = {
            **company_info,
            'bank_details': bank_details,
            **data
        }

        # ✅ Generate PDF
        pdf_bytes = create_invoice(invoice_data)

        # ✅ Save to DB
        record = invoice_data.copy()
        record['created_at'] = datetime.datetime.now()
        db.invoiceEnoylity.insert_one(record)

        # ✅ Send file
        buf = io.BytesIO(pdf_bytes)
        buf.seek(0)
        return send_file(
            buf,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"invoice_{data['invoice_number']}.pdf"
        )

    except ValueError:
        return format_response(False, "Invalid date format. Use DD-MM-YYYY", status=400)
    except Exception as e:
        print(f"Error generating invoice: {e}")
        return format_response(False, "Internal server error", status=500)

@invoice_enoylity_bp.route('/getlist', methods=['POST'])
def get_invoice_list():
    try:
        data = request.get_json() or {}
        page = int(data.get('page', 1))
        per_page = int(data.get('per_page', 10))
        search = (data.get('search') or '').strip()

        filter_criteria = {}
        if search:
            regex = {'$regex': search, '$options': 'i'}
            filter_criteria = {
                '$or': [
                    {'invoice_number': regex},
                    {'client_name': regex},
                    {'invoice_date': regex}
                ]
            }

        skip = (page - 1) * per_page
        cursor = db.invoiceEnoylity.find(filter_criteria).skip(skip).limit(per_page)
        invoices = []
        for inv in cursor:
            inv['_id'] = str(inv['_id'])
            invoices.append(inv)

        total = db.invoiceEnoylity.count_documents(filter_criteria)
        payload = {
            'invoices': invoices,
            'total': total,
            'page': page,
            'per_page': per_page
        }
        return format_response(True, 'Invoice list retrieved successfully', data=payload)

    except Exception as e:
        print(f"Error retrieving invoice list: {str(e)}")
        return format_response(False, 'Internal server error', status=500)
    


    

@invoice_enoylity_bp.route('/getinvoice', methods=['POST'])
def get_invoice_by_id():
    try:
        data = request.get_json() or {}
        invoice_id = data.get('id')
        if not invoice_id:
            return format_response(False, "id is required", status=400)

        # Validate ObjectId format
        try:
            obj_id = ObjectId(invoice_id)
        except Exception:
            return format_response(False, "Invalid id format", status=400)

        # Fetch from MongoDB
        doc = db.invoiceEnoylity.find_one({'_id': obj_id})
        if not doc:
            return format_response(False, "Invoice not found", status=404)

        # Serialize _id and return full document
        doc['_id'] = str(doc['_id'])
        return format_response(True, "Invoice retrieved successfully", doc)

    except Exception as e:
        logging.exception(f"Error fetching invoice by _id: {e}")
        return format_response(False, "Internal server error", status=500)
