from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class BusinessUnit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False) # e.g., "Fancy Lettuce"
    is_active = db.Column(db.Boolean, default=True)

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    # Balance is calculated dynamically to prevent data corruption

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    unit_id = db.Column(db.Integer, db.ForeignKey('business_unit.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    notes = db.Column(db.String(255))
    
    customer = db.relationship('Customer', backref='sales')
    business_unit = db.relationship('BusinessUnit')

class Payment(db.Model):
    """Tracks actual cash received from customers"""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    notes = db.Column(db.String(255))
    
    customer = db.relationship('Customer', backref='payments')

class Expense(db.Model):
    """Tracks money leaving the business"""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False) # e.g., Fertilizer, Seed, Sweet
    description = db.Column(db.String(255))
    
    # If null, it is a "Shared/General" expense. Otherwise, tied to a product.
    unit_id = db.Column(db.Integer, db.ForeignKey('business_unit.id'), nullable=True)
    business_unit = db.relationship('BusinessUnit')