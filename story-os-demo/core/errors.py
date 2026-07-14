"""User-safe Story OS errors with stable codes and recovery guidance."""
from __future__ import annotations

from typing import Any


class StoryOSError(RuntimeError):
    code = "SYS_ERROR"
    recoverable = False
    suggestions: tuple[str, ...] = ()

    def __init__(self, message: str = "Story OS operation failed.", *, code: str | None = None,
                 details: dict[str, Any] | None = None, recoverable: bool | None = None,
                 suggestions: list[str] | tuple[str, ...] | None = None) -> None:
        super().__init__(message)
        if code: self.code = code
        if recoverable is not None: self.recoverable = recoverable
        if suggestions is not None: self.suggestions = tuple(str(item) for item in suggestions)
        self.details = dict(details or {})

    def public(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": self.details,
                "recoverable": bool(self.recoverable), "suggestions": list(self.suggestions)}


class ConfigError(StoryOSError): code = "CONFIG_INVALID"
class ProjectError(StoryOSError): code = "PROJECT_ERROR"
class DataCorruptionError(StoryOSError): code = "DATA_JSON_INVALID"; recoverable = True
class ValidationError(StoryOSError): code = "DATA_VALIDATION_FAILED"
class PermissionDeniedError(StoryOSError): code = "DATA_PERMISSION_DENIED"; recoverable = True
class JobSystemError(StoryOSError): code = "JOB_FAILED"; recoverable = True
class ModelError(StoryOSError): code = "MODEL_ERROR"; recoverable = True
class StorageError(StoryOSError): code = "DATA_STORAGE_FAILED"; recoverable = True
class VersionError(StoryOSError): code = "VERSION_ERROR"
class MemorySystemError(StoryOSError): code = "MEMORY_ERROR"; recoverable = True

# Public names used by service boundaries; aliases retain compatibility with
# Python built-ins at call sites that already use the built-in exceptions.
PermissionError = PermissionDeniedError
JobError = JobSystemError
MemoryError = MemorySystemError


def public_error(error: Exception) -> dict[str, Any]:
    if isinstance(error, StoryOSError): return error.public()
    return {"code": "SYS_INTERNAL_ERROR", "message": "The operation could not be completed.", "details": {}, "recoverable": False, "suggestions": ["Review System Diagnostics and retry after resolving the reported issue."]}
