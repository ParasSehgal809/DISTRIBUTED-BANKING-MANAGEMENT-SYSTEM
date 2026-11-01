import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

# Database Backend Toggle: 'mysql' or 'sqlite'
DB_BACKEND = os.environ.get("DB_BACKEND", "mysql")

# MySQL Configuration (Multi-Database Distributed Topology)
MYSQL_CONFIG = {
    "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("MYSQL_PORT", 3306)),
    "user": os.environ.get("MYSQL_USER", "root"),
    "password": os.environ.get("MYSQL_PASSWORD", ""),
    "coordinator_db": "bank_coordinator",
}

# Central Coordinator Node SQLite Database (Fallback)
COORDINATOR_DB_PATH = DATA_DIR / "central_coordinator.db"

# Branch Database Configurations (Distributed Nodes)
BRANCHES = {
    "BR001": {
        "branch_id": "BR001",
        "name": "Downtown Central Branch",
        "code": "DT-01",
        "city": "Metropolis Downtown",
        "mysql_database": "bank_branch_br001",
        "db_filename": "branch_BR001.db",
        "db_path": DATA_DIR / "branch_BR001.db",
        "color": "blue",
        "status": "ONLINE"
    },
    "BR002": {
        "branch_id": "BR002",
        "name": "Midtown Financial Branch",
        "code": "MT-02",
        "city": "Financial District",
        "mysql_database": "bank_branch_br002",
        "db_filename": "branch_BR002.db",
        "db_path": DATA_DIR / "branch_BR002.db",
        "color": "emerald",
        "status": "ONLINE"
    },
    "BR003": {
        "branch_id": "BR003",
        "name": "Uptown Tech Park Branch",
        "code": "UT-03",
        "city": "Silicon Boulevard",
        "mysql_database": "bank_branch_br003",
        "db_filename": "branch_BR003.db",
        "db_path": DATA_DIR / "branch_BR003.db",
        "color": "purple",
        "status": "ONLINE"
    }
}

# Roles for RBAC
ROLE_ADMIN = "ADMIN"
ROLE_BRANCH_MANAGER = "BRANCH_MANAGER"
ROLE_TELLER = "TELLER"
ROLE_CUSTOMER = "CUSTOMER"

VALID_ROLES = [ROLE_ADMIN, ROLE_BRANCH_MANAGER, ROLE_TELLER, ROLE_CUSTOMER]

# Application Settings
SECRET_KEY = os.environ.get("SECRET_KEY", "adbms-distributed-banking-secret-key-2026")
PORT = int(os.environ.get("PORT", 5050))
DEBUG = True
