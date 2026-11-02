import time
import logging
from typing import Dict, Any, Optional
from database import log_event, set_service_state, get_service_state

logger = logging.getLogger("cloudguard.recovery")

class RecoveryEngine:
    """
    Deterministic Auto-Recovery Engine.
    Handles simulated failure recovery attempts up to MAX_RETRIES per incident.
    Prevents duplicate concurrent recovery runs.
    """
    MAX_RETRIES = 3

    def __init__(self, service_state: Dict[str, Any], db_path: Optional[str] = None):
        self.service_state = service_state
        self.db_path = db_path or "cloudguard.db"
        self._is_recovering = False

    def attempt_recovery(self) -> Dict[str, Any]:
        """
        Executes recovery sequence with retry limits.
        Enforces maximum of 3 attempts per incident and prevents duplicate runs.
        Verifies health restoration before logging success.
        """
        if self._is_recovering:
            logger.warning("Recovery sequence already in progress. Skipping duplicate execution.")
            return {"status": "in_progress", "attempts": 0}

        self._is_recovering = True
        logger.warning("Recovery sequence triggered.")

        attempt = 0
        success = False

        try:
            while attempt < self.MAX_RETRIES:
                attempt += 1
                logger.info(f"Auto-recovery attempt {attempt}/{self.MAX_RETRIES} in progress...")

                log_event(
                    event_type="RECOVERY_ATTEMPT",
                    status="IN_PROGRESS",
                    details=f"Executing recovery step {attempt}/{self.MAX_RETRIES}: resetting simulated service state.",
                    db_path=self.db_path,
                )

                # Execute recovery action on shared service state in memory and database
                self.service_state["healthy"] = True
                self.service_state["failure_reason"] = None
                set_service_state(healthy=True, failure_reason=None, db_path=self.db_path)

                # Verify health is restored from source of truth
                persisted_state = get_service_state(db_path=self.db_path)
                if persisted_state.get("healthy") is True and persisted_state.get("failure_reason") is None:
                    success = True
                    break

            if success:
                logger.info(f"Recovery successful on attempt {attempt}.")
                log_event(
                    event_type="RECOVERY",
                    status="SUCCESS",
                    details=f"Service successfully recovered and verified healthy after {attempt} attempt(s).",
                    db_path=self.db_path,
                )
                return {"status": "recovered", "attempts": attempt}
            else:
                logger.error("Auto-recovery exceeded max retries. Manual intervention required.")
                log_event(
                    event_type="RECOVERY",
                    status="FAILED",
                    details=f"Auto-recovery failed after {self.MAX_RETRIES} attempts. System remains unhealthy.",
                    db_path=self.db_path,
                )
                return {"status": "failed", "attempts": attempt}
        finally:
            self._is_recovering = False
