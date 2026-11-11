"""Display the manual remainder of Fireball's old copied-card reminders.

New bundles use the reviewed typed row. Saved bundles keep their original
events and mechanics: only exact known source-card fragments are adapted.
Reaction outcomes emitted under Fireball's source remain untouched.
"""
from . import hook

_GEOMETRY = "20-foot-radius sphere"
_MANUAL = "Unattended flammable objects ignite."
_COPIED = frozenset({
    "A compressed fire pearl erupts.", _MANUAL,
    "Cultivation Level Damage: 5-10: 6d6; 11-16: 8d6; 17-20: 10d6.",
    "Augment - 2 CP: Increase damage by 2d6. After the attack resolves, take Fire damage equal to twice your Proficiency Bonus.",
})


@hook("history_event_metadata")
def legacy_reminder(event, events):
    if event.get("event_type") != "GM_RIDER" or not str(event.get("source_definition_id") or "").endswith(".FIRE_TAL_FIREBALL_ART"):
        return None
    payload = event.get("payload") or {}
    if payload.get("automated") or payload.get("adjudication_text"):
        return None
    text = " ".join(str(payload.get("rider") or "").split())
    if text == _GEOMETRY:
        return {"history_hidden": True}
    parts = {part.strip() for part in text.split(" / ") if part.strip()}
    if parts and parts <= _COPIED:
        return {"rider_display_text": _MANUAL} if _MANUAL in parts else {"history_hidden": True}
    return None
