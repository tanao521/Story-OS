"""Append-only, content-free conservative usage reconciliation records."""
from __future__ import annotations

import json
import math
import os
import re
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_RECORD_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
RECONCILIATION_RECORD_VERSION = "1"
_SUPPORTED_RECORD_VERSIONS = frozenset({RECONCILIATION_RECORD_VERSION})


class ProviderUsageReconciliationError(ValueError):
    """Safe domain error that never includes a filesystem path or record data."""

    INVALID_RECORD = "RECONCILIATION_RECORD_INVALID"
    INVALID_RECORD_ID = "RECONCILIATION_RECORD_ID_INVALID"
    PATH_NOT_CONTAINED = "RECONCILIATION_PATH_NOT_CONTAINED"
    ALREADY_EXISTS = "RECONCILIATION_ALREADY_EXISTS"
    WRITE_FAILED = "RECONCILIATION_WRITE_FAILED"

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ProviderUsageReconciliation:
    local_text_tokens: int
    conservative_estimated_tokens: int
    provider_prompt_tokens: Optional[int]
    difference_tokens: Optional[int]
    difference_ratio: Optional[float]
    policy_revision: str
    profile_revision: str
    counter_revision: str
    model_id: str
    safe_request_fingerprint: str
    usage_completeness: str
    timestamp: str
    record_version: str = RECONCILIATION_RECORD_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.record_version, str)
            or self.record_version
            not in _SUPPORTED_RECORD_VERSIONS
        ):
            raise ProviderUsageReconciliationError(
                ProviderUsageReconciliationError.INVALID_RECORD
            )
        for value in (
            self.local_text_tokens,
            self.conservative_estimated_tokens,
        ):
            if type(value) is not int or value < 0:
                raise ProviderUsageReconciliationError(
                    ProviderUsageReconciliationError.INVALID_RECORD
                )
        for value in (self.provider_prompt_tokens, self.difference_tokens):
            if value is not None and type(value) is not int:
                raise ProviderUsageReconciliationError(
                    ProviderUsageReconciliationError.INVALID_RECORD
                )
        if self.provider_prompt_tokens is not None and self.provider_prompt_tokens < 0:
            raise ProviderUsageReconciliationError(
                ProviderUsageReconciliationError.INVALID_RECORD
            )
        for value in (
            self.policy_revision, self.profile_revision,
            self.counter_revision, self.model_id, self.timestamp,
        ):
            if not isinstance(value, str) or not value.strip():
                raise ProviderUsageReconciliationError(
                    ProviderUsageReconciliationError.INVALID_RECORD
                )
        if (
            not isinstance(self.safe_request_fingerprint, str)
            or _FINGERPRINT_PATTERN.fullmatch(self.safe_request_fingerprint) is None
            or self.usage_completeness not in {"complete", "incomplete"}
        ):
            raise ProviderUsageReconciliationError(
                ProviderUsageReconciliationError.INVALID_RECORD
            )
        if self.usage_completeness == "incomplete":
            if any(value is not None for value in (
                self.provider_prompt_tokens, self.difference_tokens, self.difference_ratio
            )):
                raise ProviderUsageReconciliationError(
                    ProviderUsageReconciliationError.INVALID_RECORD
                )
            return
        if self.provider_prompt_tokens is None:
            raise ProviderUsageReconciliationError(
                ProviderUsageReconciliationError.INVALID_RECORD
            )
        expected_difference = (
            self.provider_prompt_tokens - self.conservative_estimated_tokens
        )
        if self.difference_tokens != expected_difference:
            raise ProviderUsageReconciliationError(
                ProviderUsageReconciliationError.INVALID_RECORD
            )
        if self.conservative_estimated_tokens == 0:
            if self.difference_ratio is not None:
                raise ProviderUsageReconciliationError(
                    ProviderUsageReconciliationError.INVALID_RECORD
                )
        else:
            expected_ratio = expected_difference / self.conservative_estimated_tokens
            if (
                type(self.difference_ratio) is not float
                or not math.isfinite(self.difference_ratio)
                or self.difference_ratio != expected_ratio
            ):
                raise ProviderUsageReconciliationError(
                    ProviderUsageReconciliationError.INVALID_RECORD
                )

    @classmethod
    def build(
        cls, *, local_text_tokens: int, conservative_estimated_tokens: int,
        provider_prompt_tokens: Optional[int], policy_revision: str,
        profile_revision: str, counter_revision: str, model_id: str,
        safe_request_fingerprint: str,
    ) -> "ProviderUsageReconciliation":
        for value in (local_text_tokens, conservative_estimated_tokens):
            if type(value) is not int or value < 0:
                raise ProviderUsageReconciliationError(
                    ProviderUsageReconciliationError.INVALID_RECORD
                )
        if (
            provider_prompt_tokens is not None
            and (type(provider_prompt_tokens) is not int or provider_prompt_tokens < 0)
        ):
            raise ProviderUsageReconciliationError(
                ProviderUsageReconciliationError.INVALID_RECORD
            )
        complete = provider_prompt_tokens is not None
        difference = provider_prompt_tokens - conservative_estimated_tokens if complete else None
        ratio = (
            difference / conservative_estimated_tokens
            if complete and conservative_estimated_tokens > 0
            else None
        )
        return cls(
            local_text_tokens=local_text_tokens,
            conservative_estimated_tokens=conservative_estimated_tokens,
            provider_prompt_tokens=provider_prompt_tokens if complete else None,
            difference_tokens=difference,
            difference_ratio=ratio,
            policy_revision=policy_revision,
            profile_revision=profile_revision,
            counter_revision=counter_revision,
            model_id=model_id,
            safe_request_fingerprint=safe_request_fingerprint,
            usage_completeness="complete" if complete else "incomplete",
            timestamp=datetime.now(timezone.utc).isoformat(),
            record_version=RECONCILIATION_RECORD_VERSION,
        )


