# Distributed Banking Management System (OmniBank)
### Advanced Database Management Systems (ADBMS) Mini Project

A production-grade simulation of a **Distributed Banking Management System** where multiple branch nodes maintain separate, autonomous relational databases but share customer and transaction information via a centralized coordinator catalog, distributed query processor, two-phase commit (2PC) engine, and distributed lock manager.

---

## 🌟 Key Highlights & ADBMS Concepts Implemented

| ADBMS Concept | Implementation in this Project |
| :--- | :--- |
| **Distributed Architecture** | 1 Central Coordinator (`bank_coordinator` MySQL DB) + 3 Autonomous Branch Nodes (`bank_branch_br001`, `bank_branch_br002`, `bank_branch_br003` MySQL DBs). |
| **Horizontal Fragmentation** | `Accounts` and `Transactions` tables partitioned horizontally by `branch_id`. Global reconstruction via `UNION ALL`. |
| **Vertical Fragmentation** | `Customer` relation split into Fragment 1 (Central Demographics) and Fragment 2 (Branch Financial/KYC Profile). Reconstructed via Distributed Join (`⨝`). |
| **Data Allocation & Catalog** | Global Data Dictionary (GDD) and directory routing index resolving account numbers to physical MySQL branch schemas. |
| **Distributed Query Processing** | Query decomposition, data localization, predicate pushdown, distributed partitioned aggregation (`SUM`, `AVG`, `COUNT`), and visual execution plans. |
| **Transaction Management (ACID)** | Strict ACID guarantees across local and cross-branch transactions using MySQL InnoDB engine. |
| **Two-Phase Commit (2PC)** | Full state machine (`PREPARING`, `PREPARED`, `COMMITTING`, `COMMITTED`, `ABORTED`) with participant voting, WAL logging, and interactive failure injection. |
| **Concurrency Control (Strict 2PL)** | Distributed Lock Manager (DLM) supporting Shared (`S`) and Exclusive (`X`) locks with Strict 2-Phase Locking to eliminate cascading aborts. |
| **Deadlock Management** | Dynamic **Wait-For Graph (WFG)** with Depth-First Search (DFS) cycle detection and automated victim selection (youngest transaction abort). |
| **Database Recovery (WAL)** | Write-Ahead Logging on Coordinator and Branches, with REDO/UNDO crash recovery and in-doubt 2PC resolution. |
| **Role-Based Access Control (RBAC)** | Role permissions enforced for `ADMIN`, `BRANCH_MANAGER`, `TELLER`, and `CUSTOMER`. |

---

## 🏗️ Distributed Multi-Database Topology (MySQL 8+ InnoDB Cluster)

```text
                           ┌──────────────────────────────────────────────┐
                           │      CENTRAL COORDINATOR NODE                │
                           │      MySQL Schema: bank_coordinator          │
                           │                                              │
                           │  - Global Data Dictionary (GDD)              │
                           │  - Global Users & RBAC Directory             │
                           │  - Vertical Fragment 1: customers_global     │
                           │  - Global Account Directory (Routing Table)  │
                           │  - Global Loans Directory                    │
                           │  - 2PC Coordinator Log (coordinator_wal)    │
                           │  - Global Lock Registry (global_locks)       │
                           │  - Central Audit Trail (audit_logs)          │
                           └──────────────────────┬───────────────────────┘
                                                  │
                 ┌────────────────────────────────┼────────────────────────────────┐
                 │ RPC / 2PC Phase 1 & 2          │ Distributed Queries            │ Local WAL Replay
                 ▼                                ▼                                ▼
   ┌───────────────────────────┐    ┌───────────────────────────┐    ┌───────────────────────────┐
   │       BRANCH NODE 1       │    │       BRANCH NODE 2       │    │       BRANCH NODE 3       │
   │  MySQL: bank_branch_br001 │    │  MySQL: bank_branch_br002 │    │  MySQL: bank_branch_br003 │
   │  Downtown Central Branch  │    │ Midtown Financial Branch  │    │  Uptown Tech Park Branch  │
   ├───────────────────────────┤    ├───────────────────────────┤    ├───────────────────────────┤
   │ • Horizontal Fragment:    │    │ • Horizontal Fragment:    │    │ • Horizontal Fragment:    │
   │   Accounts (BR001)        │    │   Accounts (BR002)        │    │   Accounts (BR003)        │
   │ • Vertical Fragment 2:    │    │ • Vertical Fragment 2:    │    │ • Vertical Fragment 2:    │
   │   customers_local (BR001) │    │   customers_local (BR002) │    │   customers_local (BR003) │
   │ • Local Ledger:           │    │ • Local Ledger:           │    │ • Local Ledger:           │
   │   transactions            │    │   transactions            │    │   transactions            │
   │ • Participant 2PC WAL:    │    │ • Participant 2PC WAL:    │    │ • Participant 2PC WAL:    │
   │   branch_wal              │    │   branch_wal              │    │   branch_wal              │
   └───────────────────────────┘    └───────────────────────────┘    └───────────────────────────┘
```

