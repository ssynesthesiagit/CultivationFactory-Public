"""Read-only journal statistics for the table summary API.

No hooks, dice, engine calls or persistence writes. Damage totals are committed
post-reduction damage, including temporary HP; HP damage is also exposed. Older
journals lacking packet detail report that limitation instead of inventing rolls.
Attack/save outcomes are the recorded outcomes, with recorded corrections applied.
"""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from .ext.retained_updates import is_retained_update
from .ext.life_state import is_deceased
from .relations import relation, ENEMY


def metrics() -> dict[str, Any]:
    return {
        "damage_dealt": {"total": 0, "by_type": {}},
        "damage_taken": {"rolled": 0, "applied": 0, "hp_damage": 0, "temporary_hp_absorbed": 0},
        "healing_done": 0, "healing_received": 0, "temporary_hp_granted": 0,
        "attacks": {"made": 0, "hits": 0, "misses": 0, "critical_hits": 0, "concealment_misses": 0},
        "saves_forced": {"total": 0, "failed": 0},
        "saves_made": {"passed": 0, "failed": 0},
        "creatures_downed": [], "times_downed": 0, "resources_spent": {},
        "reactions_used": 0, "turns_taken": 0, "conditions_applied_to_enemies": {},
    }


def _number(value: Any) -> int:
    return max(0, value) if type(value) is int else 0


def _increment(mapping: dict, key: str, amount: int = 1) -> None:
    mapping[key] = mapping.get(key, 0) + amount


def _add(total: dict, part: dict) -> None:
    for key, value in part.items():
        if isinstance(value, dict):
            for name, amount in value.items():
                if isinstance(amount, dict):
                    for label, count in amount.items():
                        _increment(total[key][name], label, count)
                else:
                    _increment(total[key], name, amount)
        elif isinstance(value, list):
            total[key].extend(value)
        else:
            total[key] += value


