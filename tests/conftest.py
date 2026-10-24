import pytest
import sys
import os

# This tells Python to look in the folder above this one for app.py
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app as flask_app
from models import db, BusinessUnit, Customer

@pytest.fixture
def app():
    """Sets up a temporary application and database for testing."""
    # Use a temporary in-memory database
    flask_app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"
    })
    
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    """A test client that can make 'fake' web requests to our routes."""
    return app.test_client()

@pytest.fixture
def seed_data(app):
    """Adds some basic test data before each test runs."""
    unit1 = BusinessUnit(name="Lettuce")
    unit2 = BusinessUnit(name="Celery")
    customer = Customer(name="Restaurant ABC")
    
    db.session.add_all([unit1, unit2, customer])
    db.session.commit()
    
    return {"lettuce": unit1, "celery": unit2, "customer": customer}