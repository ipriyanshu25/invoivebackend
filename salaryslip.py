# from flask import Flask, request, jsonify
# import datetime
# import calendar
# import re
# from dateutil.relativedelta import relativedelta

# app = Flask(__name__)

# class SalarySlipGenerator:
#     def __init__(self, employee_data, current_date=None):
#         self.employee_data = employee_data
#         self.salary_details = {}
#         self.tax_details = {}
        
#         # Set current date
#         if current_date:
#             self.current_date = datetime.datetime.strptime(current_date, '%d-%m-%Y')
#         else:
#             self.current_date = datetime.datetime.now()
        
#         self.employee_data['current_month'] = self.current_date.month
#         self.employee_data['current_year'] = self.current_date.year
        
#         # Calculate total days in the month
#         days_in_month = calendar.monthrange(self.employee_data['current_year'], 
#                                            self.employee_data['current_month'])[1]
#         self.employee_data['total_days'] = days_in_month
#         self.employee_data['working_days'] = days_in_month - self.employee_data.get('lop', 0)
    
#     def validate_email(self, email):
#         """Validate email format"""
#         pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
#         return re.match(pattern, email) is not None
    
#     def validate_date(self, date_str):
#         """Validate date format (DD-MM-YYYY)"""
#         try:
#             datetime.datetime.strptime(date_str, '%d-%m-%Y')
#             return True
#         except ValueError:
#             return False
    
#     def calculate_salary(self):
#         """Calculate salary based on working days and deductions"""
#         base_salary = self.employee_data['base_salary']
#         total_days = self.employee_data['total_days']
#         working_days = self.employee_data['working_days']
        
#         # Calculate per day salary
#         per_day_salary = base_salary / total_days
        
#         # Calculate monthly salary after LOP
#         monthly_salary = per_day_salary * working_days
        
#         # Annual salary projection
#         annual_salary = base_salary * 12
        
#         # Store salary details
#         self.salary_details['per_day_salary'] = per_day_salary
#         self.salary_details['monthly_salary'] = monthly_salary
#         self.salary_details['annual_salary'] = annual_salary
        
#         # Calculate deductions and net salary
#         self.calculate_tax()
        
#         # Professional Tax (assumed fixed for simplicity)
#         professional_tax = 200 if monthly_salary > 15000 else 0
        
#         # Calculate net salary
#         monthly_tax = self.tax_details['annual_tax'] / 12
#         net_salary = monthly_salary - monthly_tax - professional_tax
        
#         self.salary_details['professional_tax'] = professional_tax
#         self.salary_details['monthly_tax'] = monthly_tax
#         self.salary_details['net_salary'] = net_salary
    
#     def calculate_tax(self):
#             annual_income = self.salary_details['annual_salary']
        
#         # Standard deduction and taxable income calculation
#             standard_deduction = 75000
#             taxable_income = annual_income - standard_deduction
#             tax = 0

#             # Compute tax only if taxable income exceeds ₹4,00,000
#             if taxable_income > 400000:
#                 remaining_income = taxable_income - 400000

#                 # Slab 1: ₹4,00,001 to ₹8,00,000 @ 5%
#                 slab = min(remaining_income, 400000)
#                 tax += slab * 0.05
#                 remaining_income -= slab

#                 # Slab 2: ₹8,00,001 to ₹12,00,000 @ 10%
#                 if remaining_income > 0:
#                     slab = min(remaining_income, 400000)
#                     tax += slab * 0.10
#                     remaining_income -= slab

#                 # Slab 3: ₹12,00,001 to ₹16,00,000 @ 15%
#                 if remaining_income > 0:
#                     slab = min(remaining_income, 400000)
#                     tax += slab * 0.15
#                     remaining_income -= slab

#                 # Slab 4: ₹16,00,001 to ₹20,00,000 @ 20%
#                 if remaining_income > 0:
#                     slab = min(remaining_income, 400000)
#                     tax += slab * 0.20
#                     remaining_income -= slab

#                 # Slab 5: ₹20,00,001 to ₹24,00,000 @ 25%
#                 if remaining_income > 0:
#                     slab = min(remaining_income, 400000)
#                     tax += slab * 0.25
#                     remaining_income -= slab

#                 # Slab 6: Above ₹24,00,000 @ 30%
#                 if remaining_income > 0:
#                     tax += remaining_income * 0.30