def build_summary(engine: Any, match_id: str) -> dict[str, Any]:
    """Project recorded events and final actor snapshots into JSON-safe metrics.

    Source ownership in the sealed action catalogue attributes native saves that
    did not record a source actor. A missing source stays unattributed. Downings
    mean transitions from positive HP to zero, not attacks on an already dying
    creature. Overkill remains the journal's hp_damage, rather than a new roll or
    a guessed HP loss. Temporary HP granted means the increase in the pool.
    """
    rows = {}
    for actor in engine.state.actors.values():
        rows[actor.entity_id] = {
            "entity_id": actor.entity_id, "display_name": actor.display_name,
            "team": actor.team_id, "summoner": actor.owner_id if actor.summon is not None else None,
            "final_hp": actor.current_hp, "maximum_hp": actor.maximum_hp,
            "life_state": "DEAD" if is_deceased(actor) else actor.life_state or ("CONSCIOUS" if actor.current_hp > 0 else "DEFEATED"),
            "active": actor.active, "metrics": metrics(),
        }
    totals = {key: row["metrics"] for key, row in rows.items()}
    limitations: set[str] = set()
    attacks: dict[str, dict] = {}
    latest_attack: dict[str, str] = {}
    down: set[str] = set()
    teams = {key: row["team"] for key, row in rows.items()}
    # Recover original sides before walking journal side changes forward.
    for event in reversed(engine.events):
        if event.event_type == "ACTOR_SIDE_CHANGED" and event.actor_id in teams:
            teams[event.actor_id] = event.payload["previous_team_id"]
    relations = getattr(engine.state, "relations", None)
    if any(event.event_type == "RELATION_CHANGED" for event in engine.events):
        relations = None
        limitations.add("Conditions put on enemies are counted by the starting sides; if a creature changed sides early in the fight, a few of those counts may be off.")
    def enemies(left: str, right: str) -> bool:
        state = SimpleNamespace(relations=relations)
        return relation(state, SimpleNamespace(entity_id=left, team_id=teams[left]),
                        SimpleNamespace(entity_id=right, team_id=teams[right])) == ENEMY
    sources = {key: action.owner_id for key, action in engine.action_catalog.items()}
    # Native auto-failure emits a marker before the resolved SAVE_ROLLED (with
    # possible reaction events between them). Keep unpaired historical markers.
    pending_auto: dict[tuple, list[int]] = {}
    paired_auto: set[int] = set()
    for index, event in enumerate(engine.events):
        if event.event_type in {"INTENT_ACCEPTED", "TURN_STARTED", "TURN_ENDED"}:
            # An incomplete historical save cannot pair with a later action.
            pending_auto.clear()
        if event.event_type not in {"SAVE_AUTO_FAILED", "SAVE_ROLLED"}:
            continue
        ability = event.payload.get("ability") or str(event.payload.get("reason", "")).rsplit(":", 1)[-1]
        key = (event.actor_id, event.source_definition_id, ability.upper())
        if event.event_type == "SAVE_AUTO_FAILED":
            pending_auto.setdefault(key, []).append(index)
        elif pending_auto.get(key) and type(event.payload.get("success")) is bool:
            paired_auto.add(pending_auto[key].pop())
    for index, event in enumerate(engine.events):
        kind, p = event.event_type, event.payload
        actor_id, targets = event.actor_id, event.target_ids
        source = event.source_definition_id
        own = totals.get(actor_id)
        if kind == "ACTOR_SIDE_CHANGED" and actor_id in teams:
            teams[actor_id] = p["team_id"]
        elif kind == "RELATION_CHANGED":
            after = p.get("relations_after") or {}
            relations = SimpleNamespace(actors=after.get("actors", {}), teams=after.get("teams", {}))
        if kind == "SUMMON_APPEARED":
            for target in targets:
                if target in rows:
                    rows[target]["summoner"] = actor_id
        if kind == "INTENT_ACCEPTED" and actor_id and source:
            # Only action ownership, never END_TURN/system or a save's victim.
            if p.get("kind") in {"ACTION", "BONUS_ACTION"}:
                sources[source] = actor_id
        if kind == "DAMAGE_COMMITTED":
            hp = _number(p.get("hp_damage"))
            absorbed = _number(p.get("temporary_hp_absorbed"))
            applied = _number(p.get("reduced_to", hp + absorbed))
            rolled = _number(p.get("rolled_or_pending_damage", applied))
            if "rolled_or_pending_damage" not in p:
                limitations.add("Some older hits did not record their damage before defenses, so 'damage taken' and 'soaked' may understate what was blocked.")
            if "temporary_hp_absorbed" not in p or "reduced_to" not in p:
                limitations.add("Some older hits did not record how much was blocked or absorbed by temporary HP, so those amounts are missing.")
            for target in targets:
                if target not in totals:
                    continue
                taken = totals[target]["damage_taken"]
                for key, amount in (("rolled", rolled), ("applied", applied), ("hp_damage", hp), ("temporary_hp_absorbed", absorbed)):
                    taken[key] += amount
                if own is not None:
                    own["damage_dealt"]["total"] += applied
                    _increment(own["damage_dealt"]["by_type"], str(p.get("damage_type") or "UNKNOWN"), applied)
                if p.get("remaining_hp") == 0 and hp and target not in down:
                    down.add(target)
                    totals[target]["times_downed"] += 1
                    if own is not None:
                        own["creatures_downed"].append(target)
        elif kind == "HEALING_APPLIED":
            recorded = type(p.get("after")) is int and type(p.get("before")) is int
            if not recorded:
                limitations.add("Some older heals did not record how much HP they restored, so healing may be lower than it really was.")
            healed = max(0, p["after"] - p["before"]) if recorded else 0
            for target in targets:
                if target in totals:
                    totals[target]["healing_received"] += healed
                    if recorded and p["after"] > 0:
                        down.discard(target)
                    if own is not None:
                        own["healing_done"] += healed
        elif kind == "TEMP_HP_GRANTED" and own is not None:
            recorded = type(p.get("after")) is int and type(p.get("before")) is int
            if not recorded:
                limitations.add("Some older temporary-HP gains did not record the amount, so temporary HP given may be lower than it really was.")
            else:
                own["temporary_hp_granted"] += max(0, p["after"] - p["before"]) * len(targets)
        elif kind == "ATTACK_ROLLED" and own is not None:
            roll_id = str(p.get("roll_id") or event.sequence)
            attacks[roll_id] = {"actor": actor_id, "hit": p.get("provisional_hit") if type(p.get("provisional_hit")) is bool else None,
                                "critical": _number(p.get("natural_result")) >= _number(p.get("critical_threshold", 20))}
            latest_attack[actor_id] = roll_id
        elif kind == "ATTACK_FORCED_MISS":
            attack = attacks.get(str(p.get("roll_id")))
            if attack is not None:
                attack["hit"] = False
        elif kind == "ATTACK_CRITICAL_RESOLVED":
            attack = attacks.get(str(p.get("roll_id")))
            if attack is not None and type(p.get("critical")) is bool:
                attack["critical"] = p["critical"]
        elif kind == "ATTACK_LOCATION_MISSED" and own is not None:
            own["attacks"]["made"] += 1
            own["attacks"]["misses"] += 1
        elif kind in {"PASSIVE_TRIGGERED", "REACTION_RESOLVED"}:
            if p.get("miss_chance_percent") and p.get("missed") is True and own is not None:
                own["attacks"]["made"] += 1
                own["attacks"]["misses"] += 1
                own["attacks"]["concealment_misses"] += 1
            if "hit_after_correction" in p:
                attack = attacks.get(str(p.get("roll_id")))
                if attack is not None:
                    attack["hit"] = p["hit_after_correction"] is True
            if "hit_after_recheck" in p:
                # Typed self-defense targets the attacker; native self-defense
                # targets the defender. Ally defense explicitly records protects.
                protected = p.get("protects") or actor_id
                for roll_id in reversed(list(attacks)):
                    attack = attacks[roll_id]
                    if (latest_attack.get(attack["actor"]) == roll_id and attack.get("target") == protected
                            and (not targets or attack["actor"] in targets or protected in targets)):
                        attack["hit"] = p["hit_after_recheck"] is True
                        if p.get("critical") is True:
                            attack["critical"] = True
                        break
            if (kind == "REACTION_RESOLVED" and own is not None
                    and not p.get("passive") and not p.get("carried_budget")):
                own["reactions_used"] += 1
        elif kind in {"SAVE_ROLLED", "SAVE_AUTO_FAILED"} and own is not None:
            if index in paired_auto:
                continue
            success = p.get("success") if kind == "SAVE_ROLLED" else False
            if type(success) is bool:
                own["saves_made"]["passed" if success else "failed"] += 1
                caster = p.get("source_actor_id") or sources.get(source)
                if caster in totals and caster != actor_id:
                    totals[caster]["saves_forced"]["total"] += 1
                    totals[caster]["saves_forced"]["failed"] += int(not success)
                elif caster is None:
                    limitations.add("Some saving throws did not record whose ability caused them, so they are not credited to anyone.")
            else:
                limitations.add("Some saving throws did not record whether they passed, so they are left out of the save counts.")
        elif kind == "RESOURCE_SPENT" and own is not None:
            _increment(own["resources_spent"], str(p.get("resource_id") or "UNKNOWN"), _number(p.get("amount")))
        elif kind == "TURN_STARTED" and own is not None:
            own["turns_taken"] += 1
        elif kind == "CONDITION_APPLIED" and own is not None and not is_retained_update(kind, p):
            for target in targets:
                if target in teams and enemies(actor_id, target):
                    _increment(own["conditions_applied_to_enemies"], str(p.get("condition_id") or "UNKNOWN"))
        elif kind in {"LIFE_STATE_CHANGED", "ENTITY_DEFEATED"} and own is not None:
            if kind == "ENTITY_DEFEATED" or p.get("life_state") in {"DYING", "STABLE", "CONSCIOUS"}:
                if actor_id not in down:
                    own["times_downed"] += 1
                    down.add(actor_id)
            elif p.get("life_state") is None:
                down.discard(actor_id)
        if kind == "ATTACK_ROLLED" and own is not None:
            attacks[roll_id]["target"] = targets[0] if targets else None
    if any(event.event_type == "D20_REWRITTEN" for event in engine.events):
        limitations.add("Save counts use the roll's result; an ability that later turned a save into a success or failure may not be reflected.")
    for attack in attacks.values():
        out = totals[attack["actor"]]["attacks"]
        out["made"] += 1
        if attack["hit"] is None:
            limitations.add("Some older attacks did not record whether they hit, so they count as attacks made but not as hits or misses (hit rates may look low).")
        else:
            out["hits" if attack["hit"] else "misses"] += 1
        out["critical_hits"] += int(attack["hit"] is True and attack["critical"])
    team_totals: dict[str, dict] = {}
    rollups = {key: deepcopy(value) for key, value in totals.items() if not rows[key]["summoner"]}
    for key, row in rows.items():
        _add(team_totals.setdefault(row["team"], metrics()), totals[key])
        owner = row["summoner"]
        seen = {key}
        while owner in rows and owner not in seen:
            seen.add(owner)
            if owner in rollups:
                _add(rollups[owner], totals[key])
            owner = rows[owner]["summoner"]
    highlights = {}
    for name, path in (("most_damage_dealt", ("damage_dealt", "total")), ("most_healing", ("healing_done",)), ("most_damage_taken", ("damage_taken", "applied"))):
        values = {}
        for key, value in totals.items():
            for part in path:
                value = value[part]
            values[key] = value
        maximum = max(values.values(), default=0)
        highlights[name] = {"value": maximum, "entity_ids": sorted(key for key, value in values.items() if value == maximum and maximum > 0)}
    return {"schema": "TianxiaFightSummary.v1", "match_id": match_id, "event_count": len(engine.events),
            "terminal": bool(engine.state.terminal_result), "actors": [rows[key] for key in sorted(rows)],
            "teams": [{"team": key, "metrics": team_totals[key]} for key in sorted(team_totals)],
            "summoner_totals": [{"entity_id": key, "metrics": rollups[key]} for key in sorted(rollups)],
            "highlights": highlights, "limitations": sorted(limitations)}