---

## 🚀 How to Run in VS Code

### Quick Start (1-Click in Terminal)
1. Open Terminal in VS Code (`Ctrl + ~` or `Cmd + ~`).
2. Run the launch script:
   ```bash
   ./run.sh
   ```
3. Open your browser at: **`http://127.0.0.1:5050`**

### Running via VS Code Debugger (F5)
1. Open the project folder in VS Code:
   `File` &rarr; `Open Folder...` &rarr; Select `/Users/parassehgal/Documents/distributed_banking_system`
2. Press **`F5`** (or open the **Run & Debug** tab on the left and click **"Python: Distributed Banking System"**).
3. The server starts up and logs the multi-node cluster status in the terminal.

---

## 🔑 Pre-Seeded Users & RBAC Roles

The system has quick-switch buttons right in the navigation bar and login screen:

| Role | Username | Password | Assigned Branch | Scope of Access |
| :--- | :--- | :--- | :--- | :--- |
| **ADMIN** | `admin` | `admin123` | Global | Full control: all branches, 2PC failure simulations, DLM, Deadlock tool, audit logs, system reset. |
| **BRANCH_MANAGER** | `mgr_downtown` | `manager123` | `BR001` | Downtown branch operations, KYC updates, loan review & approval. |
| **BRANCH_MANAGER** | `mgr_midtown` | `manager123` | `BR002` | Midtown branch operations, commercial loan evaluations. |
| **BRANCH_MANAGER** | `mgr_uptown` | `manager123` | `BR003` | Uptown branch operations, tech startup credit evaluations. |
| **TELLER** | `teller_downtown`| `teller123` | `BR001` | Front-desk cash deposits, withdrawals, customer onboarding, transfers. |
| **CUSTOMER** | `alice` | `customer123` | `BR001` | Self-service: view own accounts (`ACC-1001`, `ACC-1002`), initiate transfers, apply for loans. |
| **CUSTOMER** | `bob` | `customer123` | `BR001` & `BR003` | Multi-branch customer owning accounts in both Downtown and Uptown branches. |

---

## 🧩 Project Modules

### 1. Customer Management (`/customers`)
- **Vertical Fragmentation**:
  - Demographics are stored on the Central Coordinator in `customers_global`.
  - Financial Profile, Credit Score, and KYC Status are stored in the local branch database in `customers_local`.
- **Reconstruction Algorithm**:
  $$\text{Customer} = \text{customers\_global} \bowtie_{\text{customer\_id}} \text{customers\_local}$$
- Shows side-by-side SQL fragments and schemas.

### 2. Multiple Branch Management (`/branches`)
- Live inspection of all 3 autonomous branch database nodes.
- Ability to view raw table records for `accounts`, `customers_local`, `transactions`, and `branch_wal`.
- Ability to simulate a node going offline / coming online.

### 3. Account Management (`/accounts`)
- **Horizontal Fragmentation**:
  - $\text{Accounts}_{\text{BR001}} = \sigma_{\text{branch\_id} = '\text{BR001}'}(\text{Accounts})$
  - $\text{Accounts}_{\text{BR002}} = \sigma_{\text{branch\_id} = '\text{BR002}'}(\text{Accounts})$
  - $\text{Accounts}_{\text{BR003}} = \sigma_{\text{branch\_id} = '\text{BR003}'}(\text{Accounts})$
- Global reconstruction:
  $$\text{Accounts} = \text{Accounts}_{\text{BR001}} \cup \text{Accounts}_{\text{BR002}} \cup \text{Accounts}_{\text{BR003}}$$
- Features cash deposit and cash withdrawal with Strict 2PL exclusive locks.

### 4. Money Transfer & Live Two-Phase Commit Visualizer (`/transfer`)
- **Intra-Branch Transfer**: When source and destination accounts are in the same branch, executes locally as a single ACID transaction.
- **Cross-Branch Transfer**: When accounts reside on different branch nodes, activates the **Two-Phase Commit Coordinator**:
  - **Phase 1 (Prepare)**: Coordinator logs `PREPARING` in central WAL, sends prepare request to both branch nodes, branches acquire Exclusive Locks via DLM, check balance invariants, and write `PREPARED` to local WAL.
  - **Decision Point**: All commit $\to$ Coordinator writes `GLOBAL_COMMIT`. Any abort $\to$ `GLOBAL_ABORT`.
  - **Phase 2 (Commit/Abort)**: Dispatches decision, participants update balances, write `COMMITTED` to local WAL, and release Strict 2PL locks.
