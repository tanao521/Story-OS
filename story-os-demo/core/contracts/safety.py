"""Shared hash, idempotency, and API-safe result contracts."""
from __future__ import annotations

import hashlib
import json
import ntpath
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_OPERATION_TOKEN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_OPERATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ABSOLUTE_PATH = re.compile(r"(?i)(?:[a-z]:[\\/][^\s]*|(?:^|\s)(?:\\\\|/)[^\s]*)")
_SENSITIVE_DETAIL_KEYS = {
    "api_key", "authorization", "content", "data_root", "file_path", "path",
    "project_root", "prompt", "stack", "text", "traceback",
}


class SafetyContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class OperationEnvelopeError(SafetyContractError):
    pass


@dataclass(frozen=True)
class HashExpectation:
    expected_sha256: str | None = None
    candidate_sha256: str | None = None
    allow_missing_target: bool = False

    def __post_init__(self) -> None:
        expected = HashGuard.normalize_sha256(self.expected_sha256) if self.expected_sha256 else None
        candidate = HashGuard.normalize_sha256(self.candidate_sha256) if self.candidate_sha256 else None
        if expected is None and not self.allow_missing_target:
            raise SafetyContractError("HASH_EXPECTATION_REQUIRED", "A complete expected SHA-256 is required.")
        object.__setattr__(self, "expected_sha256", expected)
        object.__setattr__(self, "candidate_sha256", candidate)

    @classmethod
    def for_new_target(cls, *, candidate_sha256: str | None = None) -> "HashExpectation":
        return cls(candidate_sha256=candidate_sha256, allow_missing_target=True)


@dataclass(frozen=True)
class HashValidationResult:
    actual_sha256: str | None
    expected_sha256: str | None
    matched: bool
    target_exists: bool


