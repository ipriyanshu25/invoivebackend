
# chant gt format 

# from flask import Flask, request, send_file, jsonify
# from fpdf import FPDF
# import os
# import time
# from datetime import datetime, timedelta
# import io

# app = Flask(__name__)

# # COLORS
# BLACK      = (0, 0, 0)
# LIGHT_PINK = (255, 240, 245)
# DARK_PINK  = (219, 112, 147)

# # Company info
# COMPANY_INFO = {
#     "name":       "MHD Tech",
#     "address":    "8825 Perimeter Park Blvd Ste 501",
#     "city_state": "Jacksonville, Florida, USA",
#     "phone":      "+15075561971",
#     "youtube":    "youtube.com/@mhd_tech",
#     "email":      "aria@mhdtechpro.com"
# }

# class InvoicePDF(FPDF):
#     def header(self):
#         # Logo top‑right, larger size
#         logo_path = 'logomhd.png'
#         if os.path.isfile(logo_path):
#             self.image(logo_path, x=self.w - self.r_margin - 40, y=10, w=40)
#         # Company info (left)
#         self.set_xy(self.l_margin, 10)
#         self.set_font('Arial', 'B', 18)
#         self.set_text_color(*BLACK)
#         self.cell(0, 10, COMPANY_INFO['name'], ln=1)
#         self.set_font('Arial', '', 11)
#         self.cell(0, 6, COMPANY_INFO['address'], ln=1)
#         self.cell(0, 6, COMPANY_INFO['city_state'], ln=1)
#         self.cell(0, 6, f"Phone: {COMPANY_INFO['phone']}", ln=1)
#         # clickable YouTube URL
#         self.set_text_color(0, 0, 255)
#         self.cell(0, 6, COMPANY_INFO['youtube'], ln=1,
#                   link=f"https://{COMPANY_INFO['youtube']}")
#         # clickable email
#         self.cell(0, 6, COMPANY_INFO['email'], ln=1,
#                   link=f"mailto:{COMPANY_INFO['email']}")
#         self.set_text_color(*BLACK)
#         self.ln(12)

#     def footer(self):
#         self.set_y(-15)
#         self.set_font('Arial', 'I', 8)
#         self.set_text_color(100, 100, 100)
#         self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')


# @app.route('/generate-invoice', methods=['POST'])
# def generate_invoice_endpoint():
#     try:
#         data = request.get_json()
#         bt_name    = data['bill_to_name']
#         bt_addr    = data['bill_to_address']
#         bt_city    = data['bill_to_city']
#         bt_mail    = data['bill_to_email']
#         items      = data.get('items', [])
#         invoice_date = data['invoice_date']      # "DD-MM-YYYY"
#         payment_method = data.get('payment_method', 0)  # 0 = PayPal, 1 = Bank

#         # Invoice counter
#         counter_file = 'invoice_counter.txt'
#         if not os.path.exists(counter_file):
#             with open(counter_file, 'w') as f:
#                 f.write('0')
#         with open(counter_file, 'r+') as f:
#             idx = int(f.read().strip()) + 1
#             f.seek(0)
#             f.write(str(idx))
#             f.truncate()
#         inv_no = f"INV{idx:05d}"

#         # Compute due date = bill date + 6 days
#         bd = datetime.strptime(invoice_date, '%d-%m-%Y')
#         due_date = (bd + timedelta(days=6)).strftime('%d-%m-%Y')

#         # Build PDF in memory
#         pdf = InvoicePDF()
#         pdf.invoice_number = inv_no
#         pdf.invoice_date   = invoice_date
#         pdf.due_date       = due_date
#         pdf.add_page()

#         # ---- Bill To section (light-pink background) ----
#         pdf.set_fill_color(*LIGHT_PINK)
#         pdf.set_text_color(*BLACK)
#         pdf.set_font('Arial', 'B', 12)
#         pdf.cell(0, 8, 'Bill To:', ln=1, fill=True)
#         pdf.set_font('Arial', '', 11)
#         for line in (bt_name, bt_addr, bt_city, bt_mail):
#             pdf.cell(0, 6, line, ln=1, fill=True)
#         pdf.ln(10)

