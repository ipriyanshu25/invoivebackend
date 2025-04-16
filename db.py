from pymongo import MongoClient
# MongoDB setup
client = MongoClient('mongodb://localhost:27017/')
db = client['invoice_db']
