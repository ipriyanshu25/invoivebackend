import re
import bcrypt
import logging
from flask import Blueprint, request, jsonify
from pymongo import MongoClient, errors as pymongo_errors
from bson import ObjectId
from utils import format_response
from db import db

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# Configure logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_default_admin():
    try:
        default_email = "admin@enoylity.com"
        default_password = "Admin@1234"
        # Use case-insensitive query to check for existence.
        existing_admin = db.admin.find_one({
            'email': {'$regex': f'^{re.escape(default_email)}$', '$options': 'i'}
        })
        if not existing_admin:
            hashed_password = bcrypt.hashpw(
                default_password.encode('utf-8'), 
                bcrypt.gensalt()
            ).decode('utf-8')
            admin_data = {
                "adminId": str(ObjectId()),
                "email": default_email,
                "password": hashed_password
            }
            db.admin.insert_one(admin_data)
            logger.info("Default admin created.")
    except pymongo_errors.PyMongoError as e:
        logger.error("Error creating default admin: %s", e)

create_default_admin()

@admin_bp.route("/login", methods=["POST"])
def login_admin():
    try:
        input_data = request.get_json()
        if not input_data:
            return format_response(False, "Missing JSON payload.", None, 400)

        email = input_data.get('email')
        password = input_data.get('password')

        if not email or not password:
            return format_response(False, "Email and password are required.", None, 400)

        # Use a case-insensitive regex query to find the admin.
        query = {'email': {'$regex': f'^{re.escape(email)}$', '$options': 'i'}}
        admin = db.admin.find_one(query)
        if admin and bcrypt.checkpw(password.encode('utf-8'), admin['password'].encode('utf-8')):
            # Remove sensitive data before sending the response.
            admin.pop('_id', None)
            admin.pop('password', None)
            admin['role'] = "admin"
            return format_response(True, "Login successful", admin, 200)
        else:
            return format_response(False, "Invalid email or password", None, 404)

    except Exception as e:
        logger.exception("Exception during login: %s", e)
        return format_response(False, "Internal server error.", None, 500)

@admin_bp.route("/update", methods=["POST"])
def update_admin():
    try:
        data = request.get_json() or {}
        admin_id = data.get("adminId")
        if not admin_id:
            return format_response(False, "adminId is required.", None, 400)

        if "email" not in data or "password" not in data:
            return format_response(False, "Both email and new password are required for update.", None, 400)

        new_email = data.get("email")
        new_password = data.get("password")
        update_fields = {"email": new_email}

        # Check for email uniqueness excluding the current admin (case-insensitive).
        query = {
            "email": {'$regex': f'^{re.escape(new_email)}$', '$options': 'i'},
            "adminId": {"$ne": admin_id}
        }
        existing_admin = db.admin.find_one(query)
        if existing_admin:
            return format_response(False, "Another admin with this email already exists.", None, 404)

        # Validate the new password using regex.
        password_regex = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,16}$"
        if not re.match(password_regex, new_password):
            return format_response(
                False, 
                "Password must be 8-16 characters and include uppercase, lowercase, a number, and a special character.", 
                None, 
                400
            )
        if "gmail" in new_password.lower():
            return format_response(False, "Password should not contain 'gmail'.", None, 400)

        # Hash the new password
        hashed_password = bcrypt.hashpw(
            new_password.encode('utf-8'), 
            bcrypt.gensalt()
        ).decode('utf-8')
        update_fields["password"] = hashed_password

        result = db.admin.update_one({"adminId": admin_id}, {"$set": update_fields})
        if result.matched_count == 0:
            return format_response(False, "Admin not found.", None, 404)

        updated_admin = db.admin.find_one(
            {"adminId": admin_id}, 
            {"_id": 0, "password": 0}
        )
        return format_response(True, "Admin details updated successfully.", updated_admin, 200)
    
    except pymongo_errors.PyMongoError as e:
        logger.error("Database error during update: %s", e)
        return format_response(False, "Database error occurred.", None, 500)
    except Exception as e:
        logger.exception("Exception during admin update: %s", e)
        return format_response(False, "Internal server error.", None, 500)