"""Presentation contract for compiled action economy, shared by sheet and menu.

These labels never change legality or costs. NONE means an active use consumes
no action; it does not mean that the ability is passive.
"""
LABELS = {"ACTION": "Action", "BONUS_ACTION": "Bonus action", "REACTION": "Reaction",
          "FREE": "Free", "MOVE": "Movement", "NONE": "No action"}
GROUPS = {"ACTION": "actions", "BONUS_ACTION": "bonus", "REACTION": "reactions",
          "FREE": "free", "MOVE": "movement", "NONE": "no_action"}
# The slot words every surface prints for a spent economy (owner 2026-10-15: "what spent my action?").
# Only a use that spends a turn slot gets a confirmation line; NONE/FREE/MOVE spend none.
# Mirrored in APP/static/tabletop/action-economy.js (ECONOMY_SPEND); the audit parity regression guards the pair.
SPEND = {"ACTION": "Action", "BONUS_ACTION": "Bonus Action", "REACTION": "Reaction"}


def slot_for(economy: str, *, moving: bool = False) -> str:
    return "Movement" if moving else LABELS.get(str(economy), "Action")


def group_for(economy: str) -> str:
    return GROUPS.get(str(economy), "actions")


def economy_label(economy: str) -> str:
    """The plain slot words for one use ("Bonus Action"), falling back to the section label."""
    return SPEND.get(str(economy)) or LABELS.get(str(economy), "Action")


def spend_clause(economy: str) -> str:
    """'used your Bonus Action', or '' when a use spends no turn slot (No action, Free, Movement)."""
    label = SPEND.get(str(economy))
    return f"used your {label}" if label else ""
