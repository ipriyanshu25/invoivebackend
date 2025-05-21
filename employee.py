import math
import re
from flask import Blueprint, make_response, request, send_file, abort
from flask_pymongo import PyMongo
from datetime import datetime
from db import db
from utils import format_response
import calendar
import uuid
from salaryslip import SalarySlipGenerator

employee_bp = Blueprint('employee', __name__, url_prefix='/employee')

# Helper to generate unique employee IDs
def generate_unique_employee_id():
    while True:
        emp_id = "EMP" + ''.join(__import__('random').choices(__import__('string').digits, k=4))
        if not db.employees.find_one({"employeeId": emp_id}):
            return emp_id

@employee_bp.route('/SaveRecord', methods=['POST'])
def add_employee():
    data = request.get_json(force=True)

    # Required fields
    required = [
        "employeeId", "name", "email", "phone", "dob",
        "adharnumber", "pan_number", "date_of_joining", 
        "base_salary", "department", "designation"
    ]
    if not all(data.get(f) for f in required):
        return format_response(False, "Missing required employee details", status=400)

    # Unique checks
    if db.employees.find_one({"$or": [
        {"employeeId": data['employeeId']},
        {"email": data['email']},
        {"phone": data['phone']}
    ]}):
        return format_response(False, "Employee already exists with this ID, email, or phone number", status=409)

    # Validate dates
    for fld in ('dob', 'date_of_joining'):
        try:
            datetime.strptime(data[fld], "%Y-%m-%d")
        except ValueError:
            return format_response(False, f"{fld} must be YYYY-MM-DD", status=400)

    # Parse salaries
    try:
        base_salary = float(data['base_salary'])
        annual_salary = base_salary * 12
    except (ValueError, TypeError):
        return format_response(False, "Salary fields must be numbers", status=400)

    # Optional manual TDS stored here (not needed at creation, but allowed)
    manual = data.get('manual_tds')
    if manual is not None:
        try:
            manual = float(manual)
        except (ValueError, TypeError):
            return format_response(False, "manual_tds must be a number", status=400)

    record = {
        "employeeId": data['employeeId'],
        "name": data['name'],
        "email": data['email'],
        "phone": data['phone'],
        "dob": data['dob'],
        "adharnumber": data['adharnumber'],
        "pan_number": data['pan_number'],
        "date_of_joining": data['date_of_joining'],
        "base_salary": base_salary,
        "annual_salary": annual_salary,
        "manual_tds": manual,
        "bank_details": data.get('bank_details', {}),
        "address": data.get('address', {}),
        "department": data['department'],
        "designation": data['designation'],
        "created_at": datetime.utcnow()
    }
    db.employees.insert_one(record)
    return format_response(True, "Employee added successfully", {"employeeId": data['employeeId']}, status=201)

@employee_bp.route('/update', methods=['POST'])
def update_employee():
    data = request.get_json(force=True)
    emp_id = data.pop('employeeId', None)
    if not emp_id:
        return format_response(False, "employeeId is required", status=400)
    if not data:
        return format_response(False, "No fields provided for update", status=400)

    # Validate dates
    for fld in ('dob', 'date_of_joining'):
        if fld in data:
            try:
                datetime.strptime(data[fld], "%Y-%m-%d")
            except ValueError:
                return format_response(False, f"{fld} must be YYYY-MM-DD", status=400)

    # Parse numbers
    for num in ('base_salary', 'annual_salary', 'manual_tds'):
        if num in data:
            try:
                data[num] = float(data[num])
            except (ValueError, TypeError):
                return format_response(False, f"{num} must be a number", status=400)

    res = db.employees.update_one({"employeeId": emp_id}, {"$set": data})
    if not res.matched_count:
        abort(404)
    return format_response(True, "Employee updated successfully", {"employeeId": emp_id}, status=200)