#             # Apply rebate: No tax if annual income is up to ₹12.75 lakh
#             if annual_income <= 1275000:
#                 tax = 0

#             # Compute initial cess at 4% of the computed tax
#             cess = tax * 0.04
#             total_tax = tax + cess

#             # Apply marginal relief for annual incomes between ₹12.75 lakh and ₹15 lakh.
#             # Under marginal relief, the total tax (including cess) should not exceed the difference.
#             if 1275000 < annual_income <= 1500000:
#                 income_above_limit = annual_income - 1275000
#                 if total_tax > income_above_limit:
#                     # Back-calculate tax so that total_tax (tax + cess) equals income_above_limit.
#                     tax = income_above_limit
#                     cess = tax * 0.04
#                     total_tax = tax + cess

#             # Store the updated tax details
#             self.tax_details['taxable_income'] = taxable_income
#             self.tax_details['tax_before_cess'] = tax
#             self.tax_details['cess'] = cess
#             self.tax_details['annual_tax'] = total_tax


    
#     def calculate_experience(self):
#         """Calculate experience based on date of joining"""
#         doj = datetime.datetime.strptime(self.employee_data['doj'], '%d-%m-%Y')
#         current_date = self.current_date
        
#         experience = relativedelta(current_date, doj)
#         return experience
    
#     def generate_salary_data(self):
#         """Generate salary data in dictionary format"""
#         self.calculate_salary()
#         experience = self.calculate_experience()
    
#     # Format current date for the slip
#         slip_date = self.current_date.strftime('%d-%m-%Y')
#         month_name = self.current_date.strftime('%B')
        
#         # Get annual income from salary_details
#         annual_income = self.salary_details['annual_salary']  # This line was missing
        
#         # Tax breakdown details
#         tax_breakdown = []
#         if self.tax_details['annual_tax'] > 0:
#             tax_breakdown.append({"slab": "Income up to Rs. 4 lakh", "rate": "0%", "amount": 0})
            
#             if self.tax_details['taxable_income'] > 400000:
#                 slab_1_income = min(self.tax_details['taxable_income'] - 400000, 400000)
#                 slab_1_tax = slab_1_income * 0.05
#                 tax_breakdown.append({
#                     "slab": "Income Rs. 4-8 lakh", 
#                     "amount": slab_1_income, 
#                     "rate": "5%", 
#                     "tax": slab_1_tax
#                 })
            
#             if self.tax_details['taxable_income'] > 800000:
#                 slab_2_income = min(self.tax_details['taxable_income'] - 800000, 400000)
#                 slab_2_tax = slab_2_income * 0.10
#                 tax_breakdown.append({
#                     "slab": "Income Rs. 8-12 lakh", 
#                     "amount": slab_2_income, 
#                     "rate": "10%", 
#                     "tax": slab_2_tax
#                 })
            
#             if self.tax_details['taxable_income'] > 1200000:
#                 slab_3_income = self.tax_details['taxable_income'] - 1200000
#                 slab_3_tax = slab_3_income * 0.15
#                 tax_breakdown.append({
#                     "slab": "Income above Rs. 12 lakh", 
#                     "amount": slab_3_income, 
#                     "rate": "15%", 
#                     "tax": slab_3_tax
#                 })
        
#         # Prepare result dictionary
#         result = {
#             "employee_details": {
#                 "full_name": self.employee_data['full_name'],
#                 "email": self.employee_data['email'],
#                 "dob": self.employee_data['dob'],
#                 "doj": self.employee_data['doj'],
#                 "experience": f"{experience.years} years, {experience.months} months",
#                 "working_days": f"{self.employee_data['working_days']}/{self.employee_data['total_days']}",
#                 "lop": self.employee_data.get('lop', 0)
#             },
#             "salary_details": {
#                 "base_salary": self.employee_data['base_salary'],
#                 "per_day_salary": self.salary_details['per_day_salary'],
#                 "monthly_salary": self.salary_details['monthly_salary'],
#                 "annual_salary": self.salary_details['annual_salary'],
#                 "professional_tax": self.salary_details['professional_tax'],
#                 "monthly_tax": self.salary_details['monthly_tax'],
#                 "net_salary": self.salary_details['net_salary']
#             },
#             "tax_details": {
#                 "taxable_income": self.tax_details['taxable_income'],
#                 "tax_before_cess": self.tax_details['tax_before_cess'],
#                 "cess": self.tax_details['cess'],
#                 "annual_tax": self.tax_details['annual_tax'],
#                 "tax_breakdown": tax_breakdown,
#                 "rebate_applied": annual_income <= 1275000,
#                 "marginal_relief_applicable": 1275000 < annual_income <= 1500000
#             },
#             "pay_period": f"{month_name} {self.employee_data['current_year']}",
#             "generated_on": slip_date
#         }
        
