from flask import Blueprint, request
from db import db
from utils import format_response
import os
import random
import string
from datetime import datetime
from pymongo import ReturnDocument
import importlib

# Blueprint setup
settings_bp = Blueprint("settings", __name__, url_prefix="/settings")

# Invoice modules to load default settings from
INVOICE_MODULES = {
    "MHD Tech": "invoiceMHD",  # MHD Tech invoice module
    "Enoylity Studio": "invoiceEnoylity",  # Enoylity Studio invoice module
    "Enoylity Media Creations LLC": "invoiceEnoylityLLC"  # Enoylity Tech invoice module
}

# Default salary slip company information
DEFAULT_SALARY_SLIP_INFO = {
    "company_title":"ENOYLITY MEDIA CREATIONS",
    "company_name": "Enoylity Media Creations Private Limited",
    "address_line1": "Ekam Enclave II, 301A, Ramai Nagar, near Kapil Nagar Square",
    "address_line2": "Nari Road, Nagpur, Maharashtra, India 440026"
}

def generate_unique_id():
    """Generate a unique 16-digit ID"""
    return ''.join(random.choices(string.digits, k=16))

def extract_company_info(module_name):
    try:
        module = importlib.import_module(module_name)
        default_settings = getattr(module, "DEFAULT_SETTINGS", {})

        if module_name == "invoiceMHD":
            # pull company_info, paypal_details and bank_details
            company_info   = default_settings.get("company_info", {})
            paypal_details = default_settings.get("paypal_details", {})
            bank_details   = default_settings.get("bank_details", {})
            return {
                "company_info":   company_info,
                "paypal_details": paypal_details,
                "bank_details":   bank_details
            }

        elif module_name == "invoiceEnoylity":
            company_info = {
                "name":    default_settings.get("company_name", ""),
                "tagline": default_settings.get("company_tagline", ""),
                "address": default_settings.get("company_address", ""),
                "email":   default_settings.get("company_email", ""),
                "phone":   default_settings.get("company_phone", ""),
                "website": default_settings.get("website", "")
            }
            bank_details = default_settings.get("bank_details", {})
            return {
                "company_info":   company_info,
                "bank_details":   bank_details
            }

        elif module_name == "invoiceEnoylityLLC":
            company_info   = default_settings.get("company_info", {})
            paypal_details = default_settings.get("paypal_details", {})
            bank_details   = default_settings.get("bank_details", {})
            return {
                "company_info":   company_info,
                "paypal_details": paypal_details,
                "bank_details":   bank_details
            }

        return {}

    except (ImportError, AttributeError) as e:
        print(f"Error extracting company info from {module_name}: {e}")
        return {}


    except (ImportError, AttributeError) as e:
        print(f"Error extracting company info from {module_name}: {e}")
        return {}
    
def get_or_create_invoice_settings(invoice_type):
    """Get or create settings for an invoice type"""
    # Check if invoice type is valid
    if invoice_type not in INVOICE_MODULES:
        return None
    
    # Try to find existing settings
    settings = db.settings_invoice.find_one({"invoice_type": invoice_type})
    
    if not settings:
        # Create new settings
        module_name = INVOICE_MODULES[invoice_type]
        default_info = extract_company_info(module_name)
        
        settings = {
            "settings_id": generate_unique_id(),
            "invoice_type": invoice_type,
            "created_at": datetime.now(),
            "last_updated": datetime.now(),
            "editable_fields": default_info
        }
        
        # Insert into database
        db.settings_invoice.insert_one(settings)
    
    return settings

def get_or_create_salary_settings():
    """Get or create settings for salary slip"""
    # Try to find existing settings
    settings = db.settings_salary.find_one({"settings_type": "salary_slip"})
    
    if not settings:
        # Create new settings
        settings = {
            "settings_id": generate_unique_id(),
            "settings_type": "salary_slip",
            "created_at": datetime.now(),
            "last_updated": datetime.now(),
            "company_info": DEFAULT_SALARY_SLIP_INFO
        }
        
        # Insert into database
        db.settings_salary.insert_one(settings)
    
    return settings

@settings_bp.route('/getlist', methods=['GET'])
def list_invoice_settings():
    """List all available invoice settings"""
    settings_list = []
    
    for invoice_type in INVOICE_MODULES:
        settings = get_or_create_invoice_settings(invoice_type)
        if settings:
            settings_list.append({
                "settings_id": settings["settings_id"],
                "invoice_type": settings["invoice_type"],
                "last_updated": settings.get("last_updated", "")
            })
    
    return format_response(True, "Invoice settings retrieved", data=settings_list)

@settings_bp.route('/invoice', methods=['GET'])
def get_invoice_settings():
    """Get settings by unique ID via query parameter"""
    settings_id = request.args.get('settings_id')
    if not settings_id:
        return format_response(
            False,
            "Query parameter 'settings_id' is required",
            status=400
        )

    settings = db.settings_invoice.find_one({"settings_id": settings_id})
    if not settings:
        return format_response(
            False,
            f"Settings with ID '{settings_id}' not found",
            status=404
        )

    # Convert ObjectId to string for JSON serialization
    settings["_id"] = str(settings["_id"])

    return format_response(
        True,
        "Settings retrieved successfully",
        data=settings
    )


