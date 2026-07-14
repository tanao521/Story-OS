"""Small orchestration facade; individual services retain ownership of their data."""
from __future__ import annotations

from core.project_context import ProjectContext
from creative_loop.critic_service import CriticService
from creative_loop.evolution_service import EvolutionService
from creative_loop.experiment_service import ExperimentService
from creative_loop.health_service import HealthService
from creative_loop.issue_detector import IssueDetector
from creative_loop.pattern_service import PatternService
from creative_loop.outcome_service import OutcomeService
from creative_loop.proposal_service import ProposalService
from creative_loop.reflection_service import ReflectionService
from creative_loop.profile_service import AnalysisProfileService
from creative_loop.lifecycle import LifecycleService


class CreativeLoop:
    def __init__(self, context: ProjectContext) -> None:
        self.context=context; self.reflections=ReflectionService(context); self.health=HealthService(context); self.issues=IssueDetector(context); self.proposals=ProposalService(context); self.experiments=ExperimentService(context); self.patterns=PatternService(context); self.outcomes=OutcomeService(context); self.evolution=EvolutionService(context); self.critic=CriticService(); self.profiles=AnalysisProfileService(context); self.lifecycle=LifecycleService(context)

    def reflect_chapter(self, chapter_id: int, *, force: bool = False, profile: str | None = None) -> dict:
        settings = self.profiles.resolved(profile)
        reflection=self.reflections.reflect(chapter_id, force=force, analysis_profile=settings["profile"], prompt_version=settings["prompt_version"])
        health=self.health.calculate(reflection); issues=self.issues.detect(reflection,health)
        critic=self.critic.critique(reflection,health,self.issues.list()) if settings["enable_deep_critic"] else None
        return {"reflection":reflection,"health":health,"issues":issues,"critic":critic,"analysis_profile":settings}

    def overview(self) -> dict:
        return {"latest_health":self.health.latest(),"health_history":self.health.history(10),"issues":self.issues.list(),"proposals":self.proposals.list(),"experiments":self.experiments.list(),"patterns":self.patterns.list(),"outcomes":self.outcomes.list(),"timeline":self.evolution.timeline(limit=30),"analysis_profile":self.profiles.get(),"system_health":self.system_health()}

    def system_health(self) -> dict:
        committed = list(self.context.chapters_dir.glob("chapter_*.md")) if self.context.chapters_dir.exists() else []
        reflections = self.reflections.list(); health = self.health.history(200); proposals = self.proposals.list(); experiments = self.experiments.list(); patterns = self.patterns.list()
        jobs = [self.reflections.store.read_json(path, default={}, expected_type=dict) or {} for path in self.context.jobs_dir.glob("*.json")] if self.context.jobs_dir.exists() else []
        return {"reflection_coverage": {"completed": len([x for x in reflections if x.get("status") == "completed"]), "chapters": len(committed)}, "health_coverage": {"records": len(health), "chapters": len(committed)}, "open_issues": len(self.issues.list("open")), "pending_proposals": len([x for x in proposals if x.get("status") in {"pending", "reviewing", "modified"}]), "experiments": len(experiments), "failed_tasks": len([x for x in jobs if x.get("status") == "failed"]), "failed_experiments": len([x for x in experiments if x.get("status") == "failed"]), "author_confirmation_rate": round(len([x for x in patterns if x.get("status") in {"confirmed", "rejected"}]) / len(patterns), 2) if patterns else None, "knowledge_deposits": len([x for x in patterns if x.get("status") == "confirmed"])}
