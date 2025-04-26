from flask import Flask, request, jsonify, send_file, Blueprint
import datetime
import calendar
import re
import requests
import os
from dateutil.relativedelta import relativedelta
import io
from num2words import num2words
from utils import format_response

# Import standard FPDF without extensions
from fpdf import FPDF

# Import the settings utility function
from settings import get_current_salary_settings

salary_bp = Blueprint("salaryslip", __name__, url_prefix="/salary")

class ImprovedSalarySlipPDF(FPDF):
    """An improved PDF class for better-looking salary slips"""
    def __init__(self, company_info=None):
        # Use portrait mode (P), mm as units, A4 format
        super().__init__(orientation='P', unit='mm', format='A4')
        
        # Store company info
        self.company_info = company_info or {}
        
        # ─── Register Lexend fonts ───────────────────────────────────────────────
        # Make sure you have placed Lexend-Regular.ttf and Lexend-Bold.ttf under static/fonts/
        self.add_font('Lexend', '', os.path.join('static', 'Lexend-Regular.ttf'), uni=True)
        self.add_font('Lexend', 'B', os.path.join('static', 'Lexend-Bold.ttf'), uni=True)
        # Set Lexend as the default throughout
        self.set_font('Lexend', '', 11)
        self.set_auto_page_break(auto=True, margin=15)
        
        # Define colors
        self.primary_color = (96, 95, 198)      # Dark blue for main headings
        self.secondary_color = (70, 130, 180)  # Steel blue for subheadings
        
        # Page margins
        self.left_margin = 15
        self.right_margin = 15
        self.set_margins(self.left_margin, 10, self.right_margin)
        self.logo_path = None
        logo_url = 'https://www.enoylitystudio.com/wp-content/uploads/2024/02/enoylity-final-logo.png'
        local_logo = 'enoylity-final-logo.png'
        if not os.path.isfile(local_logo):
            try:
                resp = requests.get(logo_url, timeout=5)
                resp.raise_for_status()
                with open(local_logo, 'wb') as f:
                    f.write(resp.content)
            except Exception:
                # if fetch fails, we'll just skip the logo
                pass
        if os.path.isfile(local_logo):
            self.logo_path = local_logo

    def header(self):
        # Company name from settings - Use company_title if available, otherwise fallback
        company_title = self.company_info.get('company_title', 'ENOYLITY MEDIA CREATIONS')
        
        self.set_font('Lexend', 'B', 18)
        self.set_text_color(*self.primary_color)
        self.cell(110, 10, company_title, 0, 0, 'L')

        # Logo (if we have one) at top‑right
        if self.logo_path:
            logo_w = 40  # mm width
            x_pos = self.w - self.right_margin - logo_w
            self.image(self.logo_path, x=x_pos, y=10, w=logo_w)

        # Rest of your header (line, address, etc.) - using settings data
        self.ln(15)
        self.set_draw_color(*self.primary_color)
        self.set_line_width(0.5)
        self.line(self.left_margin, self.get_y(), self.w - self.right_margin, self.get_y())
        self.ln(3)
        
        # Get company details from settings
        company_name = self.company_info.get('company_name', 'Enoylity Media Creations Private Limited')
        address_line1 = self.company_info.get('address_line1', 'Ekam Enclave II, 301A, Ramai Nagar, near Kapil Nagar Square')
        address_line2 = self.company_info.get('address_line2', 'Nari Road, Nagpur, Maharashtra, India 440026')
        
        self.set_font('Lexend', 'B', 11)
        self.set_text_color(*self.secondary_color)
        self.cell(180, 5, company_name, 0, 1, 'L')
        self.ln(1)
        self.set_font('Lexend', '', 9)
        self.set_text_color(*self.secondary_color)
        self.cell(180, 5, address_line1, 0, 1, 'L')
        self.cell(180, 5, address_line2, 0, 1, 'L')
        self.ln(2)

    def footer(self):
        self.set_y(-15)
        self.set_font('Lexend', '', 8)
        self.set_text_color(100, 100, 100)  # Grey color for footer
        self.cell(0, 10, '-- This is a system-generated document. --', 0, 0, 'C')

    # Updated safe_float method that handles various input types
    def safe_float(self, value):
        """Safely convert a string or number to float"""
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            # Remove currency prefix and any commas before converting
            cleaned_value = value.replace('Rs. ', '').replace(',', '')
            try:
                return float(cleaned_value)
            except ValueError:
                return 0.0
        return 0.0  # Default return for other cases

    def create_salary_slip(self, data):
        self.add_page()
        
        # Title with primary color
        self.set_font('Lexend', 'B', 12)
        self.set_text_color(*self.primary_color)
        self.cell(180, 10, f"Payslip for the month of {data['pay_period']}", 0, 1, 'L')
        
        # Add a line below the title
        self.set_draw_color(*self.secondary_color)
        self.set_line_width(0.3)
        self.line(self.left_margin, self.get_y(), self.w - self.right_margin, self.get_y())
        
        # Space after line
        self.ln(4)
        
        # Employee details section with better formatting
        self.set_text_color(0, 0, 0)
        employee = data['employee_details']
        
        # Column widths for better layout
        left_col_width = 33
        data_col_width = 52
        
        # Create 2 column layout with improved visual hierarchy
        self.set_font('Lexend', 'B', 9)
        self.set_text_color(*self.secondary_color)
        self.cell(left_col_width, 6, 'Employee Name:', 0, 0)
        self.set_font('Lexend', '', 9)
        self.set_text_color(0, 0, 0)
        self.cell(data_col_width, 6, employee['full_name'], 0, 0)
        
        self.set_font('Lexend', 'B', 9)
        self.set_text_color(*self.secondary_color)
        self.cell(left_col_width, 6, 'Employee No:', 0, 0)
        self.set_font('Lexend', '', 9)
        self.set_text_color(0, 0, 0)
        self.cell(data_col_width, 6, str(employee['emp_no']), 0, 1)
        
        self.set_font('Lexend', 'B', 9)
        self.set_text_color(*self.secondary_color)
        self.cell(left_col_width, 6, 'Designation:', 0, 0)
        self.set_font('Lexend', '', 9)
        self.set_text_color(0, 0, 0)
        self.cell(data_col_width, 6, employee['designation'], 0, 0)
        
        self.set_font('Lexend', 'B', 9)
        self.set_text_color(*self.secondary_color)
        self.cell(left_col_width, 6, 'Department:', 0, 0)
        self.set_font('Lexend', '', 9)
        self.set_text_color(0, 0, 0)
        self.cell(data_col_width, 6, employee['department'], 0, 1)
        
        self.set_font('Lexend', 'B', 9)
        self.set_text_color(*self.secondary_color)
        self.cell(left_col_width, 6, 'Date of Joining:', 0, 0)
        self.set_font('Lexend', '', 9)
        self.set_text_color(0, 0, 0)
        self.cell(data_col_width, 6, employee['doj'], 0, 0)
        
        self.set_font('Lexend', 'B', 9)
        self.set_text_color(*self.secondary_color)
        self.cell(left_col_width, 6, 'Bank Account:', 0, 0)
        self.set_font('Lexend', '', 9)
        self.set_text_color(0, 0, 0)
        self.cell(data_col_width, 6, str(employee['bank_account']), 0, 1)
        
        self.set_font('Lexend', 'B', 9)
        self.set_text_color(*self.secondary_color)
        self.cell(left_col_width, 6, 'Paid Days', 0, 0)
        self.set_font('Lexend', '', 9)
        self.set_text_color(0, 0, 0)
        self.cell(data_col_width, 6, str(employee['working_days']), 0, 0)
        
        self.set_font('Lexend', 'B', 9)
        self.set_text_color(*self.secondary_color)
        self.cell(left_col_width, 6, 'PAN:', 0, 0)
        self.set_font('Lexend', '', 9)
        self.set_text_color(0, 0, 0)
        self.cell(data_col_width, 6, str(employee['pan']), 0, 1)
        
        # Add space after employee details
        self.set_x(self.left_margin)
        self.set_font('Lexend', 'B', 9)
        self.set_text_color(*self.secondary_color)
        self.cell(left_col_width, 6, 'LOP Days:', 0, 0)
        self.set_font('Lexend', '', 9)
        self.set_text_color(0, 0, 0)
        self.cell(data_col_width, 6, str(employee['lop']), 0, 0)
        

        self.set_font('Lexend', 'B', 9)
        self.set_text_color(*self.secondary_color)
        self.cell(left_col_width, 6, 'Monthly Salary:', 0, 0)
        self.set_font('Lexend', '', 9)
        self.set_text_color(0, 0, 0)
        self.cell(data_col_width, 6, str(employee['month_salary']), 0, 1)

        self.ln(5)
        
        # Calculate usable width for the table
        table_width = self.w - self.left_margin - self.right_margin - 4  # -4 for 2mm margin on each side
        
        # Pay summary header with primary color
        self.set_font('Lexend', 'B', 12)
        self.set_text_color(*self.primary_color)
        self.cell(0, 10, 'EMPLOYEE PAY SUMMARY', 0, 1, 'C')
        
        # Add 2mm margin on both sides
        self.set_x(self.left_margin + 2)
        
        # Table header
        self.set_font('Lexend', 'B', 10)
        self.set_text_color(255, 255, 255)
        self.set_fill_color(*self.primary_color)
        
        # Define more balanced column widths
        col1 = table_width * 0.4  # Earnings (40%)
        col2 = table_width * 0.15  # Amount (15%)
        col3 = table_width * 0.3  # Deductions (30%)
        col4 = table_width * 0.15  # Amount (15%)
        
        # First row headers
        self.cell(col1, 8, 'EARNINGS', 1, 0, 'C', True)
        self.cell(col2, 8, 'AMOUNT', 1, 0, 'C', True)
        self.cell(col3, 8, 'DEDUCTIONS', 1, 0, 'C', True)
        self.cell(col4, 8, 'AMOUNT', 1, 1, 'C', True)
        
        # Earnings and deductions data with alternating background for better readability
        self.set_text_color(0, 0, 0)
        self.set_font('Lexend', '', 9)
        
        # Calculate max rows needed between earnings and deductions
        earnings = data['salary_details']['earnings']
        
        # Filter out Professional Tax from deductions
        deductions = [item for item in data['salary_details'].get('deductions', []) 
                    if item['name'] != 'Professional Tax']
        
        max_rows = max(len(earnings), len(deductions))
        
        # Add rows with alternating background
        for i in range(max_rows):
            # Add light background for even rows
            if i % 2 == 0:
                fill = True
                self.set_fill_color(240, 240, 250)  # Very light blue
            else:
                fill = False
            
            # Set X position for consistent margins
            self.set_x(self.left_margin + 2)
            
            # Earnings columns
            if i < len(earnings):
                item = earnings[i]
                self.cell(col1, 7, item['name'], 'LR', 0, fill=fill)
                self.cell(col2, 7, item['amount'], 'LR', 0, 'R', fill=fill)
            else:
                self.cell(col1, 7, '', 'LR', 0, fill=fill)
                self.cell(col2, 7, '', 'LR', 0, fill=fill)
            
            # Deductions columns
            if i < len(deductions):
                item = deductions[i]
                self.cell(col3, 7, item['name'], 'LR', 0, fill=fill)
                self.cell(col4, 7, item['amount'], 'LR', 0, 'R', fill=fill)
            else:
                self.cell(col3, 7, '', 'LR', 0, fill=fill)
                self.cell(col4, 7, '', 'LR', 0, fill=fill)
            
            self.ln()
        
        # Recalculate total deductions without Professional Tax - FIXED to handle float values
        total_deductions_amount = sum(self.safe_float(item['amount']) for item in deductions)
        
        # Total row with highlighting
        self.set_x(self.left_margin + 2)
        self.set_font('Lexend', 'B', 10)
        self.set_fill_color(220, 230, 240)  # Light blue background
        self.cell(col1, 8, 'Gross Earnings', 1, 0, fill=True)
        self.cell(col2, 8, data['salary_details']['gross_earnings'], 1, 0, 'R', fill=True)
        self.cell(col3, 8, 'Total Deductions', 1, 0, fill=True)
        self.cell(col4, 8, f"Rs. {total_deductions_amount:.2f}", 1, 1, 'R', fill=True)
        
        # Recalculate net payable - FIXED to handle float values
        gross_earnings = self.safe_float(data['salary_details']['gross_earnings'])
        net_payable = gross_earnings - total_deductions_amount
        annual_net_payable = net_payable * 12
        
        # Net payable with better highlighting
        self.ln(3)
        
        # Net Monthly Salary
        self.set_font('Lexend', 'B', 11)
        self.set_text_color(*self.primary_color)
        self.cell(120, 8, 'Net Monthly Salary', 0, 0)
        self.cell(60, 8, f"Rs. {net_payable:.2f}", 0, 1, 'R')
        
        # Amount in words
        self.set_font('Lexend', '', 9)
        self.set_text_color(60, 60, 60)  # Dark grey
        
        # Integer rupees and optional paise
        rupees = int(net_payable)
        paise = round((net_payable - rupees) * 100)

        # Build the words
        if paise:
            rupee_words = num2words(rupees, lang='en_IN')
            paise_words = num2words(paise, lang='en_IN')
            amount_words = f"{rupee_words} Rupees and {paise_words} Paise"
        else:
            amount_words = f"{num2words(rupees, lang='en_IN')} Rupees"

        # Title‑case and wrap
        amount_in_words = f"({amount_words.title()} Only)"
        self.cell(0, 7, amount_in_words, 0, 1)
        
        # Add tax notes if applicable
        if data.get('tax_notes'):
            self.ln(3)
            self.set_font('Lexend', '', 8)
            self.set_text_color(80, 80, 80)
            for note in data['tax_notes']:
                self.cell(0, 5, note, 0, 1)


