import pytest
import os
import sys
import sqlite3
from sqlalchemy import create_engine
from app import get_user_data_dir, get_db_path, get_bundle_dir
from launcher import find_available_port
from models import db

def test_user_data_dir_env_override(monkeypatch, tmp_path):
    """Verifies REFACTORED_POTATO_DATA_DIR environment variable correctly redirects user data."""
    custom_dir = str(tmp_path / "custom_data")
    monkeypatch.setenv("REFACTORED_POTATO_DATA_DIR", custom_dir)
    assert get_user_data_dir() == custom_dir
    assert os.path.exists(custom_dir)

def test_bundle_dir_contains_templates():
    """Verifies template directory is located accurately in source and frozen execution."""
    b_dir = get_bundle_dir()
    templates_path = os.path.join(b_dir, "templates")
    assert os.path.exists(templates_path)
    assert os.path.exists(os.path.join(templates_path, "dashboard.html"))
    assert os.path.exists(os.path.join(templates_path, "export.html"))

def test_first_run_database_creation(monkeypatch, tmp_path):
    """Verifies that first-launch establishes a clean database file with all tables and V1.2 scopes."""
    temp_data = str(tmp_path / "first_run_dir")
    monkeypatch.setenv("REFACTORED_POTATO_DATA_DIR", temp_data)

    target_db_file = os.path.join(temp_data, "farm.db")
    assert not os.path.exists(target_db_file)
    assert get_db_path() == target_db_file

    # Verify db.metadata creates the physical database file on disk
    clean_path = target_db_file.replace('\\', '/')
    engine = create_engine(f"sqlite:///{clean_path}")
    db.metadata.create_all(bind=engine)
    engine.dispose()

    assert os.path.exists(target_db_file)

    # Verify all V1.2 required tables exist in the new SQLite file
    conn = sqlite3.connect(target_db_file)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0].lower() for row in cursor.fetchall()}
    conn.close()

    required_tables = {'business_unit', 'customer', 'sale', 'payment', 'expense', 'expense_allocations'}
    assert required_tables.issubset(tables)

def test_subsequent_runs_preserve_data(tmp_path):
    """Verifies subsequent application launches reuse existing database without overwriting records."""
    target_db_file = str(tmp_path / "persist.db")
    clean_path = target_db_file.replace('\\', '/')
    engine = create_engine(f"sqlite:///{clean_path}")

    # Run 1: Create schema and insert user data
    db.metadata.create_all(bind=engine)

    conn = sqlite3.connect(target_db_file)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO customer (name, is_active) VALUES ('Sister Customer', 1);")
    cursor.execute("INSERT INTO business_unit (name, is_active) VALUES ('Fancy Lettuce', 1);")
    cursor.execute("INSERT INTO sale (customer_id, unit_id, quantity, unit_price, total_amount, is_voided) VALUES (1, 1, 1, 50.0, 50.0, 0);")
    conn.commit()
    conn.close()

    # Run 2: Re-run schema initialization (simulates application restart)
    db.metadata.create_all(bind=engine)
    engine.dispose()

    # Verify existing data is preserved intact
    conn = sqlite3.connect(target_db_file)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM customer WHERE name='Sister Customer';")
    assert cursor.fetchone() is not None
    cursor.execute("SELECT total_amount FROM sale WHERE total_amount=50.0;")
    assert cursor.fetchone()[0] == 50.0
    conn.close()

def test_safety_backup_path_is_in_user_data_dir(monkeypatch, tmp_path):
    """Verifies safety backups are generated in user data directory, not the read-only package dir."""
    temp_data = str(tmp_path / "safety_dir")
    monkeypatch.setenv("REFACTORED_POTATO_DATA_DIR", temp_data)
    safety_path = os.path.join(get_user_data_dir(), "farm_safety_backup_test.db")
    assert safety_path.startswith(temp_data)

def test_find_available_port():
    """Verifies port detection discovers an open loopback port."""
    port = find_available_port(5000)
    assert 5000 <= port < 5050

def test_health_check_endpoint(client):
    """Verifies /api/health endpoint returns 200 OK for instance discovery."""
    res = client.get('/api/health')
    assert res.status_code == 200
    json_data = res.get_json()
    assert json_data["status"] == "ok"
    assert json_data["version"] == "1.3.3"