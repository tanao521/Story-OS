from __future__ import annotations

import json
from pathlib import Path

import commands
from core.project import ensure_project_structure
from core.setup_wizard import create_story_project


def _form() -> dict[str, object]:
    return {
        "title": "我剪辑命运，现实全崩了",
        "genre": "其他",
        "custom_genre": "命运剪辑流",
        "length_type": "长篇",
        "target_word_count": 3000000,
        "narration": "第三人称有限视角",
        "character_structure": "单男主",
        "romance_level": "轻微",
        "tone": "冷峻但不绝望",
        "writing_style": "电影感",
        "world_style": "现代都市暗层存在叙事能力者",
        "focus": ["被剪辑过的死亡事件", "舆论操控", "命运剪辑师对抗"],
        "avoid": ["不要写成普通系统爽文", "不要能力无代价万能化"],
        "anti_ai_style_rules": ["减少不是A而是B句式", "减少破折号", "避免总结式结尾"],
    }


def test_create_story_project_initializes_lifecycle_files(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    result = create_story_project(_form(), "data")

    for relative in [
        "data/project_config.json",
        "data/story_spec.json",
        "data/story_blueprint.json",
        "data/plot_state.json",
        "data/chapter_index.json",
        "data/characters.json",
        "data/world_rules.json",
        "data/world_bible.json",
        "data/state.json",
        "data/project.md",
        "chapters/.gitkeep",
        "logs/generation.log",
    ]:
        assert (tmp_path / relative).exists(), relative
    blueprint = json.loads((tmp_path / "data/story_blueprint.json").read_text(encoding="utf-8"))
    assert blueprint["basic_settings"]["title"] == "我剪辑命运，现实全崩了"
    assert blueprint["basic_settings"]["target_words"] == 3000000
    assert blueprint["world_and_plot"]["plot_focus"]
    assert "story_blueprint_path" in result


def test_plan_next_repairs_missing_blueprint(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    create_story_project(_form(), "data")
    (tmp_path / "data/story_blueprint.json").unlink()

    result = commands.plan_next_command()

    assert result["status"] == "success"
    assert (tmp_path / "data/story_blueprint.json").exists()
    assert (tmp_path / "data/next_chapter_plan.json").exists()
    assert "缺少 data/story_blueprint.json" not in result["message"]


def test_ensure_project_structure_backs_up_broken_blueprint(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "story_spec.json").write_text(json.dumps(_form(), ensure_ascii=False), encoding="utf-8")
    (data_dir / "story_blueprint.json").write_text("{ broken", encoding="utf-8")

    ensure_project_structure(tmp_path)

    assert (data_dir / "story_blueprint.broken.json").exists()
    blueprint = json.loads((data_dir / "story_blueprint.json").read_text(encoding="utf-8"))
    assert blueprint["project_meta"]["status"] == "initialized"