#         return result

#     def generate_formatted_slip(self):
#         """Generate formatted salary slip as a dictionary"""
#         salary_data = self.generate_salary_data()
        
#         # Format numbers for display
#         for key in ['base_salary', 'monthly_salary', 'annual_salary', 'net_salary']:
#             salary_data['salary_details'][key] = f"₹ {salary_data['salary_details'][key]:,.2f}"
            
#         for key in ['taxable_income', 'tax_before_cess', 'cess', 'annual_tax']:
#             salary_data['tax_details'][key] = f"₹ {salary_data['tax_details'][key]:,.2f}"
            
#         salary_data['salary_details']['per_day_salary'] = f"₹ {salary_data['salary_details']['per_day_salary']:,.2f}"
#         salary_data['salary_details']['monthly_tax'] = f"₹ {salary_data['salary_details']['monthly_tax']:,.2f}"
#         salary_data['salary_details']['professional_tax'] = f"₹ {salary_data['salary_details']['professional_tax']:,.2f}"
        
#         # Format tax breakdown
#         for item in salary_data['tax_details']['tax_breakdown']:
#             if 'amount' in item:
#                 item['amount'] = f"₹ {item['amount']:,.2f}"
#             if 'tax' in item:
#                 item['tax'] = f"₹ {item['tax']:,.2f}"
        
#         # Add notes
#         if salary_data['tax_details']['rebate_applied']:
#             salary_data['notes'] = ["You qualify for rebate under Section 87A. No tax applicable."]
#         elif salary_data['tax_details']['marginal_relief_applicable']:
#             salary_data['notes'] = ["Marginal relief applied to your tax calculation."]
#         else:
#             salary_data['notes'] = ["Standard tax calculation applied as per new tax regime."]
            
#         salary_data['notes'].append("This salary slip is computer generated and does not require a signature.")
        
#         return salary_data


# @app.route('/generate-salary-slip', methods=['POST'])
# def generate_salary_slip():
#     try:
#         # Get JSON data from request
#         data = request.get_json()
        
#         if not data or 'employee_data' not in data:
#             return jsonify({
#                 "status": "error",
#                 "message": "Missing employee_data in request"
#             }), 400
        
#         # Validate required fields
#         required_fields = ['full_name', 'email', 'dob', 'doj', 'base_salary']
#         for field in required_fields:
#             if field not in data['employee_data']:
#                 return jsonify({
#                     "status": "error",
#                     "message": f"Missing required field: {field}"
#                 }), 400
        
#         # Validate email format
#         employee_data = data['employee_data']
#         generator = SalarySlipGenerator({})  # Temporary instance for validation
#         if not generator.validate_email(employee_data['email']):
#             return jsonify({
#                 "status": "error",
#                 "message": "Invalid email format"
#             }), 400
        
#         # Validate date formats
#         for date_field in ['dob', 'doj']:
#             if not generator.validate_date(employee_data[date_field]):
#                 return jsonify({
#                     "status": "error",
#                     "message": f"Invalid date format for {date_field}. Use DD-MM-YYYY"
#                 }), 400
        
#         # Validate base_salary
#         if not isinstance(employee_data['base_salary'], (int, float)) or employee_data['base_salary'] <= 0:
#             return jsonify({
#                 "status": "error",
#                 "message": "Base salary must be a positive number"
#             }), 400
        
#         # Set default LOP if not provided
#         if 'lop' not in employee_data:
#             employee_data['lop'] = 0
        
#         # Create salary slip generator
#         generator = SalarySlipGenerator(
#             employee_data,
#             current_date=data.get('current_date')
#         )
        
#         # Generate salary data (choose between raw or formatted)
#         if data.get('format', 'raw') == 'formatted':
#             salary_data = generator.generate_formatted_slip()
#         else:
#             salary_data = generator.generate_salary_data()
        
