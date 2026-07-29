from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web" / "static" / "simulator-usable-loop.js").read_text(encoding="utf-8")
TURN_JS = (ROOT / "web" / "static" / "simulator-narrative-turn.js").read_text(encoding="utf-8")


def test_continue_reads_authoritative_next_plan_without_constructing_turn_id():
    assert "continueNextTurn" in JS
    assert 'pushUrl({ view: "narrative-turn", turn_id: null' in JS
    assert "storyos:narrative-turn-confirmed" in TURN_JS
    assert "generateOperationId" in TURN_JS


def test_result_acknowledgement_is_single_primary_action():
    assert "data-continue-next-turn" in JS
    assert "Continue to next turn" in JS

