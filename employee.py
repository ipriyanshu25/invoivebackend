from flask import Blueprint, request, send_file, abort
from flask_pymongo import PyMongo
from bson import ObjectId
from datetime import datetime
from db import db
from utils import format_response
import re
import math
import random
import string
from salaryslip import SalarySlipGenerator
import calendar
import uuid
from io import BytesIO
import os

employee_bp = Blueprint('employee', __name__, url_prefix='/employee')

# Helper to generate unique employee IDs

def generate_unique_employee_id():
    while True:
        emp_id = "EMP" + ''.join(random.choices(string.digits, k=4))
        if not db.employees.find_one({"employeeId": emp_id}):
            return emp_id

@employee_bp.route('/SaveRecord', methods=['POST'])
def add_employee():
    data = request.get_json(force=True)
    # Required fields
    required = ["name", "email", "phone", "dob", "adharnumber", "pan_number", "date_of_joining",  "base_salary", "department", "designation"]
    if not all(data.get(f) for f in required):
        return format_response(False, "Missing required employee details", status=400)

    # Check uniqueness
    if db.employees.find_one({"$or": [{"email": data['email']}, {"phone": data['phone']}] }):
        return format_response(False, "Employee already exists with this email or phone number", status=409)

    # Validate dates
    for field in ("dob", "date_of_joining"):  
        try:
            datetime.strptime(data[field], "%Y-%m-%d")
        except ValueError:
            return format_response(False, f"{field} must be YYYY-MM-DD", status=400)

    # Parse numeric
    try:
        data['annual_salary'] = float(data['base_salary']) * 12
        data['base_salary'] = float(data['base_salary'])
    except (ValueError, TypeError):
        return format_response(False, "Salary fields must be numbers", status=400)

    # Generate ID and assemble record
    employee_id = generate_unique_employee_id()
    record = {
        "employeeId": employee_id,
        "name": data['name'],
        "email": data['email'],
        "phone": data['phone'],
        "dob": data['dob'],
        "adharnumber": data['adharnumber'],
        "pan_number": data['pan_number'],
        "date_of_joining": data['date_of_joining'],
        "annual_salary": data['annual_salary'],
        "base_salary":data['base_salary'],
        "bank_details": data.get('bank_details', {}),
        "address": data.get('address', {}),
        "department": data['department'],
        "designation": data['designation'],
        "created_at": datetime.utcnow()
    }
    _ = db.employees.insert_one(record)
    return format_response(True, "Employee added successfully", {"employeeId": employee_id}, status=201)

