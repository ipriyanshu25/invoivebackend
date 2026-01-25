import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, request
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import jwt_required, get_jwt, create_access_token

from db import db
from utils import format_response

subadmin_bp = Blueprint("subadmin", __name__, url_prefix="/subadmin")
UTC = ZoneInfo("UTC")

PERMISSIONS = {
    "View payslip details":     "View payslip details",
    "Generate payslip":         "Generate payslip",
    "View Invoice details":     "View Invoice details",
    "Generate invoice details": "Generate invoice details",
    "Add Employee Details":     "Add Employee details",
    "View Employee Details":    "View employee details",
    "Manage KPI":               "Manage KPI",
    "KPI":                      "KPI",
}

PASSWORD_REGEX = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$")

def _now_utc():
    return datetime.now(UTC)

def _require_admin():
    claims = get_jwt() or {}
    if (claims.get("role") or "").lower() != "admin":
        raise PermissionError("Admin only")

def _validate_zone_ids(zone_ids: list[str]) -> bool:
    if not isinstance(zone_ids, list) or not zone_ids:
        return False
    count = db.zones.count_documents({"zoneId": {"$in": zone_ids}, "isActive": True})
    return count == len(zone_ids)

@subadmin_bp.route("/register", methods=["POST"])
@jwt_required()
def register_subadmin():
    try:
        _require_admin()
        data = request.get_json(force=True) or {}

        employee_id = (data.get("employeeid") or "").strip()
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        perms = data.get("permissions", {}) or {}
        zone_ids = data.get("zoneIds")  # optional

        if not all([employee_id, username, password]):
            return format_response(False, "Missing fields: employeeid, username, password", None, 400)

        if not PASSWORD_REGEX.match(password):
            return format_response(False, "Password must include upper, lower, number, special char (min 8).", None, 400)

        # verify employee exists + has zoneId
        emp = db.employees.find_one({"employeeId": employee_id}, {"zoneId": 1})
        if not emp:
            return format_response(False, "No such employee", None, 404)

        emp_zone = emp.get("zoneId")
        if not emp_zone:
            return format_response(False, "Employee has no zoneId assigned", None, 400)

        # default zoneIds to employee zone if not provided
        if not zone_ids:
            zone_ids = [emp_zone]

        if not _validate_zone_ids(zone_ids):
            return format_response(False, "One or more zoneIds invalid/inactive", None, 400)

        # ensure no existing subadmin for this employee
        if db.subadmin.find_one({"employeeId": employee_id}):
            return format_response(False, "Subadmin already exists for this employee", None, 409)

        if db.subadmin.find_one({"username": username}):
            return format_response(False, "Username already taken", None, 409)

        pw_hash = generate_password_hash(password)
        permission_flags = {k: int(bool(perms.get(k))) for k in PERMISSIONS.keys()}

        subadmin_id = str(uuid.uuid4())
        now = _now_utc()

        db.subadmin.insert_one({
            "subadminId": subadmin_id,
            "employeeId": employee_id,
            "username": username,
            "password_hash": pw_hash,
            "permissions": permission_flags,
            "zoneIds": zone_ids,
            "isActive": True,
            "createdAt": now,
            "updatedAt": now
        })

        return format_response(True, "Subadmin registered", {"subadminId": subadmin_id}, 201)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except Exception:
        return format_response(False, "Internal server error", None, 500)

