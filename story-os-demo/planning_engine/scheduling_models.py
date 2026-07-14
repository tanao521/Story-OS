"""Schema constants for author-operated narrative scheduling records."""
from __future__ import annotations

SUBJECT_TYPES = {"plot_thread", "character_arc", "foreshadowing"}
SCHEDULE_STATUSES = {"planned", "reviewed", "elapsed", "cancelled", "invalid"}
PRIORITIES = {"low", "medium", "high"}
ACTIONS = {
    "plot_thread": {"introduce", "advance", "escalate", "complicate", "reveal", "converge", "pause", "resolve"},
    "character_arc": {"establish_state", "pressure", "choice", "setback", "realization", "change", "relapse", "relationship_shift", "arc_payoff"},
    "foreshadowing": {"plant", "reinforce", "misdirect", "reveal_partial", "payoff", "delay", "cancel"},
}
ACTION_ORDER = {
    "plot_thread": {"introduce": 0, "advance": 1, "escalate": 2, "complicate": 2, "reveal": 3, "converge": 4, "pause": 5, "resolve": 6},
    "character_arc": {"establish_state": 0, "pressure": 1, "choice": 2, "setback": 2, "realization": 3, "change": 4, "relapse": 4, "relationship_shift": 4, "arc_payoff": 5},
    "foreshadowing": {"plant": 0, "reinforce": 1, "misdirect": 1, "reveal_partial": 2, "delay": 2, "payoff": 3, "cancel": 4},
}
