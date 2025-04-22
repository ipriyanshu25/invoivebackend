import re
import uuid
from flask import Blueprint, request
from werkzeug.security import generate_password_hash, check_password_hash
from db import db  # MongoDB connection for employees, subadmin, admin collections
from utils import format_response

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


@subadmin_bp.route('/register', methods=['POST'])
def register_subadmin():
    try:
        data = request.get_json() or {}
        admin_id    = data.get('adminid')
        employee_id = data.get('employeeid')
        username    = data.get('username')
        password    = data.get('password')
        perms       = data.get('permissions', {})

        if not all([admin_id, employee_id, username, password]):
            return format_response(False,
                                   'Missing required fields: adminid, employeeid, username, or password',
                                   status=400)

        if not db.admin.find_one({'adminId': admin_id}):
            return format_response(False, 'Invalid adminId', status=403)

        if not PASSWORD_REGEX.match(password):
            return format_response(False,
                                   'Password must be at least 8 chars and include uppercase, lowercase, number, special char',
                                   status=400)

        if not db.employees.find_one({'employeeId': employee_id}):
            return format_response(False, 'No such employee', status=404)

        if db.subadmin.find_one({'employeeId': employee_id}):
            return format_response(False,
                                   'Subadmin credentials already exist for this employee, please login',
                                   status=409)

        if db.subadmin.find_one({'username': username}):
            return format_response(False, 'Username already taken', status=409)

        pw_hash = generate_password_hash(password)
        permission_flags = { key: int(bool(perms.get(key))) for key in PERMISSIONS.keys() }
        subadmin_id = str(uuid.uuid4())

        db.subadmin.insert_one({
            'subadminId': subadmin_id,
            'employeeId': employee_id,
            'username': username,
            'password_hash': pw_hash,
            'permissions': permission_flags
        })

        return format_response(True,
                               'Subadmin registered successfully',
                               data={'subadminId': subadmin_id})

    except Exception:
        return format_response(False, 'Internal server error', status=500)


@subadmin_bp.route('/updaterecord', methods=['POST'])
def update_subadmin():
    try:
        data = request.get_json() or {}
        subadmin_id = data.get('subadminId')
        updates = data.get('updates', {})

        if not subadmin_id:
            return format_response(False, 'subadminId is required', status=400)

        existing = db.subadmin.find_one({'subadminId': subadmin_id})
        if not existing:
            return format_response(False, 'Subadmin not found', status=404)

        update_fields = {}

        if 'username' in updates:
            new_username = updates['username']
            if db.subadmin.find_one({'username': new_username, 'subadminId': {'$ne': subadmin_id}}):
                return format_response(False, 'Username already in use', status=409)
            update_fields['username'] = new_username

        if 'password' in updates:
            new_password = updates['password']
            if not PASSWORD_REGEX.match(new_password):
                return format_response(False,
                                       'Password must be at least 8 chars and include uppercase, lowercase, number, special char',
                                       status=400)
            update_fields['password_hash'] = generate_password_hash(new_password)

        if 'permissions' in updates:
            perms = updates['permissions']
            update_fields['permissions'] = { key: int(bool(perms.get(key))) for key in PERMISSIONS.keys() }

        if not update_fields:
            return format_response(False, 'No valid fields to update', status=400)

        db.subadmin.update_one({'subadminId': subadmin_id}, {'$set': update_fields})
        return format_response(True, 'Subadmin updated successfully')

    except Exception:
        return format_response(False, 'Internal server error', status=500)


@subadmin_bp.route('/deleterecord', methods=['POST'])
def delete_subadmin():
    try:
        data = request.get_json() or {}
        subadmin_id = data.get('subadminId')

        if not subadmin_id:
            return format_response(False, 'subadminId is required', status=400)

        result = db.subadmin.delete_one({'subadminId': subadmin_id})
        if result.deleted_count == 0:
            return format_response(False, 'Subadmin not found', status=404)

        return format_response(True, 'Subadmin deleted successfully')

    except Exception:
        return format_response(False, 'Internal server error', status=500)


@subadmin_bp.route('/getlist', methods=['POST'])
def get_subadmin_list():
    try:
        data = request.get_json() or {}
        page = int(data.get('page', 1))
        page_size = int(data.get('pageSize', 10))
        search = (data.get('search') or '').strip()

        query = {}
        if search:
            query['$or'] = [
                {'username': {'$regex': search, '$options': 'i'}},
                {'employeeId': {'$regex': search, '$options': 'i'}}
            ]

        total = db.subadmin.count_documents(query)
        subadmins = list(
            db.subadmin.find(query, {'_id': 0, 'password_hash': 0})
                       .skip((page - 1) * page_size)
                       .limit(page_size)
        )

        payload = {
            'subadmins': subadmins,
            'total': total,
            'page': page,
            'pageSize': page_size
        }
        return format_response(True, 'Subadmin list retrieved successfully', data=payload)

    except Exception:
        return format_response(False, 'Internal server error', status=500)


@subadmin_bp.route('/login', methods=['POST'])
def login_subadmin():
    try:
        data = request.get_json() or {}
        username = data.get('username')
        password = data.get('password')

        if not all([username, password]):
            return format_response(False, 'Missing username or password', status=400)

        user = db.subadmin.find_one({'username': username})
        if not user or not check_password_hash(user['password_hash'], password):
            return format_response(False, 'Invalid credentials', status=401)

        resp = {
            'role': 'subadmin',
            'permissions': user.get('permissions', {})
        }
        return format_response(True, 'Login successful', data=resp)

    except Exception:
        return format_response(False, 'Internal server error', status=500)