#         # Return response
#         return jsonify({
#             "status": "success",
#             "data": salary_data
#         })
    
#     except Exception as e:
#         return jsonify({
#             "status": "error",
#             "message": str(e)
#         }), 500

# if __name__ == '__main__':
#     app.run(debug=True, host='0.0.0.0', port=5000)































from flask import Flask, request, jsonify, send_file
import datetime
import calendar
import re
import os
from dateutil.relativedelta import relativedelta
import io
from num2words import num2words

# Import standard FPDF without extensions
from fpdf import FPDF

app = Flask(__name__)

class BasicSalarySlipPDF(FPDF):
    """A simplified PDF class that avoids Unicode issues"""
    def __init__(self):
        # Use portrait mode (P), mm as units, A4 format
        FPDF.__init__(self, orientation='P', unit='mm', format='A4')
        self.set_auto_page_break(auto=True, margin=15)
        # Colors
        self.blue_color = (0, 51, 153)  # RGB for dark blue

    def header(self):
        # Company name in blue
        self.set_font('Arial', 'B', 16)
        self.set_text_color(0, 51, 153)
        self.cell(0, 10, 'COSMOTECH AI PRIVATE LIMITED', 0, 1, 'C')
        
        # Company address
        self.set_font('Arial', '', 8)
        self.cell(0, 5, 'Urbtech Trade Center IS block 1 and 2, Sector 132, Noida', 0, 1, 'C')
        self.cell(0, 5, 'Noida Uttar Pradesh 201305, India', 0, 1, 'C')
        
        # Line break after header
        self.ln(5)
 
    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, '-- This is a system-generated document. --', 0, 0, 'C')

    def create_salary_slip(self, data):
        self.add_page()
        
        # Title
        self.set_font('Arial', 'B', 12)
        self.set_text_color(0, 51, 153)
        self.cell(0, 10, f"Payslip for the month of {data['pay_period']}", 0, 1, 'C')
        self.ln(5)
        
        # Employee details section
        self.set_font('Arial', 'B', 10)
        self.set_text_color(0, 0, 0)
        
        # Left column
        col_width = 95
        employee = data['employee_details']
        
        # Create 2 column layout
        self.set_font('Arial', 'B', 8)
        self.cell(30, 6, 'Employee Name:', 0, 0)
        self.set_font('Arial', '', 8)
        self.cell(65, 6, employee['full_name'], 0, 0)
        
        self.set_font('Arial', 'B', 8)
        self.cell(30, 6, 'Employee No:', 0, 0)
        self.set_font('Arial', '', 8)
        self.cell(65, 6, str(employee['emp_no']), 0, 1)
        
        self.set_font('Arial', 'B', 8)
        self.cell(30, 6, 'Designation:', 0, 0)
        self.set_font('Arial', '', 8)
        self.cell(65, 6, employee['designation'], 0, 0)
        
        self.set_font('Arial', 'B', 8)
        self.cell(30, 6, 'Department:', 0, 0)
        self.set_font('Arial', '', 8)
        self.cell(65, 6, employee['department'], 0, 1)
        
        self.set_font('Arial', 'B', 8)
        self.cell(30, 6, 'Date of Joining:', 0, 0)
        self.set_font('Arial', '', 8)
        self.cell(65, 6, employee['doj'], 0, 0)
        
        self.set_font('Arial', 'B', 8)
        self.cell(30, 6, 'Bank Account:', 0, 0)
        self.set_font('Arial', '', 8)
        self.cell(65, 6, str(employee['bank_account']), 0, 1)
        
        self.set_font('Arial', 'B', 8)
        self.cell(30, 6, 'Work Location:', 0, 0)
        self.set_font('Arial', '', 8)
        self.cell(65, 6, data['company_name'], 0, 0)
        
        self.set_font('Arial', 'B', 8)
        self.cell(30, 6, 'PAN:', 0, 0)
        self.set_font('Arial', '', 8)
        self.cell(65, 6, str(employee['pan']), 0, 1)
        
        self.ln(5)
        
        # Attendance details
        self.set_font('Arial', 'B', 9)
        self.cell(30, 6, 'Paid Days:', 0, 0)
        self.set_font('Arial', '', 9)
        self.cell(30, 6, str(employee['working_days']), 0, 0)
        
        self.set_font('Arial', 'B', 9)
        self.cell(30, 6, 'LOP Days:', 0, 0)
        self.set_font('Arial', '', 9)
        self.cell(30, 6, str(employee['lop']), 0, 1)
        
        self.ln(10)
        
        # Pay summary header
        self.set_font('Arial', 'B', 11)
        self.set_text_color(0, 51, 153)
        self.cell(0, 10, 'EMPLOYEE PAY SUMMARY', 0, 1, 'C')
        
        # Table header
        self.set_font('Arial', 'B', 9)
        self.set_text_color(255, 255, 255)
        self.set_fill_color(0, 51, 153)
        
        # Define column widths (removed YTD columns)
        col1 = 95  # Earnings
        col2 = 35  # Amount
        col3 = 35  # Deductions
        col4 = 35  # Amount
        
        # First row headers
        self.cell(col1, 8, 'EARNINGS', 1, 0, 'C', True)
        self.cell(col2, 8, 'AMOUNT', 1, 0, 'C', True)
        self.cell(col3, 8, 'DEDUCTIONS', 1, 0, 'C', True)
        self.cell(col4, 8, 'AMOUNT', 1, 1, 'C', True)
        
        # Earnings and deductions data
        self.set_text_color(0, 0, 0)
        self.set_font('Arial', '', 8)
        
        # Calculate max rows needed between earnings and deductions
        earnings = data['salary_details']['earnings']
        deductions = data['salary_details'].get('deductions', [])
        max_rows = max(len(earnings), len(deductions))
        
        # Add rows
        for i in range(max_rows):
            # Earnings columns
            if i < len(earnings):
                item = earnings[i]
                self.cell(col1, 7, item['name'], 'LR', 0)
                self.cell(col2, 7, item['amount'], 'LR', 0, 'R')
            else:
                self.cell(col1, 7, '', 'LR', 0)
                self.cell(col2, 7, '', 'LR', 0)
            
            # Deductions columns
            if i < len(deductions):
                item = deductions[i]
                self.cell(col3, 7, item['name'], 'LR', 0)
                self.cell(col4, 7, item['amount'], 'LR', 0, 'R')
            else:
                self.cell(col3, 7, '', 'LR', 0)
                self.cell(col4, 7, '', 'LR', 0)
            
            self.ln()
        
        # Total row
        self.set_font('Arial', 'B', 8)
        self.cell(col1, 7, 'Gross Earnings', 1, 0)
        self.cell(col2, 7, data['salary_details']['gross_earnings'], 1, 0, 'R')
        self.cell(col3, 7, 'Total Deductions', 1, 0)
        self.cell(col4, 7, data['salary_details']['total_deductions'], 1, 1, 'R')
        
        # Net payable
        self.ln(5)
        self.set_font('Arial', 'B', 9)
        self.cell(100, 7, 'Total Net Payable', 0, 0)
        self.cell(60, 7, data['salary_details']['net_payable'], 0, 1, 'R')
        
        # Amount in words
        self.set_font('Arial', 'I', 8)
        self.cell(0, 7, f"({data['salary_details']['amount_in_words']})", 0, 1)
        
        # Note
        self.set_font('Arial', '', 8)
        self.cell(0, 7, '**Total Net Payable = Gross Earnings - Total Deductions', 0, 1)
        
        # Add tax notes if applicable
        if data.get('tax_notes'):
            self.ln(3)
            self.set_font('Arial', 'I', 8)
            for note in data['tax_notes']:
                self.cell(0, 5, note, 0, 1)

