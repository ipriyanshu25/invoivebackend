from flask import Flask, request, jsonify,Blueprint, send_file
from flask_pymongo import PyMongo
from bson import ObjectId
from datetime import datetime
from db import db
from salaryslip import SalarySlipGenerator

employee_bp = Blueprint('employee', __name__,url_prefix='/employees')

# Helper function for formatting consistent responses
def format_response(success, message, data=None, status_code=200):
    return jsonify({
        "success": success,
        "message": message,
        "data": data or {}
    }), status_code

import random
import string

import random
import string

def generate_unique_employee_id():
    while True:
        emp_id = "EMP" + ''.join(random.choices(string.digits, k=4))
        if not db.employees.find_one({"employeeId": emp_id}):
            return emp_id



@employee_bp.route('/saverecord', methods=['POST'])
def add_employee():
    try:
        data = request.get_json()

        name = data.get("name")
        email = data.get("email")
        phone = data.get("phone")
        dob = data.get("dob")
        adharnumber = data.get("adharnumber")
        pan_number = data.get("pan_number")
        date_of_joining = data.get("date_of_joining")
        monthly_salary = data.get("monthly_salary")
        department = data.get("department")
        designation = data.get("designation")
        bank_details = data.get("bank_details")
        address = data.get("address")

        if not all([
            name, email, phone, dob, adharnumber, pan_number,
            date_of_joining, monthly_salary, department, designation
        ]):
            return format_response(False, "Missing required employee details", status_code=400)

        # Uniqueness check
        existing_employee = db.employees.find_one({
            "$or": [
                {"email": email},
                {"phone": phone}
            ]
        })
        if existing_employee:
            return format_response(False, "Employee already exists with this email or phone number", status_code=409)

        # Date format validation
        try:
            datetime.strptime(dob, "%Y-%m-%d")
            datetime.strptime(date_of_joining, "%Y-%m-%d")
        except ValueError:
            return format_response(False, "Date format must be YYYY-MM-DD", status_code=400)

        try:
            monthly_salary = float(monthly_salary)
        except ValueError:
            return format_response(False, "Monthly salary must be a number", status_code=400)

        annual_salary = round(monthly_salary * 12, 2)
        ctc = annual_salary

        # Remove 'cities' if present in address
        if address and "cities" in address:
            address.pop("cities")

        # Generate unique employee ID
        employee_id = generate_unique_employee_id()

        employee_record = {
            "employeeId": employee_id,
            "name": name,
            "email": email,
            "phone": phone,
            "dob": dob,
            "adharnumber": adharnumber,
            "pan_number": pan_number,
            "date_of_joining": date_of_joining,
            "monthly_salary": monthly_salary,
            "annual_salary": annual_salary,
            "ctc": ctc,
            "department": department,
            "designation": designation,
            "bank_details": bank_details,
            "address": address,
            "created_at": datetime.utcnow()
        }

        db.employees.insert_one(employee_record)

        return format_response(True, "Employee added successfully", {
            "employee_id": employee_id
        }, 201)

    except Exception as e:
        return format_response(False, str(e), status_code=500)


@employee_bp.route('/getemp', methods=['POST'])
def get_employee():
    try:
        data = request.get_json()
        employee_id = data.get("employee_id")
        if not employee_id:
            return format_response(False, "Employee ID is required", status_code=400)

        # Query using employeeId instead of ObjectId
        employee = db.employees.find_one({"employeeId": employee_id})
        if not employee:
            return format_response(False, "Employee not found", status_code=404)

        employee_data = {
            "employeeId": employee.get("employeeId"),
            "name": employee.get("name"),
            "email": employee.get("email"),
            "phone": employee.get("phone"),
            "dob": employee.get("dob"),
            "adharnumber": employee.get("adharnumber"),
            "pan_number": employee.get("pan_number"),
            "department":employee.get("department"),
            "designation":employee.get("designation"),
            "date_of_joining": employee.get("date_of_joining"),
            "annual_salary": employee.get("annual_salary"),
            "monthly_salary": employee.get("monthly_salary"),
            "ctc": employee.get("ctc"),
            "bank_details": employee.get("bank_details"),
            "address": employee.get("address"),
        }

        return format_response(True, "Employee retrieved successfully.", {"employee": employee_data}, 200)

    except Exception as e:
        return format_response(False, str(e), status_code=500)