class SalarySlipGenerator:
    def __init__(self, employee_data, current_date=None):
        self.employee_data = employee_data
        self.salary_details = {}
        self.tax_details = {}
        
        # Fetch company settings from database
        self.company_settings = get_current_salary_settings()
        
        # Set current date
        if current_date:
            self.current_date = datetime.datetime.strptime(current_date, '%d-%m-%Y')
        else:
            self.current_date = datetime.datetime.now()
        
        self.employee_data['current_month'] = self.current_date.month
        self.employee_data['current_year'] = self.current_date.year
        
        # Calculate total days in the month
        days_in_month = calendar.monthrange(self.employee_data['current_year'], 
                                           self.employee_data['current_month'])[1]
        self.employee_data['total_days'] = days_in_month
        self.employee_data['working_days'] = days_in_month - self.employee_data.get('lop', 0)
    
    def validate_email(self, email):
        """Validate email format"""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    
    def validate_date(self, date_str):
        """Validate date format (DD-MM-YYYY)"""
        try:
            datetime.datetime.strptime(date_str, '%d-%m-%Y')
            return True
        except ValueError:
            return False
    
    def calculate_tax(self):
        """Calculate income tax based on annual salary"""
        # Calculate annual income from salary structure
        annual_income = self.annual_salary
        
        # Standard deduction and taxable income calculation
        standard_deduction = 75000
        taxable_income = annual_income - standard_deduction
        tax = 0

        # Compute tax only if taxable income exceeds ₹4,00,000
        if taxable_income > 400000:
            remaining_income = taxable_income - 400000

            # Slab 1: ₹4,00,001 to ₹8,00,000 @ 5%
            slab = min(remaining_income, 400000)
            tax += slab * 0.05
            remaining_income -= slab

            # Slab 2: ₹8,00,001 to ₹12,00,000 @ 10%
            if remaining_income > 0:
                slab = min(remaining_income, 400000)
                tax += slab * 0.10
                remaining_income -= slab

            # Slab 3: ₹12,00,001 to ₹16,00,000 @ 15%
            if remaining_income > 0:
                slab = min(remaining_income, 400000)
                tax += slab * 0.15
                remaining_income -= slab

            # Slab 4: ₹16,00,001 to ₹20,00,000 @ 20%
            if remaining_income > 0:
                slab = min(remaining_income, 400000)
                tax += slab * 0.20
                remaining_income -= slab

            # Slab 5: ₹20,00,001 to ₹24,00,000 @ 25%
            if remaining_income > 0:
                slab = min(remaining_income, 400000)
                tax += slab * 0.25
                remaining_income -= slab

            # Slab 6: Above ₹24,00,000 @ 30%
            if remaining_income > 0:
                tax += remaining_income * 0.30

        # Apply rebate: No tax if annual income is up to ₹12.75 lakh
        if annual_income <= 1275000:
            tax = 0

        # Compute initial cess at 4% of the computed tax
        cess = tax * 0.04
        total_tax = tax + cess

        # Apply marginal relief for annual incomes between ₹12.75 lakh and ₹15 lakh.
        if 1275000 < annual_income <= 1500000:
            income_above_limit = annual_income - 1275000
            if total_tax > income_above_limit:
                total_tax = income_above_limit

        # Store the tax details
        self.tax_details['taxable_income'] = taxable_income
        self.tax_details['tax_before_cess'] = tax
        self.tax_details['cess'] = cess
        self.tax_details['annual_tax'] = total_tax
        self.tax_details['monthly_tax'] = total_tax / 12
        self.tax_details['rebate_applied'] = annual_income <= 1275000
        self.tax_details['marginal_relief_applicable'] = 1275000 < annual_income <= 1500000
        
    
    def calculate_salary(self):
        """Calculate salary after LOP deductions and then compute gross salary correctly."""
        # 1) Pull in structure and dates
        salary_structure = self.employee_data['salary_structure']
        total_days = self.employee_data['total_days']
        lop_days = self.employee_data.get('lop', 0)  # can be 1, 0.5, etc.

        # 2) Define allowed components
        allowed_components = {'Basic Pay', 'House Rent Allowance', 'Performance Bonus', 'Overtime Bonus', 'Special Allowance'}

        # 3) Prepare adjusted earnings list
        earnings = []
        adjusted_special_allowance = 0.0

        for item in salary_structure:
            name = item['name']
            if name not in allowed_components:
                continue  # Skip other components

            amount = item['amount']

            if name == 'Special Allowance':
                # Calculate LOP deduction only on Special Allowance
                per_day = amount / total_days
                lop_deduction = per_day * lop_days
                amount = max(0.0, amount - lop_deduction)
                adjusted_special_allowance = amount  # Save adjusted Special Allowance

            earnings.append({
                'name': name,
                'amount': f"Rs. {amount:.2f}"
            })

        # 4) Now, calculate gross_monthly after LOP adjustment
        gross_monthly = sum(float(item['amount'].replace('Rs. ', '')) for item in earnings)

        # 5) For tax purposes, annual income is based on **full gross without LOP deduction**
        full_gross_monthly = sum(
            item['amount'] for item in salary_structure
            if item['name'] in allowed_components
        )
        self.annual_salary = full_gross_monthly * 12

        # 6) Run existing tax logic
        tax_notes = self.calculate_tax()  # populates self.tax_details
        monthly_tax = self.tax_details['monthly_tax']

        # 7) Prepare deductions (only Income Tax/TDS here)
        deductions = []
        if monthly_tax > 0:
            deductions.append({
                'name': 'Income Tax (TDS)',
                'amount': f"Rs. {monthly_tax:.2f}"
            })

        # 8) Totals: TDS only (LOP already deducted inside earnings/gross)
        total_deductions_amount = monthly_tax
        net_payable = gross_monthly - total_deductions_amount
        annual_net_payable = net_payable * 12

        # 9) Store everything for PDF rendering
        self.salary_details = {
            'earnings': earnings,
            'deductions': deductions,
            'gross_earnings': f"Rs. {gross_monthly:.2f}",
            'total_deductions': f"Rs. {total_deductions_amount:.2f}",
            'net_payable': f"Rs. {net_payable:.2f}",
            'annual_income': f"Rs. {self.annual_salary:.2f}",
            'annual_net_payable': f"Rs. {annual_net_payable:.2f}",
            'amount_in_words': f"{num2words(int(net_payable), lang='en_IN').title()} Only"
        }

        return tax_notes


    
    def calculate_experience(self):
        """Calculate experience based on date of joining"""
        doj = datetime.datetime.strptime(self.employee_data['doj'], '%d-%m-%Y')
        current_date = self.current_date
        
        experience = relativedelta(current_date, doj)
        return experience
    
    def generate_salary_data(self):
        """Generate salary data in dictionary format"""
        tax_notes = self.calculate_salary()
        experience = self.calculate_experience()
        
        # Format current date for the slip
        slip_date = self.current_date.strftime('%d-%m-%Y')
        month_name = self.current_date.strftime('%B')
        
        # Use company name from settings if available
        company_name = self.company_settings.get('company_name', 'Enoylity Media Creations')
        
        # Prepare result dictionary
        result = {
            "employee_details": {
                "full_name": self.employee_data['full_name'],
                "designation": self.employee_data.get('designation', 'Employee'),
                "doj": self.employee_data['doj'],
                "emp_no": self.employee_data.get('emp_no', ''),
                "department": self.employee_data.get('department', ''),
                "bank_account": self.employee_data.get('bank_account', ''),
                "pan": self.employee_data.get('pan', ''),
                "working_days": self.employee_data['working_days'],
                "lop": self.employee_data.get('lop', 0),
                "month_salary": self.employee_data.get('monthly_salary')
            },
            "salary_details": self.salary_details,
            "tax_details": self.tax_details,
            "pay_period": f"{month_name} {self.employee_data['current_year']}",
            "generated_on": slip_date,
            "company_name": company_name,
            "tax_notes": tax_notes
        }
        
        return result
    
    def generate_pdf(self):
        """Generate PDF salary slip"""
        salary_data = self.generate_salary_data()
        
        # Use our improved PDF class with company settings
        pdf = ImprovedSalarySlipPDF(company_info=self.company_settings)
        pdf.create_salary_slip(salary_data)
        
        # Save PDF to a bytes buffer
        pdf_buffer = io.BytesIO()
        pdf_bytes = pdf.output(dest='S').encode('latin-1')  # 'S' means return as string
        pdf_buffer.write(pdf_bytes)
        pdf_buffer.seek(0)
        
        return pdf_buffer


