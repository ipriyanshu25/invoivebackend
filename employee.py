from flask import Flask, request, jsonify,Blueprint, send_file
from flask_pymongo import PyMongo
from bson import ObjectId
from datetime import datetime
from db import db
from salaryslip import SalarySlipGenerator

employees_collection = db["employees"]
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
        if not employees_collection.find_one({"employeeId": emp_id}):
            return emp_id



@employee_bp.route('/add_employee', methods=['POST'])
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
        annual_salary = data.get("annual_salary")
        bank_details = data.get("bank_details")
        address = data.get("address")

        if not all([name, email, phone, dob, adharnumber, pan_number, date_of_joining, annual_salary]):
            return format_response(False, "Missing required employee details", status_code=400)

        # Uniqueness check: email or phone already exists
        existing_employee = employees_collection.find_one({
            "$or": [
                {"email": email},
                {"phone": phone}
            ]
        })
        if existing_employee:
            return format_response(False, "Employee already exists with this email or phone number", status_code=409)

        # Validate date formats
        try:
            datetime.strptime(dob, "%Y-%m-%d")
            datetime.strptime(date_of_joining, "%Y-%m-%d")
        except ValueError:
            return format_response(False, "Date format must be YYYY-MM-DD", status_code=400)

        try:
            annual_salary = float(annual_salary)
        except ValueError:
            return format_response(False, "Annual salary must be a number", status_code=400)

        monthly_salary = round(annual_salary / 12, 2)
        ctc = annual_salary

        # Generate unique employee ID like EMP1023
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
            "annual_salary": annual_salary,
            "monthly_salary": monthly_salary,
            "ctc": ctc,
            "bank_details": bank_details,
            "address": address,
            "created_at": datetime.utcnow()
        }

        result = employees_collection.insert_one(employee_record)

        return format_response(True, "Employee added successfully", {
            "employee_id": employee_id
        }, 201)

    except Exception as e:
        return format_response(False, str(e), status_code=500)


@employee_bp.route('/getemp/<employee_id>', methods=['GET'])
def get_employee(employee_id):
    try:
        employee = employees_collection.find_one({"_id": ObjectId(employee_id)})
        if not employee:
            return format_response(False, "Employee not found", status_code=404)

        employee_data = {
            "employeeId": str(employee["_id"]),
            "name": employee.get("name"),
            "email": employee.get("email"),
            "phone": employee.get("phone"),
            "dob": employee.get("dob").strftime("%Y-%m-%d"),
            "adharnumber": employee.get("adharnumber"),
            "pan_number": employee.get("pan_number"),
            "date_of_joining": employee.get("date_of_joining").strftime("%Y-%m-%d"),
            "annual_salary": employee.get("annual_salary"),
            "monthly_salary": employee.get("monthly_salary"),
            "ctc": employee.get("ctc"),
            "bank_details": employee.get("bank_details"),
            "address": employee.get("address"),
        }

        return format_response(True, "Employee retrieved successfully.", {"employee": employee_data}, 200)

    except Exception as e:
        return format_response(False, str(e), status_code=500)

@employee_bp.route('/update/<employee_id>', methods=['PUT'])
def update_employee(employee_id):
    try:
        data = request.get_json()

        update_fields = {}
        if "dob" in data:
            data["dob"] = datetime.strptime(data["dob"], "%Y-%m-%d")
        if "date_of_joining" in data:
            data["date_of_joining"] = datetime.strptime(data["date_of_joining"], "%Y-%m-%d")
        if "annual_salary" in data:
            data["annual_salary"] = float(data["annual_salary"])
            data["monthly_salary"] = round(data["annual_salary"] / 12, 2)
            data["ctc"] = data["annual_salary"]

        for key in data:
            update_fields[key] = data[key]

        result = employees_collection.update_one({"_id": ObjectId(employee_id)}, {"$set": update_fields})
        if result.matched_count == 0:
            return format_response(False, "Employee not found", status_code=404)

        return format_response(True, "Employee updated successfully.", {"employeeId": employee_id}, 200)

    except Exception as e:
        return format_response(False, str(e), status_code=500)

@employee_bp.route('/getall', methods=['GET'])
def get_all_employees():
    try:
        employees = employees_collection.find()
        employees_list = []
        for emp in employees:
            employees_list.append({
                "employeeId": str(emp["_id"]),
                "name": emp.get("name"),
                "email": emp.get("email"),
                "phone": emp.get("phone"),
                "cities": emp.get("address", {}).get("cities", []) if isinstance(emp.get("address"), dict) else []
            })

        response_data = {
            "states": [
                {
                    "employeeId": emp["employeeId"],
                    "name": emp["name"],
                    "address": emp["cities"]
                }
                for emp in employees_list
            ]
        }

        return format_response(True, "Employees retrieved successfully.", response_data, 200)

    except Exception as e:
        return format_response(False, str(e), status_code=500)
    
@employee_bp.route('/get_salary_slip/<employee_id>', methods=['GET'])
def get_salary_slip(employee_id):
    emp = employees_collection.find_one({'employeeId': employee_id})
    if not emp:
        return jsonify({'success': False, 'message': 'Employee not found'}), 404

    # Prepare data for slip
    emp_data = {
        'full_name': emp.get('name'),
        'doj': datetime.strptime(emp.get('date_of_joining'), '%Y-%m-%d').strftime('%d-%m-%Y'),
        'salary_structure': [
            {'name': 'Basic Pay', 'amount': emp.get('monthly_salary')}
        ],
        'lop': int(request.args.get('lop', 0)),
        'designation': emp.get('designation', ''),
        'department': emp.get('department', ''),
        'emp_no': emp.get('employeeId'),
        'bank_account': emp.get('bank_details', {}).get('account_number', ''),
        'pan': emp.get('pan_number'),
        'company_name': 'Enoylity Studio'
    }

    generator = SalarySlipGenerator(emp_data, current_date=request.args.get('current_date'))
    pdf_buf = generator.generate_pdf()
    return send_file(
        pdf_buf,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f"salary_slip_{employee_id}.pdf"
    )


