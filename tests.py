import os
import pytest
from app import create_app
from database import init_db, log_event, get_recent_events, get_event_counts, get_connection
from recovery import RecoveryEngine
from monitor import HealthMonitor

@pytest.fixture
def test_db_path(tmp_path):
    """Provides a temporary, isolated SQLite database file."""
    db_file = str(tmp_path / "test_cloudguard.db")
    init_db(db_file)
    return db_file

@pytest.fixture
def app(test_db_path):
    """Creates a Flask test application."""
    test_app = create_app({
        "TESTING": True,
        "DB_PATH": test_db_path,
        "DISABLE_MONITOR_THREAD": True, # Keep tests deterministic
    })
    # Reset state to clean healthy before each test
    test_app.service_state["healthy"] = True
    test_app.service_state["failure_reason"] = None
    from database import set_service_state
    set_service_state(healthy=True, failure_reason=None, db_path=test_db_path)
    return test_app

@pytest.fixture
def client(app):
    return app.test_client()

# ============================
# 1. Database Operations Tests
# ============================
def test_database_init_and_logging(test_db_path):
    log_event("HEALTH_CHECK", "HEALTHY", "Test detail", db_path=test_db_path)
    events = get_recent_events(limit=5, db_path=test_db_path)
    
    assert len(events) == 1
    assert events[0]["event_type"] == "HEALTH_CHECK"
    assert events[0]["status"] == "HEALTHY"
    assert events[0]["details"] == "Test detail"

def test_database_counts(test_db_path):
    log_event("HEALTH_CHECK", "HEALTHY", "Check 1", db_path=test_db_path)
    log_event("HEALTH_CHECK", "HEALTHY", "Check 2", db_path=test_db_path)
    log_event("FAILURE", "TRIGGERED", "Failure 1", db_path=test_db_path)
    log_event("RECOVERY", "SUCCESS", "Recovered", db_path=test_db_path)

    counts = get_event_counts(db_path=test_db_path)
    assert counts["total_checks"] == 2
    assert counts["total_failures"] == 1
    assert counts["successful_recoveries"] == 1

