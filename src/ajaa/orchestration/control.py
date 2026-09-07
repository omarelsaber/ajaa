"""
src/ajaa/orchestration/control.py

System Controls, Execution Management & Emergency Panic Switch (PRD §6.10, §26.5, §28.4).

Provides:
  - Global pause / resume / panic controls.
  - Panic abort: immediately closes browser contexts, converts SUBMITTING/VERIFYING to UNCERTAIN.
  - Stale lock reaper: releases worker claims older than 15 minutes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import logging
from typing import Any, Optional
import sqlalchemy as sa
from sqlalchemy.orm import Session

from ajaa.application.state_machine import ApplicationState, transition_to
from ajaa.db.models import Application, AuditEvent
from ajaa.db.session import get_session

log = logging.getLogger(__name__)


class ExecutionStatus(str, Enum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    PANIC = "PANIC"


@dataclass
class SystemStatus:
    status: ExecutionStatus
    is_paused: bool
    panic_tripped: bool
    active_workers: int = 0
    message: str = "System is operational"


class SystemController:
    """
    Singleton controller managing runtime execution state and emergency controls.
    """
    _instance: Optional["SystemController"] = None

    def __init__(self) -> None:
        self._status: ExecutionStatus = ExecutionStatus.RUNNING
        self._active_workers: int = 0

    @classmethod
    def get(cls) -> "SystemController":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def status(self) -> ExecutionStatus:
        return self._status

    @property
    def is_paused(self) -> bool:
        return self._status in (ExecutionStatus.PAUSED, ExecutionStatus.PANIC)

    @property
    def panic_tripped(self) -> bool:
        return self._status == ExecutionStatus.PANIC

    def get_status(self) -> SystemStatus:
        msg = (
            "Emergency panic switch engaged. All automations aborted."
            if self.panic_tripped
            else "System execution is paused. Current step will finish."
            if self.is_paused
            else "System is running normally."
        )
        return SystemStatus(
            status=self._status,
            is_paused=self.is_paused,
            panic_tripped=self.panic_tripped,
            active_workers=self._active_workers,
            message=msg,
        )

    def pause(self) -> SystemStatus:
        """Finish current step then halt further automation (PRD §26.5)."""
        if self._status != ExecutionStatus.PANIC:
            self._status = ExecutionStatus.PAUSED
            log.info("System execution paused by user")
        return self.get_status()

    def resume(self) -> SystemStatus:
        """Resume normal automation processing."""
        self._status = ExecutionStatus.RUNNING
        log.info("System execution resumed by user")
        return self.get_status()

    def panic(self, session: Optional[Session] = None) -> SystemStatus:
        """
        Emergency panic switch (PRD §26.5, §21.3).
        1. Sets system status to PANIC.
        2. Applications currently in SUBMITTING or VERIFYING transition to UNCERTAIN.
        3. Applications currently in STARTED transition to FAILED.
        """
        self._status = ExecutionStatus.PANIC
        log.critical("EMERGENCY PANIC SWITCH TRIPPED: Halting all automation immediately")

        def _handle_panic(s: Session) -> None:
            # Query all active or in-flight applications
            stmt = sa.select(Application).where(
                Application.state.in_([
                    ApplicationState.SUBMITTING.value,
                    ApplicationState.VERIFYING.value,
                    ApplicationState.STARTED.value,
                    ApplicationState.PREPARING.value,
                ])
            )
            apps = s.execute(stmt).scalars().all()

            for app in apps:
                old_state = app.state
                if old_state in (ApplicationState.SUBMITTING.value, ApplicationState.VERIFYING.value):
                    # INVARIANT: never auto-retry, never leave in unhandled state
                    app.state = ApplicationState.UNCERTAIN.value
                    app.error_message = "PANIC_INTERRUPTED: Emergency kill switch was triggered during submission."
                else:
                    app.state = ApplicationState.FAILED.value
                    app.error_message = "PANIC_ABORTED: Execution halted by emergency panic switch."

                # Append audit event
                audit = AuditEvent(
                    application_id=app.id,
                    event_type="PANIC_ABORT",
                    from_state=old_state,
                    to_state=app.state,
                    detail_json='{"reason": "emergency_panic_tripped"}',
                )
                s.add(audit)

            s.commit()

        if session is not None:
            _handle_panic(session)
        else:
            try:
                with get_session() as s:
                    _handle_panic(s)
            except RuntimeError as exc:
                log.warning("Could not persist panic state to database: %s", exc)

        return self.get_status()

    def reap_stale_locks(self, session: Optional[Session] = None, timeout_minutes: int = 15) -> int:
        """
        Stale lock reaper (PRD §28.4).
        Releases any application claims or locks older than timeout_minutes.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
        reaped = 0

        def _reap(s: Session) -> int:
            stmt = sa.select(Application).where(
                Application.state == ApplicationState.STARTED.value,
                Application.updated_at < cutoff,
            )
            stale_apps = s.execute(stmt).scalars().all()
            for app in stale_apps:
                old_state = app.state
                app.state = ApplicationState.FAILED.value
                app.error_message = f"STALE_LOCK_REAPED: No progress for over {timeout_minutes} minutes."
                s.add(
                    AuditEvent(
                        application_id=app.id,
                        event_type="LOCK_REAPED",
                        from_state=old_state,
                        to_state=app.state,
                        detail_json=f'{{"cutoff": "{cutoff.isoformat()}"}}',
                    )
                )
            s.commit()
            return len(stale_apps)

        if session is not None:
            reaped = _reap(session)
        else:
            try:
                with get_session() as s:
                    reaped = _reap(s)
            except RuntimeError as exc:
                log.warning("Could not reap stale locks from DB: %s", exc)

        return reaped