@employee_bp.route('/update', methods=['POST'])
def update_employee():
    data = request.get_json(force=True)
    emp_id = data.pop('employeeId', None)
    if not emp_id:
        return format_response(False, "employeeId is required", status=400)
    if not data:
        return format_response(False, "No fields provided for update", status=400)

    # Validate any provided dates
    for fld in ("dob", "date_of_joining"):
        if fld in data:
            try:
                datetime.strptime(data[fld], "%Y-%m-%d")
            except ValueError:
                return format_response(False, f"{fld} must be YYYY-MM-DD", status=400)
    # Numeric fields
    for num in ("annual_salary", "base_salary"):  
        if num in data:
            try:
                data[num] = float(data[num])
            except (ValueError, TypeError):
                return format_response(False, f"{num} must be a number", status=400)

    result = db.employees.update_one({"employeeId": emp_id}, {"$set": data})
    if not result.matched_count:
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
    # Serialize
    emp['created_at'] = emp['created_at'].isoformat() if emp.get('created_at') else None
    emp.pop('_id', None)
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
    emp_id = data.get('employee_id')
    payslip_month = data.get('month')
    if not emp_id or not payslip_month:
        return format_response(False, "Missing required fields: employee_id or month", status=400)
    try:
        month_date = datetime.strptime(payslip_month, "%m-%Y")
    except ValueError:
        return format_response(False, "Invalid month format. Use MM-YYYY", status=400)
    emp = db.employees.find_one({"employeeId": emp_id})
    if not emp:
        abort(404)
    year, month = month_date.year, month_date.month
    max_days = calendar.monthrange(year, month)[1]
    date_str = f"{max_days:02d}-{month:02d}-{year}"
    # Build salary structure
    incoming_map = {item['name']: float(item.get('amount', 0)) for item in data.get('salary_structure', [])}
    allowance_names = [
        "Basic Pay", "House Rent Allowance",
        "Performance Bonas", "Overtime Bonas", "Special Allowance"
    ]
    final = []

    # calculate basic amount once
    basic_amt = float(emp.get('base_salary', 0)) / 2

    for name in allowance_names:
        if name == "Basic Pay":
            amt = basic_amt
        elif name == "House Rent Allowance":
            amt = basic_amt * 0.60   # 60% of basic pay
        elif name == "Special Allowance":
            amt = basic_amt * 0.40   # 60% of basic pay
        else:
            amt = incoming_map.get(name, 0.0)
        final.append({"name": name, "amount": amt})

    emp_snapshot = {
        "full_name": emp['name'],
        "emp_no": emp['employeeId'],
        "designation": emp.get('designation', ''),
        "department": emp.get('department', ''),
        "doj": datetime.strptime(emp['date_of_joining'], "%Y-%m-%d").strftime("%d-%m-%Y"),
        "bank_account": emp.get('bank_details', {}).get('account_number', ''),
        "pan": emp.get('pan_number'),
        "monthly_salary":emp.get('annual_salary')/12,
        "lop": float(data.get('lop', 0)),
        "salary_structure": final
    }
    # Generate PDF
    pdf_buf = SalarySlipGenerator(emp_snapshot, current_date=date_str).generate_pdf()
    payslip_id = str(uuid.uuid4())
    db.payslips.insert_one({
        "payslipId": payslip_id,
        "employeeId": emp_id,
        "month": month,
        "year": year,
        "generated_on": datetime.utcnow(),
        "lop_days": emp_snapshot['lop'],
        "salary_structure": final,
        "emp_snapshot": emp_snapshot,
        "filename": f"salary_slip_{emp_id}.pdf"
    })
    return send_file(pdf_buf, mimetype='application/pdf', as_attachment=True, download_name=f"salary_slip_{emp_id}.pdf")

@employee_bp.route('/getpayslips', methods=['POST'])
def get_payslips():
    params = request.get_json(force=True) or {}
    query = {}
    if params.get('search'):
        query['$text'] = {'$search': params['search']}
    if params.get('month'):
        query['month'] = int(params['month'])
    if params.get('year'):
        query['year'] = int(params['year'])
    page = max(int(params.get('page', 1)), 1)
    size = max(int(params.get('pageSize', 10)), 1)
    total = db.payslips.count_documents(query)
    cursor = db.payslips.find(query, {'_id': 0}).skip((page-1)*size).limit(size)
    payslips = [{**p, 'download_link': f"/download/{p['payslipId']}"} for p in cursor]
    if not payslips:
        abort(404)
    return format_response(True, "Payslips retrieved successfully", {
        'payslips': payslips,
        'pagination': { 'totalRecords': total, 'currentPage': page, 'totalPages': math.ceil(total/size) }
    }, status=200)

@employee_bp.route('/viewpdf/<payslip_id>', methods=['GET'])
def view_payslip_pdf(payslip_id):
    payslip = db.payslips.find_one({"payslipId": payslip_id})
    if not payslip:
        abort(404)
    file_path = os.path.join('path/to/salary/slips', payslip['filename'])
    if not os.path.exists(file_path):
        return format_response(False, "Payslip PDF file not found", status=404)
    return send_file(file_path, mimetype='application/pdf', as_attachment=True, download_name=payslip['filename'])
