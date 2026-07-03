from __future__ import annotations

import json

from core.setup_wizard import build_initial_state
from system.file_store import save_json
from system.validators import validate_story_spec


def make_story_spec() -> dict[str, object]:
    return {
        "title": "未命名小说",
        "genre": "科幻",
        "length_type": "长篇",
        "target_word_count": 300000,
        "world_style": "近未来末世",
        "tone": "灰暗但不绝望",
        "writing_style": "电影感",
        "narration": "第三人称有限视角",
        "character_structure": "群像文",
        "romance_level": "轻微",
        "focus": ["生存", "人物成长"],
        "avoid": ["不要流水账"],
        "anti_ai_style_rules": [
            "减少‘不是A，而是B’句式",
            "减少破折号",
            "避免总结式表达",
            "避免过度解释人物情绪",
            "用动作和细节代替情绪直述",
        ],
        "need_outline": True,
    }


def test_build_initial_state_uses_story_spec_world_style() -> None:
    story_spec = make_story_spec()

    state = build_initial_state(story_spec)

    assert state["project_status"] == "initialized"
    assert state["current_stage"] == "setup"
    assert state["current_chapter"] == 0
    assert state["world"]["style"] == "近未来末世"


def test_initial_state_memory_policy_keeps_three_working_chapters() -> None:
    state = build_initial_state(make_story_spec())

    assert state["memory_policy"]["working_context_chapters"] == 3


def test_validate_story_spec_returns_no_errors_for_complete_spec() -> None:
    errors = validate_story_spec(make_story_spec())

    assert errors == []


def test_save_json_writes_utf8_json_file(tmp_path) -> None:
    target = tmp_path / "story_spec.json"
    story_spec = make_story_spec()

    save_json(str(target), story_spec)

    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["title"] == "未命名小说"
    assert loaded["focus"] == ["生存", "人物成长"]
