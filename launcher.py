"""
Refactored Potato — Desktop Application Launcher (V1.3.3)
Manages single-instance lifecycle, dynamic loopback port reservation, and browser launch.
"""
import sys
import os
import socket
import webbrowser
import threading
import time
import json
import urllib.request
import signal
from app import app, init_db, get_user_data_dir, get_db_path

def find_available_port(start_port=5000, max_attempts=50):
    """Finds an available TCP port on loopback (127.0.0.1)."""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"Could not bind to any port in range {start_port}-{start_port + max_attempts}")

def get_running_instance_port(data_dir):
    """Detects if Refactored Potato is already running by querying its health endpoint."""
    info_file = os.path.join(data_dir, "instance.json")
    if not os.path.exists(info_file):
        return None
    try:
        with open(info_file, 'r') as f:
            data = json.load(f)
        port = data.get("port")
        if not port:
            return None
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/health", headers={'User-Agent': 'RefactoredPotatoLauncher'})
        with urllib.request.urlopen(req, timeout=1.2) as resp:
            if resp.status == 200:
                return port
    except Exception:
        # Instance file was stale or process died
        pass
    return None

def write_instance_file(data_dir, port):
    info_file = os.path.join(data_dir, "instance.json")
    try:
        with open(info_file, 'w') as f:
            json.dump({"port": port, "pid": os.getpid(), "started": time.time()}, f)
    except Exception:
        pass

def remove_instance_file(data_dir):
    info_file = os.path.join(data_dir, "instance.json")
    try:
        if os.path.exists(info_file):
            os.remove(info_file)
    except Exception:
        pass

def main():
    data_dir = get_user_data_dir()
    db_path = get_db_path()

    print("=" * 60)
    print(" Refactored Potato — Farm Business Management")
    print("=" * 60)
    print(f" Data Directory: {data_dir}")
    print(f" Database File:  {db_path}")

    # Check for single-instance
    running_port = get_running_instance_port(data_dir)
    if running_port:
        print(f"\n[INFO] Refactored Potato is already running on port {running_port}!")
        print("Opening existing application in your browser...")
        webbrowser.open(f"http://127.0.0.1:{running_port}/")
        time.sleep(1.5)
        sys.exit(0)

    # First-run safe database initialization
    print("\n[INFO] Verifying database schema...")
    try:
        init_db(app)
        print("[SUCCESS] Database is ready.")
    except Exception as e:
        print(f"\n[CRITICAL ERROR] Failed to initialize database: {e}")
        input("\nPress Enter to exit...")
        sys.exit(1)

    port = find_available_port(5000)
    app_url = f"http://127.0.0.1:{port}/"

    write_instance_file(data_dir, port)

    def open_browser():
        time.sleep(1.2)
        webbrowser.open(app_url)

    threading.Thread(target=open_browser, daemon=True).start()

    print(f"\n Server running at: {app_url}")
    print(" Loopback binding:  127.0.0.1 (Local only)")
    print("\n Keep this window open while using the application.")
    print(" To close: Close this window or press Ctrl+C.")
    print("=" * 60 + "\n")

    def cleanup(signum=None, frame=None):
        remove_instance_file(data_dir)
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, cleanup)

    try:
        app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)
    finally:
        remove_instance_file(data_dir)

if __name__ == '__main__':
    main()