#         # ---- Invoice Details section (light-pink background) ----
#         pdf.set_fill_color(*LIGHT_PINK)
#         pdf.set_text_color(*BLACK)
#         pdf.set_font('Arial', 'B', 12)
#         pdf.cell(0, 8, 'Invoice Details:', ln=1, fill=True)
#         pdf.set_font('Arial', '', 11)
#         pdf.cell(0, 7, f"Invoice #: {inv_no}", ln=1, fill=True)
#         pdf.cell(0, 7, f"Bill Date: {invoice_date}", ln=1, fill=True)
#         pdf.cell(0, 7, f"Due Date:  {due_date}", ln=1, fill=True)
#         pdf.ln(10)

#         # ---- Items table header ----
#         pdf.set_fill_color(*DARK_PINK)
#         pdf.set_text_color(255, 255, 255)
#         pdf.set_font('Arial', 'B', 12)
#         pdf.cell(90, 10, 'DESCRIPTION', 0, 0, 'C', fill=True)
#         pdf.cell(30, 10, 'RATE',        0, 0, 'C', fill=True)
#         pdf.cell(20, 10, 'QTY',         0, 0, 'C', fill=True)
#         pdf.cell(45, 10, 'AMOUNT',      0, 1, 'C', fill=True)

#         # ---- Items rows ----
#         pdf.set_text_color(*BLACK)
#         pdf.set_font('Arial', '', 11)
#         subtotal = 0
#         for it in items:
#             desc = it.get('description', '')
#             rate = it.get('price', 0.0)
#             qty  = it.get('quantity', 1)
#             amt  = rate * qty
#             subtotal += amt

#             pdf.cell(90, 8, desc, 0, 0, 'L')
#             pdf.cell(30, 8, f'${rate:.2f}', 0, 0, 'R')
#             pdf.cell(20, 8, str(qty),       0, 0, 'C')
#             pdf.cell(45, 8, f'${amt:.2f}',  0, 1, 'R')

#         # ---- PayPal fee logic ----
#         if payment_method == 0:
#             fee = subtotal * 0.053
#             total = subtotal + fee
#             pdf.ln(4)
#             pdf.set_font('Arial', '', 11)
#             pdf.cell(140, 8, 'PayPal Fee (5.3%)', 0, 0, 'R')
#             pdf.cell(45, 8, f'${fee:.2f}', 0, 1, 'R')
#         else:
#             total = subtotal

#         pdf.ln(8)
#         # ---- Total ----
#         pdf.set_font('Arial', 'B', 14)
#         pdf.set_text_color(*BLACK)
#         pdf.cell(130, 10, 'TOTAL', 0, 0, 'R')
#         pdf.cell(45, 10, f'USD ${total:.2f}', 0, 1, 'R')
#         pdf.ln(10)

#         # ---- Default note ----
#         pdf.set_font('Arial', 'I', 12)
#         pdf.set_text_color(*BLACK)
#         pdf.multi_cell(0, 6, 'Note: Thank you for your business.', 0, 'L')

#         # Stream PDF to client
#         buffer = io.BytesIO()
#         buffer.write(pdf.output(dest='S').encode('latin1'))
#         buffer.seek(0)
#         return send_file(
#             buffer,
#             mimetype='application/pdf',
#             as_attachment=True,
#             download_name=f"invoice_{inv_no}.pdf"
#         )

#     except KeyError as ke:
#         return jsonify({"error": f"Missing field: {ke}"}), 400
#     except Exception as e:
#         return jsonify({"error": str(e)}), 500


# if __name__ == '__main__':
#     app.run(debug=True)




# clude format 


from flask import Flask, request, send_file, jsonify
from fpdf import FPDF
import os
from datetime import datetime, timedelta
import time

app = Flask(__name__)

class InvoicePDF(FPDF):
    def header(self):
        # Company name at top left with increased font size and different style
        self.set_font('Helvetica', 'B', 22)
        self.set_text_color(0, 0, 0)
        self.cell(100, 10, "MHD TECH", 0, 1, 'L')
        
        # Company address below company name (no background)
        self.set_font('Helvetica', '', 10)
        self.cell(100, 5, "Tualatin, Oregon", 0, 1, 'L')
        self.cell(100, 5, "Washington USA 97062", 0, 1, 'L')
        self.cell(100, 5, "Phone: +15075561971", 0, 1, 'L')
        self.cell(100, 5, "aria@mhdtechpro.com", 0, 1, 'L')
        self.cell(100, 5, "youtube.com/@mhd_tech", 0, 1, 'L')
        
        # MHD logo on the right
        try:
            self.image('logomhd.png', 160, 10, 40)
        except:
            # Logo placeholder in case the file is missing
            self.set_xy(160, 15)
            self.set_font('Helvetica', 'B', 16)
            self.cell(40, 10, 'MHD LOGO', 0, 0, 'C')
        
        self.ln(15)  # Move down after header

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 9)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

