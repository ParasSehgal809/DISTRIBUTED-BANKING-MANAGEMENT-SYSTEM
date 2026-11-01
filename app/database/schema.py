from app.config import BRANCHES, COORDINATOR_DB_PATH, DB_BACKEND, MYSQL_CONFIG
from app.database.connection import get_coordinator_connection, get_branch_connection

# =====================================================================
# MySQL Schemas (InnoDB Engine for Strict ACID & Row Locks)
# =====================================================================

COORDINATOR_SCHEMA_MYSQL = """
CREATE TABLE IF NOT EXISTS branches (
    branch_id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    code VARCHAR(32) NOT NULL UNIQUE,
    city VARCHAR(128) NOT NULL,
    db_filename VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ONLINE',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS global_users (
    user_id VARCHAR(64) PRIMARY KEY,
    username VARCHAR(64) NOT NULL UNIQUE,
    email VARCHAR(128) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(32) NOT NULL,
    branch_id VARCHAR(32),
    customer_id VARCHAR(64),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS customers_global (
    customer_id VARCHAR(64) PRIMARY KEY,
    full_name VARCHAR(128) NOT NULL,
    email VARCHAR(128) NOT NULL UNIQUE,
    phone VARCHAR(32) NOT NULL,
    gov_id_type VARCHAR(32) NOT NULL,
    gov_id_number VARCHAR(64) NOT NULL UNIQUE,
    home_address TEXT NOT NULL,
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS global_account_directory (
    account_number VARCHAR(64) PRIMARY KEY,
    customer_id VARCHAR(64) NOT NULL,
    branch_id VARCHAR(32) NOT NULL,
    account_type VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers_global(customer_id) ON DELETE CASCADE,
    FOREIGN KEY (branch_id) REFERENCES branches(branch_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS global_loans (
    loan_id VARCHAR(64) PRIMARY KEY,
    customer_id VARCHAR(64) NOT NULL,
    branch_id VARCHAR(32) NOT NULL,
    account_number VARCHAR(64) NOT NULL,
    requested_amount DOUBLE NOT NULL,
    approved_amount DOUBLE DEFAULT 0.0,
    interest_rate DOUBLE NOT NULL,
    duration_months INT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    purpose VARCHAR(255) NOT NULL,
    reviewed_by VARCHAR(64),
    review_comments TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers_global(customer_id) ON DELETE CASCADE,
    FOREIGN KEY (branch_id) REFERENCES branches(branch_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS coordinator_wal (
    tx_id VARCHAR(64) PRIMARY KEY,
    tx_type VARCHAR(64) NOT NULL,
    state VARCHAR(32) NOT NULL,
    source_branch VARCHAR(32),
    dest_branch VARCHAR(32),
    source_account VARCHAR(64),
    dest_account VARCHAR(64),
    amount DOUBLE,
    payload_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS global_locks (
    lock_id VARCHAR(64) PRIMARY KEY,
    resource_id VARCHAR(64) NOT NULL,
    tx_id VARCHAR(64) NOT NULL,
    lock_type VARCHAR(8) NOT NULL,
    owner VARCHAR(64) NOT NULL,
    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS audit_logs (
    log_id INT AUTO_INCREMENT PRIMARY KEY,
    actor_username VARCHAR(64) NOT NULL,
    actor_role VARCHAR(32) NOT NULL,
    action VARCHAR(64) NOT NULL,
    branch_id VARCHAR(32),
    details TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
"""

BRANCH_SCHEMA_MYSQL = """
CREATE TABLE IF NOT EXISTS branch_meta (
    branch_id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    city VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ONLINE'
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS customers_local (
    customer_id VARCHAR(64) PRIMARY KEY,
    kyc_status VARCHAR(32) NOT NULL DEFAULT 'VERIFIED',
    credit_score INT NOT NULL DEFAULT 700,
    occupation VARCHAR(128) NOT NULL,
    annual_income DOUBLE NOT NULL,
    risk_rating VARCHAR(32) NOT NULL DEFAULT 'LOW',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS accounts (
    account_number VARCHAR(64) PRIMARY KEY,
    customer_id VARCHAR(64) NOT NULL,
    branch_id VARCHAR(32) NOT NULL,
    account_type VARCHAR(32) NOT NULL,
    balance DOUBLE NOT NULL,
    currency VARCHAR(8) NOT NULL DEFAULT 'USD',
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    version INT NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_balance CHECK (balance >= 0.0)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS transactions (
    tx_id VARCHAR(64) PRIMARY KEY,
    global_tx_id VARCHAR(64),
    account_number VARCHAR(64) NOT NULL,
    type VARCHAR(32) NOT NULL,
    amount DOUBLE NOT NULL,
    balance_after DOUBLE NOT NULL,
    related_account VARCHAR(64),
    related_branch VARCHAR(32),
    description VARCHAR(255),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_number) REFERENCES accounts(account_number) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS branch_wal (
    wal_id INT AUTO_INCREMENT PRIMARY KEY,
    tx_id VARCHAR(64) NOT NULL,
    state VARCHAR(32) NOT NULL,
    account_number VARCHAR(64) NOT NULL,
    delta DOUBLE NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
"""

