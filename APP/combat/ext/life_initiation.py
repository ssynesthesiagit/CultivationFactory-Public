"""Life Initiation: obvious signs and optional, scoped Medicine key substitution.

Recognition never diagnoses hidden causes. External causes/DCs/applicability
come from typed GM clinical cases; represented signs come from live conditions.
Native actor-owned choices use the existing Ask-me transport on any actor's turn.
"""
import copy
import hashlib
import json

from . import effect, hook, note
from ..medical_cases import CATEGORIES, scene_distance

SOURCE = "LIFE_BASE_LIFE_INITIATION"
KNOWLEDGE = "condition:typed.clinical_knowledge."
RECOGNIZED = "condition:typed.life_recognition."


@hook("scene_fact_validate")
def validate_scene_case(engine, subject, kind, record):
    if kind != "clinical":
        return None
    from ..medical_cases import validate_case, retract_case
    from ..scene_facts import records
    target = engine.state.actors[subject]
    bundle = next((b for b in engine.typed_bundle_documents if b["actor_id"] == subject), {})
    historical = [*bundle.get("clinical_cases", []), *records(target.conditions, kind)]
    if not isinstance(record, dict):
        raise ValueError("Supply a typed clinical declaration.")
    if record.get("type") == "clinical_case_retraction":
        return retract_case(historical, {"id": record.get("fact_id"), "source_note": record.get("source_note")})
    keys = {"type", "authority", "treatment_sources"}
    validated = validate_case({k: v for k, v in record.items() if k not in keys})
    if any(r.get("id") == validated["id"] for r in historical):
        raise ValueError("That case ID has already been recorded. Use a new ID for a new ruling.")
    return validated


@hook("actor_private_facts")
def examiner_findings(engine, viewer):
    from ..medical_cases import knowledge
    rows = knowledge(engine, viewer.entity_id)
    return [{"source": "Life Initiation", **row} for row in rows] or None


@hook("recent_event_view")
def private_event_view(document, engine, viewer):
    """Keep clinical causes out of every other seat, including allied seats."""
    encoded = json.dumps(document)
    if "condition:table.fact." in encoded or "table_fact_json" in encoded:
        from ..scene_facts import private_event_view
        document = private_event_view(document)
        encoded = json.dumps(document)
    if KNOWLEDGE not in encoded and "Life Initiation private medical finding" not in encoded:
        return document
    out = copy.deepcopy(document)
    viewer_id = getattr(viewer, "entity_id", None)
    if "Life Initiation private medical finding" in encoded and document.get("actor_id") != viewer_id:
        out["payload"] = {}
        return out
    def redact(value):
        if isinstance(value, list):
            return [redact(v) for v in value]
        if not isinstance(value, dict):
            return value
        result = {k: redact(v) for k, v in value.items()}
        if str(value.get("condition_id") or "").startswith(KNOWLEDGE) and value.get("target_id") != viewer_id:
            result["data"] = {"label": "Medical finding (private)"}
        return result
    out["payload"] = redact(out["payload"])
    return out


@hook("history_event_view")
def clinical_history_view(document):
    """The public feed's raw event snapshots also omit private medical facts."""
    return private_event_view(document, None, None)


@hook("advancement_options")
def clinical_input_options(options, sheet, talents):
    """Named Life treatment references for a GM's source-specific clinical input."""
    return {**options, "medical_treatments": [{"id": r["canonical_talent_id"], "name": r["display_name"]}
            for r in talents if r.get("owning_canonical_sphere_id") == "tianxia.sphere.life"],
            "medical_cases": [{"id": r["id"], "category": r["category"]} for r in sheet.get("clinical_cases", [])]}


@hook("clinical_treatment_allowed")
def clinical_treatment(talent_id, mechanic):
    return True if mechanic.get("sphere_id") == "tianxia.sphere.life" and mechanic.get("kind") == "talent" else None


