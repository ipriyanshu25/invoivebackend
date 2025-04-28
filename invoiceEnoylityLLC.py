from flask import Blueprint, request, send_file
import io
import os
import logging
from datetime import datetime
from fpdf import FPDF
from pymongo import ReturnDocument

from utils import format_response
from db import db
from settings import get_current_settings
import copy
from random import choices
import string as _str

# Configure logging
logging.basicConfig(level=logging.ERROR)

# Blueprint setup
enoylity_bp = Blueprint("enoylity", __name__, url_prefix="/invoiceEnoylityLLC")

# Invoice type key in settings_invoice
INVOICE_TYPE = "Enoylity Media Creations LLC"

# Default template settings
DEFAULT_SETTINGS = {
    "logo_path": "enoylitytechlogo.png",
    "fonts": {
        "regular": os.path.join('static', 'Lexend-Regular.ttf'),
        "bold":    os.path.join('static', 'Lexend-Bold.ttf')
    },
    "colors": {
        "black":      [0, 0, 0],
        "light_pink": [255, 228, 241],
        "dark_pink":  [199, 21, 133]
    },
    "company_info": {
        "name":       "Enoylity Media Creations LLC",
        "address":    "444 Alaska Avenue, Suite AVJ801",
        "city_state": "Torrance, California, 90503, USA",
        "phone":      "+15075561971",
        "youtube":    "youtube.com/@enoylitytech",
        "email":      "support@enoylity.com"
    },
    "paypal_details": {
        "receiver_email": "support@enoylity.com",
        "paypal_name":    "Enoylity Media Creation"
    },
    "bank_details": {
        "account_name":        "Enoylity Media Creations LLC",
        "account_number":      "200000523466",
        "routing_number":      "064209588",
        "bank_name":           "Thread Bank",
        "bank_address":        "210 E Main St, Rogersville TN 37857"
    }
}


