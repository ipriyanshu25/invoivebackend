from flask import Flask, request, send_file, jsonify, Blueprint
import io, os, datetime, uuid, random, string, requests
from fpdf import FPDF
from PIL import Image
from pymongo import MongoClient
from db import db

app = Flask(__name__)
salary_bp = Blueprint("salaryslip", __name__, url_prefix="/salary")
invoices_collection = db['invoiceEnoylity']

# Fixed company details
COMPANY_DETAILS = {
    'company_name': 'Enoylity Studio',
    'company_tagline': 'Enoylity Media Creations Private Limited',
    'company_address': 'Ekam Enclave II, 301A, Ramai Nagar, near Kapil Nagar Square\nNari Road, Nagpur, Maharashtra, India 440026',
    'company_email': 'support@enoylity.com',
    'company_phone': '+919284290181',
    'website': 'https://www.enoylitystudio.com/'
}
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
LOGO_URL = 'https://www.enoylitystudio.com/wp-content/uploads/2024/02/enoylity-final-logo.png'
LOGO_FILENAME = 'enoylity-final-logo.png'
LOGO_PATH = os.path.join(ASSETS_DIR, LOGO_FILENAME)

# ensure assets dir
os.makedirs(ASSETS_DIR, exist_ok=True)
# download logo if missing
if not os.path.isfile(LOGO_PATH):
    try:
        resp = requests.get(LOGO_URL, timeout=5)
        resp.raise_for_status()
        with open(LOGO_PATH, 'wb') as f:
            f.write(resp.content)
    except Exception as e:
        print(f"Warning: could not fetch logo – {e}")

class InvoicePDF(FPDF):
    def __init__(self):
        super().__init__()
        self.invoice_data = None
        self.logo_path = LOGO_PATH if os.path.isfile(LOGO_PATH) else None
        self.light_blue = (235,244,255)
        self.dark_blue = (39,60,117)
        self.medium_blue = (100,149,237)

    def header(self):
        if self.page_no() > 1:
            if self.logo_path:
                logo_w = 20
                x = self.w - self.r_margin - logo_w
                self.image(self.logo_path, x=x, y=8, w=logo_w)
            self.set_font('Arial','B',10)
            self.set_text_color(*self.dark_blue)
            self.cell(0,10,f"Invoice #{self.invoice_data['invoice_number']} (Continued)",0,1,'R')

    def footer(self):
        self.set_y(-20)
        self.set_font('Arial','I',8)
        self.set_text_color(100,100,100)
        if self.invoice_data:
            contact = f"{COMPANY_DETAILS['company_email']} | {COMPANY_DETAILS['company_phone']} | {COMPANY_DETAILS['website']}"
            self.cell(0,6,contact,0,1,'C')
        self.cell(0,6,f'Page {self.page_no()}',0,0,'C')

