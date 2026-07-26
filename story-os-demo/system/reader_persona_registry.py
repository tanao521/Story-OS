from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.contracts.reader_persona import (
    FocusWeights,
    PersonaArchetype,
    PersonaPreferences,
    PersonaSensitivity,
    ReaderPersona,
    VALID_FOCUS_DIMENSIONS,
)


class ReaderPersonaRegistryError(Exception):
    pass


class ReaderPersonaRegistry:
    _instance: Optional["ReaderPersonaRegistry"] = None
    _personas: Dict[str, ReaderPersona] = {}

    def __new__(cls) -> "ReaderPersonaRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._personas = cls._load_builtin_personas()
        return cls._instance

    @classmethod
    def _load_builtin_personas(cls) -> Dict[str, ReaderPersona]:
        personas = {}

        hook_driven = ReaderPersona(
            persona_id="hook_driven_reader",
            persona_schema_version="1.0",
            persona_version="1.0",
            display_name="钩子驱动型读者",
            description="关注开篇吸引力、章末钩子、悬念和回报，决定是否继续阅读",
            archetype=PersonaArchetype.HOOK_DRIVEN,
            focus_weights=FocusWeights(
                hook=0.25,
                pacing=0.15,
                conflict=0.15,
                clarity=0.10,
                continuity=0.10,
                payoff=0.15,
                style_naturalness=0.05,
                emotion=0.05,
            ),
            sensitivity=PersonaSensitivity(
                risk_sensitivity=0.7,
                repetition_sensitivity=0.5,
                slow_opening_sensitivity=0.8,
                continuity_sensitivity=0.3,
                logic_gap_sensitivity=0.4,
            ),
            preferences=PersonaPreferences(
                preferred_pacing="fast",
                preferred_dialogue_density="medium",
                preferred_emotion_intensity="high",
                preferred_hook_strength="strong",
            ),
        )
        personas[hook_driven.persona_id] = hook_driven

        character_empathy = ReaderPersona(
            persona_id="character_empathy_reader",
            persona_schema_version="1.0",
            persona_version="1.0",
            display_name="角色共情型读者",
            description="关注人物情绪、动机可理解性、关系变化、情感回报和行为自然度",
            archetype=PersonaArchetype.CHARACTER_EMPATHY,
            focus_weights=FocusWeights(
                hook=0.05,
                pacing=0.10,
                conflict=0.15,
                clarity=0.15,
                continuity=0.15,
                payoff=0.10,
                style_naturalness=0.15,
                emotion=0.25,
            ),
            sensitivity=PersonaSensitivity(
                risk_sensitivity=0.5,
                repetition_sensitivity=0.4,
                slow_opening_sensitivity=0.3,
                continuity_sensitivity=0.6,
                logic_gap_sensitivity=0.5,
            ),
            preferences=PersonaPreferences(
                preferred_pacing="balanced",
                preferred_dialogue_density="high",
                preferred_emotion_intensity="high",
                preferred_hook_strength="moderate",
            ),
        )
        personas[character_empathy.persona_id] = character_empathy

        pacing_sensitive = ReaderPersona(
            persona_id="pacing_sensitive_reader",
            persona_schema_version="1.0",
            persona_version="1.0",
            display_name="节奏敏感型读者",
            description="关注推进速度、信息密度、段落节奏、重复和长时间无事件变化",
            archetype=PersonaArchetype.PACING_SENSITIVE,
            focus_weights=FocusWeights(
                hook=0.10,
                pacing=0.30,
                conflict=0.15,
                clarity=0.15,
                continuity=0.10,
                payoff=0.10,
                style_naturalness=0.05,
                emotion=0.05,
            ),
            sensitivity=PersonaSensitivity(
                risk_sensitivity=0.6,
                repetition_sensitivity=0.8,
                slow_opening_sensitivity=0.7,
                continuity_sensitivity=0.4,
                logic_gap_sensitivity=0.3,
            ),
            preferences=PersonaPreferences(
                preferred_pacing="fast",
                preferred_dialogue_density="medium",
                preferred_emotion_intensity="moderate",
                preferred_hook_strength="moderate",
            ),
        )
        personas[pacing_sensitive.persona_id] = pacing_sensitive

        continuity_core = ReaderPersona(
            persona_id="continuity_core_reader",
            persona_schema_version="1.0",
            persona_version="1.0",
            display_name="连续性核心读者",
            description="关注前后连续性、设定一致性、人物状态、时间线和未解释的逻辑跳跃",
            archetype=PersonaArchetype.CONTINUITY_SENSITIVE,
            focus_weights=FocusWeights(
                hook=0.05,
                pacing=0.10,
                conflict=0.10,
                clarity=0.15,
                continuity=0.35,
                payoff=0.10,
                style_naturalness=0.10,
                emotion=0.05,
            ),
            sensitivity=PersonaSensitivity(
                risk_sensitivity=0.5,
                repetition_sensitivity=0.3,
                slow_opening_sensitivity=0.2,
                continuity_sensitivity=0.9,
                logic_gap_sensitivity=0.8,
            ),
            preferences=PersonaPreferences(
                preferred_pacing="balanced",
                preferred_dialogue_density="medium",
                preferred_emotion_intensity="low",
                preferred_hook_strength="weak",
            ),
        )
        personas[continuity_core.persona_id] = continuity_core

        world_logic = ReaderPersona(
            persona_id="world_logic_reader",
            persona_schema_version="1.0",
            persona_version="1.0",
            display_name="世界逻辑型读者",
            description="关注世界规则、因果关系、能力边界、资源限制和情节解决是否依赖偶然",
            archetype=PersonaArchetype.WORLD_LOGIC,
            focus_weights=FocusWeights(
                hook=0.05,
                pacing=0.10,
                conflict=0.15,
                clarity=0.20,
                continuity=0.15,
                payoff=0.10,
                style_naturalness=0.10,
                emotion=0.15,
            ),
            sensitivity=PersonaSensitivity(
                risk_sensitivity=0.4,
                repetition_sensitivity=0.3,
                slow_opening_sensitivity=0.3,
                continuity_sensitivity=0.7,
                logic_gap_sensitivity=0.9,
            ),
            preferences=PersonaPreferences(
                preferred_pacing="balanced",
                preferred_dialogue_density="low",
                preferred_emotion_intensity="low",
                preferred_hook_strength="moderate",
            ),
        )
        personas[world_logic.persona_id] = world_logic

        return personas

    def get_persona(self, persona_id: str) -> ReaderPersona:
        persona = self._personas.get(persona_id)
        if persona is None:
            raise ReaderPersonaRegistryError(f"Unknown persona_id: {persona_id}")
        if not persona.enabled:
            raise ReaderPersonaRegistryError(f"Persona {persona_id} is disabled")
        return persona

    def list_personas(self) -> List[ReaderPersona]:
        return sorted(self._personas.values(), key=lambda x: x.persona_id)

    def validate_persona_ids(self, persona_ids: List[str]) -> None:
        seen = set()
        for pid in persona_ids:
            if pid in seen:
                raise ReaderPersonaRegistryError(f"Duplicate persona_id: {pid}")
            seen.add(pid)
            self.get_persona(pid)

    def calculate_persona_set_fingerprint(self, persona_ids: List[str]) -> str:
        import hashlib
        import json

        sorted_ids = sorted(persona_ids)
        payload = []
        for pid in sorted_ids:
            persona = self.get_persona(pid)
            payload.append({
                "persona_id": persona.persona_id,
                "persona_version": persona.persona_version,
                "persona_fingerprint": persona.persona_fingerprint,
            })
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def get_persona_versions(self, persona_ids: List[str]) -> Dict[str, str]:
        return {pid: self.get_persona(pid).persona_version for pid in persona_ids}

    def is_valid_focus_dimension(self, dimension: str) -> bool:
        return dimension in VALID_FOCUS_DIMENSIONS