@employee_bp.route('/delete', methods=['POST'])
def delete_employee():
    emp_id = request.get_json(force=True).get('employeeId')
    if not emp_id:
        return format_response(False, "employeeId is required", status=400)
    res = db.employees.delete_one({"employeeId": emp_id})
    if not res.deleted_count:
        abort(404)
    return format_response(True, "Employee deleted successfully", status=200)

@employee_bp.route('/getrecord', methods=['GET'])
def get_record():
    emp_id = request.args.get('employeeId')
    if not emp_id:
        return format_response(False, "Query parameter 'employeeId' is required", status=400)
    emp = db.employees.find_one({"employeeId": emp_id})
    if not emp:
        abort(404)
    emp.pop('_id', None)
    emp['created_at'] = emp.get('created_at').isoformat() if emp.get('created_at') else None
    return format_response(True, "Employee retrieved successfully", {"employee": emp}, status=200)
@employee_bp.route('/getlist', methods=['POST'])
def get_all_employees():
    params = request.get_json(force=True) or {}
    search = (params.get('search') or '').strip()
    page = max(int(params.get('page', 1)), 1)
    size = max(int(params.get('pageSize', 10)), 1)
    query = {}
    if search:
        regex = re.compile(re.escape(search), re.IGNORECASE)
        query['$or'] = [{'name': regex}, {'email': regex}, {'phone': regex}]
    total = db.employees.count_documents(query)
    skip = (page - 1) * size
    cursor = db.employees.find(query).skip(skip).limit(size)
    results = []
    for e in cursor:
        e.pop('_id', None)
        results.append(e)
    total_pages = math.ceil(total / size)
    return format_response(True, "Employees retrieved successfully", {
        "employees": results,
        "total": total,
        "page": page,
        "pageSize": size,
        "totalPages": total_pages
    }, status=200)
@employee_bp.route('/salaryslip', methods=['POST'])
def get_salary_slip():
    data = request.get_json(force=True)
    emp_id = data.get('employeeId')or data.get('employee_id')
    payslip_month = data.get('month')
    if not emp_id or not payslip_month:
        return format_response(False, "Missing required fields: employeeId or month", status=400)

    try:
        mdate = datetime.strptime(payslip_month, "%m-%Y")
    except ValueError:
        return format_response(False, "Invalid month format. Use MM-YYYY", status=400)

    emp = db.employees.find_one({"employeeId": emp_id})
    if not emp:
        abort(404)

    # Calculate end-of-month date string
    year, month = mdate.year, mdate.month
    last_day = calendar.monthrange(year, month)[1]
    date_str = f"{last_day:02d}-{month:02d}-{year}"

    # Parse manual override from this request (takes precedence)
    manual = data.get('Tax Deduction at Source (TDS)')
    if manual is not None:
        try:
            manual = float(manual)
        except (ValueError, TypeError):
            return format_response(False, "Tax Deduction at Source (TDS) must be a number", status=400)
    else:
        # fall back to stored employee value
        manual = emp.get('Tax Deduction at Source (TDS)')

    # Build salary_structure list
    incoming = data.get('salary_structure', [])
    final_struct = []
    allowance_names = ["Basic Pay", "House Rent Allowance", "Performance Bonus", "Overtime Bonus", "Special Allowance"]
    for name in allowance_names:
        amt = next((float(item['amount']) for item in incoming if item['name']==name), 0.0)
        final_struct.append({"name": name, "amount": amt})

    # Prepare snapshot for PDF
    emp_snapshot = {
        "full_name": emp['name'],
        "emp_no": emp['employeeId'],
        "designation": emp.get('designation',''),
        "department": emp.get('department',''),
        "doj": datetime.strptime(emp['date_of_joining'], "%Y-%m-%d").strftime("%d-%m-%Y"),
        "bank_account": emp.get('bank_details',{}).get('account_number',''),
        "pan": emp.get('pan_number',''),
        "lop": float(data.get('lop',0)),
        "salary_structure": final_struct,
        "Tax Deduction at Source (TDS)": manual
    }

    # Generate PDF
    generator = SalarySlipGenerator(emp_snapshot, current_date=date_str)
    pdf_buf = generator.generate_pdf()

    # Optionally save record
    payslip_id = str(uuid.uuid4())
    month_name = calendar.month_name[month]
    db.payslips.insert_one({
        "payslipId": payslip_id,
        "employeeId": emp_id,
        "month": month_name,
        "year": year,
        "generated_on": datetime.utcnow(),
        "lop_days": emp_snapshot['lop'],
        "salary_structure": final_struct,
        "emp_snapshot": emp_snapshot,
        "filename": f"salary_slip_{emp_id}.pdf"
    })

    return send_file(pdf_buf, mimetype='application/pdf', as_attachment=True,
                     download_name=f"salary_slip_{emp_id}.pdf")


