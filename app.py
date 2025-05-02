from flask import Flask
from flask_cors import CORS
from admin import admin_bp
from employee import employee_bp
from subadmin import subadmin_bp
from salaryslip import salary_bp
from invoiceMHD import invoice_bp
from invoiceEnoylity import invoice_enoylity_bp
from invoiceEnoylityLLC import enoylity_bp
from settings import settings_bp



app = Flask(__name__)
CORS(app) 



app.register_blueprint(admin_bp)
app.register_blueprint(employee_bp)
app.register_blueprint(subadmin_bp)
app.register_blueprint(salary_bp)
app.register_blueprint(invoice_bp)
app.register_blueprint(invoice_enoylity_bp)
app.register_blueprint(enoylity_bp)
app.register_blueprint(settings_bp)



if __name__ == '__main__':
    app.run(debug=True)