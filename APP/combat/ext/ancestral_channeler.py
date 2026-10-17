"""Ancestral Channeler (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md "04. Ancestral Channeler": Ancestor Offices, Ancestral Favor, CL3 Council of
the Remembered, CL6 Possession by the Past, CL10 Legacy Made Present, CL14 Ancestral Legion, CL18 Ancestral Ascension).
No Spheres 5e or D&D 5.5e counterpart. Ownership: the ``spirit_tradition`` rows of combat/rules/feature_blocks.d/riders_c8.json
(combat/ext/spirit_traditions.py; Possession by the Past keeps its ``d20_rewrite`` row of auto_H1.json); every hook returns early for a
creature without its row. Shared helpers used: spirit_traditions.row/feature_of/is_spirit_feature/affected_by/damaged_by/context/
pick_creature/can_react; menus.toggle_actions/picks; needle.ask; d20_rewrite.affordable/pool_id; passive_rows.row_of.

What runs:
  * Ancestor Offices (CL3; a third at CL10, Legacy Made Present): the sheet does not record them, so they are a standing free
    choice (combat/ext/menus.py, one free button per Office, two kept, three with Legacy Made Present). The built-in AI and a player
    who never chose use Warrior, Healer, Wayfarer.
  * Borrow the Office (Legacy Made Present; Bonus Action, 2 Resonance, 10 minutes): one button per Office, only the chosen Offices are
    offered. One borrowed Office at a time (a new one replaces it). Once on each of your turns, when a Spirit Awakening feature of yours
    resolves on your turn, the borrowed Office's expression applies:
      Healer   -- one ally the feature affected gains Temporary HP equal to your Proficiency Bonus (you pick when several).
      Warrior  -- one creature the feature damaged cannot make Opportunity Attacks until the start of your next turn.
      Wayfarer -- you, or one willing ally the feature affected, may move 5 feet without provoking Opportunity Attacks.
    Archivist, Magistrate and Ritualist expressions reveal information or constrain speech: the GM's lines (they stay riders).
  * Possession by the Past, Old Guard (CL6 Reaction, 1 Favor or 2 Resonance): when you are hit by an attack, add your Wisdom
    modifier to your AC against that attack; offered only when that turns the hit into a miss (a natural 20 still hits). The
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

    return menus.picks(engine, actor, MENU) or list(DEFAULT_OFFICES)


def _menu_row(owned: Any) -> dict[str, Any]:
    return {"type": "menu", "id": MENU, "name": "Ancestor Offices", "count": 3 if LEGACY in owned else 2,
            "label": "Choose your Ancestor Offices", "options": list(OFFICES), "default": list(DEFAULT_OFFICES)}


def _office_of(action: Any) -> str:
    """The Office a Borrow the Office / Ancestral Ascension button is for (its typed row names it)."""
    typed = (action.parameters or {}).get("typed") or {}
    return next((str(row.get("office")) for row in typed.get("effects") or []
                 if isinstance(row, dict) and row.get("type") in ("ancestral_borrow_office", "ancestral_ascend")), "")


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
        "Warrior": ("HOSTILE_ENTITY", 5, [
            {"type": "attack", "attack_kind": "cultivation_melee", "count": 1, "evidence": "Make one ... Cultivation Attack",
             "on_hit": [{"type": "damage", "applies_to": "target", "dice": {"count": 8, "sides": 8}, "damage_types": ["force", "psychic"],
                         "evidence": "deal an additional 8d8 Force or Psychic damage"},
                        {"type": "condition", "applies_to": "target", "condition": "reaction_denied", "expires_on": "START_OF_SOURCE_NEXT_TURN",
                         "evidence": "the target cannot take Reactions until the start of your next turn"},
                        {"type": "healing_reduction", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN",
                         "evidence": "cannot regain Hit Points until the start of your next turn"}],
             "on_miss": []}],
            "One melee Cultivation Attack: on a hit, 8d8 Force or Psychic damage, and the target cannot take Reactions or regain Hit Points "
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
    office = str(row.get("office") or "")
    held = _ascended(ctx.actor)
    if held is not None:
        _remove(ctx.engine, ctx.actor, held, "REPLACED")
    for used in [c for c in ctx.actor.conditions.values() if c.condition_id == AUTHORITY_USED and c.source_actor_id == ctx.actor.entity_id]:
        _remove(ctx.engine, ctx.actor, used, "REPLACED")  # a new activation has its own Ascendant Office Authority
    ctx.engine._apply_condition(ctx.actor, ASCENDED, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"office": office, "label": f"Ancestral Ascension: {office} (the scene)"})


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
def posture(engine: Any, actor: Any, source: str) -> None:
    """The ancestor's posture after Possession by the Past: no Reactions until the start of your next turn (no Office's Source Rule
    permits an opportunity attack), which also keeps Possession by the Past from being used again."""
    engine._apply_condition(actor, POSTURE, source, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"label": "Ancestor's posture: no Reactions until the start of your next turn"})


@hook("hit_response")
def old_guard(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> tuple[int, bool] | None:
    from .passive_rows import row_of

    holder = row_of(engine, target.entity_id, "d20_rewrite", "possession_by_the_past") if target is not None else None
    if holder is None or attacker is None or attacker.team_id == target.team_id or natural == 20:
        return None
    from .d20_rewrite import affordable, pool_id

    if not st.can_react(target):
        return None
    wisdom = int(holder.get("key_mod") or 0)
    if wisdom <= 0 or total >= effective_ac + wisdom:
        return None  # it would still hit: Old Guard cannot turn it into a miss
    payment = affordable(target, ((("favor", 1),), (("resonance", 2),)))
    if not payment:
        return None
    from . import needle

    paid = " and ".join(f"{amount} {pool.title()}" for pool, amount in payment)
    chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "OLD_GUARD", attacker.entity_id), target, "choice:needle.ancestral.old_guard",
                        ["use"], labels={"use": f"Old Guard: +{wisdom} AC against this attack ({paid}, your Reaction)"},
                        prompt=f"{attacker.display_name}'s attack hits {target.display_name} ({total} against AC {effective_ac}). Use "
                               f"Possession by the Past (Old Guard) to add your Wisdom modifier ({wisdom}) to your AC against it and turn it "
                               f"into a miss? Costs {paid} and your Reaction; afterwards you cannot take Reactions until the start of your "
                               "next turn.", preferred=["use"], allow_decline=True, name="Possession by the Past: Old Guard",
                        feature_id=POSSESSION, target_id=target.entity_id)
    if not chosen:
        return None
    for pool, amount in payment:
        engine._spend_resource(target, pool_id(target, pool), amount, POSSESSION)
    target.reaction_available = False
    engine._append_event("REACTION_RESOLVED", POSSESSION, actor_id=target.entity_id, target_ids=(attacker.entity_id,),
                         payload={"checkpoint": "ATTACK_HIT_BEFORE_DAMAGE", "ac_bonus": wisdom, "new_ac": effective_ac + wisdom,
                                  "hit_after_recheck": False, "reaction_name": "Possession by the Past (Old Guard)"})
    posture(engine, target, POSSESSION)
    note(engine, POSSESSION, target, f"{target.display_name} uses Possession by the Past (Old Guard): +{wisdom} AC against "
                                     f"{attacker.display_name}'s attack, which misses; the ancestor's posture lingers (no Reactions until "
                                     "the start of its next turn).", (attacker,))
    return effective_ac + wisdom, False