@employee_bp.route('/getpayslips', methods=['POST'])
def get_payslips():
    params = request.get_json(force=True) or {}
    query = {}
    if params.get('search'):
        query['$text'] = {'$search': params['search']}
    if params.get('month'):
        query['month'] = params['month']
    if params.get('year'):
        query['year'] = int(params['year'])
    page = max(int(params.get('page', 1)), 1)
    size = max(int(params.get('pageSize', 10)), 1)
    total = db.payslips.count_documents(query)
    cursor = db.payslips.find(query, {'_id': 0}).skip((page-1)*size).limit(size)
    payslips = [{**p, 'download_link': f"/download/{p['payslipId']}"} for p in cursor]
    if not payslips:
        return format_response(True, "No payslips found", {
            'payslips': [],
            'pagination': {
                'totalRecords': 0,
                'currentPage': page,
                'totalPages': 0
            }
        }, status=200)
    return format_response(True, "Payslips retrieved successfully", {
        'payslips': payslips,
        'pagination': { 'totalRecords': total, 'currentPage': page, 'totalPages': math.ceil(total/size) }
    }, status=200)

@employee_bp.route('/viewpdf/<payslip_id>', methods=['GET'])
def view_payslip_pdf(payslip_id):
    payslip = db.payslips.find_one({"payslipId": payslip_id})
    if not payslip:
        return format_response(False, "Payslip not found", status=404)

    emp_snapshot = payslip.get('emp_snapshot')
    if not emp_snapshot:
        return format_response(False, "Payslip does not contain employee snapshot", status=400)

    generated_on = payslip.get('generated_on')
    if not generated_on:
        return format_response(False, "Payslip does not have generation date", status=400)
    generated_on_str = generated_on.strftime("%d-%m-%Y")

    pdf_buf = SalarySlipGenerator(emp_snapshot, current_date=generated_on_str).generate_pdf()
    response = make_response(send_file(
        pdf_buf,
        mimetype='application/pdf',
        as_attachment=False
    ))
    response.headers['Content-Disposition'] = f"inline; filename='{payslip.get('filename', 'salary_slip.pdf')}'"
    return response

@employee_bp.route('/getpayslip', methods=['GET'])
def get_payslip_details():
    payslip_id = request.args.get('payslipId')
    if not payslip_id:
        return format_response(False, "Query parameter 'payslipId' is required", status=400)
    payslip = db.payslips.find_one({"payslipId": payslip_id}, {'_id': 0})
    if not payslip:
        abort(404)
    return format_response(True, "Payslip details retrieved successfully", {"payslip": payslip}, status=200)

@employee_bp.route('/deletepayslip', methods=['POST'])
def delete_payslip():
    payslip_id = request.get_json(force=True).get('payslipId')
    if not payslip_id:
        return format_response(False, "payslipId is required", status=400)
    res = db.payslips.delete_one({"payslipId": payslip_id})
    if not res.deleted_count:
        abort(404)
    return format_response(True, "Payslip deleted successfully", status=200)

# Allowance names – amounts must be provided in salary_structure payload
allowance_names = [
    "Basic Pay", "House Rent Allowance",
    "Performance Bonus", "Overtime Bonus", "Special Allowance"
]

