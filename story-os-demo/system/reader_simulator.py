from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.contracts.reader_simulation import (
    EmotionCurveNode,
    EngagementScore,
    FlagCategory,
    FlagSeverity,
    OptimizationSuggestion,
    ProblemFlag,
    ReaderSimulationResult,
    ReaderSimulationSnapshot,
    ReaderSimulationSource,
    ReaderSimulationRequest,
    ReaderSimulationRun,
    RetentionLevel,
    RetentionRisk,
    RunStatus,
    SimulationMode,
    NovelHealth,
    to_public_score,
    score_level,
    retention_level,
)
from core.project_context import ProjectContext, get_project_context
from system.data_store import DataStore
from system.version_manager import (
    get_selected_version,
    list_versions,
    read_version_payload,
)


EVALUATOR_VERSION = "reader-rule-v1"
SNAPSHOT_SCHEMA_VERSION = "1.0"
RUN_SCHEMA_VERSION = "1.0"


class ReaderSimulatorError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class ReaderSimulatorService:
    def __init__(self, context: Optional[ProjectContext] = None) -> None:
        self.context = context or get_project_context()
        self.store = DataStore(self.context)

    def run_simulation(
        self,
        request: ReaderSimulationRequest,
    ) -> ReaderSimulationRun:
        self._validate_request(request)

        run_id = self._generate_run_id(request)
        run = ReaderSimulationRun(
            run_id=run_id,
            run_schema_version=RUN_SCHEMA_VERSION,
            status=RunStatus.COMPLETED,
            request=request,
            snapshot=ReaderSimulationSnapshot(
                snapshot_id="",
                snapshot_schema_version=SNAPSHOT_SCHEMA_VERSION,
                project_id="",
                timeline_id="",
                chapter_id=0,
                source=ReaderSimulationSource(
                    chapter_id=0,
                    source_version_id="",
                    source_type="",
                    source_path="",
                    source_hash="",
                    title="",
                    character_count=0,
                    resolved_at=datetime.now(),
                ),
            ),
            warnings=[],
        )

        try:
            snapshot = self._build_snapshot(request)
            result = self._evaluate(snapshot)
            run = ReaderSimulationRun(
                run_id=run_id,
                run_schema_version=RUN_SCHEMA_VERSION,
                status=RunStatus.COMPLETED,
                request=request,
                snapshot=snapshot,
                result=result,
                warnings=[],
                created_at=datetime.now(),
                completed_at=datetime.now(),
            )
        except Exception as exc:
            run = ReaderSimulationRun(
                run_id=run_id,
                run_schema_version=RUN_SCHEMA_VERSION,
                status=RunStatus.FAILED,
                request=request,
                snapshot=run.snapshot,
                warnings=[],
                error=str(exc),
                created_at=datetime.now(),
                completed_at=datetime.now(),
            )

        return run

    def _validate_request(self, request: ReaderSimulationRequest) -> None:
        if request.mode != SimulationMode.RULE:
            raise ReaderSimulatorError(
                "SIMULATION_MODE_NOT_SUPPORTED",
                f"Unsupported mode: {request.mode.value}. Only 'rule' mode is supported.",
            )
        if request.chapter_id < 1:
            raise ReaderSimulatorError(
                "INVALID_CHAPTER_ID", "chapter_id must be >= 1"
            )

    def _generate_run_id(self, request: ReaderSimulationRequest) -> str:
        seed = json.dumps(
            {
                "project_id": request.project_id,
                "timeline_id": request.timeline_id,
                "chapter_id": request.chapter_id,
                "source_version_id": request.source_version_id,
                "timestamp": datetime.now().isoformat(),
            },
            sort_keys=True,
        )
        return hashlib.sha256(seed.encode()).hexdigest()[:16]

    def _resolve_version(
        self, chapter_id: int, source_version_id: Optional[str]
    ) -> dict[str, Any]:
        versions = list_versions(chapter_id, self.context.data_dir)

        if source_version_id:
            parts = source_version_id.split("_v")
            if len(parts) == 2:
                source_type, version_str = parts
                try:
                    version = int(version_str)
                except ValueError:
                    pass
                else:
                    for item in versions.get("drafts", []):
                        if (
                            item.get("source_type") == source_type
                            and item.get("version") == version
                        ):
                            return item
                    for item in versions.get("edited", []):
                        if (
                            item.get("source_type") == source_type
                            and item.get("version") == version
                        ):
                            return item
                    for item in versions.get("manual", []):
                        if (
                            item.get("source_type") == source_type
                            and item.get("version") == version
                        ):
                            return item
            raise ReaderSimulatorError(
                "VERSION_NOT_FOUND",
                f"version_id '{source_version_id}' not found for chapter {chapter_id}",
            )

        selected = versions.get("selected", {})
        if selected:
            source_type = selected.get("source_type")
            version = selected.get("version")
            for item in versions.get("drafts", []):
                if (
                    item.get("source_type") == source_type
                    and item.get("version") == version
                ):
                    return item
            for item in versions.get("edited", []):
                if (
                    item.get("source_type") == source_type
                    and item.get("version") == version
                ):
                    return item
            for item in versions.get("manual", []):
                if (
                    item.get("source_type") == source_type
                    and item.get("version") == version
                ):
                    return item

        manual = versions.get("manual", [])
        if manual:
            return manual[-1]
        edited = versions.get("edited", [])
        if edited:
            return edited[-1]
        drafts = versions.get("drafts", [])
        if drafts:
            return drafts[-1]

        raise ReaderSimulatorError(
            "NO_VERSION_AVAILABLE",
            f"No version found for chapter {chapter_id}",
        )

    def _read_version_content(self, version_info: dict[str, Any]) -> tuple[str, str]:
        payload = read_version_payload(version_info)
        text = (
            payload.get("manual_text")
            or payload.get("edited_text")
            or payload.get("draft_text")
            or ""
        )
        content_hash = hashlib.sha256(str(text).encode()).hexdigest()
        return str(text), content_hash

    def _build_snapshot(self, request: ReaderSimulationRequest) -> ReaderSimulationSnapshot:
        version_info = self._resolve_version(request.chapter_id, request.source_version_id)
        text, content_hash = self._read_version_content(version_info)

        source = ReaderSimulationSource(
            chapter_id=request.chapter_id,
            source_version_id=f"{version_info['source_type']}_v{version_info['version']:03d}",
            source_type=version_info["source_type"],
            source_path=self._relative_path(version_info.get("json_path", "")),
            source_hash=content_hash,
            title=version_info.get("chapter_title", ""),
            character_count=len(text),
            resolved_at=datetime.now(),
        )

        missing_inputs: list[str] = []
        story_spec = self._load_story_spec(missing_inputs)
        chapter_plan = self._load_chapter_plan(request.chapter_id, missing_inputs)
        chapter_summary = self._load_chapter_summary(request.chapter_id, missing_inputs)
        pacing_data = self._load_pacing_data(request.chapter_id, missing_inputs)
        climax_data = self._load_climax_data(request.chapter_id, missing_inputs)
        conflict_data = self._load_conflict_data(request.chapter_id, missing_inputs)
        continuity_state = self._load_continuity_state(request.chapter_id, missing_inputs)

        context_refs = self._build_context_refs(request.chapter_id)
        context_hash = self._compute_context_hash(
            request=request,
            source_hash=content_hash,
            source_type=version_info["source_type"],
            title=version_info.get("chapter_title", ""),
            story_spec=story_spec,
            chapter_plan=chapter_plan,
            chapter_summary=chapter_summary,
            pacing_data=pacing_data,
            climax_data=climax_data,
            conflict_data=conflict_data,
            continuity_state=continuity_state,
            context_refs=context_refs,
            missing_inputs=missing_inputs,
        )

        snapshot_id = hashlib.sha256(
            f"{request.project_id}:{request.timeline_id}:{request.chapter_id}:{content_hash}:{context_hash}".encode()
        ).hexdigest()[:16]

        return ReaderSimulationSnapshot(
            snapshot_id=snapshot_id,
            snapshot_schema_version=SNAPSHOT_SCHEMA_VERSION,
            project_id=request.project_id,
            timeline_id=request.timeline_id,
            chapter_id=request.chapter_id,
            source=source,
            story_spec=story_spec,
            chapter_plan=chapter_plan,
            chapter_summary=chapter_summary,
            pacing_data=pacing_data,
            climax_data=climax_data,
            conflict_data=conflict_data,
            continuity_state=continuity_state,
            quality_evidence={},
            context_refs=context_refs,
            context_hash=context_hash,
            missing_inputs=missing_inputs,
            created_at=datetime.now(),
        )

    def _build_context_hash_payload(
        self,
        request: ReaderSimulationRequest,
        source_hash: str,
        source_type: str,
        title: str,
        story_spec: dict[str, Any],
        chapter_plan: dict[str, Any],
        chapter_summary: dict[str, Any],
        pacing_data: dict[str, Any],
        climax_data: dict[str, Any],
        conflict_data: dict[str, Any],
        continuity_state: dict[str, Any],
        context_refs: dict[str, Any],
        missing_inputs: list[str],
    ) -> dict[str, Any]:
        refs_payload = {}
        if "recent_chapters" in context_refs:
            refs_payload["recent_chapters"] = sorted(
                context_refs["recent_chapters"], key=lambda x: x.get("chapter_id", 0)
            )
        if "recent_summaries" in context_refs:
            refs_payload["recent_summaries"] = sorted(
                context_refs["recent_summaries"], key=lambda x: x.get("chapter_id", 0)
            )

        return {
            "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
            "project_id": request.project_id,
            "timeline_id": request.timeline_id,
            "chapter_id": request.chapter_id,
            "source_hash": source_hash,
            "source_type": source_type,
            "title": title,
            "story_spec": story_spec,
            "chapter_plan": chapter_plan,
            "chapter_summary": chapter_summary,
            "pacing_data": pacing_data,
            "climax_data": climax_data,
            "conflict_data": conflict_data,
            "continuity_state": continuity_state,
            "context_refs": refs_payload,
            "missing_inputs": sorted(missing_inputs),
        }

    def _compute_context_hash(
        self,
        request: ReaderSimulationRequest,
        source_hash: str,
        source_type: str,
        title: str,
        story_spec: dict[str, Any],
        chapter_plan: dict[str, Any],
        chapter_summary: dict[str, Any],
        pacing_data: dict[str, Any],
        climax_data: dict[str, Any],
        conflict_data: dict[str, Any],
        continuity_state: dict[str, Any],
        context_refs: dict[str, Any],
        missing_inputs: list[str],
    ) -> str:
        payload = self._build_context_hash_payload(
            request=request,
            source_hash=source_hash,
            source_type=source_type,
            title=title,
            story_spec=story_spec,
            chapter_plan=chapter_plan,
            chapter_summary=chapter_summary,
            pacing_data=pacing_data,
            climax_data=climax_data,
            conflict_data=conflict_data,
            continuity_state=continuity_state,
            context_refs=context_refs,
            missing_inputs=missing_inputs,
        )
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _load_story_spec(self, missing_inputs: list[str]) -> dict[str, Any]:
        spec_path = self.context.data_dir / "story_spec.json"
        if not self.store.exists(spec_path):
            missing_inputs.append("story_spec")
            return {}
        try:
            return self.store.read_json(spec_path, default={})
        except Exception:
            missing_inputs.append("story_spec")
            return {}

    def _load_chapter_plan(self, chapter_id: int, missing_inputs: list[str]) -> dict[str, Any]:
        planning_path = self.context.data_dir / "planning" / "planning.json"
        if not self.store.exists(planning_path):
            missing_inputs.append("chapter_plan")
            return {}
        try:
            planning = self.store.read_json(planning_path, default={})
            chapters = planning.get("chapters", [])
            for chapter in chapters:
                if int(chapter.get("chapter_number", chapter.get("chapter_id", 0)) or 0) == chapter_id:
                    return chapter
            return {}
        except Exception:
            missing_inputs.append("chapter_plan")
            return {}

    def _load_chapter_summary(self, chapter_id: int, missing_inputs: list[str]) -> dict[str, Any]:
        summary_path = self.context.summaries_dir / f"chapter_{chapter_id:03d}_summary.json"
        try:
            return self.store.read_json(summary_path, default={})
        except Exception:
            missing_inputs.append("chapter_summary")
            return {}

    def _load_pacing_data(self, chapter_id: int, missing_inputs: list[str]) -> dict[str, Any]:
        try:
            chapter_plan = self._load_chapter_plan(chapter_id, [])
            return chapter_plan.get("pacing_design", {})
        except Exception:
            missing_inputs.append("pacing_data")
            return {}

    def _load_climax_data(self, chapter_id: int, missing_inputs: list[str]) -> dict[str, Any]:
        try:
            chapter_plan = self._load_chapter_plan(chapter_id, [])
            return chapter_plan.get("climax_design", {})
        except Exception:
            missing_inputs.append("climax_data")
            return {}

    def _load_conflict_data(self, chapter_id: int, missing_inputs: list[str]) -> dict[str, Any]:
        try:
            chapter_plan = self._load_chapter_plan(chapter_id, [])
            return chapter_plan.get("conflict_design", {})
        except Exception:
            missing_inputs.append("conflict_data")
            return {}

    def _load_continuity_state(self, chapter_id: int, missing_inputs: list[str]) -> dict[str, Any]:
        try:
            state = self.store.read_json(self.context.data_dir / "state.json", default={})
            return {"current_chapter": state.get("current_chapter", 0)}
        except Exception:
            missing_inputs.append("continuity_state")
            return {}

    def _build_context_refs(self, chapter_id: int) -> dict[str, Any]:
        refs: dict[str, Any] = {
            "recent_chapters": [],
            "recent_summaries": [],
        }

        for prev_id in range(max(1, chapter_id - 3), chapter_id):
            summary_path = self.context.summaries_dir / f"chapter_{prev_id:03d}_summary.json"
            try:
                summary = self.store.read_json(summary_path, default={})
                if summary:
                    refs["recent_summaries"].append(
                        {"chapter_id": prev_id, "summary": summary.get("summary", "")[:500]}
                    )
            except Exception:
                pass

            chapter_path = self.context.chapters_dir / f"chapter_{prev_id:03d}.md"
            try:
                if self.store.exists(chapter_path):
                    refs["recent_chapters"].append({"chapter_id": prev_id})
            except Exception:
                pass

        return refs

    def _relative_path(self, abs_path: str) -> str:
        try:
            return Path(abs_path).relative_to(self.context.root).as_posix()
        except (OSError, ValueError):
            return ""

    def _evaluate(self, snapshot: ReaderSimulationSnapshot) -> ReaderSimulationResult:
        from system.quality_checker import evaluate_text_by_rules

        text = self._read_chapter_text(snapshot)
        if not text:
            return self._empty_result(snapshot)

        chapter_plan = snapshot.chapter_plan
        story_spec = snapshot.story_spec
        characters = story_spec.get("characters", {})
        world_bible = story_spec.get("world_bible", {})
        state = snapshot.continuity_state

        quality_result = evaluate_text_by_rules(
            text, chapter_plan, story_spec, characters, world_bible, state
        )

        engagement = self._build_engagement_score(snapshot, quality_result)
        retention = self._build_retention_risk(quality_result)
        emotion_curve = self._build_emotion_curve(text, snapshot)
        problem_flags = self._build_problem_flags(quality_result)
        suggestions = self._build_suggestions(quality_result, problem_flags)
        health = self._build_novel_health(snapshot, quality_result)

        return ReaderSimulationResult(
            engagement_score=engagement,
            retention_risk=retention,
            reader_emotion_curve=emotion_curve,
            problem_flags=problem_flags,
            optimization_suggestions=suggestions,
            novel_health=health,
            evaluator_version=EVALUATOR_VERSION,
            evaluated_at=datetime.now(),
        )

    def _read_chapter_text(self, snapshot: ReaderSimulationSnapshot) -> str:
        try:
            version_info = self._resolve_version(
                snapshot.chapter_id, snapshot.source.source_version_id
            )
            text, _ = self._read_version_content(version_info)
            return text
        except Exception:
            return ""

    def _empty_result(self, snapshot: ReaderSimulationSnapshot) -> ReaderSimulationResult:
        return ReaderSimulationResult(
            engagement_score=EngagementScore(
                score=0.0,
                level="critical",
                reasons=["No chapter text available"],
                evidence=[],
            ),
            retention_risk=RetentionRisk(
                score=100.0,
                level=RetentionLevel.CRITICAL,
                risk_points=["No chapter text available"],
            ),
            reader_emotion_curve=[],
            problem_flags=[
                ProblemFlag(
                    code="empty_text",
                    severity=FlagSeverity.HIGH,
                    category=FlagCategory.CONTENT,
                    message="章节文本为空",
                    evidence=[],
                )
            ],
            optimization_suggestions=[],
            novel_health=NovelHealth(
                overall_score=0.0,
                pacing=0.0,
                clarity=0.0,
                continuity=0.0,
                conflict=0.0,
                payoff=0.0,
                style_stability=0.0,
                warnings=["No chapter text available"],
            ),
            evaluator_version=EVALUATOR_VERSION,
            evaluated_at=datetime.now(),
        )

    def _build_engagement_score(
        self, snapshot: ReaderSimulationSnapshot, quality: dict[str, Any]
    ) -> EngagementScore:
        scores = quality.get("scores", {})
        pacing = float(scores.get("pacing", 0.5))
        hook = float(scores.get("hook_strength", 0.5))
        emotion = float(scores.get("style_naturalness", 0.5))

        normalized = round((pacing * 0.4 + hook * 0.35 + emotion * 0.25), 4)
        normalized = max(0.0, min(1.0, normalized))
        score = to_public_score(normalized)
        level = score_level(score)

        reasons: list[str] = []
        evidence: list[str] = []

        if pacing >= 0.8:
            reasons.append("节奏紧凑")
        elif pacing < 0.5:
            reasons.append("节奏偏慢")
        evidence.append(f"pacing={to_public_score(pacing):.1f}")

        if hook >= 0.8:
            reasons.append("结尾钩子有力")
        elif hook < 0.5:
            reasons.append("结尾钩子较弱")
        evidence.append(f"hook_strength={to_public_score(hook):.1f}")

        if emotion >= 0.8:
            reasons.append("风格自然")
        elif emotion < 0.5:
            reasons.append("风格不够自然")
        evidence.append(f"style_naturalness={to_public_score(emotion):.1f}")

        if not reasons:
            reasons.append("综合评估")

        return EngagementScore(score=score, level=level, reasons=reasons, evidence=evidence)

    def _build_retention_risk(self, quality: dict[str, Any]) -> RetentionRisk:
        overall = float(quality.get("overall_score", 0.5))
        normalized = round(1.0 - overall, 4)
        normalized = max(0.0, min(1.0, normalized))
        score = to_public_score(normalized)
        level = retention_level(score)

        risk_points: list[str] = []
        scores = quality.get("scores", {})

        if float(scores.get("readability", 1.0)) < 0.6:
            risk_points.append("可读性较低")
        if float(scores.get("hook_strength", 1.0)) < 0.5:
            risk_points.append("缺少吸引继续阅读的钩子")
        if float(scores.get("style_naturalness", 1.0)) < 0.5:
            risk_points.append("文本风格不够自然")
        if float(scores.get("story_goal_alignment", 1.0)) < 0.5:
            risk_points.append("章节目标不清晰")

        if not risk_points:
            risk_points.append("整体评估")

        return RetentionRisk(score=score, level=level, risk_points=risk_points)

    def _build_emotion_curve(self, text: str, snapshot: ReaderSimulationSnapshot) -> list[EmotionCurveNode]:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            return []

        nodes: list[EmotionCurveNode] = []
        total = len(paragraphs)
        segment_size = max(1, total // 5)

        for i in range(0, total, segment_size):
            end = min(i + segment_size, total)
            segment = paragraphs[i:end]
            position = (i + segment_size // 2) / total

            segment_text = "\n".join(segment)
            tension = self._calculate_tension(segment_text)
            curiosity = self._calculate_curiosity(segment_text, snapshot)
            intensity = self._calculate_intensity(segment_text)
            payoff = self._calculate_payoff(segment_text)

            labels = ["开篇", "发展", "高潮", "回落", "结尾"]
            label_idx = min(i // segment_size, len(labels) - 1)

            nodes.append(
                EmotionCurveNode(
                    position=round(position, 2),
                    segment_label=labels[label_idx],
                    tension=round(tension, 2),
                    curiosity=round(curiosity, 2),
                    emotional_intensity=round(intensity, 2),
                    payoff=round(payoff, 2),
                    evidence=[],
                )
            )

        return nodes

    def _calculate_tension(self, text: str) -> float:
        action_terms = ["走", "看", "推", "跑", "打开", "停", "听", "抓", "退", "冲"]
        conflict_terms = ["冲突", "危险", "压力", "争", "挡", "威胁", "失败", "代价"]
        score = 0.5
        if any(term in text for term in action_terms):
            score += 0.2
        if any(term in text for term in conflict_terms):
            score += 0.2
        return min(1.0, score)

    def _calculate_curiosity(self, text: str, snapshot: ReaderSimulationSnapshot) -> float:
        hook_text = snapshot.chapter_plan.get("pacing_design", {}).get("ending_hook", "")
        if hook_text and hook_text in text[-500:]:
            return 0.7
        question_markers = ["？", "?", "为什么", "如何", "怎么"]
        count = sum(text.count(m) for m in question_markers)
        return min(1.0, 0.3 + count * 0.1)

    def _calculate_intensity(self, text: str) -> float:
        exclamation_count = text.count("！") + text.count("!")
        question_count = text.count("？") + text.count("?")
        return min(1.0, 0.3 + (exclamation_count + question_count) * 0.1)

    def _calculate_payoff(self, text: str) -> float:
        resolution_terms = ["终于", "原来", "明白了", "真相", "结局"]
        if any(term in text for term in resolution_terms):
            return 0.7
        return 0.3

    def _build_problem_flags(self, quality: dict[str, Any]) -> list[ProblemFlag]:
        flags: list[ProblemFlag] = []
        quality_flags = quality.get("flags", [])

        for qf in quality_flags:
            severity = self._map_severity(qf.get("severity", "medium"))
            category = self._map_category(qf.get("type", "content"))

            flags.append(
                ProblemFlag(
                    code=str(qf.get("type", "")),
                    severity=severity,
                    category=category,
                    message=str(qf.get("message", "")),
                    evidence=[str(e) for e in qf.get("evidence", [])],
                )
            )

        return flags

    def _map_severity(self, severity: str) -> FlagSeverity:
        if severity == "high":
            return FlagSeverity.HIGH
        if severity == "medium":
            return FlagSeverity.MEDIUM
        return FlagSeverity.LOW

    def _map_category(self, flag_type: str) -> FlagCategory:
        mapping = {
            "story_goal_alignment": FlagCategory.CONTENT,
            "continuity": FlagCategory.CONTINUITY,
            "character_voice": FlagCategory.CHARACTER,
            "style_naturalness": FlagCategory.STYLE,
            "anti_ai_style": FlagCategory.STYLE,
            "pacing": FlagCategory.PACING,
            "hook_strength": FlagCategory.STRUCTURE,
            "readability": FlagCategory.READABILITY,
        }
        return mapping.get(flag_type, FlagCategory.CONTENT)

    def _build_suggestions(
        self, quality: dict[str, Any], problem_flags: list[ProblemFlag]
    ) -> list[OptimizationSuggestion]:
        suggestions: list[OptimizationSuggestion] = []
        flag_codes = {f.code for f in problem_flags}

        if "hook_strength" in flag_codes:
            suggestions.append(
                OptimizationSuggestion(
                    priority=1,
                    target="结尾钩子",
                    reason="结尾钩子较弱，读者可能缺乏继续阅读的动力",
                    expected_effect="增强读者好奇心，提高下一章阅读意愿",
                    related_flag_codes=["hook_strength"],
                )
            )

        if "style_naturalness" in flag_codes or "anti_ai_style" in flag_codes:
            suggestions.append(
                OptimizationSuggestion(
                    priority=2,
                    target="叙述风格",
                    reason="文本存在模板化或AI风格表达",
                    expected_effect="使文本更自然，接近真人写作",
                    related_flag_codes=["style_naturalness", "anti_ai_style"],
                )
            )

        if "character_voice" in flag_codes:
            suggestions.append(
                OptimizationSuggestion(
                    priority=3,
                    target="人物对话",
                    reason="缺少可识别的人物台词",
                    expected_effect="增强人物辨识度和代入感",
                    related_flag_codes=["character_voice"],
                )
            )

        if "story_goal_alignment" in flag_codes:
            suggestions.append(
                OptimizationSuggestion(
                    priority=4,
                    target="章节目标",
                    reason="章节内容未充分体现章节目标",
                    expected_effect="使章节更聚焦，推进主线剧情",
                    related_flag_codes=["story_goal_alignment"],
                )
            )

        if "readability" in flag_codes:
            suggestions.append(
                OptimizationSuggestion(
                    priority=5,
                    target="可读性",
                    reason="文本长度或结构影响阅读体验",
                    expected_effect="提升阅读流畅度",
                    related_flag_codes=["readability"],
                )
            )

        return suggestions

    def _build_novel_health(self, snapshot: ReaderSimulationSnapshot, quality: dict[str, Any]) -> NovelHealth:
        scores = quality.get("scores", {})

        overall_norm = float(quality.get("overall_score", 0.5))
        pacing_norm = float(scores.get("pacing", 0.5))
        clarity_norm = float(scores.get("readability", 0.5))
        continuity_norm = float(scores.get("continuity", 0.5))
        conflict_norm = float(scores.get("story_goal_alignment", 0.5)) * 0.5 + float(scores.get("character_voice", 0.5)) * 0.5
        payoff_norm = float(scores.get("hook_strength", 0.5))
        style_norm = float(scores.get("style_naturalness", 0.5))

        overall = to_public_score(overall_norm)
        pacing = to_public_score(pacing_norm)
        clarity = to_public_score(clarity_norm)
        continuity = to_public_score(continuity_norm)
        conflict = to_public_score(conflict_norm)
        payoff = to_public_score(payoff_norm)
        style_stability = to_public_score(style_norm)

        warnings: list[str] = []
        if overall < 40:
            warnings.append("整体健康度较低，建议全面检查")
        if pacing < 40:
            warnings.append("节奏过慢，可能影响读者体验")
        if payoff < 40:
            warnings.append("结尾缺少有效钩子")

        return NovelHealth(
            overall_score=overall,
            pacing=pacing,
            clarity=clarity,
            continuity=continuity,
            conflict=conflict,
            payoff=payoff,
            style_stability=style_stability,
            warnings=warnings,
        )