class SalarySlipGenerator:
    def __init__(self, employee_data, current_date=None):
        self.employee_data = employee_data
        self.salary_details = {}
        self.tax_details = {}
        
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
        
        # Return tax notes
        tax_notes = []
        if self.tax_details['rebate_applied']:
            tax_notes.append("*You qualify for rebate under Section 87A. No tax applicable.")
        elif self.tax_details['marginal_relief_applicable']:
            tax_notes.append("*Marginal relief applied to your tax calculation.")
        
        return tax_notes
    
    def calculate_salary(self):
        """Calculate salary based on working days and deductions"""
        # Use the salary structure from employee data
        salary_structure = self.employee_data['salary_structure']
        total_days = self.employee_data['total_days']
        working_days = self.employee_data['working_days']
        
        # Calculate base salary from salary structure
        base_salary = sum(item['amount'] for item in salary_structure)
        
        # Calculate annual salary
        self.annual_salary = base_salary * 12
        
        # Calculate per day salary
        per_day_salary = base_salary / total_days
        
        # Calculate monthly salary after LOP
        monthly_salary = per_day_salary * working_days
        
        # Calculate each component based on working days
        earnings = []
        for item in salary_structure:
            amount = item['amount'] * working_days / total_days
            earnings.append({
                'name': item['name'],
                'amount': f"Rs. {amount:.2f}"
            })
        
        # Calculate tax
        tax_notes = self.calculate_tax()
        
        # Set up deductions
        deductions = []
        monthly_tax = self.tax_details['monthly_tax']
        
        # Add income tax to deductions if applicable
        if monthly_tax > 0:
            deductions.append({
                'name': 'Income Tax',
                'amount': f"Rs. {monthly_tax:.2f}"
            })
        
        # Add professional tax (if applicable)
        professional_tax = 200 if monthly_salary > 15000 else 0
        if professional_tax > 0:
            deductions.append({
                'name': 'Professional Tax',
                'amount': f"Rs. {professional_tax:.2f}"
            })
        
        # Calculate total deductions
        total_deductions = monthly_tax + professional_tax
        
        # Calculate net payable
        net_payable = monthly_salary - total_deductions
        
        # Store salary details
        self.salary_details['earnings'] = earnings
        self.salary_details['deductions'] = deductions
        self.salary_details['gross_earnings'] = f"Rs. {monthly_salary:.2f}"
        self.salary_details['total_deductions'] = f"Rs. {total_deductions:.2f}"
        self.salary_details['net_payable'] = f"Rs. {net_payable:.2f}"
        
        # Convert amount to words
        amount_in_words = f"Indian Rupee {num2words(int(net_payable))} Only"
        self.salary_details['amount_in_words'] = amount_in_words.title()
        
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
                "lop": self.employee_data.get('lop', 0)
            },
            "salary_details": self.salary_details,
            "tax_details": self.tax_details,
            "pay_period": f"{month_name} {self.employee_data['current_year']}",
            "generated_on": slip_date,
            "company_name": self.employee_data.get('company_name', 'Cosmotech AI Private Limited'),
            "tax_notes": tax_notes
        }
        
        return result
    
    def generate_pdf(self):
        """Generate PDF salary slip"""
        salary_data = self.generate_salary_data()
        
        # Use our simplified PDF class
        pdf = BasicSalarySlipPDF()
        pdf.create_salary_slip(salary_data)
        
        # Save PDF to a bytes buffer - FIX FOR THE ERROR
        pdf_buffer = io.BytesIO()
        pdf_bytes = pdf.output(dest='S').encode('latin-1')  # 'S' means return as string
        pdf_buffer.write(pdf_bytes)
        pdf_buffer.seek(0)
        
        return pdf_buffer

