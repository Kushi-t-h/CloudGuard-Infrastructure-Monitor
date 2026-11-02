import os
import logging
from flask import Flask, jsonify, render_template, request, redirect, url_for
from database import (
    init_db,
    log_event,
    get_recent_events,
    get_event_counts,
    get_service_state,
    set_service_state,
)
from monitor import HealthMonitor

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cloudguard.app")

# Shared state for simulated application health
service_state = {
    "healthy": True,
    "failure_reason": None,
}

def create_app(test_config=None) -> Flask:
    app = Flask(__name__)
    
    db_path = "cloudguard.db"
    monitor_interval = 5

    # Each app instance gets its own service state dict unless passed in
    app.service_state = {
        "healthy": True,
        "failure_reason": None,
    }

    if test_config:
        app.config.update(test_config)
        if "DB_PATH" in test_config:
            db_path = test_config["DB_PATH"]
        if "MONITOR_INTERVAL" in test_config:
            monitor_interval = test_config["MONITOR_INTERVAL"]
        if "SERVICE_STATE" in test_config:
            app.service_state = test_config["SERVICE_STATE"]

    # Initialize SQLite database
    init_db(db_path=db_path)

    # Initialize shared state from database ground truth
    initial_persisted = get_service_state(db_path=db_path)
    app.service_state["healthy"] = initial_persisted.get("healthy", True)
    app.service_state["failure_reason"] = initial_persisted.get("failure_reason")

    # Start background monitor daemon unless explicitly disabled (useful for isolated unit tests)
    if not app.config.get("DISABLE_MONITOR_THREAD", False):
        monitor = HealthMonitor(
            service_state=app.service_state,
            interval=monitor_interval,
            db_path=db_path
        )
        monitor.start()
        app.monitor = monitor

    @app.route("/")
    def dashboard():
        """Dashboard view showing real-time status and logs refreshed from shared state."""
        current_state = get_service_state(db_path=db_path)
        app.service_state["healthy"] = current_state["healthy"]
        app.service_state["failure_reason"] = current_state["failure_reason"]

        events = get_recent_events(limit=15, db_path=db_path)
        counts = get_event_counts(db_path=db_path)
        return render_template(
            "dashboard.html",
            service_status=current_state,
            events=events,
            counts=counts
        )

    @app.route("/health", methods=["GET"])
    def health_check():
        """
        Public health-check endpoint.
        Returns 200 OK when healthy, 503 SERVICE UNAVAILABLE when degraded.
        Always reads real-time persisted service state.
        """
        current_state = get_service_state(db_path=db_path)
        app.service_state["healthy"] = current_state["healthy"]
        app.service_state["failure_reason"] = current_state["failure_reason"]

        if current_state["healthy"]:
            return jsonify({
                "status": "UP",
                "healthy": True,
                "message": "Service is operational"
            }), 200
        else:
            return jsonify({
                "status": "DOWN",
                "healthy": False,
                "reason": current_state.get("failure_reason", "Simulated degradation")
            }), 503

    @app.route("/simulate-failure", methods=["POST"])
    def simulate_failure():
        """Simulate an application failure safely without impacting the host machine."""
        reason = request.form.get("reason", "Simulated Database Connection Timeout")
        set_service_state(healthy=False, failure_reason=reason, db_path=db_path)
        app.service_state["healthy"] = False
        app.service_state["failure_reason"] = reason

        log_event(
            event_type="FAILURE",
            status="TRIGGERED",
            details=f"Injected simulated failure: {reason}",
            db_path=db_path
        )
        logger.warning(f"Failure simulation activated: {reason}")

        if request.headers.get("Accept") == "application/json":
            return jsonify({
                "message": "Simulated failure injected",
                "status": "DOWN",
                "reason": reason
            }), 200

        return redirect(url_for("dashboard"))

    @app.route("/api/events", methods=["GET"])
    def api_events():
        """API endpoint to fetch recent events as JSON."""
        events = get_recent_events(limit=20, db_path=db_path)
        return jsonify(events), 200

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Resource not found"}), 404

    @app.errorhandler(500)
    def internal_error(e):
        logger.error(f"Internal server error: {e}")
        return jsonify({"error": "Internal server error"}), 500

    return app

if __name__ == "__main__":
    app = create_app()
    # Runs on port 5000 inside container or local environment
    app.run(host="0.0.0.0", port=5000, debug=False)
