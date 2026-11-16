"""Seal reaction trigger semantics from private source text at authority build time."""
from __future__ import annotations

import hashlib


def seal_trigger_events(mechanics: dict[str, dict], readings: dict[tuple[str, str], dict]) -> None:
    """Resolve trigger events and qualifiers once, retaining their provenance."""
    from combat.reaction_triggers import (
        _match_from_event, classify_mechanic_all, classify_trigger, declared_reading,
        event_from_match, trigger_qualifiers, trigger_text, typed_classifications,
    )

    for key, mechanic in mechanics.items():
        activation = mechanic.get("activation")
        if not isinstance(activation, dict):
            continue
        for field in ("trigger_events", "trigger_qualifiers", "trigger_events_source"):
            activation.pop(field, None)
        trigger, printed = trigger_text(mechanic, free=activation.get("economy") in ("no_action", "passive"))
        if not trigger:
            continue
        if trigger != printed:
            matches, source = [classify_trigger(trigger)], "evidence"
        else:
            matches = classify_mechanic_all(mechanic, readings)
            digest = hashlib.sha256(str(printed or "").encode("utf-8")).hexdigest()
            if typed_classifications(mechanic) is not None:
                source = "classification"
            elif declared_reading(mechanic) is not None:
                source = "declared"
            elif (str(mechanic.get("mechanic_id")), digest) in readings:
                source = "reading"
            else:
                source = "parsed"
        events = [event_from_match(match) for match in matches]
        for match, event in zip(matches, events):
            assert _match_from_event(event, None) == match, (key, match, event)
        activation["trigger_events"] = events
        activation["trigger_qualifiers"] = trigger_qualifiers(trigger, printed, mechanic.get("use_limit"))
        activation["trigger_events_source"] = source
