from flask import Blueprint, request, send_file
import io
import os
import logging
from datetime import datetime
from fpdf import FPDF
from pymongo import ReturnDocument
import math
from utils import format_response
from db import db
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
        self.add_font('Lexend', '', settings['fonts']['regular'], uni=True)
        self.add_font('Lexend', 'B', settings['fonts']['bold'], uni=True)
        self.set_font('Lexend', '', 11)

    def header(self):
        s = self.settings
        if os.path.isfile(s['logo_path']):
            self.image(s['logo_path'], x=self.l_margin, y=10, w=40)
        ci = s['company_info']
        self.set_xy(self.l_margin, 10)
        self.set_font('Lexend','B',18)
        self.set_text_color(*s['colors']['black'])
        self.cell(0,10,ci['name'],ln=1,align='R')
        self.set_font('Lexend','',11)
        for line in (ci['address'], ci['city_state'], f"Phone: {ci['phone']}", ci.get('youtube',''), ci['email']):
            self.cell(0,6,line,ln=1,align='R')
        self.ln(12)

    def footer(self):
        self.set_y(-15)
        self.set_font('Lexend','',8)
        self.multi_cell(0,5,f"Page {self.page_no()}",align='C')

@enoylity_bp.route('/generate-invoice', methods=['POST'])
def generate_invoice_endpoint():
    try:
        raw = db.settings_invoice.find_one({"invoice_type": INVOICE_TYPE}) or {}
        editable = raw.get('editable_fields', {})
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        for k,v in editable.items():
            if isinstance(v, dict) and k in settings:
                settings[k].update(v)
            else:
                settings[k] = v

        data = request.get_json() or {}
        phone = data.get('bill_to_phone')
        if phone and (not phone.isdigit() or len(phone)!=10):
            return format_response(False,"Phone number must be exactly 10 digits if provided",status=400)
        for field,msg in {"bill_to_name":"Billing name is required","bill_to_address":"Billing address is required","invoice_date":"Invoice date is required","due_date":"Due date is required"}.items():
            if not data.get(field): return format_response(False,msg,status=400)

        bt_name=data['bill_to_name']; bt_addr=data['bill_to_address']; bt_phone=data.get('bill_to_phone',''); bt_mail=data.get('bill_to_email','')
        note=data.get('note',''); bank_note=data.get('bank_Note',''); items=data.get('items',[])
        payment_method=int(data.get('payment_method',0)); invoice_date=data['invoice_date']; due_date=data['due_date']
        inv_num=get_next_invoice_number()
        try:
            datetime.strptime(invoice_date,'%d-%m-%Y'); datetime.strptime(due_date,'%d-%m-%Y')
        except ValueError:
            return format_response(False,"Dates must be DD-MM-YYYY",status=400)

        pdf=InvoicePDF(settings); pdf.invoice_number=inv_num; pdf.invoice_date=invoice_date; pdf.due_date=due_date; pdf.add_page()

        lines = [bt_name, bt_addr, bt_phone, bt_mail]
        x, y = pdf.l_margin, pdf.get_y()
        width = pdf.w - pdf.l_margin - pdf.r_margin
        indent, padding = 4, 7
        header_h, line_h = 7, 7
        block_h = header_h + len(lines)*line_h + padding*2

        # Draw the background rectangle
        pdf.set_fill_color(*settings['colors']['light_pink'])
        pdf.rect(x, y, width, block_h, 'F')

        # Set position for "Bill To:" header
        pdf.set_xy(x+indent, y+indent)
        pdf.set_font('Lexend', 'B', 12)
        pdf.set_text_color(*settings['colors']['black'])
        pdf.multi_cell(width-2*indent, header_h, 'Bill To:')

        # Set font for the address lines
        pdf.set_font('Lexend', '', 11)

        # Add each line of the address with word wrap
        for ln in lines:
            pdf.set_x(x+indent)
            pdf.multi_cell(width-2*indent, line_h, ln)

        pdf.ln(padding)
        pdf.ln(5)

        # Invoice Details
        details=[f"Invoice #: {inv_num}",f"Bill Date: {invoice_date}",f"Due Date: {due_date}"]
        y2=pdf.get_y(); pdf.set_fill_color(*settings['colors']['light_pink']); pdf.rect(x,y2,width,8+len(details)*6+3,'F')
        pdf.set_xy(x+3,y2+3); pdf.set_font('Lexend','B',12); pdf.cell(0,8,'Invoice Details:',ln=1)
        pdf.set_font('Lexend','',10)
        for d in details: pdf.set_x(x+3); pdf.cell(0,6,d,ln=1)
        pdf.ln(7)
        
        # Items
        pdf.set_fill_color(*settings['colors']['dark_pink']); pdf.set_text_color(255,255,255); pdf.set_font('Lexend','B',12)
        pdf.cell(90,10,'DESCRIPTION',0,0,'C',True); pdf.cell(30,10,'RATE',0,0,'C',True); pdf.cell(20,10,'QTY',0,0,'C',True); pdf.cell(45,10,'AMOUNT',0,1,'C',True)
        pdf.set_text_color(*settings['colors']['black']); pdf.set_font('Lexend','',11)
        subtotal=0
        for it in items:
            desc=it.get('description',''); rate=float(it.get('price',0)); qty=int(it.get('quantity',1)); amt=rate*qty; subtotal+=amt
            pdf.cell(90,8,desc,0,0,'L'); pdf.cell(30,8,f'${rate:.2f}',0,0,'C'); pdf.cell(20,8,str(qty),0,0,'C'); pdf.cell(45,8,f'${amt:.2f}',0,1,'C')
        # Fees & Total
        if payment_method==0: fee=subtotal*0.056; total=subtotal+fee; pdf.ln(4); pdf.set_font('Lexend','',13); pdf.cell(140,8,'PayPal Fee',0,0,'R'); pdf.cell(45,8,f'$ {fee:.2f}',0,1,'C')
        else: total=subtotal
        pdf.ln(6); pdf.set_font('Lexend','B',14); pdf.cell(135,8,'TOTAL ',0,0,'R'); pdf.cell(39,8,f'USD $ {total:.2f}',0,1,'C')
        # Payment Info & Note
        pdf.ln(10); x=pdf.l_margin; y=pdf.get_y(); width=pdf.w-pdf.l_margin-pdf.r_margin; leftw=width/2-5; rightw=leftw
        if payment_method==0:
            pdf.set_xy(x,y); pdf.set_font('Lexend','B',12); pdf.cell(leftw,6,'PayPal Details:',ln=1)
            pdf.set_font('Lexend','',11); pp=settings['paypal_details']; pdf.cell(leftw,6,f"Receiver: {pp['receiver_email']}",ln=1); pdf.cell(leftw,6,f"PayPal Name: {pp['paypal_name']}",ln=1)
            if note:
                nx,ny=x+leftw+10,y; pdf.set_xy(nx,ny); pdf.set_font('Lexend','B',12); pdf.multi_cell(rightw,6,'Note:',align='L')
                pdf.set_font('Lexend','',11); pdf.set_xy(nx,pdf.get_y()); pdf.multi_cell(rightw,6,note,align='L')
        elif payment_method==1:
            pdf.set_xy(x,y); pdf.set_font('Lexend','B',12); pdf.cell(leftw,6,'Bank Details:',ln=1)
            pdf.set_font('Lexend','',11); bk=settings['bank_details']
            for line in (f"Account Name: {bk['account_name']}",f"Account No:   {bk['account_number']}",f"Routing No:   {bk['routing_number']}",f"Bank:         {bk['bank_name']}",f"Address:      {bk['bank_address']}"): pdf.multi_cell(leftw,6,line)
            if bank_note:
                pdf.ln(2); pdf.set_font('Lexend','B',12); pdf.multi_cell(leftw,6,'Bank Note:'); pdf.set_font('Lexend','',11); pdf.multi_cell(leftw,6,bank_note)
            if note:
                nx,ny=x+leftw+10,y; pdf.set_xy(nx,ny); pdf.set_font('Lexend','B',12); pdf.multi_cell(rightw,6,'Note:',align='L')
                pdf.set_font('Lexend','',11); pdf.set_xy(nx,pdf.get_y()); pdf.multi_cell(rightw,6,note,align='L')
        else:
            if note:
                pdf.set_font('Lexend','B',12); pdf.cell(0,6,'Note:',ln=1); pdf.set_font('Lexend','',11); pdf.multi_cell(0,6,note)
        # Persist
        inv_id=''.join(choices(_str.digits,k=16)); record={
            'invoiceenoylityId':inv_id,'invoice_number':inv_num,'invoice_date':invoice_date,'due_date':due_date,
            'bill_to':{'name':bt_name,'address':bt_addr,'bt_phone':bt_phone,'email':bt_mail},'items':items,
            'payment_method':payment_method,'subtotal':subtotal,'total':total,'note':note,'bank_Note':bank_note,'created_at':datetime.utcnow()
        }
        if payment_method==0: record['payment_info']=settings['paypal_details']
        elif payment_method==1: record['payment_info']=settings['bank_details']
        db.invoiceEnoylityLLC.insert_one(record)
        buf=io.BytesIO(pdf.output(dest='S').encode('latin1')); buf.seek(0)
        return send_file(buf,mimetype='application/pdf',as_attachment=True,download_name=f"invoice_{inv_num}.pdf")
    except KeyError as ke:
        return format_response(False,f"Missing field: {ke}",status=400)
    except Exception:
        logging.exception("Error generating invoice for Enoylity")
        return format_response(False,"Internal server error",status=500)
    

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