class ProviderUsageReconciliationStore:
    def __init__(self, root: Path) -> None:
        raw_root = Path(root)
        raw_root.mkdir(parents=True, exist_ok=True)
        if raw_root.is_symlink():
            raise ProviderUsageReconciliationError(
                ProviderUsageReconciliationError.PATH_NOT_CONTAINED
            )
        self.root = raw_root.resolve(strict=True)

    def append(self, record_id: str, record: ProviderUsageReconciliation) -> Path:
        if (
            not isinstance(record_id, str)
            or _RECORD_ID_PATTERN.fullmatch(record_id) is None
        ):
            raise ProviderUsageReconciliationError(
                ProviderUsageReconciliationError.INVALID_RECORD_ID
            )
        if not isinstance(record, ProviderUsageReconciliation):
            raise ProviderUsageReconciliationError(
                ProviderUsageReconciliationError.INVALID_RECORD
            )
        try:
            if self.root.is_symlink() or self.root.resolve(strict=True) != self.root:
                raise ProviderUsageReconciliationError(
                    ProviderUsageReconciliationError.PATH_NOT_CONTAINED
                )
        except OSError as exc:
            raise ProviderUsageReconciliationError(
                ProviderUsageReconciliationError.PATH_NOT_CONTAINED
            ) from exc
        path = self.root / f"{record_id}.json"
        try:
            resolved_parent = path.parent.resolve(strict=True)
            resolved_target = (resolved_parent / path.name).resolve(strict=False)
        except OSError as exc:
            raise ProviderUsageReconciliationError(
                ProviderUsageReconciliationError.PATH_NOT_CONTAINED
            ) from exc
        if resolved_parent != self.root or resolved_target.parent != self.root:
            raise ProviderUsageReconciliationError(
                ProviderUsageReconciliationError.PATH_NOT_CONTAINED
            )
        try:
            payload = json.dumps(
                asdict(record), ensure_ascii=False, indent=2, sort_keys=True,
            ).encode("utf-8") + b"\n"
        except (TypeError, ValueError) as exc:
            raise ProviderUsageReconciliationError(
                ProviderUsageReconciliationError.INVALID_RECORD
            ) from exc
        temp_name = f".{record_id}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        temp_path = self.root / temp_name
        try:
            with temp_path.open("xb", encoding=None) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temp_path, resolved_target)
        except FileExistsError as exc:
            raise ProviderUsageReconciliationError(
                ProviderUsageReconciliationError.ALREADY_EXISTS
            ) from exc
        except OSError as exc:
            raise ProviderUsageReconciliationError(
                ProviderUsageReconciliationError.WRITE_FAILED
            ) from exc
        finally:
            try:
                temp_path.unlink()
            except OSError:
                pass
        return resolved_target
