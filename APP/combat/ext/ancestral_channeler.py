"""Ancestral Channeler (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md "04. Ancestral Channeler": Ancestor Offices, Ancestral Favor, CL3 Council of
the Remembered, CL6 Possession by the Past, CL10 Legacy Made Present, CL14 Ancestral Legion, CL18 Ancestral Ascension).
No Spheres 5e or D&D 5.5e counterpart. Ownership: the ``spirit_tradition`` rows of combat/rules/feature_blocks.d/riders_c8.json
(combat/ext/spirit_traditions.py; Possession by the Past keeps its ``d20_rewrite`` row of auto_H1.json); every hook returns early for a
creature without its row. Shared helpers used: spirit_traditions.row/feature_of/is_spirit_feature/affected_by/damaged_by/context/
pick_creature/can_react; menus.toggle_actions/picks; needle.ask; d20_rewrite.affordable/pool_id; passive_rows.row_of.

What runs:
  * Ancestor Offices (CL3; a third at CL10, Legacy Made Present): native characters record their covenant and Office choices.
    Those obligations persist; CL10 can append the third Office, and suppression makes unavailable benefits dormant without
    erasing the record. Explicit historical feature-only sheets retain their old menus; native unknown choices stay unknown.
  * Borrow the Office (Legacy Made Present; Bonus Action, 2 Resonance, 10 minutes): one button per Office, only the chosen Offices are
    offered. One borrowed Office at a time (a new one replaces it). Once on each of your turns, when a Spirit Awakening feature of yours
    resolves on your turn, the borrowed Office's expression applies:
      Healer   -- one ally the feature affected gains Temporary HP equal to your Proficiency Bonus (you pick when several).
      Warrior  -- one creature the feature damaged cannot make Opportunity Attacks until the start of your next turn.
      Wayfarer -- you, or one willing ally the feature affected, may move 5 feet without provoking Opportunity Attacks.
    Archivist, Magistrate and Ritualist expressions reveal information or constrain speech: the GM's lines (they stay riders).
  * Possession by the Past, Old Guard (CL6 Reaction, 1 Favor or 2 Resonance): when you are hit by an attack, add your Wisdom
    modifier to your AC against that attack; the player may use it even if the attack will still hit. Automatic play prefers it
    when it turns the hit into a miss; the engine's normal critical-hit threshold still governs. The
    reroll of a failed save (Remembered Resistance) is combat/ext/d20_rewrite_rules.py. After either, the ancestor's posture lingers
    until the start of your next turn: you cannot take Reactions (``posture``; no Office's Source Rule permits an exception).
  * Ancestral Ascension (CL18 Bonus Action, 10 Resonance, the scene): one button per chosen Office (the Ascendant Office). +2 AC and
    Advantage on Intelligence, Wisdom and Charisma saves are its typed rows. While it lasts:
      - the Ascendant Office's Borrow the Office expression also applies, alongside one different borrowed Office ("Borrow the Office
        for the Ascendant Office activates without cost and does not prevent you from maintaining one different borrowed Office");
      - once per turn when a Spirit Awakening feature of yours resolves, one creature Resonance Marked by you within 60 feet suffers
        your ordinary Spiritual Pressure effect (combat/ext/spirit_awakening.py);
      - Ascendant Office Authority, once during the activation (no action is printed: a free use on your turn), for the Ascendant
        Office only: Healer -- touch a creature: it regains 8d8 + Wisdom modifier HP and one ordinary poison or disease on it ends;
        Warrior -- one melee Cultivation Attack: 8d8 Force or Psychic, and the target cannot take Reactions or regain HP until the
        start of your next turn; Magistrate -- a creature within 60 feet makes a Charisma save, its failure the GM's line.

Plug-in surface: effects ancestral_borrow_office, ancestral_ascend, ancestral_authority, ancestral_cleanse; hooks compile_actions,
candidate_allowed, technique_used, hit_response. Public helper: ``posture(engine, actor, source)`` (also used by
d20_rewrite_rules.py's Possession by the Past reroll).
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.ancestral_channeler.feature."
COUNCIL = TRADITION + "council_of_the_remembered"
POSSESSION = TRADITION + "possession_by_the_past"
LEGACY = TRADITION + "legacy_made_present"
ASCENSION = TRADITION + "ancestral_ascension"
OFFICES = ("Archivist", "Healer", "Magistrate", "Warrior", "Wayfarer", "Ritualist")
DEFAULT_OFFICES = ["Warrior", "Healer", "Wayfarer"]
MENU = "ancestral_channeler.offices"
BORROWED = "condition:typed.ancestral_borrowed_office"
ASCENDED = "condition:typed.ancestral_ascension"
AUTHORITY_USED = "condition:typed.ancestral_authority_used"
POSTURE = "condition:typed.reaction_denied"
AUTHORITY = {"Healer": "Hands That Remember Life", "Warrior": "Thousand Battles in One Body", "Magistrate": "Judgment of the Lineage Court"}


# ------------------------------------------------------------------------------------------------------------------ Offices
def offices(engine: Any, actor: Any) -> list[str]:
    from . import menus
    from .spiritual_state import active_offices

    bundle = next((row for row in engine.typed_bundle_documents if row['actor_id'] == actor.entity_id), {})
    recorded = active_offices(actor)
    if 'spiritual_path_cl' in bundle:
        return recorded  # native acquisition never invents an unrecorded Office
    return recorded or menus.picks(engine, actor, MENU) or list(DEFAULT_OFFICES)


@hook('compile_bundle')
def covenant_favor(bundle, info):
    """Scene Favor needs the recorded covenant and actual strain/taboo facts."""
    from copy import deepcopy
    pool = 'resource:named.favor'
    if not any(str(r.get('feature_id', '')).startswith(TRADITION) for r in bundle['typed_passives']):
        return None
    if not any(r['resource_id'] == pool for r in bundle['actor_template']['resources']):
        return None
    out = deepcopy(bundle)
    record = info['owner_sheet'].get('spiritual_state') or {}
    facts = record.get('facts', {}).get(CHANNELER_SOURCE, {})
    permitted = (record.get('covenant') and facts.get('anchor_strained', {}).get('value') == 0
                 and facts.get('taboo_since_session', {}).get('value') == 0)
    for resource in out['actor_template']['resources']:
        if resource['resource_id'] == pool:
            resource['initial'] = int(bool(permitted))
    return out


CHANNELER_SOURCE = 'tianxia.tradition.spirit.ancestral_channeler'


@hook('match_initialize')
@hook('activity_initialize')
def initialize_covenant_favor(engine):
    from .spiritual_state import read, fact
    for actor in engine.state.actors.values():
        pool = 'resource:named.favor'
        if pool not in actor.resources or not any(str(r.get('feature_id', '')).startswith(TRADITION)
                for r in engine.typed_passive_rows.get(actor.entity_id, [])):
            continue
        # Journey facts may have been entered after compilation. Use the bundle
        # receipt directly so initialization order cannot invent eligibility.
        bundle = next((b for b in engine.typed_bundle_documents if b['actor_id'] == actor.entity_id), {})
        if bundle.get('spiritual_scene_id') and not bundle.get('lineage_scene_new', 1):
            continue  # returning to the same scene cannot refill spent Favor
        record = bundle.get('spiritual_state', {})
        facts = record.get('facts', {}).get(CHANNELER_SOURCE, {})
        from .lineage_reconciliation import STRAIN
        import json
        native_strain = any(json.loads(raw)['condition_id'] == STRAIN for raw in
            bundle.get('journey_setup', {}).get('encounter_snapshot', {}).get('conditions', {}).values())
        initial = int(bool(record.get('covenant') and facts.get('anchor_strained', {}).get('value') == 0
                           and facts.get('taboo_since_session', {}).get('value') == 0 and not native_strain))
        initial = min(actor.resource_maximums[pool], initial + int(bundle.get('lineage_favor_acts', 0)))
        difference = actor.resources[pool] - initial
        if difference > 0:
            engine._spend_resource(actor, pool, difference, COUNCIL)
        elif difference < 0:
            engine._gain_resource(actor, pool, -difference, COUNCIL)


@hook('event')
def office_favor(engine, event_type, kwargs):
    if event_type != 'CHECK_ROLLED':
        return
    from .spiritual_state import associated
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    data = kwargs.get('payload') or {}
    if data.get('roll_kind') == 'opposed_check':
        return  # the public opposed_check_resolved hook handles both sides
    if actor is None or 'resource:named.favor' not in actor.resources or not data.get('success'):
        return
    skill = data.get('skill') or data.get('check')
    if not associated(actor, skill):
        return
    pb = actor.proficiency_bonus
    meaningful = (int(data.get('dc') or 0) >= 10 + pb or bool(data.get('defender')))
    if not meaningful:
        return
    obstacle = str(data.get('obstacle_id') or kwargs.get('source_definition_id')) + ':' + ','.join(kwargs.get('target_ids') or ())
    award_office_favor(engine, actor, obstacle)


def award_office_favor(engine, actor, obstacle):
    """One scene award per unchanged, source-identified meaningful obstacle."""
    name = 'condition:typed.ancestral_favor_obstacle'
    if any(c.condition_id == name and c.data.get('obstacle') == obstacle for c in actor.conditions.values()):
        return
    from .spiritual_state import scene_id
    engine._apply_condition(actor, name, COUNCIL, actor.entity_id, expires_on='UNTIL_REMOVED',
                            data={'obstacle': obstacle, 'source_scene_id': scene_id(engine, actor),
                                  'label': 'Lineage Favor already earned for this obstacle this scene'})
    engine._gain_resource(actor, 'resource:named.favor', 1, COUNCIL)


@hook('opposed_check_resolved')
def opposed_office_favor(ctx, target, result, actor_check, target_check):
    from .spiritual_state import associated, meaningful_hostile
    sides = [(ctx.actor, target, actor_check, result.actor, result.success),
             (target, ctx.actor, target_check, result.target, not result.success)]
    for actor, opponent, spec, roll, succeeded in sides:
        if (actor is None or roll is None or not succeeded or 'resource:named.favor' not in actor.resources
                or not associated(actor, spec.get('skill'))):
            continue
        meaningful = ((result.dc is not None and result.dc >= 10 + actor.proficiency_bonus)
                      or meaningful_hostile(ctx.engine, actor, opponent))
        if not meaningful:
            continue
        latest = max((e.sequence for e in ctx.engine.events if e.event_type == 'INTENT_ACCEPTED'
                      and e.actor_id == opponent.entity_id), default=0)
        obstacle = f'{ctx.source}:{opponent.entity_id}:{latest}'
        award_office_favor(ctx.engine, actor, obstacle)


def _menu_row(owned: Any) -> dict[str, Any]:
    return {"type": "menu", "id": MENU, "name": "Ancestor Offices", "count": 3 if LEGACY in owned else 2,
            "label": "Choose your Ancestor Offices", "options": list(OFFICES), "default": list(DEFAULT_OFFICES)}


def _office_of(action: Any) -> str:
    """The Office a Borrow the Office / Ancestral Ascension button is for (its typed row names it)."""
    typed = (action.parameters or {}).get("typed") or {}
    return next((str(row.get("office")) for row in typed.get("effects") or []
                 if isinstance(row, dict) and row.get("type") in ("ancestral_borrow_office", "ancestral_ascend")), "")


def _strike_ready(engine: Any, actor: Any, action: Any) -> bool:
    """Whether a strike's own prerequisites hold right now: its compiled requires_condition (an improvised
    weapon must be grabbed first) and, for a weapon, that the weapon is held in a ready grip.
    The ordinary Action economy is deliberately not checked; the authority pays for the strike."""
    from .martial_strikes import ready
    return ready(engine, actor, action)


def _ordinary_strikes(engine: Any, actor: Any, target: Any) -> list[tuple[Any, Any, dict[str, Any], list[dict[str, Any]]]]:
    """Eligible ordinary weapon/unarmed strikes, filtered by provenance, prerequisites and target geometry.
    Each entry carries the compiled action's own effects, so the strike can run the whole action (for a thrown
    weapon, the cleanup that removes it from hand)."""
    from .martial_strikes import options
    return options(engine, actor, target, include_variants=False)


@hook("compile_actions")
def office_buttons(info: dict[str, Any]) -> list[Any] | None:
    owned = info["owned_ids"]
    out: list[Any] = []
    if COUNCIL in owned or LEGACY in owned:
        from . import menus

        count = 3 if LEGACY in owned else 2
        for button in menus.toggle_actions(info, _menu_row(owned), carry=True):
            option = str(button.parameters.get("menu_option"))
            out.append(button.model_copy(update={"parameters": {
                **button.parameters,
                "description": f"Ancestor Office: make {option} one of your {count} Offices (free; it stays until you change it; choosing "
                               f"another replaces the one chosen longest ago). Your Offices decide which Borrow the Office and Ancestral "
                               f"Ascension buttons you get."}}))
    if ASCENSION in owned:
        out.extend(_authority_actions(info))
    return out or None


@hook('candidate_allowed')
def covenant_offices_fixed(engine, actor, candidate, action):
    from .spiritual_state import read
    if action and action.parameters.get('menu_toggle') == MENU and read(actor).get('covenant'):
        return False
    return None


def _authority_actions(info: dict[str, Any]) -> list[Any]:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    numbers = info["numbers"]
    base = {"numbers": numbers, "duration": {"kind": "instant"}, "riders": [], "source": ASCENSION}
    rows = {
        "Healer": ("ALLY_OR_SELF", 5, [
            {"type": "healing", "applies_to": "target", "dice": {"count": 8, "sides": 8}, "formula": "key_ability_modifier",
             "evidence": "Restore 8d8 + Wisdom modifier Hit Points"},
            {"type": "ancestral_cleanse", "applies_to": "target",
             "evidence": "end one ordinary poison, disease, possession, curse, madness, or spiritual contamination"}],
            "Touch one creature: it regains 8d8 + your Wisdom modifier Hit Points and one ordinary poison or disease on it ends."),
        # Targeting is widened here because the selected ordinary strike owns
        # its range/reach. warrior_strike filters targets against those strikes.
        "Warrior": ("HOSTILE_ENTITY", 600, [
            {"type": "ancestral_warrior_strike", "applies_to": "target"}],
            "One weapon attack, unarmed strike, or Cultivation Attack: on a hit, normal damage plus 8d8 Force or Psychic damage, and the target cannot take Reactions or regain Hit Points "
            "until the start of your next turn."),
        "Magistrate": ("HOSTILE_ENTITY", 60, [
            {"type": "save", "applies_to": "target", "ability": "cha", "evidence": "One creature within 60 feet makes a Charisma saving throw",
             "on_fail": ["Judgment of the Lineage Court (failed Charisma save): the creature must either cease one named hostile act for the "
                         "scene or publicly state the genuine reason it refuses. It cannot be forced to reveal magically concealed "
                         "information it does not consciously know."],
             "on_success": []}],
            "One creature within 60 feet makes a Charisma save; if it fails, the GM rules which hostile act it stops or why it refuses."),
    }
    out = []
    for office, (target_kind, reach, effects, text) in rows.items():
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.ancestral_authority.{office.lower()}",
            display_name=f"Ascendant Authority: {AUTHORITY[office]} ({office})", owner_id=info["actor_id"], economy=EconomyKind.NONE,
            resolution_kind="TYPED", target_kind=target_kind, range_ft=reach,
            parameters={"typed": {**base, "effects": [*effects, {"type": "ancestral_authority", "office": office}]},
                        "expected_damage": 36 if office == "Warrior" else 0,
                        "ancestral_authority": office,
                        "description": f"Ancestral Ascension, once while it lasts (free, on your turn; Ascendant Office {office} only): {text}"}))
    return out


@hook("candidate_allowed")
def office_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    feature = st.feature_of(action)
    if feature in (LEGACY, ASCENSION) and _office_of(action) in OFFICES:
        return None if _office_of(action) in offices(engine, actor) else False
    office = (action.parameters or {}).get("ancestral_authority")
    if office:
        ascended = _ascended(actor)
        if ascended is None or (ascended.data or {}).get("office") != office:
            return False
        if any(c.condition_id == AUTHORITY_USED and c.source_actor_id == actor.entity_id for c in actor.conditions.values()):
            return False
        if office == "Warrior":
            target_ids = list(getattr(candidate, "target_ids", ()) or ())
            target = engine.state.actors.get(target_ids[0]) if target_ids else None
            if target is None or (engine._effect_distance(actor, target) > 5 and not _ordinary_strikes(engine, actor, target)):
                return False
    return None


# ----------------------------------------------------------------------------------------------------- borrowed Office
def _borrowed(actor: Any) -> list[Any]:
    return [c for c in actor.conditions.values() if c.condition_id == BORROWED and c.source_actor_id == actor.entity_id]


def _ascended(actor: Any) -> Any:
    return next((c for c in actor.conditions.values() if c.condition_id == ASCENDED and c.source_actor_id == actor.entity_id), None)


def expression_offices(actor: Any) -> list[str]:
    """The Offices whose Borrow the Office expression applies now: the borrowed one and, while ascended, the Ascendant Office."""
    found = [str((c.data or {}).get("office")) for c in _borrowed(actor)]
    ascended = _ascended(actor)
    if ascended is not None and (ascended.data or {}).get("office") not in found:
        found.append(str((ascended.data or {}).get("office")))
    return [office for office in found if office in OFFICES]


def _remove(engine: Any, actor: Any, condition: Any, reason: str) -> None:
    for iid, held in list(actor.conditions.items()):
        if held is condition:
            actor.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=held.source_actor_id,
                                 target_ids=(actor.entity_id,), payload={"condition_id": held.condition_id, "instance_id": iid, "reason": reason})


@effect("ancestral_borrow_office")
def borrow_office(ctx: Any, row: dict[str, Any]) -> None:
    office = str(row.get("office") or "")
    if office not in OFFICES:
        return
    for held in _borrowed(ctx.actor):
        _remove(ctx.engine, ctx.actor, held, "REPLACED")  # "You can maintain only one borrowed Office at a time."
    ctx.engine._apply_condition(ctx.actor, BORROWED, ctx.source, ctx.actor.entity_id, expires_on=ctx.expires_on() or "UNTIL_REMOVED",
                                data={"office": office, "label": f"Borrowed Office: {office}"})


@effect("ancestral_ascend")
def ascend(ctx: Any, row: dict[str, Any]) -> None:
    from .lineage_reconciliation import begin_presence, withdraw_for_replacement
    withdraw_for_replacement(ctx)
    office = str(row.get("office") or "")
    held = _ascended(ctx.actor)
    if held is not None:
        _remove(ctx.engine, ctx.actor, held, "REPLACED")
    for used in [c for c in ctx.actor.conditions.values() if c.condition_id == AUTHORITY_USED and c.source_actor_id == ctx.actor.entity_id]:
        _remove(ctx.engine, ctx.actor, used, "REPLACED")  # a new activation has its own Ascendant Office Authority
    ctx.engine._apply_condition(ctx.actor, ASCENDED, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"office": office, "label": f"Ancestral Ascension: {office} (the scene)"})
    begin_presence(ctx, office)


@effect("ancestral_authority")
def authority_used(ctx: Any, row: dict[str, Any]) -> None:
    ctx.engine._apply_condition(ctx.actor, AUTHORITY_USED, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": f"Ascendant Office Authority used ({row.get('office')})"})


@effect("ancestral_cleanse")
def cleanse(ctx: Any, row: dict[str, Any]) -> None:
    """End one ordinary poison or disease on the healed creature (possession, curse, madness and spiritual contamination are not
    conditions this table keeps; the GM ends one of those instead when the creature has no poison or disease)."""
    from ..typed_executor import CONDITION_PREFIX

    subject = ctx.target
    if subject is None or not subject.active:
        return
    for name in ("poisoned", "diseased"):
        if any(c.condition_id == CONDITION_PREFIX + name for c in subject.conditions.values()):
            ctx.engine._remove_condition(subject, CONDITION_PREFIX + name, ctx.source)
            return
    diseases = [c for c in subject.conditions.values() if "disease" in c.condition_id]
    if diseases:
        _remove(ctx.engine, subject, diseases[0], "CURED")
        return
    ctx.rider(f"Hands That Remember Life: {subject.display_name} bears no poison or disease the table tracks; the GM may end one "
              "ordinary possession, curse, madness or spiritual contamination on it instead.")


# --------------------------------------------------------------------------------------------------- expressions
@hook("technique_used")
def expressions(ctx: Any) -> None:
    engine, actor = ctx.engine, ctx.actor
    if not actor.active or not st.is_spirit_feature(ctx.action):
        return
    if st.row(engine, actor, "legacy_made_present") is not None and engine.state.current_actor_id == actor.entity_id:
        for office in expression_offices(actor):
            flag = f"ancestral_office_expression:{office}"
            if actor.turn_flags.get(flag):
                continue
            if _express(ctx, office):
                actor.turn_flags[flag] = True
    if st.row(engine, actor, "ancestral_ascension") is not None and _ascended(actor) is not None:
        _ascendant_pressure(ctx)


def _allies(ctx: Any, creatures: list[Any]) -> list[Any]:
    return [c for c in creatures if c.active and c.team_id == ctx.actor.team_id and c is not ctx.actor]


def _express(ctx: Any, office: str) -> bool:
    engine, actor = ctx.engine, ctx.actor
    feature = LEGACY
    if office == "Healer":
        allies = _allies(ctx, st.affected_by(engine, ctx))
        chosen = st.pick_creature(engine, ctx.intent, actor, allies, checkpoint="ANCESTRAL_HEALER", choice_id="choice:needle.ancestral.healer",
                                  prompt=f"Borrowed Office (Healer): after {ctx.action.display_name}, which ally gains Temporary Hit Points "
                                         f"equal to {actor.display_name}'s Proficiency Bonus?", name="Borrow the Office: Healer",
                                  feature_id=feature, preferred=min(allies, key=lambda c: (c.current_hp + c.temporary_hp, c.entity_id), default=None))
        if chosen is None:
            return False
        amount = int(ctx.numbers.get("pb") or 2)
        engine._grant_temp_hp(chosen, amount, feature, actor.entity_id)
        note(engine, feature, actor, f"Borrowed Office (Healer): {chosen.display_name} gains {amount} Temporary Hit Points.", (chosen,))
        return True
    if office == "Warrior":
        damaged = [c for c in st.damaged_by(engine, ctx) if c.active]
        from . import ai_controlled
        if ai_controlled(engine, actor):
            from ..target_knowledge import located
            damaged = [c for c in damaged if c.team_id != actor.team_id and located(engine, actor, c)]
        chosen = st.pick_creature(engine, ctx.intent, actor, damaged, checkpoint="ANCESTRAL_WARRIOR", choice_id="choice:needle.ancestral.warrior",
                                  prompt=f"Borrowed Office (Warrior): which creature damaged by {ctx.action.display_name} cannot make "
                                         "Opportunity Attacks until the start of your next turn?", name="Borrow the Office: Warrior",
                                  feature_id=feature, preferred=next((c for c in damaged if c.team_id != actor.team_id), None))
        if chosen is None:
            return False
        from .. import typed_executor

        sub = st.context(engine, actor, ctx.action, [chosen], ctx.numbers, ctx.intent)
        typed_executor.block_condition(sub, {"type": "condition", "applies_to": "target", "condition": "no_opportunity_attacks",
                                             "expires_on": "START_OF_SOURCE_NEXT_TURN",
                                             "evidence": "Borrowed Office (Warrior): cannot take opportunity attacks until the start of your next turn"})
        return True
    if office == "Wayfarer":
        allies = _allies(ctx, st.affected_by(engine, ctx))
        chosen = st.pick_creature(engine, ctx.intent, actor, [actor, *allies], checkpoint="ANCESTRAL_WAYFARER",
                                  choice_id="choice:needle.ancestral.wayfarer",
                                  prompt=f"Borrowed Office (Wayfarer): after {ctx.action.display_name}, who moves 5 feet without provoking "
                                         "Opportunity Attacks?", name="Borrow the Office: Wayfarer", feature_id=feature, allow_decline=True,
                                  preferred=actor)
        if chosen is None:
            return False
        from .. import typed_executor

        sub = st.context(engine, chosen, ctx.action, [], ctx.numbers, ctx.intent)
        typed_executor.run_effects(sub, [{"type": "rider_step", "distance_ft": 5, "no_oa": True, "label": "Borrowed Office (Wayfarer)"}])
        return True
    return False


def _ascendant_pressure(ctx: Any) -> None:
    engine, actor = ctx.engine, ctx.actor
    if actor.turn_flags.get("ancestral_ascension_pressure"):
        return
    from .. import typed_executor

    marked = [c for c in engine.state.actors.values() if c.active and c is not actor
              and typed_executor.bears_mark(c, actor.entity_id, "Resonance")
              and engine.grid.distance_ft(actor.position, c.position) <= 60]
    chosen = st.pick_creature(engine, ctx.intent, actor, marked, checkpoint="ANCESTRAL_ASCENSION", choice_id="choice:needle.ancestral.pressure",
                              prompt=f"Ancestral Ascension: after {ctx.action.display_name}, which creature Resonance Marked by "
                                     f"{actor.display_name} within 60 feet suffers your ordinary Spiritual Pressure effect?",
                              name="Ancestral Ascension: Spiritual Pressure", feature_id=ASCENSION,
                              preferred=min((c for c in marked if c.team_id != actor.team_id),
                                            key=lambda c: (engine.grid.distance_ft(actor.position, c.position), c.entity_id), default=None))
    if chosen is None:
        return
    actor.turn_flags["ancestral_ascension_pressure"] = True
    sub = st.context(engine, actor, ctx.action, [chosen], ctx.numbers, ctx.intent)
    typed_executor.run_effects(sub, [{"type": "spiritual_pressure", "applies_to": "target"}])


# ------------------------------------------------------------------------------------------------------ Possession
def posture(engine: Any, actor: Any, source: str, *, skill: str | None = None) -> None:
    """The ancestor's posture after Possession by the Past: no Reactions until the start of your next turn (no Office's Source Rule
    permits an opportunity attack), which also keeps Possession by the Past from being used again."""
    from . import needle
    from .spiritual_state import disputed, associated_offices
    eligible = associated_offices(actor, skill) if skill is not None else offices(engine, actor)
    chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, 'POSSESSION_OFFICE', actor.entity_id),
                        actor, 'choice:needle.ancestral.possession_office', eligible,
                        prompt=f'Possession by the Past: which Ancestor Office guides {actor.display_name}?',
                        name='Possession by the Past', feature_id=source)
    office = chosen[0] if chosen else eligible[0]
    engine._apply_condition(actor, POSTURE, source, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"office": office, "label": "Ancestor's posture: no Reactions until the start of your next turn"})
    disputes = disputed(actor)
    learned = 'condition:typed.ancestral_dispute_learned'
    if disputes and not any(c.condition_id == learned for c in actor.conditions.values()):
        from .spiritual_state import scene_id
        engine._apply_condition(actor, learned, source, actor.entity_id, expires_on='UNTIL_REMOVED',
                                data={'source_scene_id': scene_id(engine, actor), 'label': 'The lineage has explained its dispute this scene'})
        subjects = '; '.join(str(entry['value']) if isinstance(entry['value'], str) else entry['ruling']
                             for _, _, entry in disputes)
        # A choice addressed only to the owner delivers the subject without a
        # public GM_RIDER/log containing the private lineage dispute.
        needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, 'POSSESSION_DISPUTE', actor.entity_id),
                   actor, 'choice:needle.ancestral.dispute', ['understood'],
                   labels={'understood': 'The ancestor explains: ' + subjects}, prompt='Disputed Possession',
                   name='Possession by the Past', feature_id=source)


@hook("hit_response")
def old_guard(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> tuple[int, bool] | None:
    from .passive_rows import row_of

    holder = row_of(engine, target.entity_id, "d20_rewrite", "possession_by_the_past") if target is not None else None
    if holder is None or attacker is None:
        return None
    from .d20_rewrite import affordable, pool_id

    if not st.can_react(target):
        return None
    wisdom = int(holder.get("key_mod") or 0)
    from ..critical_attacks import hits
    new_ac = effective_ac + wisdom
    hit_after = hits(natural, total, new_ac, int(spec.get('critical_threshold',20)))
    from .spiritual_state import possession_costs
    payment = affordable(target, possession_costs(engine, target))
    if not payment:
        return None
    from . import needle

    paid = ' or '.join(' + '.join(f'{amount} ' + ('Ancestral Favor' if pool == 'favor' else 'Resonance')
                                for pool, amount in cost) for cost in possession_costs(engine,target))
    chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "OLD_GUARD", attacker.entity_id), target, "choice:needle.ancestral.old_guard",
                        ["use"], labels={"use": f"Old Guard: {wisdom:+d} AC against this attack ({paid}, your Reaction)"},
                        prompt=f"{attacker.display_name}'s attack hits {target.display_name} ({total} against AC {effective_ac}). Use "
                               f"Possession by the Past (Old Guard) to add your Wisdom modifier ({wisdom}) to your AC against it? "
                               f"The attack {'still hits' if hit_after else 'would miss'}. Costs {paid} and your Reaction; afterwards you cannot take Reactions until the start of your "
                               "next turn.", preferred=[] if hit_after else ["use"], default='decline' if hit_after else 'first', allow_decline=True, name="Possession by the Past: Old Guard",
                        feature_id=POSSESSION, target_id=target.entity_id)
    if not chosen:
        return None
    from .spiritual_state import choose_possession_payment
    payment = choose_possession_payment(engine, target, engine._active_intent, POSSESSION, f'{attacker.display_name}’s attack')
    if payment is None:
        return None
    with activation(engine, target, POSSESSION):
        for pool, amount in payment:
            engine._spend_resource(target, pool_id(target, pool), amount, POSSESSION)
        target.reaction_available = False
        engine._append_event("REACTION_RESOLVED", POSSESSION, actor_id=target.entity_id, target_ids=(attacker.entity_id,),
                             payload={"checkpoint": "ATTACK_HIT_BEFORE_DAMAGE", "ac_bonus": wisdom, "new_ac": new_ac,
                                      "hit_after_recheck": hit_after, "reaction_name": "Possession by the Past (Old Guard)"})
        posture(engine, target, POSSESSION)
        note(engine, POSSESSION, target, f"{target.display_name} uses Possession by the Past (Old Guard): {wisdom:+d} AC against "
                                         f"{attacker.display_name}'s attack, which {'still hits' if hit_after else 'misses'}; the ancestor's posture lingers (no Reactions until "
                                         "the start of its next turn).", (attacker,))
        return new_ac, hit_after


LEGION = TRADITION + 'ancestral_legion'
LEGION_KIND = 'Ancestral Legion'
ADVICE = 'condition:typed.ancestral_legion_advice'
INTERPOSE = 'condition:typed.ancestral_legion_interpose'


@effect('ancestral_legion')
def manifest_legion(ctx, row):
    from . import spirit_assets
    spirit_assets.manifest(ctx, LEGION_KIND, count=3, hp_pb=10, speed=30,
                          resist=('PSYCHIC', 'NECROTIC'), immune=('POISON', 'DISEASE'),
                          offices=offices(ctx.engine, ctx.actor))


@hook('compile_actions')
def legion_buttons(info):
    if LEGION not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    out = []
    for mode in ('Advise', 'Interpose', 'Ancestral Strike'):
        for payment in ('Bonus Action', 'Favor'):
            out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.legion.{mode.lower().replace(' ', '_')}.{payment.lower().replace(' ', '_')}",
                display_name=f'Legion: {mode} ({payment})', owner_id=info['actor_id'],
                economy=EconomyKind.BONUS_ACTION if payment == 'Bonus Action' else EconomyKind.NONE,
                costs=(("resource:named.favor", 1),) if payment == 'Favor' else (),
                resolution_kind='TYPED', target_kind='HOSTILE_ENTITY' if mode == 'Ancestral Strike' else 'ALLY_OR_SELF', range_ft=30 if mode == 'Ancestral Strike' else 5,
                parameters={'typed': {'numbers': info['numbers'], 'source': LEGION, 'duration': {'kind': 'instant'}, 'riders': [],
                                     'effects': [{'type': 'legion_expression', 'mode': mode}]},
                            'legion_command': mode, 'expected_damage': 13 if mode == 'Ancestral Strike' else 0,
                            'description': 'Command one shade, once on your turn: ' + mode + '. Choose the shade as the origin. '
                            'Advise grants Advantage on the ally’s next ability check before your next turn. Interpose grants twice your Proficiency Bonus '
                            'in Temporary Hit Points and half cover against one attack from the other side of the shade. '
                            'Ancestral Strike attacks a creature bearing your Resonance Mark.'}))
    return out


@hook('effect_origins')
def legion_origins(engine, actor, action):
    from . import spirit_assets
    if action.parameters.get('legion_command') or (_ascended(actor) is not None and st.is_spirit_feature(action)):
        return spirit_assets.origins(engine, actor, LEGION_KIND)
    return None


@hook('candidate_allowed')
def legion_gate(engine, actor, candidate, action):
    from . import spirit_assets
    from .. import typed_executor as te
    from ..target_knowledge import located
    if action is None:
        return None
    typed = action.parameters.get('typed') or {}
    if (action.display_name == 'Ancestral Legion'
            or any(r.get('type') == 'ancestral_legion' for r in typed.get('effects', []) if isinstance(r, dict))):
        if spirit_assets.assets(engine, actor, LEGION_KIND, live=False):
            return False
        placements = spirit_assets.legal_spaces(engine, actor.position, 30)
        from ..senses import perceives_cell
        from .needle import ai_controlled
        if ai_controlled(engine, actor):
            placements = [p for p in placements if perceives_cell(engine, actor, p)]
        return len(placements) >= 3
    mode = action.parameters.get('legion_command')
    if not mode:
        return None
    origin = candidate.metadata.get('effect_origin') or {}
    if actor.turn_flags.get('legion_commanded') or not str(origin.get('id', '')).startswith('object:spirit_asset:Ancestral Legion:'):
        return False
    targets = [engine.state.actors[t] for t in candidate.target_ids if t in engine.state.actors]
    return bool(targets) and all(located(engine, actor, t) and
          (t.team_id != actor.team_id and te.bears_mark(t, actor.entity_id, 'Resonance') if mode == 'Ancestral Strike'
           else t.team_id == actor.team_id) for t in targets)


@effect('legion_expression')
def legion_expression(ctx, row):
    from .. import typed_executor as te
    from ..action_geometry import record_for
    origin = record_for(ctx.engine, ctx.actor, ctx.source)
    if not origin or ctx.target is None:
        return
    ctx.actor.turn_flags['legion_commanded'] = True
    mode = row['mode']
    if mode == 'Advise':
        ctx.engine._apply_condition(ctx.target, ADVICE, ctx.source, ctx.actor.entity_id,
            expires_on='START_OF_SOURCE_NEXT_TURN', data={'label': 'Ancestral advice: Advantage on your next ability check'})
    elif mode == 'Interpose':
        ctx.engine._grant_temp_hp(ctx.target, 2 * int(ctx.numbers.get('pb') or 2), ctx.source, ctx.actor.entity_id)
        ctx.engine._apply_condition(ctx.target, INTERPOSE, ctx.source, ctx.actor.entity_id,
            expires_on='UNTIL_REMOVED', data={'shade': origin['id'], 'label': 'A lineage shade interposes: half cover against one attack from its other side'})
    else:
        obj = ctx.engine.state.objects[origin['id']]
        office = (obj.component.get('spirit_asset') or {}).get('office')
        kind = {'Warrior': 'force', 'Healer': 'radiant', 'Wayfarer': 'psychic', 'Magistrate': 'psychic', 'Archivist': 'psychic', 'Ritualist': 'necrotic'}.get(office, 'psychic')
        te.run_effects(ctx, [{'type': 'attack', 'attack_kind': 'cultivation_ranged', 'count': 1,
                             'on_hit': [{'type': 'damage', 'applies_to': 'target', 'dice': {'count': 2, 'sides': 8},
                                         'formula': 'key_ability_modifier', 'damage_types': [kind]}], 'on_miss': []}])


@hook('ability_check_mode')
def legion_advice(engine, actor, ability, skill, against):
    return 'ADVANTAGE' if any(c.condition_id == ADVICE for c in actor.conditions.values()) else None


@hook('directional_cover')
def legion_cover(engine, attacker, target, ray=None):
    from ..action_geometry import point
    for c in target.conditions.values():
        obj = engine.state.objects.get(c.data.get('shade')) if c.condition_id == INTERPOSE else None
        if obj is None or obj.destroyed:
            continue
        a, b, shade = point(engine, attacker), target.position, obj.position
        # Half cover only from the other side of the shade.
        if (a.x - shade.x) * (b.x - shade.x) + (a.y - shade.y) * (b.y - shade.y) < 0:
            return 2
    return 0


@hook('event')
def consume_legion_benefits(engine, event_type, kwargs):
    from .roll_context import check_receipts
    if event_type == 'CHECK_ROLLED':
        for aid, receipt in check_receipts(kwargs):
            actor = engine.state.actors.get(aid)
            if actor is not None:
                engine._remove_condition(actor, ADVICE, LEGION)
    if event_type == 'ATTACK_ROLLED':
        attacker = engine.state.actors.get(kwargs.get('actor_id'))
        for aid in kwargs.get('target_ids') or ():
            target = engine.state.actors.get(aid)
            if attacker and target and legion_cover(engine, attacker, target):
                engine._remove_condition(target, INTERPOSE, LEGION)


@hook('compile_action')
def legion_target_is_self(action, info):
    if st.feature_of(action) == LEGION and any(r.get('type') == 'ancestral_legion' for r in
            (action.parameters.get('typed') or {}).get('effects', []) if isinstance(r, dict)):
        return action.model_copy(update={'target_kind': 'SELF', 'range_ft': None})
    return None


@effect("ancestral_warrior_strike")
def warrior_strike(ctx: Any, row: dict[str, Any]) -> None:
    """One ordinary strike, with the printed additional damage and aftermath."""
    import copy
    from dataclasses import replace
    from . import needle
    target = ctx.target
    if target is None:
        return
    strikes = _ordinary_strikes(ctx.engine, ctx.actor, target)
    # A plain Cultivation Attack remains available without borrowing a paid
    # technique's extra effects or costs. Its damage is the authority's 8d8.
    # Cultivation's fallback is a melee strike; it cannot make a distant
    # target legal merely because the authority action itself has broad range.
    if ctx.engine._effect_distance(ctx.actor, target) <= 5:
        cultivation = ctx.action.model_copy(update={
            "source_definition_id": ctx.action.source_definition_id + ".cultivation",
            "display_name": "Cultivation Attack", "parameters": {"expected_damage": 0}})
        cultivation_attack = {"type": "attack", "attack_kind": "cultivation_melee", "count": 1, "on_hit": [], "on_miss": []}
        strikes.append((cultivation, cultivation_attack, ctx.typed, [cultivation_attack]))
    if not strikes:
        return
    strikes.sort(key=lambda item: (-int(item[0].parameters.get("expected_damage") or 0), item[0].source_definition_id))
    choices = [a.source_definition_id for a, _, _, _ in strikes]
    picked = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "ANCESTRAL_WARRIOR", target.entity_id),
                        ctx.actor, "choice:needle.ancestral.warrior_strike", choices,
                        labels={a.source_definition_id: a.display_name for a, _, _, _ in strikes}, preferred=choices[:1],
                        name="Thousand Battles in One Body", feature_id=ASCENSION, target_id=target.entity_id,
                        prompt=f"Choose the one strike against {target.display_name}. On a hit it deals its normal damage plus 8d8 Force or Psychic damage.")
    action, original, typed, effects = next(item for item in strikes if item[0].source_definition_id == picked[0])
    if not _strike_ready(ctx.engine, ctx.actor, action):
        return
    attack = copy.deepcopy(original)
    attack["count"] = 1
    attack["on_hit"] = [*attack.get("on_hit", []),
        {"type": "extra_damage", "applies_to": "target", "dice": {"count": 8, "sides": 8}, "damage_types": ["force", "psychic"]},
        {"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN"},
        {"type": "healing_reduction", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN",
         "evidence": "cannot regain Hit Points until the start of your next turn"}]
    sub = replace(ctx, action=action, typed={**copy.deepcopy(typed), "source": ASCENSION, "riders": []})
    from .. import typed_executor
    # The compiled action in its own order: this strike's one attack, then its other effects (a thrown
    # weapon's remove_condition(improvised)). Paid technique payloads never reach here (filtered above).
    steps = [attack if row is original else copy.deepcopy(row) for row in effects]
    typed_executor.run_effects(sub, steps)