def create_invoice(invoice_data):
    pdf = InvoicePDF()
    pdf.invoice_data = invoice_data
    pdf.add_page()

    # --- FIRST PAGE HEADER ---
    pdf.set_fill_color(*pdf.light_blue)
    pdf.rect(10, 10, 190, 50, 'F')

    if pdf.logo_path:
        pdf.image(pdf.logo_path, x=0, y=22, w=90)

    # Company name & tagline
    pdf.set_xy(55, 15)
    pdf.set_font('Arial', 'B', 20)
    pdf.set_text_color(*pdf.dark_blue)
    pdf.cell(130, 12, COMPANY_DETAILS['company_name'], align='R')

    pdf.set_xy(55, 27)
    pdf.set_font('Arial', '', 16)
    pdf.cell(130, 10, COMPANY_DETAILS['company_tagline'], align='R')

    # Invoice number, date, and due date
    pdf.set_xy(55, 38)
    pdf.set_font('Arial', '', 10)
    pdf.set_text_color(*pdf.dark_blue)
    pdf.cell(130, 8, f"Invoice Number: {invoice_data['invoice_number']}", ln=1, align='R')
    pdf.set_xy(55, 46)
    pdf.cell(130, 6, f"Bill Date: {invoice_data['date']}", ln=1, align='R')
    pdf.set_xy(55, 52)
    pdf.cell(130, 6, f"Due Date: {invoice_data['due_date']}", ln=1, align='R')

    # --- CLIENT AND COMPANY ADDRESS SECTIONS ---
    y_position = 70
    pdf.set_fill_color(*pdf.light_blue)
    pdf.rect(10, y_position, 95, 52, 'F')
    pdf.set_xy(15, y_position + 5)
    pdf.set_font('Arial', 'B', 11)
    pdf.set_text_color(*pdf.dark_blue)
    pdf.cell(85, 6, 'BILL TO', ln=1)
    pdf.set_font('Arial', '', 10)
    pdf.set_xy(15, y_position + 13)
    pdf.cell(85, 6, invoice_data['client_name'], ln=1)
    pdf.set_xy(15, y_position + 19)
    pdf.multi_cell(75, 5, invoice_data['client_address'])
    pdf.set_xy(15, y_position + 39)
    pdf.cell(85, 6, invoice_data['client_email'], ln=1)
    pdf.set_xy(15, y_position + 37)
    pdf.cell(85, 6, invoice_data.get('client_phone', ''), ln=1)

    # Company Information (right)
    pdf.rect(115, y_position, 85, 52, 'F')
    pdf.set_xy(120, y_position + 5)
    pdf.set_font('Arial', 'B', 11)
    pdf.set_text_color(*pdf.dark_blue)
    pdf.cell(75, 6, 'FROM', ln=1)
    pdf.set_font('Arial', '', 10)
    pdf.set_xy(120, y_position + 13)
    pdf.cell(75, 6, COMPANY_DETAILS['company_name'], ln=1)
    pdf.set_xy(120, y_position + 19)
    pdf.multi_cell(75, 5, COMPANY_DETAILS['company_address'])
    pdf.set_xy(120, y_position + 39)
    pdf.cell(75, 6, COMPANY_DETAILS['company_email'], ln=1)
    pdf.set_xy(120, y_position + 45)
    pdf.cell(75, 6, COMPANY_DETAILS['company_phone'], ln=1)

    # --- ITEMS TABLE HEADER ---
    y_position = 130
    pdf.set_fill_color(*pdf.light_blue)
    pdf.rect(10, y_position, 190, 12, 'F')
    pdf.set_xy(15, y_position + 3)
    pdf.set_font('Arial', 'B', 10)
    pdf.set_text_color(*pdf.dark_blue)
    pdf.cell(90, 6, 'ITEM DESCRIPTION', 0, 0, 'L')
    pdf.cell(25, 6, 'QTY', 0, 0, 'C')
    pdf.cell(30, 6, 'PRICE', 0, 0, 'R')
    pdf.cell(30, 6, 'TOTAL', 0, 1, 'R')

    # --- ITEMS LIST ---
    y_position = 145
    pdf.set_draw_color(*pdf.medium_blue)
    
    # Calculate available space for items on first page
    # Leave room for summary section (approx 80 points) and footer (20 points)
    first_page_limit = pdf.h - 100
    
    # Calculate running totals
    running_subtotal = 0
    
    for item in invoice_data['items']:
        # Check if we need a new page
        if y_position + 12 > first_page_limit and len(item['description']) > 0:
            pdf.add_page()
            y_position = 35  # Start after the header on new pages
        
        pdf.set_xy(15, y_position)
        pdf.set_font('Arial', '', 10)
        pdf.set_text_color(80, 80, 80)
        
        # Handle potentially long descriptions
        if len(item['description']) > 50:  # If description is very long
            pdf.cell(90, 6, item['description'][:50] + "...", 0, 0, 'L')
        else:
            pdf.cell(90, 6, item['description'], 0, 0, 'L')
            
        pdf.cell(25, 6, str(item['quantity']), 0, 0, 'C')
        pdf.cell(30, 6, f"${item['price']:.2f}", 0, 0, 'R')
        item_total = item['quantity'] * item['price']
        running_subtotal += item_total
        pdf.cell(30, 6, f"${item_total:.2f}", 0, 1, 'R')
        
        y_position += 10
        pdf.line(15, y_position, 190, y_position)
        y_position += 2
    
    # --- SUMMARY SECTION ---
    # If we're too close to the bottom of the page, start a new page
    if y_position > (pdf.h - 80):
        pdf.add_page()
        y_position = 35  # Start after the header
    
    y_position += 10
    pdf.set_xy(120, y_position)
    pdf.set_font('Arial', '', 10)
    pdf.cell(40, 8, 'Sub Total', 0, 0, 'L')
    pdf.cell(30, 8, f"${invoice_data['subtotal']:.2f}", 0, 1, 'R')

    y_position += 8
    pdf.set_xy(120, y_position)
    pdf.cell(40, 8, 'PayPal Fee', 0, 0, 'L')
    pdf.cell(30, 8, f"${invoice_data['paypal_fee']:.2f}", 0, 1, 'R')

    y_position += 8
    pdf.set_draw_color(*pdf.medium_blue)
    pdf.line(120, y_position, 190, y_position)

    y_position += 8
    pdf.set_xy(120, y_position)
    pdf.set_font('Arial', 'B', 12)
    pdf.set_text_color(*pdf.dark_blue)
    pdf.cell(40, 8, 'Grand Total', 0, 0, 'L')
    pdf.cell(30, 8, f"${invoice_data['total']:.2f}", 0, 1, 'R')

    # --- BANK DETAILS AND NOTES SECTIONS ---
    # If we're too close to the bottom, add a new page
    if y_position > (pdf.h - 50):
        pdf.add_page()
        y_position = 35
    else:
        y_position += 15
    
    # pdf.set_fill_color(*pdf.light_blue)
    # pdf.rect(10, y_position, 95, 35, 'F')
    # pdf.set_xy(15, y_position + 5)
    # pdf.set_font('Arial', 'B', 10)
    # pdf.set_text_color(*pdf.dark_blue)
    # pdf.cell(85, 6, 'BANK DETAILS', ln=1)
    # pdf.set_font('Arial', '', 9)
    # pdf.set_xy(15, y_position + 13)
    # pdf.cell(85, 6, invoice_data['bank_name'], ln=1)
    # pdf.set_xy(15, y_position + 19)
    # pdf.cell(85, 6, invoice_data['bank_account'], ln=1)

    # Notes section
        # --- NOTES SECTION (full‑width, centered) ---
    # Compute full printable width
    page_width = pdf.w - pdf.l_margin - pdf.r_margin
    box_height = 35  # or compute dynamically if you like

    # Header: NOTES (bold, centered)
    pdf.set_xy(pdf.l_margin, y_position + 5)
    pdf.set_font('Arial', 'B', 10)
    pdf.set_text_color(*pdf.dark_blue)
    pdf.cell(page_width, 6, 'NOTES', ln=1, align='C')

    # Body: invoice_data['notes'] (wrapped, centered)
    pdf.set_xy(pdf.l_margin, y_position + 13)
    pdf.set_font('Arial', '', 9)
    pdf.multi_cell(page_width, 6, invoice_data['notes'], align='C')


    return pdf.output(dest='S').encode('latin1')

