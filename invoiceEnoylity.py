from flask import Blueprint, request, send_file
import io
import os
import datetime
import requests
from fpdf import FPDF
from pymongo import ReturnDocument

from utils import format_response
from db import db

# Blueprint for Enoylity Studio invoices
invoice_enoylity_bp = Blueprint("invoiceEnoylity", __name__, url_prefix="/invoiceEnoy")

# Fixed company details
COMPANY_DETAILS = {
    'name': 'Enoylity Studio',
    'tagline': 'Enoylity Media Creations Private Limited',
    'address': (
        'Ekam Enclave II, 301A, Ramai Nagar, near Kapil Nagar Square\n'
        'Nari Road, Nagpur, Maharashtra, India 440026'
    ),
    'email': 'support@enoylity.com',
    'phone': '+919284290181',
    'website': 'https://www.enoylitystudio.com/',
    'bank_details': (
        'Account name: Enoylity Media Creations LLC\n'
        'Account Number: 8489753859\n'
        'ACH routing number: 026073150\n'
        'Fedwire routing number: 026073008\n'
        'SWIFT code: CMFGUS33\n'
        'Account location: United States\n'
        'Bank name: Community Federal Savings Bank\n'
        'Bank address: 89-16 Jamaica Ave, Woodhaven, NY, United States, 11421\n'
        'Account Type: Checking'
    )
}

# Logo handling setup
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
LOGO_URL = 'https://www.enoylitystudio.com/wp-content/uploads/2024/02/enoylity-final-logo.png'
LOGO_FILENAME = 'enoylity-final-logo.png'
LOGO_PATH = os.path.join(ASSETS_DIR, LOGO_FILENAME)

# Ensure assets directory exists
os.makedirs(ASSETS_DIR, exist_ok=True)

# Download logo if missing
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
        # Register Lexend fonts (ensure .ttf files are in 'static/' directory)
        self.add_font('Lexend', '', os.path.join('static', 'Lexend-Regular.ttf'), uni=True)
        self.add_font('Lexend', 'B', os.path.join('static', 'Lexend-Bold.ttf'), uni=True)
        
        self.invoice_data = None
        self.logo_path = LOGO_PATH if os.path.isfile(LOGO_PATH) else None
        self.light_blue = (235, 244, 255)
        self.dark_blue = (39, 60, 117)
        self.medium_blue = (100, 149, 237)

    def header(self):
        if self.page_no() > 1:
            if self.logo_path:
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
        
        # Contact information
        if self.invoice_data:
            contact = (
                f"{COMPANY_DETAILS['company_email']} | "
                f"{COMPANY_DETAILS['company_phone']} | "
                f"{COMPANY_DETAILS['website']}"
            )
            self.cell(0, 4, contact, 0, 1, 'C')
        
        # Page number
        self.cell(0, 4, f'Page {self.page_no()}', 0, 1, 'C')


