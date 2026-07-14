from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from core.project_context import get_project_context
from evaluation_engine import EvaluationService
from evaluation_engine.improvement_policy import ImprovementPolicyError
from evaluation_engine.improvement_service import ImprovementService
from tests.test_evaluation_engine import _project


class Gateway:
    def generate_json(self, task_type: str, *_args, **_kwargs):
        if task_type == "chapter_quality_plan":
            return {"patches": [{"issue_ids": [self.issue_id], "paragraph_start": 1, "paragraph_end": 1,
                                 "anchor": "主角在雨夜发现线索。", "action": "improve_readability", "instruction": "精简表述"}]}
        return {"replacements": [{"patch_index": 0, "anchor": "主角在雨夜发现线索。", "replacement": "主角在雨夜找到线索。"}]}


def _prepared(tmp_path: Path):
    _project(tmp_path); context = get_project_context(tmp_path)
    draft = {"chapter_id": 1, "source_type": "draft", "source_version": 1, "draft_text": "开场气氛沉静。" * 9 + "\n\n主角在雨夜发现线索。", "generation": {}}
    (tmp_path / "data" / "drafts" / "chapter_001_draft_v001.json").write_text(__import__("json").dumps(draft, ensure_ascii=False), encoding="utf-8")
    report, _ = EvaluationService(context).generate({"target_type": "chapter_draft", "chapter_number": 1})
    report["priority_issues"] = [{"issue_id": "readability-local", "title": "局部可读性", "description": "精简重复表达", "severity": "low", "fixability": "auto_low_risk", "location_refs": [], "evidence_refs": [], "affected_dimensions": ["prose_readability"]}]
    (tmp_path / "data" / "evaluations" / "chapter_001" / f"{report['evaluation_id']}.json").write_text(__import__("json").dumps(report, ensure_ascii=False), encoding="utf-8")
    service = ImprovementService(context); eligible = [item for item in report["priority_issues"] if item["fixability"] == "auto_low_risk"]
    assert eligible
    item, replay = service.prepare(report["evaluation_id"], {"issue_ids": [eligible[0]["issue_id"]], "budget": "standard", "operation_id": "improve-1"})
    return service, item, eligible[0]["issue_id"]


def test_restricted_candidate_isolated_and_recomputed(tmp_path: Path) -> None:
    service, item, issue_id = _prepared(tmp_path); gateway = Gateway(); gateway.issue_id = issue_id
    result = service.run(item["improvement_id"], gateway=gateway)
    assert result["state"] in {"qualified", "review_required", "rejected"}
    stored = service.get(item["improvement_id"])
    assert stored["candidate"]["content_path"].startswith("data/evaluations/improvements/")
    assert stored["evaluation"]["target_type"] == "chapter_candidate"
    assert stored["comparison"]["note"].startswith("Recommendation only")
    assert not (tmp_path / "data" / "chapters" / "chapter_001.md").exists()


def test_improvement_replay_and_source_change_are_rejected(tmp_path: Path) -> None:
    service, item, issue_id = _prepared(tmp_path)
    replay, replayed = service.prepare(item["evaluation_id"], {"issue_ids": [issue_id], "operation_id": "improve-1"})
    assert replayed and replay["improvement_id"] == item["improvement_id"]
    draft = tmp_path / "data" / "drafts" / "chapter_001_draft_v001.json"
    draft.write_text('{"chapter_id":1,"draft_text":"已改变。"}', encoding="utf-8")
    with pytest.raises(ImprovementPolicyError) as error:
        service.prepare(item["evaluation_id"], {"issue_ids": [issue_id], "operation_id": "new"})
    assert error.value.code == "IMPROVEMENT_SOURCE_CHANGED"


def test_policy_rejects_non_auto_issue_and_limit(tmp_path: Path) -> None:
    service, item, issue_id = _prepared(tmp_path)
    with pytest.raises(ImprovementPolicyError) as error:
        service.prepare(item["evaluation_id"], {"issue_ids": ["not-a-real-issue"]})
    assert error.value.code == "IMPROVEMENT_ISSUE_NOT_AUTO_FIXABLE"
    for number in range(2):
        service.prepare(item["evaluation_id"], {"issue_ids": [issue_id], "operation_id": f"extra-{number}"})
    with pytest.raises(ImprovementPolicyError) as error:
        service.prepare(item["evaluation_id"], {"issue_ids": [issue_id], "operation_id": "fourth"})
    assert error.value.code == "IMPROVEMENT_CANDIDATE_LIMIT"
