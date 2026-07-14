"""Deterministic, local-only commercial feedback for a single story project.

These metrics are writing aids, not claims about live readers or markets.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import re

from core.project_context import ProjectContext
from system.data_store import DataStore


PERSONAS = {
    "爽文读者": {"focus": ["升级", "逆袭", "奖励", "打脸"], "avoid": ["推进过慢", "主角长期被动"]},
    "剧情党": {"focus": ["冲突", "反转", "伏笔", "目标"], "avoid": ["逻辑断裂", "无效支线"]},
    "感情党": {"focus": ["关系变化", "情绪", "选择"], "avoid": ["角色失真", "情感悬空"]},
    "世界观党": {"focus": ["设定", "规则", "探索"], "avoid": ["规则矛盾", "信息堆砌"]},
    "悬疑党": {"focus": ["谜团", "线索", "悬念"], "avoid": ["线索无回收", "谜底太早"]},
    "轻松日常党": {"focus": ["陪伴", "幽默", "日常"], "avoid": ["持续压抑", "冲突失控"]},
}

GENRE_HINTS = {
    "玄幻": ("成长与世界规则", "竞争中等，长线展开空间较高"),
    "科幻": ("设定自洽与未知探索", "创新空间较高，需要控制信息负荷"),
    "末世": ("生存压力与资源选择", "开局冲突优势明显，需避免重复危机"),
    "悬疑": ("谜团递进与线索回收", "读者预期较高，章节结尾需要持续承诺"),
    "都市": ("现实感、关系和即时目标", "竞争较强，差异化人设很关键"),
    "历史": ("时代质感与人物因果", "研究门槛较高，规则需前后一致"),
    "游戏": ("系统反馈和阶段目标", "节奏易建立，需避免数值重复"),
    "无限流": ("副本变化与主线悬念", "钩子密度优势，世界规则要清楚"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(value: int) -> int:
    return max(0, min(100, int(value)))


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


class AnalyticsService:
    """Owns analysis records under ``data/story_analytics`` for one project."""

    def __init__(self, context: ProjectContext) -> None:
        self.context, self.store = context, DataStore(context)

    @property
    def _profile_path(self) -> str:
        return "data/story_analytics/profile.json"

    def _spec(self) -> dict[str, Any]:
        return self.store.read_json("data/story_spec.json", default={}, expected_type=dict) or {}

    def _text_for_chapter(self, chapter_id: int) -> str:
        patterns = [f"data/chapters/chapter_{chapter_id:03d}.md", f"data/chapters/chapter_{chapter_id:03d}.json"]
        for path in patterns:
            if path.endswith(".md"):
                text = self.store.read_text(path, default="") or ""
            else:
                row = self.store.read_json(path, default={}, expected_type=dict) or {}
                text = str(row.get("content") or row.get("text") or row.get("chapter_text") or "")
            if text.strip():
                return text
        return ""

    @staticmethod
    def _count(text: str, words: tuple[str, ...]) -> int:
        return sum(text.lower().count(word.lower()) for word in words)

    def market(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        spec = self._spec(); overrides = overrides or {}
        genre = str(overrides.get("genre") or spec.get("genre") or "未分类")
        premise = " ".join(str(x) for x in (spec.get("focus") or []) + [str(spec.get("title") or ""), str(spec.get("world_style") or "")])
        hint, note = GENRE_HINTS.get(genre, ("明确读者承诺与核心冲突", "需要用项目设定补足定位依据"))
        distinct = len(set(re.findall(r"[\u4e00-\u9fff]{2,}", premise)))
        score = _clamp(52 + min(24, distinct * 2) + (8 if spec.get("tone") else 0))
        result = {"market_score": score, "genre": genre, "strengths": [hint, "已有创作设定可用于形成稳定读者承诺"],
                  "risks": ["这是本地规则评估，不代表真实平台热度", "需用前 3 章验证开篇承诺是否兑现"],
                  "recommended_positioning": f"围绕“{hint}”建立清晰卖点；{note}。",
                  "source": "rule_based", "disclaimer": "非真实市场数据，不预测收入或爆款概率。", "generated_at": _now()}
        self._save_section("market", result); return result

    def audience(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        spec = self._spec(); overrides = overrides or {}; focus = [str(x) for x in _as_list(spec.get("focus"))]
        genre = str(overrides.get("genre") or spec.get("genre") or "")
        primary = "悬疑党" if "悬" in genre else "爽文读者" if any(x in genre for x in ("玄", "末世", "游戏", "无限")) else "剧情党"
        profile = PERSONAS[primary]
        result = {"primary_audience": primary, "age_range": str(overrides.get("age_range") or "18-35"),
                  "reading_preferences": list(dict.fromkeys(profile["focus"] + focus))[:6], "pain_points": profile["avoid"],
                  "expected_experience": ["尽早理解主角目标", "每章获得可感知推进", "关键承诺有后续回应"],
                  "source": "ai_simulation", "disclaimer": "读者画像是基于题材和设定的模拟，不是实际用户调研。", "generated_at": _now()}
        self._save_section("audience", result); return result

    def chapter(self, chapter_id: int, text: str = "") -> dict[str, Any]:
        text = text or self._text_for_chapter(chapter_id)
        length = len(text); opening = text[:500]; ending = text[-500:]
        hook = _clamp(38 + min(30, len(opening) // 18) + self._count(opening, ("？", "?", "危机", "秘密", "突然", "却")) * 5)
        conflict = _clamp(30 + self._count(text, ("冲突", "争", "战", "阻", "危机", "对手", "代价")) * 7)
        emotion = _clamp(32 + self._count(text, ("爱", "怕", "痛", "笑", "怒", "期待", "失望")) * 6)
        character = _clamp(42 + self._count(text, ("想", "决定", "选择", "承诺", "犹豫")) * 5)
        world = _clamp(38 + self._count(text, ("规则", "世界", "系统", "设定", "城市", "宗门")) * 5)
        pacing = _clamp(45 + min(25, length // 300) + self._count(text, ("随后", "这时", "终于", "但是")) * 2)
        ending_hook = _clamp(35 + self._count(ending, ("？", "?", "秘密", "下一", "危险", "发现", "门")) * 9)
        scores = [hook, emotion, conflict, character, world, pacing, ending_hook]
        weak = []
        names = [(hook, "开篇吸引力"), (conflict, "冲突强度"), (pacing, "节奏推进"), (ending_hook, "结尾钩子")]
        weak = [name for score, name in names if score < 55]
        suggestions = [f"加强{item}，让读者在本章内看到明确变化。" for item in weak] or ["维持当前承诺，并在下一章兑现一个已建立的问题。"]
        result = {"chapter_id": chapter_id, "word_count": length, "opening_attraction": hook, "conflict_intensity": conflict,
                  "information_density": _clamp(35 + self._count(text, ("因为", "原来", "得知", "规则")) * 6), "emotion_curve": self._emotion_timeline(text),
                  "satisfaction_points": self._satisfaction(text, chapter_id), "reversals": self._count(text, ("原来", "却", "反而", "真相")),
                  "suspense": self._count(text, ("？", "?", "秘密", "未知")), "ending_hook": ending_hook,
                  "score": {"total": round(sum(scores) / len(scores)), "hook_score": hook, "emotion_score": emotion, "conflict_score": conflict, "character_score": character, "world_score": world, "pacing_score": pacing, "ending_hook_score": ending_hook, "weak_points": weak, "suggestions": suggestions, "source": "rule_based"},
                  "source": "rule_based", "disclaimer": "基于文本信号的写作辅助评分，不代表真实读者留存。", "generated_at": _now()}
        self._save_section(f"chapters/chapter_{chapter_id:03d}", result); return result

    def retention(self, chapter_ids: list[int] | None = None) -> dict[str, Any]:
        ids = chapter_ids or [1, 2, 3]; chapters = [self.chapter(i) for i in ids if self._text_for_chapter(i)]
        if not chapters: chapters = [self.chapter(1, "")]
        first = chapters[0]["score"]; average = sum(row["score"]["total"] for row in chapters) / len(chapters)
        c1 = round(min(.92, max(.28, .35 + first["hook_score"] / 180 + first["conflict_score"] / 360)), 2)
        result = {"chapter_1_retention": c1, "chapter_3_follow_rate": round(min(.88, c1 * (.76 + average / 500)), 2),
                  "chapter_10_drop_risk": "high" if average < 55 else "medium" if average < 72 else "low",
                  "drop_points": list(dict.fromkeys(sum((row["score"]["weak_points"] for row in chapters), []))) or ["未发现明显规则风险，仍建议人工复核。"],
                  "source": "ai_simulation", "disclaimer": "这是章节文本的 AI 模拟留存分，不是实际用户行为数据。", "generated_at": _now()}
        self._save_section("retention", result); return result

    def report(self) -> dict[str, Any]:
        market = self._load_section("market") or self.market(); audience = self._load_section("audience") or self.audience(); retention = self._load_section("retention") or self.retention()
        profile = self.profile(); result = {"one_sentence_pitch": f"面向{audience['primary_audience']}的{market['genre']}故事：以{market['strengths'][0]}驱动持续阅读。",
                  "core_readers": audience, "differentiators": market["strengths"], "risks": market["risks"] + retention["drop_points"],
                  "commercial_advice": [market["recommended_positioning"], "将前 3 章的主角目标、冲突和结尾问题写得可验证。"], "profile": profile,
                  "source": "rule_based", "disclaimer": "本报告只辅助创作决策；没有接入平台、收入或真实读者数据。", "generated_at": _now()}
        self._save_section("report", result); return result

    def profile(self) -> dict[str, Any]:
        current = self.store.read_json(self._profile_path, default={}, expected_type=dict) or {}; spec = self._spec()
        return {"project_id": self.context.root.name, "genre": current.get("genre") or spec.get("genre") or "", "target_audience": current.get("target_audience") or [], "market_position": current.get("market_position") or "", "competitive_elements": current.get("competitive_elements") or [], "unique_selling_points": current.get("unique_selling_points") or [], "risk_factors": current.get("risk_factors") or [], "lifecycle": current.get("lifecycle") or {"stage": "idea", "progress": 0, "risks": [], "next_goal": "完成定位分析"}, "source": "manual_input"}

    def update_profile(self, changes: dict[str, Any]) -> dict[str, Any]:
        profile = self.profile(); allowed = {"genre", "target_audience", "market_position", "competitive_elements", "unique_selling_points", "risk_factors", "lifecycle"}
        for key in allowed:
            if key in changes: profile[key] = changes[key]
        profile["updated_at"] = _now(); self.store.write_json(self._profile_path, profile, backup=True); return profile

    def dashboard(self) -> dict[str, Any]:
        market = self._load_section("market") or self.market(); audience = self._load_section("audience") or self.audience(); retention = self._load_section("retention") or self.retention()
        chapters_dir = self.context.chapters_dir; ids = sorted(int(m.group(1)) for path in chapters_dir.glob("chapter_*.md") if (m := re.search(r"chapter_(\d+)", path.name))) if chapters_dir.exists() else []
        latest = self._load_section(f"chapters/chapter_{ids[-1]:03d}") if ids else None
        return {"market": market, "audience": audience, "retention": retention, "latest_chapter": latest, "profile": self.profile(), "metric_sources": {"market": market["source"], "audience": audience["source"], "retention": retention["source"]}}

    def _emotion_timeline(self, text: str) -> list[dict[str, Any]]:
        if not text: return []
        chunks = [text[i:i + max(1, len(text) // 5)] for i in range(0, len(text), max(1, len(text) // 5))][:5]
        labels = [("紧张", ("危", "战", "怕")), ("期待", ("希望", "终于", "将")), ("悲伤", ("失", "痛", "泪")), ("惊讶", ("竟", "突然", "震"))]
        return [{"point": index + 1, "emotion": max(labels, key=lambda item: self._count(chunk, item[1]))[0], "intensity": _clamp(35 + max(self._count(chunk, words) for _, words in labels) * 12)} for index, chunk in enumerate(chunks)]

    def _satisfaction(self, text: str, chapter_id: int) -> list[dict[str, Any]]:
        kinds = {"reversal": ("逆转", "打脸", "反而"), "upgrade": ("升级", "突破", "奖励"), "reveal": ("真相", "秘密", "揭开"), "relationship": ("信任", "拥抱", "和解")}
        return [{"type": kind, "chapter": chapter_id, "strength": min(10, self._count(text, terms) * 3)} for kind, terms in kinds.items() if self._count(text, terms)]

    def _section_path(self, name: str) -> str: return f"data/story_analytics/{name}.json"
    def _save_section(self, name: str, value: dict[str, Any]) -> None: self.store.write_json(self._section_path(name), value)
    def _load_section(self, name: str) -> dict[str, Any] | None: return self.store.read_json(self._section_path(name), default=None, expected_type=dict)