@app.route('/generate-salary-slip', methods=['POST'])
def generate_salary_slip():
    try:
        # Get JSON data from request
        data = request.get_json()
        
        if not data or 'employee_data' not in data:
            return jsonify({
                "status": "error",
                "message": "Missing employee_data in request"
            }), 400
        
        # Validate required fields
        required_fields = ['full_name', 'doj', 'salary_structure']
        for field in required_fields:
            if field not in data['employee_data']:
                return jsonify({
                    "status": "error",
                    "message": f"Missing required field: {field}"
                }), 400
        
        # Validate date formats
        employee_data = data['employee_data']
        generator = SalarySlipGenerator({})  # Temporary instance for validation
        
        if not generator.validate_date(employee_data['doj']):
            return jsonify({
                "status": "error",
                "message": f"Invalid date format for doj. Use DD-MM-YYYY"
            }), 400
        
        # Validate salary structure
        if not isinstance(employee_data['salary_structure'], list) or len(employee_data['salary_structure']) == 0:
            return jsonify({
                "status": "error",
                "message": "Salary structure must be a non-empty list"
            }), 400
        
        # Set default LOP if not provided
        if 'lop' not in employee_data:
            employee_data['lop'] = 0
        
        # Create salary slip generator
        generator = SalarySlipGenerator(
            employee_data,
            current_date=data.get('current_date')
        )
        
        # Generate PDF
        pdf_buffer = generator.generate_pdf()
        
        # Send PDF file
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"salary_slip_{employee_data['full_name'].replace(' ', '_')}.pdf"
        )
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)