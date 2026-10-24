from models import db, Sale, Payment, Expense
from app import get_customer_balance

def test_customer_balance_calculation(app, seed_data):
    """Test Case: Sales increase debt, Payments decrease debt."""
    customer = seed_data['customer']
    lettuce = seed_data['lettuce']
    
    # 1. Customer buys $100 of lettuce on credit
    sale = Sale(customer_id=customer.id, unit_id=lettuce.id, quantity=10, unit_price=10.0, total_amount=100.0)
    db.session.add(sale)
    db.session.commit()
    
    assert get_customer_balance(customer.id) == 100.0
    
    # 2. Customer pays $40
    payment = Payment(customer_id=customer.id, amount=40.0)
    db.session.add(payment)
    db.session.commit()
    
    assert get_customer_balance(customer.id) == 60.0

def test_voided_transactions_ignored(app, seed_data):
    """Test Case: Voided sales and payments should not affect balances."""
    customer = seed_data['customer']
    lettuce = seed_data['lettuce']
    
    # Record a $500 sale, but mark it as voided (like clicking Void in the ledger)
    sale = Sale(customer_id=customer.id, unit_id=lettuce.id, quantity=1, unit_price=500.0, total_amount=500.0, is_voided=True)
    db.session.add(sale)
    db.session.commit()
    
    # Balance should be 0 because the sale is voided
    assert get_customer_balance(customer.id) == 0.0

def test_v1_2_expense_scopes(app, seed_data):
    """Test Case: Verify specific vs shared expenses are stored correctly."""
    lettuce = seed_data['lettuce']
    celery = seed_data['celery']
    
    # 1. Direct Expense ($40 for Lettuce)
    direct_exp = Expense(amount=40.0, category="Fertilizer", scope="specific")
    direct_exp.allocated_units.append(lettuce)
    db.session.add(direct_exp)
    
    # 2. Shared Expense ($300 for both)
    shared_exp = Expense(amount=300.0, category="Transport", scope="shared")
    shared_exp.allocated_units.extend([lettuce, celery])
    db.session.add(shared_exp)
    
    db.session.commit()
    
    # Verify Direct Expense
    saved_direct = Expense.query.filter_by(scope="specific").first()
    assert saved_direct.amount == 40.0
    assert len(saved_direct.allocated_units) == 1
    assert saved_direct.allocated_units[0].name == "Lettuce"
    
    # Verify Shared Expense
    saved_shared = Expense.query.filter_by(scope="shared").first()
    assert saved_shared.amount == 300.0
    assert len(saved_shared.allocated_units) == 2