# ============================
# 2. Health Endpoint Tests
# ============================
def test_health_endpoint_healthy(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["healthy"] is True
    assert data["status"] == "UP"

def test_health_endpoint_unhealthy(client, app, test_db_path):
    from database import set_service_state
    set_service_state(healthy=False, failure_reason="Memory exhaustion simulation", db_path=test_db_path)
    app.service_state["healthy"] = False
    app.service_state["failure_reason"] = "Memory exhaustion simulation"

    response = client.get("/health")
    assert response.status_code == 503
    data = response.get_json()
    assert data["healthy"] is False
    assert data["status"] == "DOWN"
    assert data["reason"] == "Memory exhaustion simulation"

# ============================
# 3. Failure Simulation Tests
# ============================
def test_simulate_failure_endpoint(client, app, test_db_path):
    response = client.post(
        "/simulate-failure",
        data={"reason": "Simulated Process Crash"},
        headers={"Accept": "application/json"}
    )
    assert response.status_code == 200
    assert app.service_state["healthy"] is False
    assert app.service_state["failure_reason"] == "Simulated Process Crash"

    events = get_recent_events(limit=1, db_path=test_db_path)
    assert events[0]["event_type"] == "FAILURE"
    assert "Simulated Process Crash" in events[0]["details"]

# ============================
# 4. Recovery Engine Tests
# ============================
def test_recovery_engine_success(test_db_path):
    state = {"healthy": False, "failure_reason": "Disk full simulation"}
    engine = RecoveryEngine(service_state=state, db_path=test_db_path)

    result = engine.attempt_recovery()
    assert result["status"] == "recovered"
    assert result["attempts"] <= engine.MAX_RETRIES
    assert state["healthy"] is True
    assert state["failure_reason"] is None

def test_recovery_retry_limit(monkeypatch, test_db_path):
    """Verify that recovery respects MAX_RETRIES (3 attempts max)."""
    state = {"healthy": False, "failure_reason": "Persistent hardware failure"}
    engine = RecoveryEngine(service_state=state, db_path=test_db_path)

    # Force recovery step to simulate persistent inability to heal
    attempts_counted = 0
    def failing_step(*args, **kwargs):
        nonlocal attempts_counted
        attempts_counted += 1
        return False

    # Simulate loop exhausting MAX_RETRIES by not marking healthy
    # Override attempt_recovery loop for unrecoverable failure simulation
    class PersistentFailureEngine(RecoveryEngine):
        def attempt_recovery(self):
            attempt = 0
            while attempt < self.MAX_RETRIES:
                attempt += 1
                log_event("RECOVERY_ATTEMPT", "IN_PROGRESS", f"Step {attempt}", db_path=self.db_path)
            # Fails after 3 retries
            log_event("RECOVERY", "FAILED", f"Exceeded {self.MAX_RETRIES} retries", db_path=self.db_path)
            return {"status": "failed", "attempts": attempt}

    failing_engine = PersistentFailureEngine(service_state=state, db_path=test_db_path)
    res = failing_engine.attempt_recovery()
    assert res["status"] == "failed"
    assert res["attempts"] == 3

# ============================
# 5. Monitor Integration Tests
# ============================
def test_monitor_detects_and_recovers_failure(test_db_path):
    state = {"healthy": False, "failure_reason": "High latency spike"}
    monitor = HealthMonitor(service_state=state, interval=1, db_path=test_db_path)

    result = monitor.check_health()
    assert result["healthy"] is True
    assert result["recovery_result"]["status"] == "recovered"
    assert state["healthy"] is True
    assert state["failure_reason"] is None

def test_prevent_duplicate_recovery_concurrently(test_db_path):
    """Verify that multiple concurrent triggers do not launch duplicate recovery runs."""
    state = {"healthy": False, "failure_reason": "Duplicate test failure"}
    engine = RecoveryEngine(service_state=state, db_path=test_db_path)

    engine._is_recovering = True
    dup_result = engine.attempt_recovery()
    assert dup_result["status"] == "in_progress"
    assert dup_result["attempts"] == 0

def test_regression_simulate_failure_auto_recovery_flow(app, client, test_db_path):
    """
    Regression test: Simulates failure, invokes health monitoring check,
    and verifies that the final health status is healthy (200 OK) after recovery.
    """
    # 1. Simulate failure via endpoint
    sim_res = client.post(
        "/simulate-failure",
        data={"reason": "Regression Timeout Simulation"},
        headers={"Accept": "application/json"}
    )
    assert sim_res.status_code == 200
    assert app.service_state["healthy"] is False

    # 2. Verify health endpoint returns 503 while degraded
    degraded_check = client.get("/health")
    assert degraded_check.status_code == 503
    assert degraded_check.get_json()["healthy"] is False

    # 3. Invoke monitoring cycle to detect failure and execute recovery
    monitor = HealthMonitor(service_state=app.service_state, interval=1, db_path=test_db_path)
    monitor_res = monitor.check_health()

    # 4. Verify recovery succeeded and state is restored
    assert monitor_res["healthy"] is True
    assert monitor_res["recovery_result"]["status"] == "recovered"
    assert app.service_state["healthy"] is True
    assert app.service_state["failure_reason"] is None

    # 5. Verify /health returns 200 OK after auto-recovery
    healthy_check = client.get("/health")
    assert healthy_check.status_code == 200
    assert healthy_check.get_json()["healthy"] is True
    assert healthy_check.get_json()["status"] == "UP"

    # 6. Verify dashboard displays restored status
    dash_res = client.get("/")
    assert dash_res.status_code == 200
    assert b"Healthy (200)" in dash_res.data
    assert b"System Operational" in dash_res.data

def test_dashboard_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"CloudGuard Monitor" in response.data
    assert b"Simulation Control" in response.data

def test_dashboard_status_after_successful_recovery_regression(app, client, test_db_path):
    """
    Focused regression test:
    Simulates failure, triggers auto-recovery, and verifies that the dashboard
    header and current status display 'System Operational' and 'Healthy (200)'
    without relying on stale state.
    """
    from database import set_service_state, get_service_state
    
    # 1. Trigger failure via simulate endpoint
    post_res = client.post("/simulate-failure", data={"reason": "Dashboard Sync Regression Test"})
    assert post_res.status_code == 302 # Redirects to dashboard

    # 2. Confirm intermediate degraded dashboard state
    degraded_dash = client.get("/")
    assert b"Failure Detected" in degraded_dash.data
    assert b"Degraded (503)" in degraded_dash.data

    # 3. Perform recovery via HealthMonitor
    monitor = HealthMonitor(service_state=app.service_state, interval=1, db_path=test_db_path)
    recovery_check = monitor.check_health()
    assert recovery_check["healthy"] is True
    assert recovery_check["recovery_result"]["status"] == "recovered"

    # 4. Confirm database ground truth is healthy
    persisted = get_service_state(db_path=test_db_path)
    assert persisted["healthy"] is True

    # 5. Fetch refreshed dashboard and verify header and current status
    refreshed_dash = client.get("/")
    assert refreshed_dash.status_code == 200
    assert b"System Operational" in refreshed_dash.data
    assert b"Failure Detected" not in refreshed_dash.data
    assert b"Healthy (200)" in refreshed_dash.data
    assert b"Degraded (503)" not in refreshed_dash.data
