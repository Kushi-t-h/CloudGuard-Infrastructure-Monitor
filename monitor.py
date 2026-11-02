import threading
import time
import logging
from typing import Dict, Any, Optional
from database import log_event, get_service_state
from recovery import RecoveryEngine

logger = logging.getLogger("cloudguard.monitor")

class HealthMonitor:
    """
    Background health monitor that inspects application status at configurable intervals.
    Automatically invokes the RecoveryEngine if an unhealthy state is detected.
    """
    def __init__(self, service_state: Dict[str, Any], interval: int = 5, db_path: Optional[str] = None):
        self.service_state = service_state
        self.interval = interval
        self.db_path = db_path or "cloudguard.db"
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self.recovery_engine = RecoveryEngine(service_state=self.service_state, db_path=self.db_path)

    def check_health(self) -> Dict[str, Any]:
        """Runs a single health check evaluation from persisted shared state."""
        persisted = get_service_state(db_path=self.db_path)
        # Check both database and in-memory service_state for unhealthiness
        is_healthy = persisted.get("healthy", True) and self.service_state.get("healthy", True)
        reason = persisted.get("failure_reason") or self.service_state.get("failure_reason")

        # Keep both in-memory dict and database in sync
        self.service_state["healthy"] = is_healthy
        self.service_state["failure_reason"] = reason

        status_str = "HEALTHY" if is_healthy else "UNHEALTHY"
        details_str = "Application response nominal (200 OK)." if is_healthy else f"Application degradation detected: {reason}."

        log_event("HEALTH_CHECK", status_str, details_str, db_path=self.db_path)

        if not is_healthy:
            logger.warning(f"Health monitor detected failure: {reason}. Initiating auto-recovery...")
            recovery_result = self.recovery_engine.attempt_recovery()
            # Re-read status after recovery attempt
            latest_persisted = get_service_state(db_path=self.db_path)
            now_healthy = latest_persisted.get("healthy", False)
            self.service_state["healthy"] = now_healthy
            self.service_state["failure_reason"] = latest_persisted.get("failure_reason")
            return {
                "healthy": now_healthy,
                "reason": self.service_state.get("failure_reason"),
                "recovery_result": recovery_result
            }

        return {"healthy": True, "reason": None}

    def _monitor_loop(self) -> None:
        while self.running:
            try:
                self.check_health()
            except Exception as e:
                logger.error(f"Error occurred during monitor cycle: {e}")
            time.sleep(self.interval)

    def start(self) -> None:
        """Starts the background monitor thread."""
        if not self.running:
            self.running = True
            self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._thread.start()
            logger.info(f"Health monitor daemon started with interval={self.interval}s.")

    def stop(self) -> None:
        """Stops the background monitor thread."""
        self.running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        logger.info("Health monitor daemon stopped.")