@hook("table_fact_projection")
def project_cases(sheet, facts):
    ended = {f.get("fact_id") for f in facts if f.get("type") == "clinical_case_retraction" and f.get("authority") == "GM"}
    cases = [f for f in facts if f.get("type") == "clinical_case" and f.get("authority") == "GM" and f.get("id") not in ended]
    if not cases:
        return sheet
    out = copy.deepcopy(sheet)
    out["clinical_cases"] = copy.deepcopy(cases)
    return out


@hook("compile_bundle")
def seal_clinical_facts(bundle, info):
    cases = info["owner_sheet"].get("clinical_cases")
    if cases:
        bundle = copy.deepcopy(bundle)
        bundle["clinical_cases"] = copy.deepcopy(cases)
    return bundle


@hook("compile_actions")
def actions(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    if SOURCE not in info["owned_ids"]:
        return None
    stats = info["owner_sheet"]["ability_scores_and_statistics"]
    from .learning_training import sequence
    skills = sequence(stats.get("skills"))
    medicine = next((r for r in skills if r.get("skill") == "Medicine"), {})
    wisdom = int(info["mods"].get("WIS", 0))
    total = int(medicine.get("bonus", wisdom))
    params = {"wisdom": wisdom, "medicine": total, "key_mod": int(info["numbers"]["key_mod"]),
              "key": str(info["owner_sheet"]["identity"].get("key_ability") or "").upper()[:3],
              "treating_ids": [k for k in info["owned_ids"]
                               if (info["mechanics"].get(k) or {}).get("sphere_id") == "tianxia.sphere.life"
                               and (info["mechanics"].get(k) or {}).get("kind") == "talent"]}
    params["treating_sources"] = {k: info["mechanics"][k]["source"]["text_sha256"] for k in params["treating_ids"]}
    if params["key"] not in ("STR", "DEX", "CON", "INT", "WIS", "CHA"):
        params["key"] = ""
    made = []
    variants = [("recognize", "Life Initiation: recognize obvious signs", EconomyKind.NONE, None)]
    for mode, name in (("identify", "identify a treatable condition"), ("stabilize", "Medicine to stabilize")):
        variants.extend((mode, f"Life Initiation: {name} ({economy.value.replace('_', ' ').title()})", economy, None)
                        for economy in (EconomyKind.ACTION, EconomyKind.BONUS_ACTION, EconomyKind.NONE))
    for mode, name, economy, distance in variants:
        made.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.life_initiation.{mode}.{economy.value}",
            display_name=name, owner_id=info["actor_id"], economy=economy, resolution_kind="TYPED",
            target_kind="ANY_CREATURE", range_ft=distance,
            parameters={"typed": {"source": SOURCE, "effects": [{"type": "life_initiation", "mode": mode}],
                                   "numbers": dict(info["numbers"]), "duration": {"kind": "instant"}},
                        "clinical_check": params, "description": (
                            "Recognize obvious signs without learning a hidden cause (free, visible creature). "
                            "To identify or stabilize, make Medicine against the GM's declared DC, examination distance and timing. "
                            "Choose Wisdom or your Life key ability; proficiency is unchanged. No resource cost.")}))
    return made


def cases(engine, target):
    from ..medical_cases import active_cases
    from ..scene_facts import records
    bundle = next((b for b in engine.typed_bundle_documents if b["actor_id"] == target.entity_id), {})
    return active_cases(bundle.get("clinical_cases") or [], records(target.conditions, "clinical"))


def journey_cases(target):
    from ..medical_cases import active_cases
    from ..scene_facts import records
    return active_cases(target["bundle"].get("clinical_cases", []),
                        records((target.get("encounter_snapshot") or {}).get("conditions", {}), "clinical"))