def create_invoice(invoice_data):
    pdf = InvoicePDF()
    pdf.invoice_data = invoice_data
    pdf.add_page()

    # First-page styled header
    pdf.set_fill_color(*pdf.light_blue)
    pdf.rect(10, 10, 190, 50, 'F')
    
    # Use the locally stored logo file
    if pdf.logo_path:
        try:
            pdf.image(pdf.logo_path, x=0, y=22, w=90) # Adjusted position and size
        except Exception as e:
            print(f"Failed to add logo to PDF: {e}")

    # Company name & tagline
    pdf.set_xy(55, 15)
    pdf.set_font('Lexend', 'B', 20)
    pdf.set_text_color(*pdf.dark_blue)
    pdf.cell(130, 12, COMPANY_DETAILS['company_name'], align='R')
    pdf.set_xy(55, 27)
    pdf.set_font('Lexend', '', 12)
    pdf.cell(130, 8, COMPANY_DETAILS['company_tagline'], align='R')
    
    # Company address right under company name
    pdf.set_xy(55, 35)
    pdf.set_font('Lexend', '', 8)
    pdf.multi_cell(130, 4, COMPANY_DETAILS['company_address'], align='R')

    # Client & Invoice Details Sections
    y = 70
    pdf.set_fill_color(*pdf.light_blue)
    
    # Client Details - Left Box
    pdf.rect(10, y, 95, 52, 'F')
    pdf.set_xy(15, y + 5)
    pdf.set_font('Lexend', 'B', 11)
    pdf.set_text_color(*pdf.dark_blue)
    pdf.cell(85, 6, 'Bill To', ln=1)
    pdf.set_font('Lexend', '', 10)
    pdf.set_xy(15, y + 13)
    pdf.cell(85, 6, invoice_data['client_name'], ln=1)
    pdf.set_xy(15, y + 19)
    pdf.multi_cell(75, 5, invoice_data['client_address'])
    pdf.set_xy(15, y + 34)
    pdf.cell(85, 6, invoice_data['client_email'], ln=1)
    pdf.set_xy(15, y + 40)
    pdf.cell(85, 6, invoice_data.get('client_phone', ''), ln=1)

    # Invoice Details - Right Box
    pdf.rect(115, y, 85, 52, 'F')
    pdf.set_xy(120, y + 5)
    pdf.set_font('Lexend', 'B', 11)
    pdf.set_text_color(*pdf.dark_blue)
    pdf.cell(75, 6, 'Invoice Details', ln=1)
    pdf.set_font('Lexend', '', 10)
    
    # Invoice metadata
    pdf.set_xy(120, y + 13)
    pdf.cell(75, 6, f"Invoice Number: {invoice_data['invoice_number']}", ln=1)
    pdf.set_xy(120, y + 19)
    pdf.cell(75, 6, f"Bill Date: {invoice_data['date']}", ln=1)
    pdf.set_xy(120, y + 25)
    pdf.cell(75, 6, f"Due Date: {invoice_data['due_date']}", ln=1)
    pdf.set_xy(120, y + 31)
    pdf.cell(75, 6, f"Payment Method: {invoice_data['payment_method_text']}", ln=1)

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

    # Iterate items with dynamic pagination
    y = 145
    first_limit = pdf.h - 100
    running_sub = 0
    for item in invoice_data['items']:
        if y + 12 > first_limit:
            pdf.add_page()
            y = 35
        pdf.set_xy(15, y)
        pdf.set_font('Lexend', '', 10)
        pdf.set_text_color(80, 80, 80)
        desc = (item['description'][:50] + '...') if len(item['description']) > 50 else item['description']
        pdf.cell(90, 6, desc, 0, 0, 'L')
        pdf.cell(25, 6, str(item['quantity']), 0, 0, 'C')
        pdf.cell(30, 6, f"${item['price']:.2f}", 0, 0, 'R')
        total = item['quantity'] * item['price']
        running_sub += total
        pdf.cell(30, 6, f"${total:.2f}", 0, 1, 'R')
        y += 12
        pdf.set_draw_color(*pdf.medium_blue)
        pdf.line(15, y, 190, y)
        y += 2

    # Summary block
    if y > pdf.h - 80:
        pdf.add_page()
        y = 35
    y += 10
    pdf.set_xy(120, y)
    pdf.set_font('Lexend', '', 10)
    pdf.cell(40, 8, 'Sub Total', 0, 0, 'L')
    pdf.cell(30, 8, f"${invoice_data['subtotal']:.2f}", 0, 1, 'R')
    y += 8
    if invoice_data.get('paypal_fee', 0) > 0:
        pdf.set_xy(120, y)
        pdf.cell(40, 8, 'PayPal Fee', 0, 0, 'L')
        pdf.cell(30, 8, f"${invoice_data['paypal_fee']:.2f}", 0, 1, 'R')
        y += 8
        pdf.set_draw_color(*pdf.medium_blue)
        pdf.line(120, y, 190, y)
    pdf.set_draw_color(*pdf.medium_blue)
    pdf.line(120, y, 190, y)
    y += 8
    pdf.set_xy(120, y)
    pdf.set_font('Lexend', 'B', 12)
    pdf.set_text_color(*pdf.dark_blue)
    pdf.cell(40, 8, 'Grand Total', 0, 0, 'L')
    pdf.cell(30, 8, f"${invoice_data['total']:.2f}", 0, 1, 'R')

    # Footer sections for bank details and notes
    y += 20
    if y > pdf.h - 80:
        pdf.add_page()
        y = 35
    
    # Bank Details - Left Section
    pdf.set_xy(15, y)
    pdf.set_font('Lexend', 'B', 10)
    pdf.set_text_color(*pdf.dark_blue)
    pdf.cell(85, 6, 'BANK DETAILS', ln=1)
    pdf.set_xy(15, y + 8)
    pdf.set_font('Lexend', '', 9)
    pdf.set_text_color(80, 80, 80)
    pdf.multi_cell(85, 5, COMPANY_DETAILS.get('bank_details', 'Bank details not provided'))
    
    # Notes Section - Right Side
    pdf.set_xy(115, y)
    pdf.set_font('Lexend', 'B', 10)
    pdf.set_text_color(*pdf.dark_blue)
    pdf.cell(75, 6, 'NOTES', ln=1)
    pdf.set_xy(115, y + 8)
    pdf.set_font('Lexend', '', 9)
    pdf.set_text_color(80, 80, 80)
    pdf.multi_cell(85, 5, invoice_data['notes'])

    return pdf.output(dest='S').encode('latin1')


def get_next_invoice_number():
    """
    Atomically increment and return the next invoice number.
    Uses a counter document in MongoDB named 'Enoylity Studio counter'.
    """
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
        required = [
            'date', 'client_name', 'client_address'
        ]
        for field in required:
            if field not in data:
                return format_response(False, f"Missing required field: {field}", status=400)

        # Generate and attach invoice number
        invoice_number = get_next_invoice_number()
        data['invoice_number'] = invoice_number

        # Parse dates
        try:
            inv_date = datetime.datetime.strptime(data['date'], '%d-%m-%Y')
        except ValueError:
            return format_response(False, "Invalid date format for 'date'. Use DD-MM-YYYY", status=400)
        due = inv_date + datetime.timedelta(days=7)
        data['due_date'] = due.strftime('%d-%m-%Y')

        # Calculate totals
        items = data['items']
        subtotal = sum(i['quantity'] * i['price'] for i in items)
        data['subtotal'] = subtotal
        pm = int(data.get('payment_method', 0))
        paypal_fee = round(subtotal * 0.055, 2) if pm == 0 else 0.0
        data['paypal_fee'] = paypal_fee
        data['total'] = subtotal + paypal_fee
        
        # Set payment method text
        payment_methods = {0: "PayPal", 1: "Bank Transfer"}
        data['payment_method_text'] = payment_methods.get(pm, "Other")

        # Format address and merge details
        data['client_address'] = data['client_address'].replace(', ', '\n')
        invoice_data = {**COMPANY_DETAILS, **data}

        # Create PDF
        pdf_bytes = create_invoice(invoice_data)

        # Save record in DB
        record = invoice_data.copy()
        record['created_at'] = datetime.datetime.now()
        db.invoiceEnoylity.insert_one(record)

        # Send file
        buf = io.BytesIO(pdf_bytes)
        buf.seek(0)
        return send_file(
            buf,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"invoice_{invoice_number}.pdf"
        )

    except Exception as e:
        print(f"Error generating invoice: {str(e)}")
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
                    {'date': regex}
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




    