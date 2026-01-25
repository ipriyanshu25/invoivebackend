import re
import bcrypt
import logging
from flask import Blueprint, request, abort
from bson import ObjectId
from pymongo import errors as pymongo_errors
from flask_jwt_extended import create_access_token, jwt_required, get_jwt

from utils import format_response
from db import db

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _require_admin():
    claims = get_jwt() or {}
    if (claims.get("role") or "").lower() != "admin":
        raise PermissionError("Admin only")

def create_default_admin():
    """
    Default admin:
      Email: admin@enoylity.com
      Password: Admin@1234
    """
    try:
        default_email = "admin@enoylity.com"
        default_password = "Admin@1234"

        existing = db.admin.find_one({
            "email": {"$regex": f"^{re.escape(default_email)}$", "$options": "i"}
        })

        if not existing:
            hashed = bcrypt.hashpw(default_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            db.admin.insert_one({
                "adminId": str(ObjectId()),
                "email": default_email,
                "password": hashed,
                # Optional: if you ever want zone-limited admin, store zoneIds here.
                # "zoneIds": ["*"]
            })
            logger.info("Default admin created.")
    except pymongo_errors.PyMongoError as e:
        logger.error("Error creating default admin: %s", e)

create_default_admin()

@admin_bp.route("/login", methods=["POST"])
def login_combined():
    """
    Returns JWT token with claims:
      Admin:
        role=admin, zoneIds=["*"] (or admin.zoneIds if present)
      Subadmin:
        role=subadmin, zoneIds=[...], permissions={...}
    """
    try:
        data = request.get_json(force=True) or {}
        email_or_username = (data.get("email") or "").strip()
        password = data.get("password") or ""

        if not email_or_username or not password:
            return format_response(False, "Email/Username and password are required.", None, 400)

        # ---- Admin login ----
        admin = db.admin.find_one({
            "email": {"$regex": f"^{re.escape(email_or_username)}$", "$options": "i"}
        })

        if admin and bcrypt.checkpw(password.encode("utf-8"), admin["password"].encode("utf-8")):
            # admin zones: default all
            admin_zone_ids = admin.get("zoneIds") or ["*"]

            claims = {
                "role": "admin",
                "adminId": admin.get("adminId"),
                "zoneIds": admin_zone_ids
            }

            token = create_access_token(identity=admin.get("adminId"), additional_claims=claims)

            return format_response(True, "Admin login successful.", {
                "role": "admin",
                "adminId": admin.get("adminId"),
                "zoneIds": admin_zone_ids,
                "token": token,
            }, 200)

        # ---- Subadmin login ----
        sub = db.subadmin.find_one({"username": email_or_username})
        if sub and sub.get("password_hash") and __import__("werkzeug.security").security.check_password_hash(sub["password_hash"], password):
            zone_ids = sub.get("zoneIds") or []

            # fallback for old subadmin records -> derive zone from employee
            if not zone_ids:
                emp = db.employees.find_one({"employeeId": sub.get("employeeId")}, {"zoneId": 1})
                if emp and emp.get("zoneId"):
                    zone_ids = [emp["zoneId"]]

            claims = {
                "role": "subadmin",
                "subadminId": sub.get("subadminId"),
                "employeeId": sub.get("employeeId"),
                "permissions": sub.get("permissions", {}),
                "zoneIds": zone_ids
            }

            token = create_access_token(identity=sub.get("subadminId"), additional_claims=claims)

            return format_response(True, "Subadmin login successful.", {
                "role": "subadmin",
                "subadminId": sub.get("subadminId"),
                "employeeId": sub.get("employeeId"),
                "permissions": sub.get("permissions", {}),
                "zoneIds": zone_ids,
                "token": token
            }, 200)

        return format_response(False, "Invalid credentials.", None, 401)

    except pymongo_errors.PyMongoError as e:
        logger.error("Database error during login: %s", e)
        return format_response(False, "Database error occurred.", None, 500)
    except Exception as e:
        logger.exception("Exception during login: %s", e)
        return format_response(False, "Internal server error.", None, 500)

@admin_bp.route("/update", methods=["POST"])
@jwt_required()
def update_admin():
    try:
        _require_admin()
        data = request.get_json(force=True) or {}

        admin_id = (data.get("adminId") or "").strip()
        new_email = (data.get("email") or "").strip()
        new_password = data.get("password") or ""

        if not admin_id:
            return format_response(False, "adminId is required.", None, 400)
        if not new_email or not new_password:
            return format_response(False, "Both email and new password are required.", None, 400)

        conflict = db.admin.find_one({
            "email": {"$regex": f"^{re.escape(new_email)}$", "$options": "i"},
            "adminId": {"$ne": admin_id}
        })
        if conflict:
            return format_response(False, "Another admin with this email already exists.", None, 409)

        pwd_regex = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,16}$"
        if not re.match(pwd_regex, new_password):
            return format_response(False, "Password must be 8-16 chars with upper, lower, number, special char.", None, 400)
        if "gmail" in new_password.lower():
            return format_response(False, "Password should not contain 'gmail'.", None, 400)

        hashed = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        result = db.admin.update_one({"adminId": admin_id}, {"$set": {"email": new_email, "password": hashed}})
        if result.matched_count == 0:
            abort(404)

        updated = db.admin.find_one({"adminId": admin_id}, {"_id": 0, "password": 0})
        return format_response(True, "Admin details updated successfully.", updated, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except pymongo_errors.PyMongoError as e:
        logger.error("Database error during update: %s", e)
        return format_response(False, "Database error occurred.", None, 500)
    except Exception as e:
        logger.exception("Exception during admin update: %s", e)
        return format_response(False, "Internal server error.", None, 500)