# Generate sequential invoice numbers
def get_next_invoice_number():
    counter = db.invoice_counters.find_one_and_update(
        {"_id": f"{INVOICE_TYPE} counter"},
        {"$inc": {"sequence_value": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    seq = counter.get("sequence_value", 1)
    return f"INV{seq:05d}"

class InvoicePDF(FPDF):
    def __init__(self, settings, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.settings = settings
        # Register fonts
        self.add_font('Lexend', '', settings['fonts']['regular'], uni=True)
        self.add_font('Lexend', 'B', settings['fonts']['bold'],    uni=True)
        self.set_font('Lexend', '', 11)

    def header(self):
        s = self.settings
        # Logo
        if os.path.isfile(s['logo_path']):
            self.image(s['logo_path'], x=self.l_margin, y=10, w=40)
        # Company info aligned right
        ci = s['company_info']
        self.set_xy(self.l_margin, 10)
        self.set_font('Lexend', 'B', 18)
        self.set_text_color(*s['colors']['black'])
        self.cell(0, 10, ci['name'], ln=1, align='R')
        self.set_font('Lexend', '', 11)
        self.cell(0, 6, ci['address'], ln=1, align='R')
        self.cell(0, 6, ci['city_state'], ln=1, align='R')
        self.cell(0, 6, f"Phone: {ci['phone']}", ln=1, align='R')
        self.cell(0, 6, ci.get('youtube', ''), ln=1, align='R')
        self.cell(0, 6, ci['email'], ln=1, align='R')
        self.ln(12)

@enoylity_bp.route('/generate-invoice', methods=['POST'])
def generate_invoice_endpoint():
    try:
        # 1️⃣ Load editable_fields for this invoice type
        raw = db.settings_invoice.find_one({"invoice_type": INVOICE_TYPE}) or {}
        editable = raw.get('editable_fields', {})

        # 2️⃣ Build effective settings by deep-merging
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        for k, v in editable.items():
            if isinstance(v, dict) and k in settings:
                settings[k].update(v)
            else:
                settings[k] = v

        # 3️⃣ Parse & validate input
        data = request.get_json() or {}
        phone = data.get('bill_to_phone')
        if phone:
            if not phone.isdigit() or len(phone) != 10:
                return format_response(False, "Phone number must be exactly 10 digits if provided", status=400)
        
        required_fields = {
            "bill_to_name":     "Billing name is required",
            "bill_to_address":  "Billing address is required",
            "invoice_date":     "Invoice date is required",
            "due_date":         "Due date is required"
        }

        for field, error_msg in required_fields.items():
            if not data.get(field):
                return format_response(False, error_msg, status=400)

        bt_name = data['bill_to_name']
        bt_addr = data['bill_to_address']
        bt_phone = data.get('bill_to_phone',"")
        bt_mail = data.get('bill_to_email',"")
        note      = data.get('note', '')
        bank_note = data.get('bank_Note', '')
        items   = data.get('items', [])
        payment_method = int(data.get('payment_method', 0))
        invoice_date   = data['invoice_date']
        due_date       = data['due_date']

        # 4️⃣ Invoice numbering and date check
        inv_num = get_next_invoice_number()
        try:
            datetime.strptime(invoice_date, '%d-%m-%Y')
            datetime.strptime(due_date,   '%d-%m-%Y')
        except ValueError:
            return format_response(False, "Dates must be DD-MM-YYYY", status=400)

        # 5️⃣ Generate PDF
        pdf = InvoicePDF(settings)
        pdf.invoice_number = inv_num
        pdf.invoice_date   = invoice_date
        pdf.due_date       = due_date
        pdf.add_page()

        # — Bill To block
        lines = [bt_name, bt_addr, bt_phone, bt_mail]
        x, y = pdf.l_margin, pdf.get_y()
        width = pdf.w - pdf.l_margin - pdf.r_margin
        indent, padding = 4, 7
        header_h, line_h = 13, 7
        block_h = header_h + len(lines)*line_h + padding
        pdf.set_fill_color(*settings['colors']['light_pink'])
        pdf.rect(x, y, width, block_h, 'F')
        pdf.set_xy(x+indent, y+indent)
        pdf.set_font('Lexend','B',12)
        pdf.set_text_color(*settings['colors']['black'])
        pdf.cell(0, header_h, 'Bill To:', ln=1)
        pdf.set_font('Lexend','',11)
        for ln in lines:
            pdf.set_x(x+indent)
            pdf.cell(0, line_h, ln, ln=1)
        pdf.ln(padding)

        # — Invoice Details block
        details = [
            f"Invoice #: {inv_num}",
            f"Bill Date: {invoice_date}",
            f"Due Date: {due_date}"
        ]
        y2 = pdf.get_y()
        block_h2 = header_h + len(details)*line_h + padding
        pdf.set_fill_color(*settings['colors']['light_pink'])
        pdf.rect(x, y2, width, block_h2, 'F')
        pdf.set_xy(x+indent, y2+indent)
        pdf.set_font('Lexend','B',12)
        pdf.cell(0, header_h, 'Invoice Details:', ln=1)
        pdf.set_font('Lexend','',10)
        for d in details:
            pdf.set_x(x+indent)
            pdf.cell(0, line_h, d, ln=1)
        pdf.ln(padding)

        # — Items table
        pdf.set_fill_color(*settings['colors']['dark_pink'])
        pdf.set_text_color(255,255,255)
        pdf.set_font('Lexend','B',12)
        pdf.cell(90,10,'DESCRIPTION',0,0,'C',True)
        pdf.cell(30,10,'RATE',0,0,'C',True)
        pdf.cell(20,10,'QTY',0,0,'C',True)
        pdf.cell(45,10,'AMOUNT',0,1,'C',True)
        pdf.set_text_color(*settings['colors']['black'])
        pdf.set_font('Lexend','',11)
        subtotal = 0
        for it in items:
            desc = it.get('description','')
            rate = float(it.get('price',0))
            qty  = int(it.get('quantity',1))
            amt  = rate*qty
            subtotal += amt
            pdf.cell(90,8,desc,0,0,'L')
            pdf.cell(30,8,f'${rate:.2f}',0,0,'C')
            pdf.cell(20,8,str(qty),0,0,'C')
            pdf.cell(45,8,f'${amt:.2f}',0,1,'C')

        # — Payment fee & total
        if payment_method == 0:
            fee = subtotal * 0.056
            total = subtotal + fee
            pdf.ln(4)
            pdf.set_font('Lexend','',13)
            pdf.cell(140,8,'PayPal Fee',0,0,'R')
            pdf.cell(45,8,f'$ {fee:.2f}',0,1,'C')
        else:
            total = subtotal
        pdf.ln(6)
        pdf.set_font('Lexend','B',14)
        pdf.cell(135,8,'TOTAL ',0,0,'R')
        pdf.cell(39,8,f'USD $ {total:.2f}',0,1,'C')

        # — Payment Info & Note side-by-side
        pdf.ln(10)
        x = pdf.l_margin
        y = pdf.get_y()
        width = pdf.w - pdf.l_margin - pdf.r_margin

        # Split into left and right columns
        left_col_width = width / 2 - 5
        right_col_width = width / 2 - 5

        pdf.set_xy(x, y+7)  # Added padding of 6 units

        pdf.set_font('Lexend', 'B', 12)
        pdf.set_text_color(*settings['colors']['black'])

        if payment_method == 0:
            left_x   = x
            right_x  = x + left_col_width + 10
            top_y    = y

            if note:
                pdf.set_xy(right_x, top_y-1)
                pdf.set_font('Lexend', 'B', 12)
                pdf.cell(right_col_width - 12, 6, 'Note:', ln=1)

                pdf.set_font('Lexend', 11)
                pdf.set_xy(right_x, top_y + 6)
                for line in note('\n'):
                    pdf.set_x(right_x)
                    pdf.cell(right_col_width - 20, 6, line, ln=1)

            # PayPal
            pdf.set_xy(left_x, top_y)
            pdf.set_font('Lexend', 'B', 12)
            pdf.cell(left_col_width-12, 6, 'PayPal Details:', ln=1)  # Adjusted width because of padding
            paypal = settings['paypal_details']
            pdf.set_font('Lexend', '', 11)
            pdf.cell(left_col_width-12, 6, f"Receiver: {paypal['receiver_email']}", ln=1)
            pdf.cell(left_col_width-12, 6, f"PayPal Name: {paypal['paypal_name']}", ln=1)

        elif payment_method == 1:
            # define column origins
            left_x   = x
            right_x  = x + left_col_width + 10
            top_y    = y

            # ─── Left Column: Bank Details ──────────────────────────────────────────
            pdf.set_xy(left_x, top_y)
            pdf.set_font('Lexend', 'B', 12)
            pdf.cell(left_col_width - 12, 6, 'Bank Details:', ln=1)
            
            bank = settings['bank_details']
            pdf.set_font('Lexend', '', 11)
            for line in (
                f"Account Name: {bank['account_name']}",
                f"Account No:   {bank['account_number']}",
                f"Routing No:   {bank['routing_number']}",
                f"Bank:         {bank['bank_name']}",
                f"Address:      {bank['bank_address']}",
            ):
                pdf.set_x(left_x)
                pdf.cell(left_col_width - 20, 6, line, ln=1)

            # optional Bank Note underneath
            if bank_note:
                pdf.ln(2)
                pdf.set_x(left_x)
                pdf.set_font('Lexend', 'B', 12)
                pdf.cell(left_col_width - 12, 6, 'Bank Note:', ln=1)
                pdf.set_font('Lexend', '', 11)
                pdf.set_x(left_x)
                pdf.multi_cell(left_col_width - 12, 6, bank_note)

            # ─── Right Column: Generic Note ─────────────────────────────────────────
            if note:
                pdf.set_xy(right_x, top_y)
                pdf.set_font('Lexend', 'B', 12)
                pdf.cell(right_col_width - 12, 6, 'Note:', ln=1)

                pdf.set_font('Lexend', '', 11)
                # move down 8 points from the 'Note:' header
                pdf.set_xy(right_x, top_y + 8)
                for line in note.split('\n'):
                    pdf.set_x(right_x)
                    pdf.cell(right_col_width - 20, 6, line, ln=1)

        else:
            if note:
                pdf.set_xy(x, y)
                pdf.set_xy(x, y + 6)  # Padding on right side too

                pdf.set_font('Lexend', 'B', 12)
                pdf.cell(right_col_width-12, 6, 'Note:', ln=1)

                pdf.set_font('Lexend', '', 11)

                # Save the current X and Y to manually control text position
                start_x = x 
                start_y = y + 10

                pdf.set_xy(start_x, start_y)

                # Now split the note into lines manually
                lines = note.split('\n')
                for line in lines:
                    pdf.set_x(start_x)
                    pdf.cell(right_col_width-20, 10, line, ln=1)

                pass

        # 6️⃣ Persist invoice record
        inv_id = ''.join(choices(_str.digits, k=16))
        record = {
            'invoiceenoylityId': inv_id,
            'invoice_number':    inv_num,
            'invoice_date':      invoice_date,
            'due_date':          due_date,
            'bill_to': {
                'name':    bt_name,
                'address': bt_addr,
                'bt_phone': bt_phone,
                'email':   bt_mail
            },
            'items':             items,
            'payment_method':    payment_method,
            'subtotal':          subtotal,
            'total':             total,
            'note':             note,
            'bank_Note':        bank_note,
            'created_at':        datetime.utcnow()
        }

        # Add payment details if selected
        if payment_method == 0:
            record['payment_info'] = settings['paypal_details']
        elif payment_method == 1:
            record['payment_info'] = settings['bank_details']

        db.invoiceEnoylityLLC.insert_one(record)

        # 7️⃣ Stream PDF
        buf = io.BytesIO(pdf.output(dest='S').encode('latin1'))
        buf.seek(0)
        return send_file(buf, mimetype='application/pdf', as_attachment=True,
                         download_name=f"invoice_{inv_num}.pdf")

    except KeyError as ke:
        return format_response(False, f"Missing field: {ke}", status=400)
    except Exception:
        logging.exception("Error generating invoice for Enoylity")
        return format_response(False, "Internal server error", status=500)
    

@enoylity_bp.route('/getlist', methods=['POST'])
def list_invoices():
    try:
        # 1️⃣ Parse pagination params
        data = request.get_json() or {}
        page      = max(int(data.get('page', 1)), 1)
        page_size = max(int(data.get('page_size', 10)), 1)
        skip      = (page - 1) * page_size

        # 2️⃣ Build your query (here we list all; you could add filters)
        query = {}

        # 3️⃣ Count total docs
        total = db.invoiceEnoylityLLC.count_documents(query)

        # 4️⃣ Fetch paginated slice, sorted newest first
        cursor = (
            db.invoiceEnoylityLLC
            .find(query)
            .sort('created_at', -1)
            .skip(skip)
            .limit(page_size)
        )

        # 5️⃣ Serialize results
        invoices = []
        for doc in cursor:
            invoices.append({
                'invoiceenoylityId': doc['invoiceenoylityId'],
                'invoice_number':    doc['invoice_number'],
                'invoice_date':      doc['invoice_date'],
                'due_date':          doc['due_date'],
                'bill_to':           doc['bill_to'],
                'items':             doc.get('items', []),
                'payment_method':    doc.get('payment_method', 0),
                'subtotal':          doc.get('subtotal', 0),
                'total':             doc.get('total', 0),
                'created_at':        doc['created_at'].strftime('%Y-%m-%dT%H:%M:%SZ')
            })

        # 6️⃣ Build pagination metadata
        total_pages = (total + page_size - 1) // page_size

        return format_response(
            True,
            "Invoices retrieved",
            {
                'invoices':   invoices,
                'page':       page,
                'page_size':  page_size,
                'total':      total,
                'total_pages': total_pages
            }
        )

    except Exception as e:
        logging.exception("Error listing invoices")
        return format_response(False, "Internal server error"), 500
