"""One Court healing provider with an explicit saved-action policy gate.

blood_court_runtime actions compose PB into the ordinary offer. Only old
court_heal_bonus actions retain their historical post-receipt bonus, plane/team
membership, PB fallback, usage flag and receipt shape. No saved row is rewritten.
When both policies are present, the live policy wins and both recognize the same
recipient allowance. Legacy-only fights keep their historical stored fields.
"""
from . import hook
from .blood_court import MARKER, HEALED, courts
from .blood_riders import effect_marker


def eligible_courts(engine, subject):
    """Resolve membership and PB once, with compatibility rules per sealed source."""
    if not subject.active:
        return []
    current = list(courts(engine, subject, who="ally"))
    if current:
        return [(zone, owner, True,
                 int(zone.trigger_profile.get("numbers", {}).get("pb") or owner.proficiency_bonus))
                for zone, owner in current]
    legacy = []
    for zone in sorted(engine.state.zones.values(), key=lambda z: z.zone_id):
        owner = engine.state.actors.get(zone.owner_id or "")
        action = engine.action_catalog.get(zone.source_definition_id)
        typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
        rows = typed.get("effects") or []
        if (not zone.active or owner is None or any(r.get("type") == MARKER for r in rows)
                or effect_marker(typed, "court_heal_bonus") is None
                or owner.team_id != subject.team_id
                or not any(cell.x == subject.position.x and cell.y == subject.position.y for cell in zone.affected_cells)):
            continue
        legacy.append((zone, owner, False, int((typed.get("numbers") or {}).get("pb") or 2)))
    return legacy


def allowance(engine, subject, *, current, consume):
    """Both policy gates share usage; writing old-only fights preserves old flags."""
    turn = int(engine.state.round_number) * 1000 + int(engine.state.current_slot_index)
    flag = f"crimson_court_heal_round_{engine.state.round_number}_{engine.state.current_slot_index}"
    if subject.turn_flags.get(HEALED) == turn or subject.turn_flags.get(flag):
        return False
    if consume:
        if current:
            subject.turn_flags[HEALED] = turn
        else:
            subject.turn_flags[flag] = True
    return True


def court_bonus(engine, subject, *, current, consume=True):
    eligible = eligible_courts(engine, subject)
    if not eligible or eligible[0][2] != current:
        return None
    if not allowance(engine, subject, current=current, consume=consume):
        return None
    return eligible[0]


@hook("healing_preparation_policy")
def preparation_policy(engine, subject):
    # Membership opts in even after the recipient's bonus has been consumed.
    # Legacy-only zones and unrelated recipients retain their historical route.
    return True if any(current for _, _, current, _ in eligible_courts(engine, subject)) else None


@hook("healing_offered_bonus")
def offered_bonus(engine, subject, amount, *, consume):
    selected = court_bonus(engine, subject, current=True, consume=consume)
    return selected[3] if selected else None


@hook("event")
def legacy_receipt(engine, event_type, kwargs):
    if event_type != "HEALING_APPLIED":
        return
    payload = (kwargs or {}).get("payload") or {}
    subject = engine.state.actors.get(next(iter((kwargs or {}).get("target_ids") or ()), ""))
    if subject is None or int(payload.get("after", 0)) <= int(payload.get("before", 0)):
        return
    selected = court_bonus(engine, subject, current=False)
    if selected is None:
        return
    zone, owner, _, pb = selected
    from ..typed_executor import _reduced_healing
    amount = _reduced_healing(engine, subject, pb, healer=owner, source=zone.source_definition_id)
    before = subject.current_hp
    subject.current_hp = min(subject.maximum_hp, before + amount)
    engine._append_event("HEALING_APPLIED", zone.source_definition_id, actor_id=owner.entity_id,
                         target_ids=(subject.entity_id,), payload={"offered": amount, "before": before, "after": subject.current_hp})
