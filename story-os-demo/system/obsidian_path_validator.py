from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from system.project_clone_service import ProjectCloneService


class ObsidianPathValidator:
    WINDOWS_RESERVED = {
        "con", "prn", "aux", "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
    INVALID_CHARS = r'[<>:"/\\|?*\x00-\x1f]'

    @staticmethod
    def validate_vault_root(vault_root: Path) -> tuple[bool, str]:
        vault_root = vault_root.resolve()

        if not vault_root.exists():
            return False, "VAULT_NOT_FOUND"

        if not vault_root.is_dir():
            return False, "VAULT_NOT_DIRECTORY"

        if ProjectCloneService._is_link_or_reparse_point(vault_root):
            return False, "VAULT_IS_LINK"

        return True, ""

    @staticmethod
    def validate_target_relative_path(path: str) -> tuple[bool, str]:
        if not path:
            return False, "TARGET_EMPTY"

        if path.startswith("/"):
            return False, "TARGET_ABSOLUTE"

        if re.match(r"^[A-Za-z]:", path):
            return False, "TARGET_WINDOWS_ABSOLUTE"

        if ".." in path:
            return False, "TARGET_TRAVERSAL"

        parts = path.split("/")
        for part in parts:
            if not part:
                return False, "TARGET_EMPTY_SEGMENT"

            if part.strip() == ".":
                return False, "TARGET_CURRENT_DIR"

            if re.search(ObsidianPathValidator.INVALID_CHARS, part):
                return False, "TARGET_INVALID_CHARS"

            if part.lower() in ObsidianPathValidator.WINDOWS_RESERVED:
                return False, "TARGET_RESERVED_NAME"

        return True, ""

    @staticmethod
    def validate_target_under_vault(vault_root: Path, target_relative_path: str) -> tuple[bool, str]:
        target_full = vault_root.resolve() / target_relative_path
        target_full = target_full.resolve()

        try:
            target_full.relative_to(vault_root.resolve())
        except ValueError:
            return False, "TARGET_OUTSIDE_VAULT"

        if target_full == vault_root.resolve():
            return False, "TARGET_IS_VAULT_ROOT"

        for part in target_full.parents:
            if part == vault_root.resolve():
                break
            if ProjectCloneService._is_link_or_reparse_point(part):
                return False, "TARGET_PARENT_IS_LINK"

        return True, ""

    @staticmethod
    def validate(vault_root: Path, target_relative_path: str) -> tuple[bool, str]:
        ok, reason = ObsidianPathValidator.validate_vault_root(vault_root)
        if not ok:
            return False, reason

        ok, reason = ObsidianPathValidator.validate_target_relative_path(target_relative_path)
        if not ok:
            return False, reason

        ok, reason = ObsidianPathValidator.validate_target_under_vault(vault_root, target_relative_path)
        if not ok:
            return False, reason

        return True, ""