class HashGuard:
    """Strict SHA-256 validation without any write side effects."""

    @staticmethod
    def normalize_sha256(value: str) -> str:
        normalized = str(value or "").strip().lower()
        if not _SHA256.fullmatch(normalized):
            raise SafetyContractError("HASH_INVALID_FORMAT", "SHA-256 values must be complete 64-character hexadecimal strings.")
        return normalized

    @staticmethod
    def sha256_bytes(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    @classmethod
    def sha256_text(cls, value: str) -> str:
        return cls.sha256_bytes(str(value).encode("utf-8"))

    @classmethod
    def sha256_json(cls, value: Any) -> str:
        try:
            encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise SafetyContractError("HASH_INVALID_FORMAT", "Value cannot be serialized for SHA-256 validation.") from exc
        return cls.sha256_bytes(encoded)

    @classmethod
    def file_sha256(cls, path: str | Path) -> str:
        target = Path(path)
        if not target.exists() or not target.is_file():
            raise SafetyContractError("HASH_TARGET_NOT_FOUND", "Hash target was not found.")
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def validate_target(cls, path: str | Path, expectation: HashExpectation) -> HashValidationResult:
        target = Path(path)
        if not target.exists():
            if expectation.allow_missing_target and expectation.expected_sha256 is None:
                return HashValidationResult(None, None, True, False)
            raise SafetyContractError("HASH_TARGET_NOT_FOUND", "Hash target was not found.")
        if expectation.expected_sha256 is None:
            raise SafetyContractError("HASH_EXPECTATION_REQUIRED", "A complete expected SHA-256 is required for an existing target.")
        actual = cls.file_sha256(target)
        if actual != expectation.expected_sha256:
            raise SafetyContractError("HASH_MISMATCH", "The target SHA-256 does not match the expected value.")
        return HashValidationResult(actual, expectation.expected_sha256, True, True)

    @classmethod
    def validate_candidate(cls, actual_sha256: str, candidate_sha256: str | None) -> None:
        if candidate_sha256 is None:
            return
        if cls.normalize_sha256(actual_sha256) != cls.normalize_sha256(candidate_sha256):
            raise SafetyContractError("HASH_CANDIDATE_MISMATCH", "Candidate SHA-256 does not match the supplied payload.")


@dataclass(frozen=True)
class OperationEnvelope:
    operation_id: str
    operation_type: str
    project_id: str
    target_type: str
    target_id: str
    expected_hashes: Mapping[str, str] = field(default_factory=dict)
    confirmed: bool = False
    reason: str = ""
    requested_at: str = ""
    risk_level: str = "low"

    def __post_init__(self) -> None:
        operation_id = str(self.operation_id or "").strip()
        if not _OPERATION_ID.fullmatch(operation_id):
            raise OperationEnvelopeError("OPERATION_ID_INVALID", "operation_id is required, bounded, and must use safe characters.")
        if not _OPERATION_TOKEN.fullmatch(str(self.operation_type or "")):
            raise OperationEnvelopeError("OPERATION_TYPE_INVALID", "operation_type is invalid.")
        if not _OPERATION_TOKEN.fullmatch(str(self.target_type or "")):
            raise OperationEnvelopeError("TARGET_TYPE_INVALID", "target_type is invalid.")
        if not str(self.target_id or "").strip() or len(str(self.target_id)) > 256:
            raise OperationEnvelopeError("TARGET_TYPE_INVALID", "target_id is required and bounded.")
        if not str(self.project_id or "").strip():
            raise OperationEnvelopeError("PROJECT_REF_INVALID", "project_id is required.")
        if self.risk_level not in {"low", "high"}:
            raise OperationEnvelopeError("OPERATION_RISK_INVALID", "risk_level is invalid.")
        if not self.confirmed:
            raise OperationEnvelopeError("OPERATION_CONFIRMATION_REQUIRED", "Confirmed operations require confirmed=true.")
        reason = str(self.reason or "").strip()
        if self.risk_level == "high" and not reason:
            raise OperationEnvelopeError("OPERATION_REASON_REQUIRED", "High-risk operations require a reason.")
        if len(reason) > 2000:
            raise OperationEnvelopeError("OPERATION_REASON_INVALID", "reason exceeds the allowed length.")
        try:
            hashes = {str(key): HashGuard.normalize_sha256(value) for key, value in dict(self.expected_hashes).items()}
        except SafetyContractError as exc:
            raise OperationEnvelopeError(exc.code, str(exc)) from exc
        if any(not _OPERATION_TOKEN.fullmatch(key) for key in hashes):
            raise OperationEnvelopeError("HASH_INVALID_FORMAT", "Expected hash keys must be safe identifiers.")
        stamp = str(self.requested_at or datetime.now(timezone.utc).isoformat())
        try:
            datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise OperationEnvelopeError("OPERATION_TIMESTAMP_INVALID", "requested_at must be ISO-8601.") from exc
        object.__setattr__(self, "operation_id", operation_id)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "expected_hashes", hashes)
        object.__setattr__(self, "requested_at", stamp)

    def fingerprint(self) -> str:
        payload = {
            "operation_type": self.operation_type, "project_id": self.project_id,
            "target_type": self.target_type, "target_id": self.target_id,
            "expected_hashes": dict(sorted(self.expected_hashes.items())),
            "confirmed": self.confirmed, "reason": self.reason, "risk_level": self.risk_level,
        }
        return HashGuard.sha256_json(payload)


def _safe_detail_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _safe_detail_value(item) for key, item in value.items() if str(key).casefold() not in _SENSITIVE_DETAIL_KEYS}
    if isinstance(value, list):
        return [_safe_detail_value(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_detail_value(item) for item in value]
    if isinstance(value, str):
        if ntpath.splitdrive(value)[0] or value.startswith(("/", "\\\\", "//")) or _ABSOLUTE_PATH.search(value):
            return "[redacted]"
        return value[:500]
    return value


@dataclass(frozen=True)
class ErrorEnvelope:
    code: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"code": str(self.code or "SYS_ERROR"), "message": _safe_detail_value(str(self.message or "Operation failed.")), "details": _safe_detail_value(dict(self.details))}

    def compatibility_view(self, *, warnings: list[str] | None = None, errors: list[str] | None = None) -> dict[str, Any]:
        error = self.as_dict()
        safe_errors = [_safe_detail_value(str(item)) for item in (errors or [error["code"]])]
        return {"ok": False, "error_code": error["code"], "message": error["message"], "details": error["details"], "result": {}, "warnings": warnings or [], "errors": safe_errors, "error": {**error, "recoverable": True, "suggestions": []}}


@dataclass(frozen=True)
class SafeResult:
    data: Mapping[str, Any] = field(default_factory=dict)
    error: ErrorEnvelope | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def as_dict(self) -> dict[str, Any]:
        return {"ok": True, "data": dict(self.data)} if self.ok else {"ok": False, "error": self.error.as_dict()}
