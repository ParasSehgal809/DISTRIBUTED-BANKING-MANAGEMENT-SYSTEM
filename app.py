import sys
import socket
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app import app
from app.config import PORT, DEBUG, COORDINATOR_DB_PATH

def is_port_in_use(port: int) -> bool:
    """Checks if a given port is currently occupied."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0

def get_free_port(preferred_port: int = 5050) -> int:
    """Returns preferred_port if free, otherwise finds the next free port."""
    port = preferred_port
    while is_port_in_use(port) and port < preferred_port + 20:
        port += 1
    return port

if __name__ == "__main__":
    active_port = get_free_port(PORT)
    if active_port != PORT:
        print(f"[!] Warning: Port {PORT} was already in use by another instance.")
        print(f"[*] Automatically switched to port {active_port} to prevent crashes.")
        print(f"[*] To free port {PORT}, you can run: kill -9 $(lsof -ti:{PORT})\n")

    print("=" * 60)
    print("  Distributed Banking Management System (ADBMS Project)")
    print("=" * 60)
    print(f"  Database Engine: MySQL (PyMySQL 127.0.0.1:3306)")
    print(f"  Coordinator DB:  bank_coordinator")
    print(f"  Branch DBs:      bank_branch_br001, bank_branch_br002, bank_branch_br003")
    print(f"  Web Dashboard:   http://127.0.0.1:{active_port}")
    print("=" * 60)

    # use_reloader=False inside debugger to prevent reloader subprocess port collisions
    app.run(host="0.0.0.0", port=active_port, debug=DEBUG, use_reloader=False)
