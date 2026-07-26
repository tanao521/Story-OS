"""Append-only consent/audit storage and atomic ownership for Live execution."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.contracts.live_panel_execution import (
    LiveExecutionAttemptAudit,
    LiveExecutionBudgetPolicy,
    LiveExecutionConsentTicket,
    LiveExecutionStatus,
)
from core.project_context import ProjectContext


class LivePanelExecutionStore:
    """Project-local storage.

    Ticket and audit files are immutable.  The ownership file is the sole
    mutable coordination record and is reserved with O_EXCL before a provider
    call can begin.
    """

    def __init__(self, context: ProjectContext) -> None:
        self.context = context
        self.root = context.data_dir / "simulator" / "live_panel_execution"
        self.tickets_dir = self.root / "tickets"
        self.audits_dir = self.root / "attempt_audit"
        self.ownership_dir = self.root / "ownership"

    def save_ticket(self, ticket: LiveExecutionConsentTicket) -> Path:
        return self._save_immutable(self.tickets_dir / f"{ticket.ticket_id}.json", ticket.to_dict())

    def load_ticket(self, ticket_id: str) -> Optional[LiveExecutionConsentTicket]:
        data = self._read_json(self.tickets_dir / f"{ticket_id}.json")
        if data is None:
            return None
        try:
            budget = data["token_budget"]
            return LiveExecutionConsentTicket(
                ticket_id=str(data["ticket_id"]), project_id=str(data["project_id"]),
                timeline_id=str(data["timeline_id"]), chapter_id=int(data["chapter_id"]),
                source_version_id=data.get("source_version_id"),
                source_fingerprint=str(data["source_fingerprint"]),
                context_fingerprint=str(data.get("context_fingerprint", "")),
                ordered_persona_ids=list(data["ordered_persona_ids"]),
                execution_profile_id=str(data["execution_profile_id"]),
                profile_registry_revision=str(data["profile_registry_revision"]),
                max_provider_calls=int(data["max_provider_calls"]),
                token_budget=LiveExecutionBudgetPolicy(
                    policy_id=str(budget["policy_id"]), policy_revision=str(budget["policy_revision"]),
                    max_provider_calls=int(budget["max_provider_calls"]), max_input_tokens=budget.get("max_input_tokens"),
                    max_output_tokens=int(budget["max_output_tokens"]), max_total_tokens=budget.get("max_total_tokens"),
                    timeout_seconds=int(budget["timeout_seconds"]), cost_estimate_available=bool(budget["cost_estimate_available"]),
                    currency=budget.get("currency"), max_estimated_cost=budget.get("max_estimated_cost"),
                    estimate_source=str(budget["estimate_source"]), estimate_timestamp=budget.get("estimate_timestamp"),
                    retry_policy=str(budget.get("retry_policy", "0")), fallback_policy=str(budget.get("fallback_policy", "none")),
                ),
                consent_text_version=str(data["consent_text_version"]),
                issued_at=datetime.fromisoformat(data["issued_at"]), expires_at=datetime.fromisoformat(data["expires_at"]),
                idempotency_key=str(data["idempotency_key"]), request_fingerprint=str(data["request_fingerprint"]),
                counter_id=data.get("counter_id"), counter_revision=data.get("counter_revision"),
                counter_scope=data.get("counter_scope"),
                canonical_payload_hash=data.get("canonical_payload_hash"),
                thinking_mode=data.get("thinking_mode"),
                structured_output_mode=data.get("structured_output_mode"),
                status=LiveExecutionStatus(data.get("status", "issued")),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def append_audit(self, audit: LiveExecutionAttemptAudit) -> Path:
        return self._save_immutable(self.audits_dir / f"{audit.audit_id}.json", audit.to_dict())

    def reserve(self, ticket: LiveExecutionConsentTicket) -> tuple[bool, dict]:
        """Atomically create the sole in-flight ownership record for a ticket."""
        self.ownership_dir.mkdir(parents=True, exist_ok=True)
        path = self.ownership_dir / f"{ticket.ticket_id}.json"
        now = _utcnow().isoformat()
        record = {
            "ticket_id": ticket.ticket_id,
            "idempotency_key": ticket.idempotency_key,
            "request_fingerprint": ticket.request_fingerprint,
            "profile_registry_revision": ticket.profile_registry_revision,
            "policy_id": ticket.token_budget.policy_id,
            "policy_revision": ticket.token_budget.policy_revision,
            "counter_id": ticket.counter_id,
            "counter_revision": ticket.counter_revision,
            "counter_scope": ticket.counter_scope,
            "canonical_payload_hash": ticket.canonical_payload_hash,
            "thinking_mode": ticket.thinking_mode,
            "structured_output_mode": ticket.structured_output_mode,
            "status": LiveExecutionStatus.IN_PROGRESS.value,
            "panel_execution_id": None,
            "safe_error_code": None,
            "actual_provider_calls": 0,
            "usage_completeness": "not_applicable",
            "created_at": now,
            "updated_at": now,
        }
        try:
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            existing = self.load_ownership(ticket.ticket_id)
            return False, existing or record
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except Exception:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return True, record

    def load_ownership(self, ticket_id: str) -> Optional[dict]:
        return self._read_json(self.ownership_dir / f"{ticket_id}.json")

    def finish_ownership(
        self,
        ticket_id: str,
        *,
        status: LiveExecutionStatus,
        panel_execution_id: Optional[str],
        safe_error_code: Optional[str],
        actual_provider_calls: int,
        usage_completeness: str,
    ) -> dict:
        record = self.load_ownership(ticket_id)
        if record is None:
            raise KeyError("LIVE_OWNERSHIP_NOT_FOUND")
        record.update({
            "status": status.value,
            "panel_execution_id": panel_execution_id,
            "safe_error_code": safe_error_code,
            "actual_provider_calls": actual_provider_calls,
            "usage_completeness": usage_completeness,
            "updated_at": _utcnow().isoformat(),
        })
        path = self.ownership_dir / f"{ticket_id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        return record

    def _save_immutable(self, path: Path, data: dict) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except FileExistsError as exc:
            raise ValueError("Live execution records are immutable") from exc
        return path

    @staticmethod
    def _read_json(path: Path) -> Optional[dict]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, ValueError, json.JSONDecodeError):
            return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
