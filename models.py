from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

# Association Table for Multi-Business Shared Expenses (V1.2)
expense_allocations = db.Table('expense_allocations',
    db.Column('expense_id', db.Integer, db.ForeignKey('expense.id'), primary_key=True),
    db.Column('business_unit_id', db.Integer, db.ForeignKey('business_unit.id'), primary_key=True)
)

class BusinessUnit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, default=True)

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(50))
    location = db.Column(db.String(255))
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)

class ProductionBatch(db.Model):
    """Tracks field crop batches for Fancy Lettuce, Iceberg Lettuce, and Celery."""
    id = db.Column(db.Integer, primary_key=True)
    batch_code = db.Column(db.String(50), unique=True, nullable=False)
    unit_id = db.Column(db.Integer, db.ForeignKey('business_unit.id'), nullable=False)
    planting_date = db.Column(db.Date, nullable=False, default=lambda: datetime.utcnow().date())
    quantity_planted = db.Column(db.Integer, nullable=False)
    planted_unit = db.Column(db.String(50), nullable=False, default="seedlings")
    estimated_remaining_quantity = db.Column(db.Integer, nullable=False)  # saleable heads or stalks
    expected_harvest_date = db.Column(db.Date, nullable=True)
    expected_yield = db.Column(db.Integer, nullable=True)  # informational only
    status = db.Column(db.String(20), nullable=False, default="growing")  # growing, harvesting, completed, cancelled
    last_estimate_review_date = db.Column(db.Date, nullable=False, default=lambda: datetime.utcnow().date())
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    business_unit = db.relationship('BusinessUnit', backref='batches')

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    unit_id = db.Column(db.Integer, db.ForeignKey('business_unit.id'), nullable=False)
    batch_id = db.Column(db.Integer, db.ForeignKey('production_batch.id'), nullable=True)
    quantity = db.Column(db.Float, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    notes = db.Column(db.String(255))
    is_voided = db.Column(db.Boolean, default=False)
    
    customer = db.relationship('Customer', backref='sales')
    business_unit = db.relationship('BusinessUnit')
    batch = db.relationship('ProductionBatch', backref='sales')

class HarvestLot(db.Model):
    """Tracks cut-to-order harvest events and occasional cut surplus."""
    id = db.Column(db.Integer, primary_key=True)
    harvest_date = db.Column(db.DateTime, default=datetime.utcnow)
    batch_id = db.Column(db.Integer, db.ForeignKey('production_batch.id'), nullable=False)
    sale_id = db.Column(db.Integer, db.ForeignKey('sale.id'), nullable=True)
    quantity_harvested = db.Column(db.Integer, nullable=False)
    quantity_sold = db.Column(db.Integer, nullable=False)
    quantity_surplus = db.Column(db.Integer, nullable=False, default=0)
    quantity_remaining = db.Column(db.Integer, nullable=False, default=0)
    notes = db.Column(db.String(255), nullable=True)
    is_voided = db.Column(db.Boolean, default=False)

    batch = db.relationship('ProductionBatch', backref='harvest_lots')
    sale = db.relationship('Sale', backref=db.backref('harvest_lot', uselist=False))

class InventoryMovement(db.Model):
    """Auditable log of surplus creation, waste, spoilage, and void reversals."""
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    harvest_lot_id = db.Column(db.Integer, db.ForeignKey('harvest_lot.id'), nullable=False)
    movement_type = db.Column(db.String(30), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(255), nullable=True)

    harvest_lot = db.relationship('HarvestLot', backref='movements')

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    notes = db.Column(db.String(255))
    is_voided = db.Column(db.Boolean, default=False)
    
    customer = db.relationship('Customer', backref='payments')

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(255))
    unit_id = db.Column(db.Integer, db.ForeignKey('business_unit.id'), nullable=True)
    scope = db.Column(db.String(20), default='unallocated')
    allocated_units = db.relationship('BusinessUnit', secondary=expense_allocations, backref='shared_expenses')
    is_voided = db.Column(db.Boolean, default=False)
    business_unit = db.relationship('BusinessUnit')