# Routes remain the same...
@salary_bp.route('/upload-logo', methods=['POST'])
def upload_logo():
    try:
        if 'logo' not in request.files:
            return format_response(False, "No logo file provided", status=400)

        logo_file = request.files['logo']
        if logo_file.filename == '':
            return format_response(False, "No logo file selected", status=400)

        # Save the logo file
        logo_file.save('company_logo.png')
        return format_response(True, "Logo uploaded successfully")

    except Exception as e:
        return format_response(False, "Internal server error", status=500)


@salary_bp.route('/generate-salary-slip', methods=['POST'])
def generate_salary_slip():
    try:
        payload = request.get_json() or {}
        employee_data = payload.get('employee_data')

        if not employee_data:
            return format_response(False, "Missing 'employee_data' in request", status=400)

        # Required fields
        for field in ('full_name', 'doj', 'salary_structure'):
            if field not in employee_data:
                return format_response(False, f"Missing required field: {field}", status=400)

        # Salary structure must be a non-empty list
        if not isinstance(employee_data['salary_structure'], list) or not employee_data['salary_structure']:
            return format_response(False, "Salary structure must be a non-empty list", status=400)

        # Default LOP to 0 if absent
        employee_data.setdefault('lop', 0)

        # Instantiate generator (will set up dates & working days)
        generator = SalarySlipGenerator(
            employee_data,
            current_date=payload.get('current_date')
        )

        # Validate date format for DOJ
        if not generator.validate_date(employee_data['doj']):
            return format_response(False, "Invalid date format for doj. Use DD-MM-YYYY", status=400)

        # Generate PDF buffer
        pdf_buffer = generator.generate_pdf()

        # Stream PDF to client
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"salary_slip_{employee_data['full_name'].replace(' ', '_')}.pdf"
        )

    except Exception:
        return format_response(False, "Internal server error", status=500)