def eligible(engine, actor, target, mode, economy=None):
    from ..medical_cases import CATEGORIES
    treating = {k: v for action in engine.action_catalog.values() if action.owner_id == actor.entity_id
                for k, v in (action.parameters.get("clinical_check") or {}).get("treating_sources", {}).items()}
    from .life_state import is_deceased
    if is_deceased(target) or {t.casefold() for t in target.creature_types}.intersection({"undead", "construct"}):
        return []
    return [c for c in cases(engine, target) if c["living"]
            and engine._distance_actor_to_actor(actor, target) <= c["range_ft"]
            and (economy is None or c["economy"] == economy) and
            ((mode == "stabilize" and c["category"] == "dying" and target.life_state == "DYING")
             or (mode == "identify" and c["category"] in CATEGORIES and any(
                 treating.get(k) == v for k, v in c["treatment_sources"].items())))]


def obvious_signs(engine, target):
    return visible_signs(target.conditions, target.life_state, cases(engine, target))


def visible_signs(conditions, life_state, clinical_cases):
    """Recognize the same public signs in live and serialized encounter state.

    Only represented condition names and explicitly obvious clinical categories
    are evidence; condition metadata and hidden causes never become findings.
    """
    from ..condition_names import condition_key
    names = set()
    for condition in conditions.values():
        if isinstance(condition, str):
            condition = json.loads(condition)
        cid = condition.get("condition_id") if isinstance(condition, dict) else condition.condition_id
        names.add(condition_key(cid))
    signs = {label for condition, label in (("bleeding", "bleeding"), ("poisoned", "poisoning"),
             ("sickened", "disease"), ("suffocating", "suffocation")) if condition in names}
    if life_state == "DYING":
        signs.add("dying")
    signs.update(c["category"] for c in clinical_cases if c["obvious"] and c["category"] in CATEGORIES[:8])
    return sorted(signs)


def recognition_key(target):
    return RECOGNIZED + hashlib.sha256(target.entity_id.encode()).hexdigest()[:16]


@hook("candidate_allowed")
def allowed(engine, actor, candidate, action):
    if action is None or not action.parameters.get("clinical_check"):
        return None
    mode = action.parameters["typed"]["effects"][0]["mode"]
    targets = [engine.state.actors.get(t) for t in candidate.target_ids]
    return bool(targets) and all(t is not None
        and ((mode == "recognize" and not any(c.condition_id == recognition_key(t)
             and c.data.get("signs") == ",".join(obvious_signs(engine, t)) for c in actor.conditions.values())
             )
             or (mode != "recognize" and eligible(engine, actor, t, mode, action.economy.value))) for t in targets)


