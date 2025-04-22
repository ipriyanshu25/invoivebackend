import re
import bcrypt
import logging
from flask import Blueprint, request, abort
from werkzeug.security import check_password_hash
from bson import ObjectId
from pymongo import errors as pymongo_errors
from utils import format_response
from db import db

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# Configure logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_default_admin():
    """
    Ensures a default admin exists.
    Email: admin@enoylity.com, Password: Admin@1234
    """
    try:
        default_email = "admin@enoylity.com"
        default_password = "Admin@1234"
        existing = db.admin.find_one({
            'email': {'$regex': f'^{re.escape(default_email)}$', '$options': 'i'}
        })
        if not existing:
            hashed = bcrypt.hashpw(
                default_password.encode('utf-8'), bcrypt.gensalt()
            ).decode('utf-8')
            db.admin.insert_one({
                "adminId": str(ObjectId()),
                "email": default_email,
                "password": hashed
            })
            logger.info("Default admin created.")
    except pymongo_errors.PyMongoError as e:
        logger.error("Error creating default admin: %s", e)


create_default_admin()

@admin_bp.route("/login", methods=["POST"])
def login_combined():
    try:
        data = request.get_json(force=True)
        email_or_username = data.get('email')
        password = data.get('password')

        if not email_or_username or not password:
            return format_response(False, "Email/Username and password are required.", None, 400)

        # Attempt Admin login
        admin = db.admin.find_one({
            'email': {'$regex': f'^{re.escape(email_or_username)}$', '$options': 'i'}
        })
        if admin and bcrypt.checkpw(password.encode('utf-8'), admin['password'].encode('utf-8')):
            admin.pop('_id', None)
            admin.pop('password', None)
            admin['role'] = 'admin'
            return format_response(True, "Admin login successful.", admin, 200)

        # Attempt Subadmin login
        sub = db.subadmin.find_one({'username': email_or_username})
        if sub and check_password_hash(sub['password_hash'], password):
            sub.pop('_id', None)
            sub.pop('password_hash', None)
            sub['role'] = 'subadmin'
            return format_response(True, "Subadmin login successful.", sub, 200)

        # Invalid credentials
        return format_response(False, "Invalid credentials.", None, 401)

    except pymongo_errors.PyMongoError as e:
        logger.error("Database error during login: %s", e)
        return format_response(False, "Database error occurred.", None, 500)
    except Exception as e:
        logger.exception("Exception during login: %s", e)
        return format_response(False, "Internal server error.", None, 500)


@admin_bp.route("/update", methods=["POST"])
def update_admin():
    try:
        data = request.get_json(force=True) or {}
        admin_id = data.get('adminId')
        new_email = data.get('email')
        new_password = data.get('password')

        if not admin_id:
            return format_response(False, "adminId is required.", None, 400)
        if not new_email or not new_password:
            return format_response(False, "Both email and new password are required.", None, 400)

        # Check email uniqueness excluding current admin
        conflict = db.admin.find_one({
            'email': {'$regex': f'^{re.escape(new_email)}$', '$options': 'i'},
            'adminId': {'$ne': admin_id}
        })
        if conflict:
            return format_response(False, "Another admin with this email already exists.", None, 409)

        # Validate password strength
        pwd_regex = r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,16}$'
        if not re.match(pwd_regex, new_password):
            return format_response(
                False,
                "Password must be 8-16 characters with uppercase, lowercase, number, and special character.",
                None,
                400
            )
        if 'gmail' in new_password.lower():
            return format_response(False, "Password should not contain 'gmail'.", None, 400)

        # Hash and update
        hashed = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        result = db.admin.update_one(
            {'adminId': admin_id},
            {'$set': {'email': new_email, 'password': hashed}}
        )
        if result.matched_count == 0:
            abort(404)

        updated = db.admin.find_one(
            {'adminId': admin_id},
            {'_id': 0, 'password': 0, 'password_hash': 0}
        )
        return format_response(True, "Admin details updated successfully.", updated, 200)

    except pymongo_errors.PyMongoError as e:
        logger.error("Database error during update: %s", e)
        return format_response(False, "Database error occurred.", None, 500)
    except Exception as e:
        logger.exception("Exception during admin update: %s", e)
        return format_response(False, "Internal server error.", None, 500)