- **Failure Injection Options**:
  - Simulate Source Node Failure on Prepare.
  - Simulate Destination Node Timeout on Prepare.
  - Simulate Coordinator Crash before Commit (In-doubt state).
  - Insufficient funds abort.

### 5. Loan Management & Distributed Credit Evaluation (`/loans`)
- Customer submits loan application at any branch.
- **Distributed Evaluation**: Coordinator dispatches parallel subqueries across *all 3 branch databases* to calculate total deposits held by the applicant across the entire bank before computing debt-to-income and asset coverage ratios.
- Approval and Automated Disbursement into the customer's branch account.

### 6. Distributed Query Console (`/query-console`)
- Interactive query runner demonstrating:
  1. **Distributed Partitioned Aggregation**: Pushes local `SUM(balance)` and `COUNT(*)` down to branches, then combines partial sums into global liquidity.
  2. **Predicate Pushdown Search**: Pushes filter `WHERE balance >= $X` down to branch nodes to minimize network transmission.
  3. **Global Ledger Audit**: Distributed search across all branch transaction ledgers.
- Visual **Execution Plan** showing operator trees, timings (ms), and network bytes transferred.

### 7. ADBMS Interactive Lab (`/adbms-lab`)
- **Distributed Lock Manager (DLM)**: Real-time table of Shared (`S`) and Exclusive (`X`) locks, Strict 2PL testing.
- **Deadlock Management (Wait-For Graph)**: Generates a synthetic circular wait ($T_1 \to T_2 \to T_1$), visualizes the cycle, and resolves it by aborting the youngest victim transaction.
- **Database Crash Recovery**: Injects an in-doubt transaction into the WAL, simulates coordinator crash, and executes REDO / UNDO recovery.

---

## 🧪 Automated Test Suite

Run the full automated test suite anytime:
```bash
./venv/bin/python tests/run_all_tests.py
```
Output:
```text
test_2pc_abort_insufficient_funds ... ok
test_2pc_failure_simulation_rollback ... ok
test_successful_2pc_transfer ... ok
test_deadlock_cycle_detection ... ok
test_deadlock_resolution_victim_selection ... ok
test_distributed_partitioned_aggregation ... ok
test_predicate_pushdown_search ... ok
test_horizontal_fragmentation_isolation ... ok
test_horizontal_reconstruction_union ... ok
test_vertical_reconstruction_join ... ok
----------------------------------------------------------------------
Ran 10 tests in 1.34s - OK
[+] All ADBMS unit and integration tests passed successfully!
```

---

## 🎓 Viva / Presentation Q&A Cheat Sheet

1. **Q: Why multiple SQLite files instead of one big database?**
   - **A:** Multiple independent database files (`central_coordinator.db`, `branch_BR001.db`, `branch_BR002.db`, `branch_BR003.db`) faithfully model autonomous distributed database sites with separate disk files, separate WAL logs, and separate connection pools, satisfying distributed database architecture requirements without needing multi-server infrastructure.

2. **Q: How is Horizontal Fragmentation implemented?**
   - **A:** The `accounts` table is partitioned using the predicate `branch_id = :b_id`. Each branch database only stores its own branch's accounts. Global queries perform a distributed `UNION ALL` across all branch databases.

3. **Q: How is Vertical Fragmentation implemented?**
   - **A:** The `Customer` relation is split vertically:
     - Identity attributes (`full_name`, `email`, `phone`, `gov_id_number`) are stored in `central_coordinator.db`.
     - Financial/KYC attributes (`credit_score`, `kyc_status`, `occupation`, `annual_income`) are stored in the local branch database.
     - Reconstruction is performed via a distributed join on `customer_id`.

4. **Q: What is the role of Two-Phase Commit (2PC)?**
   - **A:** When transferring money across branches, both branch databases must either commit together or abort together. 2PC guarantees Atomicity across autonomous nodes through the Prepare Phase (voting + locking + WAL log) and Commit/Abort Phase (enacting decision).

5. **Q: How does Concurrency Control avoid cascading aborts?**
   - **A:** Through **Strict Two-Phase Locking (Strict 2PL)**: all Exclusive locks acquired during transaction execution are held until final termination (commit or abort). They are never released early, guaranteeing serializability and preventing dirty reads.