@effect("life_initiation")
def resolve(ctx, row):
    from ..condition_names import condition_key
    from .iron_fist_riders import choose
    target = ctx.target
    if target is None:
        return
    if row["mode"] == "recognize":
        signs = obvious_signs(ctx.engine, target)
        ctx.engine._apply_condition(ctx.actor, recognition_key(target), SOURCE, ctx.actor.entity_id,
            expires_on="UNTIL_REMOVED", data={"label": "Observed living signs", "signs": ",".join(signs)})
        note(ctx.engine, SOURCE, ctx.actor, f"Life Initiation: {target.display_name} shows "
             + (", ".join(sorted(signs)) if signs else "no confirmed obvious signs")
             + ". Hidden causes still require examination.", targets=(target,))
        return
    options = eligible(ctx.engine, ctx.actor, target, row["mode"], ctx.action.economy.value)
    picked = choose(ctx, "Life Initiation medical case", [c["id"] for c in options],
                    labels={c["id"]: f"{target.display_name}: {c['category'] if c['obvious'] else 'a medical concern'} (Medicine DC {c['dc']})" for c in options},
                    feature_id=SOURCE)
    if not picked:
        return
    case = next(c for c in options if c["id"] == picked[0])
    params = ctx.action.parameters["clinical_check"]
    ability_labels = {"Wisdom": f"Wisdom (Medicine), +{params['medicine']}"}
    ability_options = ["Wisdom"]
    if params["key"]:
        ability_labels["Life key"] = f"Life key ({params['key']}) Medicine, +{params['medicine'] - params['wisdom'] + params['key_mod']}"
        ability_options.append("Life key")
        from . import ai_controlled
        if ai_controlled(ctx.engine, ctx.actor) and params["key_mod"] > params["wisdom"]:
            ability_options.reverse()
    selected = choose(ctx, "Life Initiation Medicine ability", ability_options, feature_id=SOURCE,
                      labels=ability_labels)
    if not selected:
        return
    bonus = params["medicine"] + (params["key_mod"] - params["wisdom"] if selected[0] == "Life key" else 0)
    from ..typed_executor import check_mode
    from . import floored, run
    ability = params["key"] if selected[0] == "Life key" else "WIS"
    bonus += sum(int(v) for v in run("check_bonus", ctx, ctx.actor) if isinstance(v, int))
    roll = ctx.engine.roller.d20(modifier=bonus, actor_id=ctx.actor.entity_id,
        reason=f"CHECK:{SOURCE}:Medicine", mode=check_mode(ctx.actor, ability, "Medicine", engine=ctx.engine))
    ctx.engine._record_roll(roll)
    roll = floored(ctx.engine, ctx.actor, roll, case["dc"])
    success = roll.total >= case["dc"]
    ctx.engine._append_event("CHECK_ROLLED", SOURCE, actor_id=ctx.actor.entity_id, target_ids=(target.entity_id,),
        payload={"actor": roll.model_dump(mode="json"), "dc": case["dc"], "success": success, "skill": "Medicine", "ability": ability})
    if success and row["mode"] == "stabilize":
        from .life_state import stabilize
        stabilize(ctx.engine, target, SOURCE)
    elif success:
        choose(ctx, "Life Initiation private medical finding", ["record"], labels={"record": case["cause"]},
               feature_id=SOURCE, meaning="Only the examining creature learns this cause; record it in that creature's private findings.")
        key = hashlib.sha256((target.entity_id + case["id"]).encode()).hexdigest()[:16]
        ctx.engine._apply_condition(ctx.actor, KNOWLEDGE + key, SOURCE, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
            data={"label": "Medical finding (private)", "case_id": case["id"], "subject": target.entity_id, "cause": case["cause"]})
    note(ctx.engine, SOURCE, ctx.actor, f"Life Initiation: {ctx.actor.display_name}'s Medicine check for {target.display_name} "
         + ("succeeds. The examiner alone learns an identified cause." if success else "fails; no hidden cause is learned."), targets=(target,))


def scene_check(actor):
    """Read only this actor's compiled Life ownership and Medicine numbers."""
    return next((a["parameters"]["clinical_check"] for a in actor["bundle"]["action_catalog"]
                 if a.get("parameters", {}).get("clinical_check")), None)


def scene_medicine_bonus(actor, params, ability):
    """Preserve compiled training, replace only Wisdom, then apply fatigue."""
    return (params["medicine"]
            + (params["key_mod"] - params["wisdom"] if ability == "Life key" else 0)
            - 2 * int(actor.get("exhaustion", 0)))


def scene_cases(session, aid, tid, mode):
    actor, target = session.state["actors"][aid], session.state["actors"][tid]
    params = scene_check(actor)
    if params is None:
        return []
    distance = scene_distance(session, aid, tid)
    if distance is None:
        return []
    snapshot = target.get("encounter_snapshot") or {}
    if {t.casefold() for t in target["bundle"]["actor_template"].get("creature_types", [])}.intersection({"undead", "construct"}):
        return []
    if snapshot.get("life_state") not in (None, "CONSCIOUS", "DYING", "STABLE"):
        return []
    return [c for c in journey_cases(target) if c["living"] and distance <= c["range_ft"] and
            ((mode == "stabilize" and c["category"] == "dying" and snapshot.get("life_state") == "DYING")
             or (mode == "identify" and any(params["treating_sources"].get(k) == v
                                           for k, v in c["treatment_sources"].items())))]