def generate_invoice_number():
    # fetch last invoice_number, parse and increment
    last = invoices_collection.find({"invoice_number": {'$regex': '^INV\d{5}$'}}) 
    last = last.sort('invoice_number', -1).limit(1)
    try:
        prev = next(last)['invoice_number']
        num = int(prev.replace('INV','')) + 1
    except StopIteration:
        num = 90  # start at INV00090
    return f"INV{num:05d}"

def calculate_totals(items):
    """Calculate subtotal from items."""
    subtotal = sum(item['quantity'] * item['price'] for item in items)
    return subtotal

@app.route('/generate-invoice', methods=['POST'])
def generate_invoice_route():
    try:
        data = request.get_json() or {}
        # required fields
        required = ['date','client_name','client_address','client_email','items','bank_name','bank_account','notes','payment_method']
        for f in required:
            if f not in data:
                return jsonify({"error": f"Missing required field: {f}"}),400
        # invoice number
        invoice_number = generate_invoice_number()
        data['invoice_number'] = invoice_number
        # parse date and due date
        inv_date = datetime.datetime.strptime(data['date'], '%d-%m-%Y')
        due = inv_date + datetime.timedelta(days=7)
        data['due_date'] = due.strftime('%d-%m-%Y')
        # calculate subtotal
        subtotal = sum(i['quantity']*i['price'] for i in data['items'])
        data['subtotal'] = subtotal
        # payment method: 1=bank, 0=paypal
        pm = int(data.get('payment_method'))
        if pm == 0:
            fee = round(subtotal * 0.053,2)
        else:
            fee = 0.0
        data['paypal_fee'] = fee
        data['total'] = subtotal + fee
        # prepare address multiline
        data['client_address'] = data['client_address'].replace(', ', '\n')
        # merge company details
        invoice_data = {**data, **COMPANY_DETAILS}
        # generate PDF
        pdf_bytes = create_invoice(invoice_data)
        # save record
        rec = invoice_data.copy()
        rec['created_at'] = datetime.datetime.now()
        invoices_collection.insert_one(rec)
        # send PDF
        buf = io.BytesIO(pdf_bytes)
        buf.seek(0)
        return send_file(buf, mimetype='application/pdf', as_attachment=True,
                         download_name=f"invoice_{invoice_number}.pdf")
    except Exception as e:
        return jsonify({"error": str(e)}),500


@app.route('/get-invoice/<invoice_number>', methods=['GET'])
def get_invoice(invoice_number):
    try:
        # Fetch invoice data from MongoDB
        invoice_data = invoices_collection.find_one({"invoice_number": invoice_number})
        
        if not invoice_data:
            return jsonify({"error": "Invoice not found"}), 404
        
        # Remove MongoDB _id field (not JSON serializable)
        invoice_data.pop('_id', None)
        
        # Generate PDF from the data
        pdf_bytes = create_invoice(invoice_data)
        pdf_buffer = io.BytesIO(pdf_bytes)
        pdf_buffer.seek(0)
        
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"invoice_{invoice_number}.pdf"
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/get-invoice-data/<invoice_number>', methods=['GET'])
def get_invoice_data(invoice_number):
    try:
        # Fetch just the invoice data from MongoDB
        invoice_data = invoices_collection.find_one({"invoice_number": invoice_number})
        
        if not invoice_data:
            return jsonify({"error": "Invoice not found"}), 404
        
        # Remove MongoDB _id field
        invoice_data.pop('_id', None)
        
        return jsonify(invoice_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Create assets directory if it doesn't exist
    assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
    if not os.path.exists(assets_dir):
        os.makedirs(assets_dir)
    
    app.run(debug=True, port=5000)



