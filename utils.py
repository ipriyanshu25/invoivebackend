# Centralized Response Formatter

from flask import jsonify,Blueprint
utils_bp = Blueprint('utils', __name__, url_prefix="/util")


def format_response(success: bool, message: str, data=None, status: int = 200):
    """
    Constructs a standardized API response.

    Args:
        success (bool): Indicator whether the operation succeeded.
        message (str): A descriptive message about the response.
        data: Additional payload (optional).
        status (int): HTTP status code.

    Returns:
        tuple: Flask JSON response with status code.
    """
    response = {
        "success": success,
        "message": message,
        "data": data,
        "status": status
    }
    return jsonify(response), status



@utils_bp.errorhandler(404)
def resource_not_found(e):
    return format_response(False, "Resource not found.", None, 404)

# Global Error Handler: Internal Server Error
@utils_bp.errorhandler(500)
def internal_error(e):
    return format_response(False, "Internal server error.", None, 500)