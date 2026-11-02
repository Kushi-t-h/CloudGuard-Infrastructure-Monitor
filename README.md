# CloudGuard — Infrastructure Monitoring & Auto-Recovery System

A lightweight, production-modeled infrastructure health monitoring and deterministic auto-recovery service built for cloud and infrastructure engineering demonstrations.

---

## 📌 Architecture & Design

CloudGuard models the core mechanics of cloud reliability engineering (SRE):

1. **Heartbeat & Liveness Checks (`/health`)**: An HTTP endpoint providing standard status reporting (`200 OK` when healthy, `503 Service Unavailable` when degraded).
2. **Background Daemon Monitoring (`monitor.py`)**: A thread checking system health at configurable intervals, logging every check to SQLite.
3. **Safe Failure Injection (`/simulate-failure`)**: Enables testing incident management flows without impacting host system integrity.
4. **Deterministic Auto-Recovery Engine (`recovery.py`)**: SRE auto-healing logic with an exponential retry cap (maximum 3 attempts).
5. **Auditing & Event Store (`database.py`)**: An embedded SQLite datastore persisting all health checks, alerts, and recovery outcomes.
6. **Operational Dashboard (`templates/dashboard.html`)**: Real-time view of system status, total failures, successful auto-recoveries, and recent events.

```
+-----------------------------------------------------------+
|                        CloudGuard                         |
|                                                           |
|  [ Flask Web UI & API ] <---> [ Health Monitor Daemon ]   |
|         |                              |                  |
|         v                              v                  |
|  [/health , /simulate-failure]    [Auto-Recovery Engine]  |
|         |                              |                  |
|         +--------------+---------------+                  |
|                        |                                  |
|                        v                                  |
|                 [ SQLite DB ]                             |
+-----------------------------------------------------------+
```

---

## 🚀 Setup & Execution

### 1. Local Python Setup

```bash
# Navigate to the project directory
cd cloudguard

# (Optional) Create and activate a virtual environment
python -m venv venv
# On Linux/macOS: source venv/bin/activate
# On Windows: .\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python app.py
```

Access the dashboard at `http://localhost:5000` and health checks at `http://localhost:5000/health`.

---

## 🧪 Running Tests

Execute the automated Pytest suite covering database operations, health endpoints, failure detection, recovery logic, and retry limits:

```bash
pytest tests.py -v
```

---

## 🐳 Running with Docker

Build and run CloudGuard inside an isolated container with an integrated Docker healthcheck:

```bash
# Build the container image
docker build -t cloudguard:latest .

# Run the container
docker run -d -p 5000:5000 --name cloudguard-svc cloudguard:latest

# Check container health status
docker ps
```

---

## ⚠️ Limitations & Scope
- **Simulated Recovery**: The recovery logic intentionally simulates system self-healing (state resets, cache refreshes) rather than restarting host-level operating system services or external nodes.
- **Single-Node SQLite**: Designed for simplicity and zero-configuration demonstration; enterprise multi-node setups would leverage distributed datastores and message brokers.
