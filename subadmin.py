import re
import random
import string
from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from db import db  # MongoDB connection for employees, subadmin, admin collections

# Blueprint for subadmin routes
subadmin_bp = Blueprint('subadmin', __name__, url_prefix='/subadmin')

# Permission mapping: JSON field -> human-readable
PERMISSIONS = {
    'View payslip details': 'View payslip details',
    'Generate payslip': 'Generate payslip',
    'View Invoice details': 'View Invoice details',
    'Generate invoice details': 'Generate invoice details',
    'Add Employee Details': 'Add Employee details',
    'View Employee Details': 'View employee details',
}

# Password complexity: uppercase, lowercase, digit, special char, min length 8
PASSWORD_REGEX = re.compile(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$')
def generate_unique_subadmin_id():
    while True:
        subadmin_id = ''.join(random.choices(string.digits, k=16))
        if not db.subadmin.find_one({'subadminId': subadmin_id}):
            return subadmin_id

@subadmin_bp.route('/register', methods=['POST'])
def register_subadmin():
    data = request.get_json() or {}
    admin_id    = data.get('adminid')
    employee_id = data.get('employeeid')
    username    = data.get('username')
    password    = data.get('password')
    perms       = data.get('permissions', {})

    # Required fields
    if not all([admin_id, employee_id, username, password]):
        return jsonify({'error': 'Missing required fields: adminid, employeeid, username, or password'}), 400

    # Validate admin exists
    if not db.admin.find_one({'adminId': admin_id}):
        return jsonify({'error': 'Invalid adminId'}), 403

    # Validate password complexity
    if not PASSWORD_REGEX.match(password):
        return jsonify({'error': 'Password must be at least 8 chars and include uppercase, lowercase, number, special char'}), 400

    # Ensure employee exists
    if not db.employees.find_one({'employeeId': employee_id}):
        return jsonify({'error': 'No such employee'}), 404

    # Check if subadmin already created for this employee
    if db.subadmin.find_one({'employeeId': employee_id}):
        return jsonify({'error': 'Subadmin credentials already exist for this employee, please login'}), 409

    # Ensure unique username
    if db.subadmin.find_one({'username': username}):
        return jsonify({'error': 'Username already taken'}), 409

    # Generate unique 16-digit subadmin ID
    subadmin_id = generate_unique_subadmin_id()

    # Hash password
    pw_hash = generate_password_hash(password)

    # Store permission flags (0/1)
    permission_flags = { key: int(bool(perms.get(key))) for key in PERMISSIONS.keys() }

    # Insert subadmin document
    db.subadmin.insert_one({
        'subadminId': subadmin_id,
        'employeeId': employee_id,
        'username': username,
        'password_hash': pw_hash,
        'permissions': permission_flags
    })

    return jsonify({'message': 'Subadmin registered successfully', 'subadminId': subadmin_id}), 201

@subadmin_bp.route('/login', methods=['POST'])
def login_subadmin():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')

    if not all([username, password]):
        return jsonify({'error': 'Missing username or password'}), 400

    user = db.subadmin.find_one({'username': username})
    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({'error': 'Invalid credentials'}), 401

    # Return subadminId, role, and raw permission flags
    return jsonify({
        'subadminId': user.get('subadminId'),
        'role': 'subadmin',
        'permissions': user.get('permissions', {})
    }), 200