6. **Q: How does the system detect and resolve Deadlocks?**
   - **A:** A centralized **Wait-For Graph (WFG)** tracks directed edges $T_A \to T_B$ where $T_A$ is waiting for a lock held by $T_B$. A Depth-First Search (DFS) algorithm checks for directed cycles. If a cycle is detected, the youngest transaction is selected as the victim and aborted, releasing its locks.

7. **Q: How does Crash Recovery work?**
   - **A:** The recovery manager reads `coordinator_wal` and `branch_wal`:
     - If the coordinator reached `GLOBAL_COMMIT` before crashing $\to$ **REDO** phase forces commit on all participants.
     - If the coordinator was in `PREPARING` without commit $\to$ **UNDO** phase rolls back participants and clears locks.

---

## 📁 Repository Directory Structure

```text
distributed_banking_system/
├── .vscode/
│   ├── launch.json              # VS Code Debug Configurations (F5)
│   └── settings.json            # VS Code Python Environment Settings
├── app/
│   ├── __init__.py
│   ├── config.py                # System paths, branch metadata, constants
│   ├── core/
│   │   ├── catalog.py           # Global Data Dictionary & Fragmentation Engine
│   │   ├── distributed_query.py # Query Decomposition & Execution Plan Optimizer
│   │   ├── lock_manager.py      # Distributed Lock Manager (DLM) & Strict 2PL
│   │   ├── deadlock_detector.py # Wait-For Graph (WFG) & Cycle Detection
│   │   ├── two_phase_commit.py  # 2PC Coordinator & Participant Engine
│   │   ├── recovery_manager.py  # Crash Recovery & WAL Replay
│   │   └── security.py          # RBAC & Session Security
│   ├── database/
│   │   ├── connection.py        # SQLite Multi-Node Connection Pool
│   │   ├── schema.py            # DDL Schemas for Central & Branch DBs
│   │   └── seed_data.py         # Realistic Seed Data for all Nodes
│   ├── routes/
│   │   ├── auth_routes.py       # RBAC Login & Role Switcher
│   │   ├── admin_routes.py      # Admin Dashboard & Multi-Node Topology
│   │   ├── branch_routes.py     # Branch Node Table Inspector
│   │   ├── customer_routes.py   # Customer CRUD & Vertical Frag Viewer
│   │   ├── account_routes.py    # Account Management & Horizontal Frag Tabs
│   │   ├── transfer_routes.py   # Money Transfer & 2PC Visual Protocol Trace
│   │   ├── loan_routes.py       # Loan Processing & Distributed Evaluation
│   │   ├── query_routes.py      # Distributed Query Console & Plan Visualizer
│   │   └── adbms_routes.py      # Interactive ADBMS Lab (2PC, DLM, WFG, Recovery)
│   ├── templates/               # Responsive Tailwind CSS Web UI Templates
│   │   ├── base.html
│   │   ├── index.html
│   │   ├── branches.html
│   │   ├── branch_detail.html
│   │   ├── customers.html
│   │   ├── customer_detail.html
│   │   ├── customer_create.html
│   │   ├── accounts.html
│   │   ├── account_detail.html
│   │   ├── account_open.html
│   │   ├── transfer.html
│   │   ├── loans.html
│   │   ├── loan_apply.html
│   │   ├── loan_evaluate.html
│   │   ├── query_console.html
│   │   ├── adbms_lab.html
│   │   ├── login.html
│   │   └── audit_logs.html
│   └── static/
├── data/                        # Physical SQLite Multi-Node Databases
│   ├── central_coordinator.db   # Coordinator DB (Catalog, GDD, 2PC WAL, Locks)
│   ├── branch_BR001.db          # Downtown Central Branch Database
│   ├── branch_BR002.db          # Midtown Financial Branch Database
│   └── branch_BR003.db          # Uptown Tech Park Branch Database
├── tests/
│   ├── test_fragmentation.py    # Test Horizontal/Vertical Reconstruction
│   ├── test_2pc.py              # Test Two-Phase Commit & Rollback
│   ├── test_deadlock.py         # Test WFG Cycle Detection & Resolution
│   ├── test_distributed_query.py# Test Distributed Aggregation & Pushdown
│   └── run_all_tests.py         # Test Runner
├── app.py                       # Flask Application Entry Point
├── run.sh                       # macOS / Linux Startup Script
├── run.bat                      # Windows Startup Script
├── requirements.txt             # Project Dependencies
└── README.md                    # Complete Documentation & Viva Guide
```