@employee_bp.route('/update', methods=['POST'])
def update_employee():
    try:
        data = request.get_json()
        employee_id = data.get("employee_id")
        if not employee_id:
            return format_response(False, "Employee ID is required", status_code=400)

        update_fields = {}

        if "dob" in data:
            data["dob"] = datetime.strptime(data["dob"], "%Y-%m-%d")
        if "date_of_joining" in data:
            data["date_of_joining"] = datetime.strptime(data["date_of_joining"], "%Y-%m-%d")
        if "annual_salary" in data:
            data["annual_salary"] = float(data["annual_salary"])
            data["monthly_salary"] = round(data["annual_salary"] / 12, 2)
            data["ctc"] = data["annual_salary"]

        # Build update fields excluding employee_id
        for key in data:
            if key != "employee_id":
                update_fields[key] = data[key]

        result = db.employees.update_one({"_id": ObjectId(employee_id)}, {"$set": update_fields})
        if result.matched_count == 0:
            return format_response(False, "Employee not found", status_code=404)

        return format_response(True, "Employee updated successfully.", {"employeeId": employee_id}, 200)

    except Exception as e:
        return format_response(False, str(e), status_code=500)

from datetime import datetime

@employee_bp.route('/getall', methods=['POST'])
def get_all_employees():
    try:
        employees_cursor = db.employees.find()
        employees_list = []

        def format_date(value):
            if isinstance(value, datetime):
                return value.strftime("%Y-%m-%d")
            return value

        for emp in employees_cursor:
            employees_list.append({
                "employeeId": emp.get("employeeId"),
                "name": emp.get("name"),
                "email": emp.get("email"),
                "phone": emp.get("phone"),
                "dob": format_date(emp.get("dob")),
                "department": emp.get("department"),
                "designation": emp.get("designation"),
                "adharnumber": emp.get("adharnumber"),
                "pan_number": emp.get("pan_number"),
                "date_of_joining": format_date(emp.get("date_of_joining")),
                "monthly_salary": emp.get("monthly_salary"),
                "annual_salary": emp.get("annual_salary"),
                "ctc": emp.get("ctc"),
                "bank_details": emp.get("bank_details"),
                "address": emp.get("address"),
                "created_at": format_date(emp.get("created_at"))
            })

        return format_response(True, "Employees retrieved successfully.", {"employees": employees_list}, 200)

    except Exception as e:
        return format_response(False, str(e), status_code=500)

    
# from flask import Blueprint, request, jsonify, send_file
# from datetime import datetime
# from your_salaryslip_module import SalarySlipGenerator  # adjust import path
# # make sure you have `db` and any other imports (e.g. num2words) available


@employee_bp.route('/get_salary_slip', methods=['POST'])
def get_salary_slip():
    data = request.get_json() or {}
    employee_id  = data.get("employee_id")
    lop_days      = float(data.get("lop", 0))
    date_str      = data.get("date")   # e.g. "31-08-2024"
    payslip_month = data.get("month")  # e.g. "August"

    # 1. Basic validation
    if not all([employee_id, date_str, payslip_month]):
        return jsonify({"success": False, "message": "Missing required fields: employee_id, date, or month"}), 400

    try:
        # parse and confirm date format
        current_date = datetime.strptime(date_str, "%d-%m-%Y")
    except ValueError:
        return jsonify({"success": False, "message": "Invalid date format. Use DD-MM-YYYY"}), 400

    # 2. Load employee
    emp = db.employees.find_one({"employeeId": employee_id})
    if not emp:
        return jsonify({"success": False, "message": "Employee not found"}), 404

    # 3. Build the salary structure, forcing Basic Pay from the DB
    incoming = data.get("salary_structure", [])
    # map any incoming allowances by name
    incoming_map = { item["name"]: float(item.get("amount", 0)) for item in incoming }

    allowance_names = [
        "Basic Pay",
        "House Rent Allowance",
        "Conveyance Allowance",
        "Performance Bonas",
        "Overtime Bonas",
        "MED ALL",
        "OTH ALL"
    ]

    final_structure = []
    for name in allowance_names:
        if name == "Basic Pay":
            amt = float(emp.get("monthly_salary", 0))
        else:
            amt = incoming_map.get(name, 0.0)
        final_structure.append({ "name": name, "amount": amt })

    # 4. Assemble emp_data for the generator
    emp_data = {
        "full_name":       emp.get("name"),
        "emp_no":          emp.get("employeeId"),
        "designation":     emp.get("designation", ""),
        "department":      emp.get("department", ""),
        "doj":             datetime.strptime(emp.get("date_of_joining"), "%Y-%m-%d").strftime("%d-%m-%Y"),
        "bank_account":    emp.get("bank_details", {}).get("account_number", ""),
        "pan":             emp.get("pan_number"),
        "lop":             lop_days,
        "salary_structure": final_structure,
    }

    # 5. Kick off PDF generation
    # pass the original date_str so your generator's relativedelta logic works
    generator = SalarySlipGenerator(emp_data, current_date=date_str)
    pdf_buf   = generator.generate_pdf()

    # 6. Return as downloadable PDF
    return send_file(
        pdf_buf,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f"salary_slip_{employee_id}.pdf"
    )