@settings_bp.route('/invoice', methods=['POST'])
def update_invoice_settings():
    data = request.get_json() or {}

    settings_id = data.get("settings_id")
    if not settings_id:
        return format_response(False, "No settings_id provided", status=400)

    settings = db.settings_invoice.find_one({"settings_id": settings_id})
    if not settings:
        return format_response(False, f"Settings with id '{settings_id}' not found", status=404)

    update_data = {k: v for k, v in data.items() if k != "settings_id"}
    if not update_data:
        return format_response(False, "No update data provided", status=400)

    allowed_updates = {}

    if "company_info" in update_data:
        existing = settings["editable_fields"].get("company_info", {})
        allowed_updates["editable_fields.company_info"] = {**existing, **update_data["company_info"]}

    if "bank_details" in update_data and "bank_details" in settings["editable_fields"]:
        allowed_updates["editable_fields.bank_details"] = update_data["bank_details"]

    if "paypal_details" in update_data and "paypal_details" in settings["editable_fields"]:
        allowed_updates["editable_fields.paypal_details"] = update_data["paypal_details"]

    if not allowed_updates:
        return format_response(False, "No valid editable fields provided", status=400)

    allowed_updates["last_updated"] = datetime.now()

    updated = db.settings_invoice.find_one_and_update(
        {"settings_id": settings_id},
        {"$set": allowed_updates},
        return_document=ReturnDocument.AFTER
    )
    if not updated:
        return format_response(False, "Failed to update settings", status=500)

    updated["_id"] = str(updated["_id"])
    return format_response(True, f"Settings {settings_id} updated", data=updated)

@settings_bp.route('/restore', methods=['POST'])
def restore_default_settings():
    data = request.get_json() or {}

    settings_id = data.get("settings_id")
    if not settings_id:
        return format_response(False, "No settings_id provided", status=400)

    settings = db.settings_invoice.find_one({"settings_id": settings_id})
    if not settings:
        return format_response(False, f"Settings with id '{settings_id}' not found", status=404)

    invoice_type = settings.get("invoice_type")
    module_name = INVOICE_MODULES.get(invoice_type)
    default_info = extract_company_info(module_name)

    result = db.settings_invoice.update_one(
        {"settings_id": settings_id},
        {"$set": {
            "editable_fields": default_info,
            "last_updated": datetime.now()
        }}
    )
    if result.modified_count == 0:
        return format_response(False, "Failed to restore default settings", status=500)

    updated = db.settings_invoice.find_one({"settings_id": settings_id})
    updated["_id"] = str(updated["_id"])
    return format_response(True, f"Default settings restored for {settings_id}", data=updated)


# ======= NEW SALARY SLIP SETTINGS ROUTES =======

@settings_bp.route('/salary', methods=['GET'])
def get_salary_settings():
    """Get salary slip settings"""
    settings = get_or_create_salary_settings()
    
    # Convert ObjectId to string for JSON serialization
    settings["_id"] = str(settings["_id"])
    
    return format_response(
        True,
        "Salary slip settings retrieved successfully",
        data=settings
    )


@settings_bp.route('/salary', methods=['POST'])
def update_salary_settings():
    """Update company info for salary slip settings"""
    data = request.get_json() or {}

    settings_id = data.get("settings_id")
    company_info = data.get("company_info", {})

    if not settings_id:
        return format_response(False, "No settings_id provided", status=400)
    if not company_info:
        return format_response(False, "No company_info provided", status=400)

    # Fetch the existing document using settings_id
    settings = db.settings_salary.find_one({"settings_id": settings_id})
    if not settings:
        return format_response(False, "Settings not found", status=404)

    # Merge the existing company_info with the new one
    existing_info = settings.get("company_info", {})
    updated_info = {**existing_info, **company_info}

    # Update the document in DB
    result = db.settings_salary.update_one(
        {"settings_id": settings_id},
        {"$set": {
            "company_info": updated_info,
            "last_updated": datetime.now()
        }}
    )

    if result.modified_count == 0:
        return format_response(False, "No changes made to settings", status=400)

    updated = db.settings_salary.find_one({"settings_id": settings_id})
    updated["_id"] = str(updated.get("_id"))  # convert _id to string if exists

    return format_response(True, "Salary slip settings updated", data=updated)



@settings_bp.route('/salary/restore', methods=['POST'])
def restore_salary_settings():
    """Restore default salary slip settings"""
    # Update with default settings
    result = db.settings_salary.update_one(
        {"settings_type": "salary_slip"},
        {"$set": {
            "company_info": DEFAULT_SALARY_SLIP_INFO,
            "last_updated": datetime.now()
        }}
    )
    
    if result.modified_count == 0 and result.matched_count == 0:
        return format_response(False, "Failed to restore default salary slip settings", status=500)
    
    # Get updated settings
    updated = db.settings_salary.find_one({"settings_type": "salary_slip"})
    updated["_id"] = str(updated["_id"])
    
    return format_response(True, "Default salary slip settings restored", data=updated)


# Utility functions for invoice modules to access settings
def get_current_settings(invoice_type):
    """Get current settings for invoice generation"""
    settings = get_or_create_invoice_settings(invoice_type)
    if settings:
        return settings.get("editable_fields", {})
    return {}


def get_current_salary_settings():
    """Get current settings for salary slip generation"""
    settings = get_or_create_salary_settings()
    if settings:
        return settings.get("company_info", DEFAULT_SALARY_SLIP_INFO)
    return DEFAULT_SALARY_SLIP_INFO