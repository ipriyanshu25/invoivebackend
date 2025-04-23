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
    "MHD": "invoice",  # MHD Tech invoice module
    "Enoylity Studio": "invoiceEnoylity",  # Enoylity Studio invoice module
    "Enoylity Tech": "invoiceenoylitytech"  # Enoylity Tech invoice module
}

def generate_unique_id():
    """Generate a unique 16-digit ID"""
    return ''.join(random.choices(string.digits, k=16))

def extract_company_info(module_name):
    """Extract company info from the specified invoice module"""
    try:
        module = importlib.import_module(module_name)
        
        # Handle different structure based on module
        if module_name == "invoice":
            # MHD Tech
            return {"company_info": module.DEFAULT_SETTINGS.get("company_info", {})}
        
        elif module_name == "invoiceEnoylity":
            # Enoylity Studio
            company_details = module.COMPANY_DETAILS
            return {
                "company_info": {
                    "name": company_details.get("company_name", ""),
                    "tagline": company_details.get("company_tagline", ""),
                    "address": company_details.get("company_address", ""),
                    "email": company_details.get("company_email", ""),
                    "phone": company_details.get("company_phone", ""),
                    "website": company_details.get("website", "")
                },
                "bank_details": company_details.get("bank_details", "")
            }
        
        elif module_name == "invoiceenoylitytech":
            # Enoylity Tech
            return {"company_info": module.COMPANY_INFO}
        
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
    """Update editable fields for a specific invoice settings document by settings_id"""
    data = request.get_json() or {}

    # 1. Extract the settings_id from the body
    settings_id = data.get("settings_id")
    if not settings_id:
        return format_response(False, "No settings_id provided", status=400)

    # 2. Load the existing settings doc
    settings = db.settings_invoice.find_one({"settings_id": settings_id})
    if not settings:
        return format_response(False, f"Settings with id '{settings_id}' not found", status=404)

    # 3. Gather update data (everything except settings_id)
    update_data = {k: v for k, v in data.items() if k != "settings_id"}
    if not update_data:
        return format_response(False, "No update data provided", status=400)

    allowed_updates = {}

    # 4. Merge in company_info if provided
    if "company_info" in update_data:
        existing = settings["editable_fields"].get("company_info", {})
        allowed_updates["editable_fields.company_info"] = {**existing, **update_data["company_info"]}

    # 5. Overwrite bank_details if provided
    if "bank_details" in update_data and "bank_details" in settings["editable_fields"]:
        allowed_updates["editable_fields.bank_details"] = update_data["bank_details"]

    if not allowed_updates:
        return format_response(False, "No valid editable fields provided", status=400)

    # 6. Stamp with current time
    allowed_updates["last_updated"] = datetime.now()

    # 7. Persist changes
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


# Utility functions for invoice modules to access settings
def get_current_settings(invoice_type):
    """Get current settings for invoice generation"""
    settings = get_or_create_invoice_settings(invoice_type)
    if settings:
        return settings.get("editable_fields", {})
    return {}