# =====================================================================
# SQLite Schemas (Fallback)
# =====================================================================

COORDINATOR_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS branches (
    branch_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,
    city TEXT NOT NULL,
    db_filename TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ONLINE',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS global_users (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    branch_id TEXT,
    customer_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS customers_global (
    customer_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT NOT NULL,
    gov_id_type TEXT NOT NULL,
    gov_id_number TEXT NOT NULL UNIQUE,
    home_address TEXT NOT NULL,
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS global_account_directory (
    account_number TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    account_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers_global(customer_id),
    FOREIGN KEY (branch_id) REFERENCES branches(branch_id)
);

CREATE TABLE IF NOT EXISTS global_loans (
    loan_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    account_number TEXT NOT NULL,
    requested_amount REAL NOT NULL,
    approved_amount REAL DEFAULT 0.0,
    interest_rate REAL NOT NULL,
    duration_months INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    purpose TEXT NOT NULL,
    reviewed_by TEXT,
    review_comments TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers_global(customer_id),
    FOREIGN KEY (branch_id) REFERENCES branches(branch_id)
);

CREATE TABLE IF NOT EXISTS coordinator_wal (
    tx_id TEXT PRIMARY KEY,
    tx_type TEXT NOT NULL,
    state TEXT NOT NULL,
    source_branch TEXT,
    dest_branch TEXT,
    source_account TEXT,
    dest_account TEXT,
    amount REAL,
    payload_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS global_locks (
    lock_id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL,
    tx_id TEXT NOT NULL,
    lock_type TEXT NOT NULL,
    owner TEXT NOT NULL,
    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_username TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    action TEXT NOT NULL,
    branch_id TEXT,
    details TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

BRANCH_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS branch_meta (
    branch_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ONLINE'
);

CREATE TABLE IF NOT EXISTS customers_local (
    customer_id TEXT PRIMARY KEY,
    kyc_status TEXT NOT NULL DEFAULT 'VERIFIED',
    credit_score INTEGER NOT NULL DEFAULT 700,
    occupation TEXT NOT NULL,
    annual_income REAL NOT NULL,
    risk_rating TEXT NOT NULL DEFAULT 'LOW',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS accounts (
    account_number TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    account_type TEXT NOT NULL,
    balance REAL NOT NULL CHECK(balance >= 0.0),
    currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
    tx_id TEXT PRIMARY KEY,
    global_tx_id TEXT,
    account_number TEXT NOT NULL,
    type TEXT NOT NULL,
    amount REAL NOT NULL,
    balance_after REAL NOT NULL,
    related_account TEXT,
    related_branch TEXT,
    description TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_number) REFERENCES accounts(account_number)
);

CREATE TABLE IF NOT EXISTS branch_wal (
    wal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_id TEXT NOT NULL,
    state TEXT NOT NULL,
    account_number TEXT NOT NULL,
    delta REAL NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def ensure_mysql_databases_exist():
    """Ensures the 4 MySQL databases exist on the MySQL server."""
    if DB_BACKEND != "mysql":
        return
    import pymysql
    root_conn = pymysql.connect(
        host=MYSQL_CONFIG["host"],
        port=MYSQL_CONFIG["port"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        autocommit=True
    )
    try:
        with root_conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{MYSQL_CONFIG['coordinator_db']}` CHARACTER SET utf8mb4;")
            for b in BRANCHES.values():
                db_name = b.get("mysql_database", f"bank_branch_{b['branch_id'].lower()}")
                cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4;")
    finally:
        root_conn.close()


def init_all_databases():
    """Initializes schema on Coordinator and all Branch databases (MySQL or SQLite)."""
    if DB_BACKEND == "mysql":
        ensure_mysql_databases_exist()
        coord_schema = COORDINATOR_SCHEMA_MYSQL
        branch_schema = BRANCH_SCHEMA_MYSQL
    else:
        coord_schema = COORDINATOR_SCHEMA_SQLITE
        branch_schema = BRANCH_SCHEMA_SQLITE

    # 1. Initialize Central Coordinator
    coord_conn = get_coordinator_connection()
    try:
        coord_conn.executescript(coord_schema)
        coord_conn.commit()
    finally:
        coord_conn.close()

    # 2. Initialize Each Branch Database
    for b_id, b_info in BRANCHES.items():
        branch_conn = get_branch_connection(b_id)
        try:
            branch_conn.executescript(branch_schema)
            # Ensure branch_meta is populated
            branch_conn.execute(
                "REPLACE INTO branch_meta (branch_id, name, city, status) VALUES (?, ?, ?, ?)",
                (b_id, b_info["name"], b_info["city"], b_info["status"])
            )
            branch_conn.commit()
        finally:
            branch_conn.close()


if __name__ == "__main__":
    init_all_databases()
    print(f"[+] All distributed databases initialized successfully using {DB_BACKEND.upper()} backend.")
