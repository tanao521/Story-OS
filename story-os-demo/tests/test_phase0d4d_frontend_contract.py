"""Focused static guardrails for the RC1 browser-confirm implementation.

These checks supplement, and never replace, the real Chromium acceptance run.
"""
from pathlib import Path


JS_PATH = Path(__file__).resolve().parents[1] / "web" / "static" / "simulator-narrative-turn.js"


def _source() -> str:
    return JS_PATH.read_text(encoding="utf-8")


def test_stale_validation_preview_and_custom_action_fail_closed() -> None:
    source = _source()
    assert "state.validationDto.context_fingerprint !== state.contextDto.context_fingerprint" in source
    assert "state.previewDto.context_fingerprint !== state.contextDto.context_fingerprint" in source
    assert "state.previewDto.validation_status !== state.validationDto.status" in source
    assert "state.previewDto.custom_action_text_hash !== state.validationDto.custom_action_text_hash" in source


def test_action_url_update_does_not_synthesize_popstate() -> None:
    source = _source()
    push_url = source[source.index("function pushUrl"):source.index("// ---- API helpers")]
    assert "history.pushState" in push_url
    assert "dispatchEvent" not in push_url


def test_success_cleanup_is_null_safe_and_rebinds_context() -> None:
    source = _source()
    assert "if (!validation)" in source
    assert "if (!preview)" in source
    assert "await rebindContextAfterConfirm(parsed, resp.data.branch_state_revision)" in source
    assert "rebound.branch_state_revision !== expectedRevision" in source


def test_preview_completion_refreshes_confirm_gate() -> None:
    source = _source()
    preview_update = source[source.index("state.previewDto = prevResp.data"):]
    assert preview_update.index("renderPrimaryAction()") < preview_update.index("} catch (err)")

