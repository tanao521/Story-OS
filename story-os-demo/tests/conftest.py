from __future__ import annotations

import pytest

import config


@pytest.fixture(autouse=True)
def disable_real_local_model_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "USE_LOCAL_MODEL_FOR_DRAFT", False, raising=False)
    monkeypatch.setattr(config, "USE_DEEPSEEK_FOR_EDITING", False, raising=False)