@subadmin_bp.route("/updaterecord", methods=["POST"])
@jwt_required()
def update_subadmin():
    try:
        _require_admin()
        data = request.get_json(force=True) or {}
        subadmin_id = (data.get("subadminId") or "").strip()
        updates = data.get("updates", {}) or {}

        if not subadmin_id:
            return format_response(False, "subadminId is required", None, 400)

        existing = db.subadmin.find_one({"subadminId": subadmin_id})
        if not existing:
            return format_response(False, "Subadmin not found", None, 404)

        update_fields = {}

        if "username" in updates:
            new_username = (updates.get("username") or "").strip()
            if not new_username:
                return format_response(False, "username cannot be empty", None, 400)
            clash = db.subadmin.find_one({"username": new_username, "subadminId": {"$ne": subadmin_id}})
            if clash:
                return format_response(False, "Username already in use", None, 409)
            update_fields["username"] = new_username

        if "password" in updates:
            new_password = updates.get("password") or ""
            if not PASSWORD_REGEX.match(new_password):
                return format_response(False, "Password must include upper, lower, number, special char (min 8).", None, 400)
            update_fields["password_hash"] = generate_password_hash(new_password)

        if "permissions" in updates:
            perms = updates.get("permissions") or {}
            update_fields["permissions"] = {k: int(bool(perms.get(k))) for k in PERMISSIONS.keys()}

        if "zoneIds" in updates:
            zone_ids = updates.get("zoneIds")
            if not _validate_zone_ids(zone_ids):
                return format_response(False, "One or more zoneIds invalid/inactive", None, 400)
            update_fields["zoneIds"] = zone_ids

        if "isActive" in updates:
            update_fields["isActive"] = bool(updates["isActive"])

        if not update_fields:
            return format_response(False, "No valid fields to update", None, 400)

        update_fields["updatedAt"] = _now_utc()

        db.subadmin.update_one({"subadminId": subadmin_id}, {"$set": update_fields})
        return format_response(True, "Subadmin updated successfully", None, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except Exception:
        return format_response(False, "Internal server error", None, 500)

@subadmin_bp.route("/deleterecord", methods=["POST"])
@jwt_required()
def delete_subadmin():
    try:
        _require_admin()
        data = request.get_json(force=True) or {}
        subadmin_id = (data.get("subadminId") or "").strip()
        if not subadmin_id:
            return format_response(False, "subadminId is required", None, 400)

        res = db.subadmin.delete_one({"subadminId": subadmin_id})
        if not res.deleted_count:
            return format_response(False, "Subadmin not found", None, 404)

        return format_response(True, "Subadmin deleted", None, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except Exception:
        return format_response(False, "Internal server error", None, 500)

@subadmin_bp.route("/getlist", methods=["POST"])
@jwt_required()
def get_subadmin_list():
    try:
        _require_admin()
        data = request.get_json(force=True) or {}
        page = max(int(data.get("page", 1)), 1)
        page_size = max(int(data.get("pageSize", 10)), 1)
        search = (data.get("search") or "").strip()

        query = {}
        if search:
            query["$or"] = [
                {"username": {"$regex": re.escape(search), "$options": "i"}},
                {"employeeId": {"$regex": re.escape(search), "$options": "i"}},
                {"subadminId": {"$regex": re.escape(search), "$options": "i"}},
            ]

        total = db.subadmin.count_documents(query)
        cursor = (db.subadmin.find(query, {"_id": 0, "password_hash": 0})
                  .skip((page - 1) * page_size)
                  .limit(page_size))

        return format_response(True, "Subadmin list fetched", {
            "subadmins": list(cursor),
            "total": total,
            "page": page,
            "pageSize": page_size
        }, 200)

    except PermissionError as e:
        return format_response(False, str(e), None, 403)
    except Exception:
        return format_response(False, "Internal server error", None, 500)

@subadmin_bp.route("/login", methods=["POST"])
def login_subadmin():
    try:
        data = request.get_json(force=True) or {}
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""

        if not username or not password:
            return format_response(False, "Missing username or password", None, 400)

        user = db.subadmin.find_one({"username": username, "isActive": True})
        if not user or not check_password_hash(user["password_hash"], password):
            return format_response(False, "Invalid credentials", None, 401)

        zone_ids = user.get("zoneIds") or []
        if not zone_ids:
            emp = db.employees.find_one({"employeeId": user.get("employeeId")}, {"zoneId": 1})
            if emp and emp.get("zoneId"):
                zone_ids = [emp["zoneId"]]

        claims = {
            "role": "subadmin",
            "subadminId": user.get("subadminId"),
            "employeeId": user.get("employeeId"),
            "permissions": user.get("permissions", {}),
            "zoneIds": zone_ids
        }

        token = create_access_token(identity=user.get("subadminId"), additional_claims=claims)

        return format_response(True, "Login successful", {
            "role": "subadmin",
            "subadminId": user.get("subadminId"),
            "employeeId": user.get("employeeId"),
            "permissions": user.get("permissions", {}),
            "zoneIds": zone_ids,
            "token": token
        }, 200)

    except Exception:
        return format_response(False, "Internal server error", None, 500)
