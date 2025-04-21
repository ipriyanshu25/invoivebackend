from flask import Flask,Blueprint
from flask_cors import CORS
from employee import employee_bp
from salaryslip import salary_bp
from admin import admin_bp
from invoice import invoice_bp
from subadmin import subadmin_bp

app = Flask(__name__)
CORS(app)
app.register_blueprint(employee_bp)
app.register_blueprint(salary_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(invoice_bp)
app.register_blueprint(subadmin_bp)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