@hook("journey_options")
def scene_options(session, aid):
    actor = session.state["actors"][aid]
    params = scene_check(actor)
    if params is None or session.state["phase"] != "travel" or actor["incapacitated"]:
        return None
    options = []
    for tid, target in session.state["actors"].items():
        if scene_distance(session, aid, tid, physical=False) is None:
            continue
        options.append({"id": f"life:recognize:{tid}", "kind": "life_recognize", "payload": {"target": tid},
                        "label": f"Life Initiation: recognize obvious signs on {target['name']} (free; no hidden cause)."})
        for mode in ("identify", "stabilize"):
            for case in scene_cases(session, aid, tid, mode):
                # Both legal modifiers remain reachable; local AI sees only its
                # menu, and tries its higher modifier first without guessing causes.
                bonuses = {"Wisdom": scene_medicine_bonus(actor, params, "Wisdom")}
                if params["key"]:
                    bonuses["Life key"] = scene_medicine_bonus(actor, params, "Life key")
                for ability in sorted(bonuses, key=lambda a: -bonuses[a]):
                    options.append({"id": f"life:{mode}:{tid}:{case['id']}:{ability}", "kind": "life_medicine",
                        "auto_select": int(ability == max(bonuses, key=bonuses.get)),
                        "payload": {"target": tid, "mode": mode, "case_id": case["id"], "ability": ability},
                        "label": f"Life Initiation: {mode} {target['name']}'s {case['category'] if case['obvious'] else 'medical concern'} with {ability} Medicine "
                                 f"({bonuses[ability]:+d}, DC {case['dc']}; within {case['range_ft']} feet; {case['seconds']} seconds, no resource cost)."})
    return options


@hook("journey_command")
def scene_command(session, aid, kind, payload):
    if kind not in ("life_recognize", "life_medicine"):
        return None
    from ..journey import require
    offered = scene_options(session, aid) or []
    require(any(r["kind"] == kind and r["payload"] == payload for r in offered), "That Life Initiation examination is not available to this creature.")
    actor, target = session.state["actors"][aid], session.state["actors"][payload["target"]]
    if kind == "life_recognize":
        snapshot = target.get("encounter_snapshot") or {}
        signs = visible_signs(snapshot.get("conditions", {}), snapshot.get("life_state"), journey_cases(target))
        session.emit("LIFE_RECOGNITION", aid, target=payload["target"], signs=sorted(set(signs)),
                     text=f"Life Initiation: {target['name']} shows " + (", ".join(sorted(set(signs))) if signs else "no confirmed obvious signs") + ". Hidden causes require examination.")
        return True
    case = next(c for c in scene_cases(session, aid, payload["target"], payload["mode"]) if c["id"] == payload["case_id"])
    params = scene_check(actor)
    bonus = scene_medicine_bonus(actor, params, payload["ability"])
    from factory_authoring.starting_kits import seeded_roll
    natural = seeded_roll(session.state["journey_id"], f"medicine:{session.state['revision']}:{aid}:{case['id']}", 20)
    success = natural + bonus >= case["dc"]
    session.tick(case["seconds"])
    if success and payload["mode"] == "identify":
        actor.setdefault("knowledge", {})[payload["target"] + ":" + case["id"]] = case["cause"]
    elif success:
        target["encounter_snapshot"]["life_state"] = "STABLE"
        target["encounter_snapshot"]["death_saves"] = {"ok": 0, "bad": 0}
    session.emit("MEDICINE_CHECK", aid, target=payload["target"], case_id=case["id"], ability=payload["ability"],
                 natural=natural, bonus=bonus, dc=case["dc"], success=int(success), mode=payload["mode"],
                 text=f"Life Initiation: {actor['name']}'s Medicine check for {target['name']} " + ("succeeds." if success else "fails."))
    return True