# Company information
COMPANY_INFO = {
    "name": "MHD TECH",
    "address": "Tualatin, Oregon",
    "city_state": "Washington USA 97062",
    "phone": "+15075561971",
    "youtube": "youtube.com/@mhd_tech",
    "email": "aria@mhdtechpro.com"
}

@app.route('/generate-invoice', methods=['POST'])
def generate_invoice_endpoint():
    try:
        data = request.get_json()
        
        # Extract data from JSON
        bill_to_name = data.get('bill_to_name')
        bill_to_address = data.get('bill_to_address')
        bill_to_city = data.get('bill_to_city')
        bill_to_email = data.get('bill_to_email')
        items = data.get('items', [])
        payment_method = data.get('payment_method', 0)
        invoice_date = data.get('date', datetime.now().strftime("%d %B %Y"))
        
        # Generate invoice
        filename = generate_invoice(bill_to_name, bill_to_address, bill_to_city, 
                                  bill_to_email, items, payment_method, invoice_date)
        
        return send_file(filename, as_attachment=True)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def generate_invoice(bill_to_name, bill_to_address, bill_to_city, bill_to_email, 
                    items, payment_method, invoice_date):
    pdf = InvoicePDF()
    pdf.add_page()
    
    # Generate invoice number in format INV00XXX
    invoice_count = int(time.time() % 10000)
    invoice_number = f"INV{invoice_count:05d}"
    
    # Add separation line above address section
    pdf.set_draw_color(199, 21, 133)  # Dark pink
    pdf.set_line_width(0.5)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(10)  # Space after the line
    
    # Create entire address section background (light pink)
    address_section_start_y = pdf.get_y()
    
    # Create two columns - left for BILL TO, right for INVOICE DETAILS
    y_pos = pdf.get_y()
    
    # Left column - BILL TO
    pdf.set_font('Helvetica', 'B', 14)
    pdf.cell(95, 12, 'BILL TO', 0, 1, 'L')
    
    pdf.set_font('Helvetica', '', 12)
    bill_to_start_y = pdf.get_y()
    pdf.cell(95, 7, bill_to_name, 0, 1, 'L')
    pdf.cell(95, 7, bill_to_address, 0, 1, 'L')
    pdf.cell(95, 7, bill_to_city, 0, 1, 'L')
    pdf.cell(95, 7, bill_to_email, 0, 1, 'L')
    bill_to_height = pdf.get_y() - bill_to_start_y
    
    # Right column - INVOICE DETAILS
    pdf.set_xy(115, y_pos)
    pdf.set_font('Helvetica', 'B', 14)
    pdf.cell(95, 12, 'INVOICE DETAILS', 0, 1, 'L')
    
    # Invoice details
    pdf.set_font('Helvetica', '', 12)
    if isinstance(invoice_date, str) and '-' in invoice_date:
        invoice_date_obj = datetime.strptime(invoice_date, "%d-%m-%Y")
        invoice_date_formatted = invoice_date_obj.strftime("%d %B %Y")
    else:
        invoice_date_formatted = invoice_date
        invoice_date_obj = datetime.strptime(invoice_date_formatted, "%d %B %Y")
    
    invoice_details_start_y = pdf.get_y()
    pdf.set_x(115)
    pdf.cell(95, 7, f'INVOICE #: {invoice_number}', 0, 1, 'L')
    pdf.set_x(115)
    pdf.cell(95, 7, f'BILL DATE: {invoice_date_formatted}', 0, 1, 'L')
    
    due_date_obj = invoice_date_obj + timedelta(days=6)
    due_date = due_date_obj.strftime("%d %B %Y")
    pdf.set_x(115)
    pdf.cell(95, 7, f'DUE DATE: {due_date}', 0, 1, 'L')
    invoice_details_height = pdf.get_y() - invoice_details_start_y
    
    # Calculate end of address section
    address_section_end_y = max(pdf.get_y(), y_pos + bill_to_height + 12)
    address_section_height = address_section_end_y - address_section_start_y + 10  # Add padding
    
    # Now draw the background for the entire address section
    pdf.set_fill_color(255, 220, 230)  # Light pink background
    pdf.rect(10, address_section_start_y - 5, 190, address_section_height, 'F')
    
    # Redraw the text over the background
    # BILL TO
    pdf.set_xy(10, y_pos)
    pdf.set_font('Helvetica', 'B', 14)
    pdf.cell(95, 12, 'BILL TO', 0, 1, 'L')
    
    pdf.set_font('Helvetica', '', 12)
    pdf.cell(95, 7, bill_to_name, 0, 1, 'L')
    pdf.cell(95, 7, bill_to_address, 0, 1, 'L')
    pdf.cell(95, 7, bill_to_city, 0, 1, 'L')
    pdf.cell(95, 7, bill_to_email, 0, 1, 'L')
    
    # INVOICE DETAILS
    pdf.set_xy(115, y_pos)
    pdf.set_font('Helvetica', 'B', 14)
    pdf.cell(95, 12, 'INVOICE DETAILS', 0, 1, 'L')
    
    pdf.set_font('Helvetica', '', 12)
    pdf.set_x(115)
    pdf.cell(95, 7, f'INVOICE #: {invoice_number}', 0, 1, 'L')
    pdf.set_x(115)
    pdf.cell(95, 7, f'BILL DATE: {invoice_date_formatted}', 0, 1, 'L')
    pdf.set_x(115)
    pdf.cell(95, 7, f'DUE DATE: {due_date}', 0, 1, 'L')
    
    # Move to below the address section
    pdf.set_y(address_section_end_y + 15)
    
    # Darker pink separator line
    pdf.set_draw_color(199, 21, 133)
    pdf.set_line_width(0.5)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(15)
    
    # Items table header with darker pink background
    pdf.set_font('Helvetica', 'B', 12)
    pdf.set_fill_color(199, 21, 133)  # Darker pink
    pdf.set_text_color(255, 255, 255)  # White text
    pdf.cell(80, 12, 'DESCRIPTION', 0, 0, 'C', True)
    pdf.cell(40, 12, 'PRICE', 0, 0, 'C', True)
    pdf.cell(30, 12, 'QTY', 0, 0, 'C', True)
    pdf.cell(40, 12, 'TOTAL', 0, 1, 'C', True)
    
    # Items table content
    pdf.set_font('Helvetica', '', 11)
    pdf.set_text_color(0, 0, 0)  # Black text
    subtotal = 0
    
    for i, item in enumerate(items):
        desc = item.get('description', '')
        qty = item.get('quantity', 1)
        price = item.get('price', 0)
        total = qty * price
        subtotal += total
        
        pdf.cell(80, 12, desc, 0, 0, 'L')
        pdf.cell(40, 12, f'${price:.2f}', 0, 0, 'C')
        pdf.cell(30, 12, str(qty), 0, 0, 'C')
        pdf.cell(40, 12, f'${total:.2f}', 0, 1, 'C')
    
    # Calculate PayPal fees if applicable
    if payment_method == 0:  # PayPal
        paypal_fee = subtotal * 0.053
        pdf.cell(80, 12, 'PayPal fees', 0, 0, 'L')
        pdf.cell(40, 12, f'${paypal_fee:.2f}', 0, 0, 'C')
        pdf.cell(30, 12, '1', 0, 0, 'C')
        pdf.cell(40, 12, f'${paypal_fee:.2f}', 0, 1, 'C')
        total_payment = subtotal + paypal_fee
    else:  # Bank transfer
        total_payment = subtotal
    
    pdf.ln(5)
    
    # Simple total row without background color
    pdf.set_font('Helvetica', 'B', 12)
    pdf.set_text_color(0, 0, 0)  # Black text
    pdf.cell(150, 12, 'TOTAL', 0, 0, 'R')
    pdf.cell(40, 12, f'USD ${total_payment:.2f}', 0, 1, 'R')
    
    pdf.ln(25)
    
    # Simple note at the end
    pdf.set_font('Helvetica', 'I', 11)
    pdf.cell(0, 10, 'Note: 50% payment required upfront. Please process payment by the due date.', 0, 1, 'L')
    
    # Save the PDF
    filename = f'invoice_{invoice_number}.pdf'
    pdf.output(filename, 'F')
    
    return filename

if __name__ == '__main__':
    app.run(debug=True)