import pytest
import os
import tempfile
import sqlite3
from io import BytesIO
from app import validate_backup, create_backup_to_file

def test_backup_validation_healthy(app, seed_data):
    """Verifies the validation engine correctly identifies a healthy V1.2 schema database."""
    fd, temp_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    
    try:
        # Create a real backup of the seeded test database
        with app.app_context():
            create_backup_to_file(temp_path)
            
        is_valid, msg = validate_backup(temp_path)
        assert is_valid is True
        assert msg == "Valid"
    finally:
        os.remove(temp_path)

def test_backup_validation_corrupted():
    """Verifies the engine rejects non-SQLite or corrupted files safely."""
    fd, temp_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)  # <-- Added this to release the initial Windows file lock
    
    with open(temp_path, 'w') as f:
        f.write("This is not a database. This is a text file.")
        
    try:
        is_valid, msg = validate_backup(temp_path)
        assert is_valid is False
        assert "Not a valid SQLite database" in msg
    finally:
        os.remove(temp_path)

def test_backup_validation_missing_schema():
    """Verifies the engine rejects an empty SQLite database (missing V1.2 tables)."""
    fd, temp_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    
    try:
        # Initialize empty sqlite DB
        conn = sqlite3.connect(temp_path)
        conn.close()
        
        is_valid, msg = validate_backup(temp_path)
        assert is_valid is False
        assert "Missing required tables" in msg
        assert "expense_allocations" in msg
    finally:
        os.remove(temp_path)

def test_download_backup_route(client):
    """Verifies the backup download route generates and returns a valid file attachment."""
    response = client.post('/backup/download')
    
    assert response.status_code == 200
    assert response.headers['Content-Disposition'].startswith('attachment;')
    assert 'refactored_potato_backup_' in response.headers['Content-Disposition']
    # Ensure the downloaded bytes have the standard SQLite header
    assert response.data.startswith(b'SQLite format 3')

def test_restore_backup_safeguards(client):
    """Verifies the restore route gracefully rejects missing or empty file uploads."""
    # 1. No file part
    response1 = client.post('/backup/restore', data={})
    assert response1.status_code == 302 # Redirects back to settings
    
    # 2. Empty filename
    response2 = client.post('/backup/restore', data={'backup_file': (BytesIO(b""), "")})
    assert response2.status_code == 302