from flask import Flask, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager
import os
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()

from admin import admin_bp
from subadmin import subadmin_bp
from employee import employee_bp
from kpi import kpi_bp
from zones import zones_bp
from salaryslip import salary_bp
from invoiceMHD import invoice_bp
from invoiceEnoylity import invoice_enoylity_bp
from invoiceEnoylityLLC import enoylity_bp
from settings import settings_bp

app = Flask(__name__)

app.url_map.strict_slashes = False

CORS(
    app,
    resources={r"/*": {"origins": ["https://office.enoylitystudio.com"]}},
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    expose_headers=["Authorization"],
    supports_credentials=False,   # JWT in headers => keep False
    max_age=86400,
)

# ✅ Always answer preflight cleanly
@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        return ("", 204)

# ✅ JWT
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "CHANGE_ME_SUPER_SECRET")
app.config["JWT_TOKEN_LOCATION"] = ["headers"]
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(days=7)
jwt = JWTManager(app)

# ✅ register blueprints
app.register_blueprint(admin_bp)
app.register_blueprint(subadmin_bp)
app.register_blueprint(employee_bp)
app.register_blueprint(kpi_bp)
app.register_blueprint(zones_bp)
app.register_blueprint(salary_bp)
app.register_blueprint(invoice_bp)
app.register_blueprint(invoice_enoylity_bp)
app.register_blueprint(enoylity_bp)
app.register_blueprint(settings_bp)

if __name__ == "__main__":
    app.run(debug=True)