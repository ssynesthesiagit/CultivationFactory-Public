"""Disease (rider lane 10, 2026-09-29): Contagion Tokens that stack, saves against Disease, and the talents that spread, spend or
answer Contagion Tokens. Rules text: the owner's Sphere Compendium, "Disease" (authority/typed_mechanics/rules_text.json).

  Contagion Tokens   a mark ("Contagion Token", placed by Sow the Fever Seed and the rest); several from one Disease cultivator stack
                     ("a creature bearing at least two of your Contagion Tokens", "gain two Contagion Tokens"): the count is kept in the
                     marker's turn flags (``_round_contagion:<creature>``, saved with the fight) and a spent token leaves the rest.
  Against Disease    "Advantage on saving throws against Disease": a save a Disease talent forces (its source is a Disease ability, or its
                     failure would make the creature Sickened) -- for the holder of Plague-Bearing Body, the maker and allies inside the
                     Court of the Crawling Fever or World of Pestilence, creatures inside a Containment-mode Quarantine Veil, and one
                     save granted by Purging Breath.
  Plague-Bearing Body  "A creature Grappling you ... gains one Contagion Token at the start of its turn".
  Plague-Sovereign Incarnation  "your Sow the Fever Seed deals 6d10"; "creatures damaged by your Disease talents gain one Contagion Token
                     once per turn"; "Virulent Presence: When an enemy starts its turn within 20 feet of you, it makes a Constitution saving
                     throw. Failed Save: Choose one (a standing pick) ... Successful Save: Healing ... reduced by your Proficiency Bonus".
  Spreading Infection  (Reaction, 2 CP, once per round) "A creature bearing one or more of your Contagion Tokens starts its turn within 10
                     feet of another creature: Choose one nearby creature. The target makes a Constitution saving throw. Failed Save: The
                     target gains one Contagion Token. Successful Save: ... cannot gain Contagion Tokens from this talent until the start
                     of its next turn." (the nearest hostile creature)
  Epidemic Surge     "Choose up to your Proficiency Bonus creatures bearing your Contagion Tokens. Spend one Contagion Token from each ..."
  Plague Eruption    "When a creature with one or more of your Contagion Tokens fails its saving throw against this area, you may spend one of
                     those tokens to deal an additional 2d6 damage" (3d6 at Nascent Soul).
  Infection of the Cultivation Breath  (Reaction) "When a creature bearing at least two of your Contagion Tokens spends CP ... spend one of
                     those tokens. Constitution saving throw. Failed Save: ... cannot regain CP, and has Disadvantage on concentration saving
                     throws. Successful Save: The creature cannot regain CP until the start of its next turn."
  Purging Breath     its five choices as buttons (the table runs removing a token, suppressing Sickened and the Advantage on the next save).
  Quarantine Veil, Containment Mode  "Whenever a chosen creature starts its turn inside the veil, it may remove one Contagion Token from itself."
  Court of the Crawling Fever  "You and allies you choose gain:" -- Advantage on saving throws against Disease, Resistance to Poison
                     and Necrotic damage caused by Disease talents, and the Contagion Token shed (the printed immunity to the
                     maker's own Quarantine Veil and Plague Cloud damage is left to the table: the game does not add it). The maker is
                     asked once, when the aura is raised, which allies standing in it join; the answer is stored on the aura itself
                     (``trigger_profile["court_allies"]``, republished so it survives a commit and reload). Every Court on the
                     subject's team that reaches it grants independently, so an overlap never hides a benefit another Court gave
                     (``_courts_covering``), and an aura saved before that answer existed -- it carries no such field -- keeps the
                     allies it had (``_grants``); a stored empty list stays a maker's own "no one". The resistance is keyed to the
                     damage's own source ability (``pending_damage`` provenance and the ability's compiled ``sphere``), so an area's
                     save damage is covered while an enemy's Poison and the same Disease cultivator's unrelated Poison or Death
                     damage land in full.
  Spreading Infection  "You choose whether this talent can affect your allies": every creature within 10 feet is offered and the label
                     says which are allies, so that choice is the player's; an AI still takes the nearest hostile one.
  Enlarged Quarantine Veil / Narrow Quarantine  the printed radii and "no longer requires Concentration, but it lasts only until the end
                     of your next turn" ride the typed modifier's ``area_size_ft``/``area_size_ft_by_cl``/``duration``, so no GM line.
  Plague Cloud  (2 extra CP, Raise the Quarantine Veil in Outbreak Mode) "The area becomes lightly obscured, and enemies that fail their saving
                     throw against the veil also gain one Contagion Token. At Core Formation, enemies that fail also become unable to regain more
                     than half the normal Hit Points from healing until the start of your next turn." The veil that choice makes starts lightly
                     obscured, and its save hands each failing enemy one Contagion Token (the shared ``disease_tokens`` mark above). "At Core
                     Formation" is the veil's own third die-by-Realm band (CL 10-14), read with the executor's CL banding. The healing cap is the
                     engine's existing healing-halved representation (a condition carrying the ``healing_halved`` rule, as fate_riders.py and
                     zones.py's area conditions do), applied by the veil-maker so it ends at the start of the veil-maker's next turn.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note

TOKEN = "Contagion Token"
DISEASE_SPHERE = "tianxia.sphere.disease"
QUARANTINE_WARD_STATE = "quarantine_ward"
BODY = "tianxia.talent.disease.plague_bearing_body"
SOVEREIGN = "tianxia.talent.disease.plague_sovereign_incarnation"
SPREADING = "tianxia.talent.disease.spreading_infection"
BREATH = "tianxia.talent.disease.infection_of_the_cultivation_breath"
CRAWLING = "tianxia.talent.disease.court_of_the_crawling_fever"
PESTILENCE = "tianxia.talent.disease.world_of_pestilence"
VEIL = "DISEASE_BASE_RAISE_THE_QUARANTINE_VEIL"
SOW = "DISEASE_BASE_SOW_THE_FEVER_SEED"
ERUPTION = "tianxia.talent.disease.plague_eruption"
CLOUD = "tianxia.talent.disease.plague_cloud"
OUTBREAK = "Outbreak Mode"
# The Outbreak veil's own die by Realm (authority Outbreak Mode, same rows its damage uses): 1d6 / 2d6 / 3d6 / 4d6 over the printed
# CL bands Mortal 1-4, Foundation 5-9, Core Formation 10-14, Nascent Soul 15-20. Plague Cloud's "At Core Formation" is that third band
# or better, so the same ``dice_for_cl`` banding the veil's damage uses answers it (no second realm rule here).
CLOUD_DICE = ((1, 4, 1, 6), (5, 9, 2, 6), (10, 14, 3, 6), (15, 20, 4, 6))
CORE_FORMATION_BAND = 2
HEALING_HALFED = "condition:typed.plague_cloud_healing_halved"
NEXT_SAVE = "condition:typed.disease_next_save_advantage"
_BUSY = "_disease_busy"


def tokens(engine: Any, owner: Any, subject: Any) -> int:
    """How many of ``owner``'s Contagion Tokens ``subject`` carries (combat/ext/stacking_marks.py keeps the count)."""
    from . import stacking_marks

    return stacking_marks.count(engine, owner, subject, TOKEN)


def add_tokens(engine: Any, owner: Any, subject: Any, count: int, source: str, *, origin: Any = None) -> None:
    from . import stacking_marks

    if subject is None or count <= 0:
        return
    if origin is not None and not _allow_quarantine_spread(engine, origin, subject, source):
        return
    stacking_marks.add(engine, owner, subject, TOKEN, count, source)


@hook("mark_pre_apply")
def quarantine_ward_mark(ctx: Any, row: dict[str, Any], subject: Any, expires: str,
                         data: dict[str, Any] | None) -> bool | None:
    """Veto a Contagion Token mark before any placement handler can observe its shared row."""
    if str(row.get("mark") or "") != TOKEN:
        return None
    origin_id = row.get("spread_origin_id")
    if not origin_id:
        return None
    origin = ctx.engine.state.actors.get(str(origin_id))
    if origin is None:
        return None
    return False if not _allow_quarantine_spread(ctx.engine, origin, subject, ctx.source) else None


def _zone_contains(engine: Any, zone: Any, actor: Any, position: Any = None) -> bool:
    """Use the authored area geometry for ward membership and teleport boundaries."""
    from ..spatial_areas import zone_contains

    return bool(zone_contains(engine, actor, zone, at=position))


def _ward_zones(engine: Any) -> list[Any]:
    from .. import zones

    return [zone for zone in zones.typed_zones(engine)
            if zone.active and isinstance((zone.trigger_profile or {}).get(QUARANTINE_WARD_STATE), dict)]


def _allow_quarantine_spread(engine: Any, origin: Any, subject: Any, source: str) -> bool:
    """A Ward owner may permit each Contagion Token to leave their active Containment area."""
    from .rider_choices import pick

    action = engine.action_catalog.get(str(source))
    trigger_name = str(getattr(action, "display_name", "") or "the Disease talent")
    for zone in _ward_zones(engine):
        if not _zone_contains(engine, zone, origin) or _zone_contains(engine, zone, subject):
            continue
        ward_owner = engine.state.actors.get(zone.owner_id)
        if ward_owner is None:
            continue
        checkpoint = f"quarantine_spread:{zone.zone_id}:{source}:{engine.state.event_sequence}"
        chosen = pick(engine, ward_owner, checkpoint, "Quarantine Ward", ["contain", "allow"],
                      labels={"contain": "Keep the Contagion Token inside the ward",
                              "allow": f"Allow {subject.display_name} to receive the Contagion Token"},
                      preferred=["contain"], subject=subject,
                      trigger=f"{trigger_name} would spread a Contagion Token out of your ward to {subject.display_name}",
                      prompt=f"Quarantine Ward: {trigger_name} would spread a Contagion Token from inside your ward to "
                             f"{subject.display_name}. Keep it inside, or allow the spread.")
        if chosen and chosen[0] == "allow":
            continue
        note(engine, source, ward_owner,
             f"Quarantine Ward keeps a Contagion Token from spreading to {subject.display_name}.", (subject,))
        return False
    return True


@hook("choice_reactors")
def quarantine_ward_choice_reactors(engine: Any) -> tuple[str, ...]:
    """Active persisted Wards enroll their owners for off-turn spread permission."""
    return tuple(sorted({zone.owner_id for zone in _ward_zones(engine)
                         if zone.owner_id in engine.state.actors}))


@effect("disease_quarantine_ward")
def quarantine_ward(ctx: Any, _effect: dict[str, Any]) -> None:
    """Raise Quarantine Ward's persisted, selected protection on its paid Containment variant."""
    from .rider_choices import pick
    from .tabik_dark import republish, zone_made_now

    zone = zone_made_now(ctx)
    if zone is None:
        return
    inside = [actor for actor in ctx.engine.state.actors.values()
              if actor.active and _zone_contains(ctx.engine, zone, actor)]
    options = [str(actor.entity_id) for actor in sorted(inside, key=lambda row: row.entity_id)]
    labels = {str(actor.entity_id): f"{actor.display_name}: selected for Quarantine Ward protection"
              for actor in inside}
    selected = pick(ctx.engine, ctx.actor, "quarantine_ward_recipients", "Quarantine Ward", options,
                    labels=labels, subject=ctx.actor,
                    trigger="you raise the Containment veil",
                    maximum=len(options), minimum=0,
                    prompt="Quarantine Ward: choose any number of creatures inside the Containment veil. Those you "
                           "select gain Resistance to Poison and Necrotic damage caused by Disease talents while "
                           "they remain inside. Contagion Tokens cannot spread out unless you allow it. A token-bearing "
                           "creature inside that attempts to teleport out must succeed on a Charisma saving throw or "
                           "the teleport fails.") if options else []
    ward = {"selected": [str(value) for value in selected],
            "save_dc": int((ctx.numbers or {}).get("save_dc") or 10)}
    zone.trigger_profile = {**(zone.trigger_profile or {}), QUARANTINE_WARD_STATE: ward}
    republish(ctx.engine, zone, ctx.source)


def spend_token(engine: Any, owner: Any, subject: Any, source: str) -> bool:
    from . import stacking_marks

    return stacking_marks.spend(engine, owner, subject, TOKEN, source)


@effect("disease_tokens")
def token_effect(ctx: Any, eff: dict[str, Any]) -> None:
    """"gains N Contagion Tokens" (Thousand-Symptom Plague's two)."""
    subject = ctx.target
    owner = _summoner(ctx.engine, ctx.actor) or ctx.actor  # a Living Plague's token is its summoner's
    if subject is not None:
        origin_id = eff.get("spread_origin_id")
        origin = ctx.engine.state.actors.get(str(origin_id)) if origin_id else None
        # Summoned attackers spread their summoner\'s tokens from their own square.
        if origin is None and owner is not ctx.actor:
            origin = ctx.actor
        add_tokens(ctx.engine, owner, subject, int(eff.get("count") or 1), ctx.source, origin=origin)


# ------------------------------------------------------------------------------------------------------------ saves against Disease
def _active(actor: Any, feature: str) -> bool:
    return any(feature in str(c.source_definition_id) for c in actor.conditions.values()) or \
        any(feature in str(m.source_definition_id) for m in actor.modifiers.values())


def _zones_of(engine: Any, feature: str) -> list[Any]:
    from .. import zones

    return [zone for zone in zones.typed_zones(engine) if zone.active and feature in str(zone.source_definition_id)]


def _inside(zone: Any, creature: Any) -> bool:
    return any((c.x, c.y) == (creature.position.x, creature.position.y) for c in zone.affected_cells)


def _sheltered(engine: Any, subject: Any) -> bool:
    if _active(subject, BODY):
        return True
    if court_covers(engine, subject):  # "You and allies you choose gain: Advantage on saving throws against Disease"
        return True
    for zone in _zones_of(engine, PESTILENCE):
        owner = engine.state.actors.get(zone.owner_id)
        if owner is not None and owner.team_id == subject.team_id and _inside(zone, subject):
            return True
    from ..typed_executor import condition_rules

    return any(row.get("disease_containment") for row in condition_rules(subject))  # inside a Containment veil (its "inside" rule)


def _against_disease(ctx: Any, named: Any) -> bool:
    source = str(getattr(ctx, "source", "") or "")
    return "disease" in source.lower() or "sickened" in set(named or ())


@hook("save")
def disease_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if subject is None or not _against_disease(ctx, named):
        return None
    once = next(((iid, c) for iid, c in subject.conditions.items() if c.condition_id == NEXT_SAVE), None)
    if once is not None:
        subject.conditions.pop(once[0], None)
        ctx.engine._append_event("CONDITION_REMOVED", "system:disease.purging_breath", actor_id=once[1].source_actor_id, target_ids=(subject.entity_id,),
                                 payload={"condition_id": NEXT_SAVE, "instance_id": once[0]})
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return {"bonus": 0, "modes": ["ADVANTAGE"]} if _sheltered(ctx.engine, subject) else None


# ------------------------------------------------------------------------------------------------------------ the Court of the Crawling Fever's beneficiaries
COURT_ALLIES = "court_allies"
_CHOICE = "disease_court_allies"


def _names_disease(source_id: Any) -> bool:
    """Whether this id names a Disease ability: a Disease base ability, one of its talents, or a row sourced
    from one (``DISEASE_BASE_...``, ``tianxia.talent.disease....``, the Disease sphere id itself)."""
    text = str(source_id or "").lower()
    return "disease" in text or DISEASE_SPHERE in text


def caused_by_disease(engine: Any, typed: Any) -> bool:
    """Whether the damage being resolved is "caused by Disease talents".

    Read from the packet's own provenance, never from the attacker's character build: the ability's compiled
    row (``typed["sphere"]``/``typed["source"]``, the same qualification ``combat/typed_executor.py`` makes for
    Unmaking) and, for a packet the engine commits without a compiled row, the catalog id it committed that
    packet under (``combat.pending_damage.current(engine)``, the documented provenance seam other plug-ins
    read). So an area's or a save's damage is covered, while a Disease cultivator's unrelated Poison, Death or
    weapon damage -- and an enemy's own Poison -- are not.
    """
    from ..pending_damage import current

    row = typed if isinstance(typed, dict) else {}
    sphere = row.get("sphere")
    if sphere:  # a compiled ability: its own Sphere answers it, and nothing else can
        return str(sphere) == DISEASE_SPHERE
    ids = [row.get("source")]
    packet = current(engine)
    if packet is not None:
        ids.append(packet.source_id)
    return any(_names_disease(value) for value in ids if value)


def _courts_covering(engine: Any, subject: Any) -> list[tuple[Any, Any]]:
    """Every active Court of the Crawling Fever whose maker is on ``subject``'s team and whose aura ``subject`` is
    in (its own maker always is), as (aura, maker) pairs.

    A list, not the first match: two Disease cultivators on one team can have overlapping auras, and each of their
    Courts grants its own benefits independently. Which one happens to come first in the area list must not decide
    whether an ally, or a second maker standing inside the first one's aura, keeps the benefits it was given.
    """
    found: list[tuple[Any, Any]] = []
    for zone in _zones_of(engine, CRAWLING):
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or not owner.active or owner.team_id != subject.team_id:
            continue
        if subject is owner or _inside(zone, subject):
            found.append((zone, owner))
    return found


def _grants(zone: Any, owner: Any, subject: Any) -> bool:
    """Whether this one Court of the Crawling Fever's printed benefits reach ``subject``.

    Its own maker always does ("You ... gain"). An ally needs that maker's answer to "you and allies you choose" --
    except in a fight saved before the answer was stored, where the aura carries no ``court_allies`` at all: every
    ally standing in it was a beneficiary when it was raised, so those allies keep all four benefits on load rather
    than silently losing them. An answer of "none" is a stored empty list and stays one -- an ally nobody chose gains
    nothing, which is what the printed choice says.
    """
    if subject is owner:
        return True
    stored = (zone.trigger_profile or {}).get(COURT_ALLIES)
    if stored is None:  # an aura raised before the choice existed: the printed rule it ran on reached every ally
        return True
    return str(subject.entity_id) in {str(value) for value in stored}


def court_covers(engine: Any, subject: Any) -> bool:
    """"You and allies you choose gain ...": whether the printed benefits of any Court of the Crawling Fever on
    ``subject``'s team reach ``subject`` -- that Court's own maker, or an ally in its aura that the maker named when
    raising it. A beneficiary of one Court is a beneficiary even while standing inside a second, overlapping Court
    whose maker did not name them; an ally nobody chose gains nothing, which is what the printed choice says."""
    return any(_grants(zone, owner, subject) for zone, owner in _courts_covering(engine, subject))


def choose_court_allies(ctx: Any, zone: Any) -> None:
    """"You and allies you choose gain ...": the maker is asked, once, when the aura is raised, which of its
    allies standing in the Court share its benefits.

    Asked through the shared rider-choice transport (``combat/ext/rider_choices.py``), so a player answers it
    while playing the maker -- on their own turn and, with Ask me, on an AI turn too -- and an AI maker answers
    automatically and takes every ally in reach. The answer is stored on the aura itself as entity-id strings
    (``trigger_profile["court_allies"]``) and republished, so it survives the table's commit and reload and a
    saved fight replays the Court with the same beneficiaries."""
    from .rider_choices import pick

    engine, maker = ctx.engine, ctx.actor
    allies = sorted((a for a in engine.state.actors.values()
                     if a.active and a is not maker and a.team_id == maker.team_id and _inside(zone, a)),
                    key=lambda a: a.entity_id)
    if not allies:
        zone.trigger_profile = {**(zone.trigger_profile or {}), COURT_ALLIES: []}
        return
    chosen = pick(engine, maker, _CHOICE, "Court of the Crawling Fever", [a.entity_id for a in allies],
                  labels={a.entity_id: f"{a.display_name}, an ally of yours standing in the Court: joins your Court"
                          for a in allies},
                  subject=maker, trigger="you raise it (the Court lasts while you concentrate, up to 1 minute)",
                  maximum=len(allies), minimum=1,
                  prompt="Court of the Crawling Fever: you have raised the Court. Choose which of your allies standing in it gain its "
                         "benefits, which last while you concentrate, up to 1 minute: Advantage on saving throws against "
                         "Disease, Resistance to Poison and Necrotic damage caused by Disease talents, and the ability to "
                         "shed one of your Contagion Tokens at the start of each of their turns. An ally you leave out "
                         "gains none of them. You always gain them yourself. Your allies are also meant to be immune to "
                         "your Quarantine Veil and Plague Cloud damage; the game does not work that immunity out for "
                         "you, so look after it yourself and tell your table.")
    zone.trigger_profile = {**(zone.trigger_profile or {}), COURT_ALLIES: [str(value) for value in chosen]}
    named = [engine.state.actors[str(value)].display_name for value in chosen if str(value) in engine.state.actors]
    note(engine, ctx.source, maker,
         "Court of the Crawling Fever: " + (", ".join(named) + (" gain" if len(named) != 1 else " gains")
                                             + " its benefits while it lasts." if named else "no ally joins it."),
         tuple(str(value) for value in chosen))


@hook("choice_reactors")
def court_choice_reactors(engine: Any) -> tuple[str, ...]:
    """The Court of the Crawling Fever's makers, for the service's AI-step probe: a player playing the maker is
    asked which allies join the Court even when the table is stepping the fight itself. An AI maker answers the
    same question automatically (``choose_court_allies``), and a fight with no active Court enrols nobody."""
    return tuple(sorted({zone.owner_id for zone in _zones_of(engine, CRAWLING)
                         if zone.owner_id in engine.state.actors}))


@hook("damage_defenses")
def court_resistance(engine: Any, target: Any, damage_type: Any, typed: Any, source_actor_id: Any) -> list[dict[str, Any]] | None:
    """Court of the Crawling Fever: "You and allies you choose gain ... Resistance to Poison and Necrotic
    damage caused by Disease talents".

    Two printed conditions, both read off the packet itself: the damage must come from a Disease ability (never
    from the attacker's character build), and the beneficiary must be the Court's maker or an ally the maker
    chose. An enemy's Poison, and a Disease cultivator's unrelated Poison or Death damage, land in full.
    """
    kind = str(damage_type or "").upper()
    if kind not in ("POISON", "NECROTIC") or target is None or not target.active:
        return None
    if not caused_by_disease(engine, typed) or not court_covers(engine, target):
        return None
    return [{"kind": "resistance", "damage_types": [kind]}]


@hook("damage_defenses")
def quarantine_ward_resistance(engine: Any, target: Any, damage_type: Any, typed: Any,
                               source_actor_id: Any) -> list[dict[str, Any]] | None:
    """Quarantine Ward protects only its selected creatures, while they remain inside, from Disease damage."""
    kind = str(damage_type or "").upper()
    if kind not in ("POISON", "NECROTIC") or target is None or not target.active or not caused_by_disease(engine, typed):
        return None
    target_id = str(target.entity_id)
    if any(target_id in {str(value) for value in ((zone.trigger_profile or {}).get(QUARANTINE_WARD_STATE) or {}).get("selected") or []}
           and _zone_contains(engine, zone, target) for zone in _ward_zones(engine)):
        return [{"kind": "resistance", "damage_types": [kind]}]
    return None


@hook("teleport_gate")
def quarantine_ward_teleport(ctx: Any, start: Any, destination: Any) -> bool | None:
    """A token-bearing creature must pass the Ward owner's Charisma save to teleport outside its area."""
    mover = ctx.actor
    if not any(tokens(ctx.engine, owner, mover) for owner in ctx.engine.state.actors.values()):
        return None
    for zone in _ward_zones(ctx.engine):
        if not _zone_contains(ctx.engine, zone, mover, start) or _zone_contains(ctx.engine, zone, mover, destination):
            continue
        ward_owner = ctx.engine.state.actors.get(zone.owner_id)
        ward = (zone.trigger_profile or {}).get(QUARANTINE_WARD_STATE) or {}
        dc = int(ward.get("save_dc") or ((zone.trigger_profile or {}).get("numbers") or {}).get("save_dc") or 10)
        action = ctx.engine.action_catalog.get(str(ctx.source))
        trigger_name = str(getattr(action, "display_name", "") or "the teleport")
        roll = ctx.engine._roll_save(mover, "CHA", dc, zone.source_definition_id,
                                     roll_context={"source_actor_id": zone.owner_id, "named": ["Quarantine Ward"]})
        success = roll is not None and int(roll.total) >= dc
        name = ward_owner.display_name if ward_owner is not None else "the ward's maker"
        note(ctx.engine, zone.source_definition_id, ward_owner or mover,
             f"Quarantine Ward: {mover.display_name} {'succeeds' if success else 'fails'} the Charisma save against "
             f"{trigger_name} "
             f"and {name}'s ward (DC {dc}); "
             f"{'the teleport succeeds' if success else 'the teleport fails and the creature stays inside'}.", (mover,))
        if not success:
            return False
    return None


@hook("defense_description")
def court_resistance_description(engine: Any, target: Any) -> list[dict[str, Any]] | None:
    """Court of the Crawling Fever's Resistance to Poison and Necrotic damage, as the Defences card names it.

    The Court membership gate is the same ``court_covers`` the damage hook reads, so the card lists the
    Resistance only for the Court's maker and the allies it chose. The other printed half is about the
    damage's own origin, which the card has no packet to read, so it reads as a plain qualifier. Pure."""
    if target is None or not target.active or not court_covers(engine, target):
        return None
    covering = _courts_covering(engine, target)
    feature_id = str(covering[0][0].source_definition_id) if covering else None
    return [{"feature_id": feature_id, "damage_types": ["POISON", "NECROTIC"],
             "note": "only from damage caused by Disease abilities"}]


# ------------------------------------------------------------------------------------------------------------ turn starts
@hook("turn_start")
def disease_turn_start(engine: Any, actor: Any) -> None:
    if not actor.active:
        return
    from .rider_support import remove_instance
    from .suppressed_effects import restore
    for holder in engine.state.actors.values():
        for iid, condition in list(holder.conditions.items()):
            if condition.condition_id != "condition:typed.disease_sickened_suppressed" or condition.source_actor_id != actor.entity_id:
                continue
            remove_instance(engine, holder, iid, condition.source_definition_id)
            for kept in (condition.data or {}).get("kept", []):
                restore(engine, holder, kept["original"], kept["lifetime"])
    _body_grapplers(engine, actor)
    _containment_cleanse(engine, actor)
    _virulent_presence(engine, actor)
    _spreading(engine, actor)


def _body_grapplers(engine: Any, actor: Any) -> None:
    """Plague-Bearing Body: a creature Grappling the holder gains one Contagion Token at the start of its turn."""
    for holder in engine.state.actors.values():
        if holder is actor or not holder.active or not _active(holder, BODY):
            continue
        if any(c.condition_id == "condition:typed.grappled" and c.source_actor_id == actor.entity_id for c in holder.conditions.values()):
            add_tokens(engine, holder, actor, 1, f"passive:{BODY}")
            note(engine, f"passive:{BODY}", holder, f"{actor.display_name} gains a Contagion Token from grappling {holder.display_name}.", (actor.entity_id,))


def _containment_cleanse(engine: Any, actor: Any) -> None:
    """Containment Mode (and the Court's chosen allies): "Whenever a chosen creature starts its turn inside the veil, it may remove one Contagion Token
    from itself." The affected creature may decline or select which caster's token to remove."""
    from ..typed_executor import condition_rules

    if not (court_covers(engine, actor) or any(row.get("disease_containment") for row in condition_rules(actor))):
        return  # "the ability to remove one of your Contagion Tokens" (the Court's chosen allies) / Containment's chosen creatures
    for owner in engine.state.actors.values():
        if owner.team_id != actor.team_id and tokens(engine, owner, actor) > 0:
            from .rider_choices import pick
            owners = [o for o in engine.state.actors.values() if tokens(engine, o, actor) > 0]
            chosen = pick(engine, actor, "disease_containment", "Containment", [o.entity_id for o in owners],
                          labels={o.entity_id: f"Remove one of {o.display_name}'s Contagion Tokens" for o in owners},
                          subject=actor, trigger=f"{actor.display_name} starts its turn inside containment", preferred=[owner.entity_id])
            if not chosen:
                return
            owner = engine.state.actors[chosen[0]]
            spend_token(engine, owner, actor, "system:disease.containment")
            note(engine, "system:disease.containment", actor, f"{actor.display_name} sheds one Contagion Token.")
            return


VIRULENT_MENU = "disease_virulent_presence"


def _virulent_presence(engine: Any, actor: Any) -> None:
    from . import menus
    from .rider_choices import pick, intent_for
    from ..typed_executor import Context, run_effects

    for sovereign in engine.state.actors.values():
        if not sovereign.active or sovereign.team_id == actor.team_id or not _active(sovereign, SOVEREIGN):
            continue
        if engine.grid.distance_ft(sovereign.position, actor.position) > 20:
            continue
        action = engine.action_catalog.get(next((a for a in sovereign.action_ids if SOVEREIGN in a), ""))
        if action is None:
            continue
        picked = pick(engine, sovereign, VIRULENT_MENU, "Virulent Presence (Disease)",
                      ["4d8 damage", "Sickened", "Contagion Token", "No Reactions", "Healing halved"],
                      subject=actor, trigger=f"{actor.display_name} starts its turn", optional=False,
                      preferred=menus.picks(engine, sovereign, VIRULENT_MENU) or ["4d8 damage"])[0]
        fail = {"4d8 damage": [{"type": "damage", "applies_to": "target", "dice": {"count": 4, "sides": 8}, "damage_types": ["necrotic", "poison", "psychic"]}],
                "Sickened": [{"type": "condition", "applies_to": "target", "condition": "sickened", "expires_on": "START_OF_SOURCE_NEXT_TURN"}],
                "Contagion Token": [{"type": "disease_tokens", "applies_to": "target", "count": 1}],
                "No Reactions": [{"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN"}],
                "Healing halved": [{"type": "healing_reduction", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN",
                                    "evidence": "healing the enemy receives is halved until the start of your next turn"}]}.get(picked, [])
        typed = dict((action.parameters or {}).get("typed") or {})
        note(engine, f"passive:{SOVEREIGN}", sovereign, f"Virulent Presence: {actor.display_name} starts its turn near {sovereign.display_name}.", (actor.entity_id,))
        run_effects(Context(engine, sovereign, action, intent_for(engine), typed, [actor], actor, {}),
                    [{"type": "save", "ability": "con", "on_fail": fail, "on_success": [
                        {"type": "healing_reduction", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN",
                         "evidence": "Healing the enemy receives is reduced by your Proficiency Bonus until the start of your next turn."}]}])


def _spreading(engine: Any, bearer: Any) -> None:
    from .. import typed_reactions
    from .rider_support import cp_pool as _cp_pool
    from ..typed_executor import Context, run_effects
    from .rider_choices import pick, intent_for

    for owner in engine.state.actors.values():
        if not owner.active or tokens(engine, owner, bearer) <= 0:
            continue
        if not any(SPREADING in a for a in owner.action_ids) and not any(str(r.get("feature_id") or "").startswith(SPREADING)
                                                                          for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(owner.entity_id, [])):
            continue
        key = f"disease_round_spreading:{engine.state.round_number}"
        pool = _cp_pool(owner)
        if owner.turn_flags.get(key) or not typed_reactions._can_react(engine, owner) or pool is None or owner.resources.get(pool, 0) < 2:
            continue
        near = sorted([other for other in engine.state.actors.values() if other.active and other is not bearer
                       and engine.grid.distance_ft(other.position, bearer.position) <= 10
                       and not other.turn_flags.get(f"disease_spread_immune:{owner.entity_id}")],
                      key=lambda o: (o.team_id == owner.team_id, tokens(engine, owner, o), o.entity_id))
        if not near:
            continue
        chosen = pick(engine, owner, "disease_spreading", "Spreading Infection", [o.entity_id for o in near],
                      labels={o.entity_id: f"{o.display_name} ({'an ally' if o.team_id == owner.team_id else 'an enemy'}, Reaction, 2 CP)"
                              for o in near}, subject=bearer,
                      trigger=f"{bearer.display_name} starts its turn", preferred=[near[0].entity_id])
        if not chosen:
            continue
        target = engine.state.actors[chosen[0]]
        with activation(engine, owner, f"reaction:{SPREADING}"):
            owner.turn_flags[key] = True
            owner.reaction_available = False
            engine._spend_resource(owner, pool, 2, f"reaction:{SPREADING}")
            before = len(engine.events)
            action = next((engine.action_catalog[a] for a in owner.action_ids if a in engine.action_catalog), None)
            run_effects(Context(engine, owner, action, intent_for(engine), {"numbers": {"save_dc": _dc(engine, owner)}},
                                [target], target, {}),
                        [{"type": "save", "ability": "con", "on_fail": [{"type": "disease_tokens",
                          "applies_to": "target", "count": 1, "spread_origin_id": bearer.entity_id}],
                          "on_success": []}])
            rolled = next((e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED"), None)
            if rolled is not None and (rolled.payload or {}).get("success"):
                target.turn_flags[f"disease_spread_immune:{owner.entity_id}"] = True  # until the start of its next turn (turn flags reset then)
            note(engine, f"reaction:{SPREADING}", owner, f"Spreading Infection: the fever reaches for {target.display_name}.", (target.entity_id,))


def _dc(engine: Any, actor: Any) -> int:
    from .needle import save_dc

    return save_dc(engine, actor)


# ------------------------------------------------------------------------------------------------------------ Sovereign damage
@hook("attack_damage")
def sovereign_sow(ctx: Any, dice: Any) -> Any | None:
    """Plague-Sovereign Incarnation: "your Sow the Fever Seed deals 6d10 Necrotic, Poison, or Psychic damage instead of its normal damage"."""
    from ..gate2_runtime_models import DiceSpec

    if isinstance(dice, DiceSpec) and SOW in str(ctx.source) and _active(ctx.actor, SOVEREIGN):
        return DiceSpec(count=6, sides=10, modifier=dice.modifier)
    return None


@hook("event")
def sovereign_tokens(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"creatures damaged by your Disease talents gain one Contagion Token once per turn" while the Incarnation lasts."""
    if event_type != "DAMAGE_COMMITTED" or engine.__dict__.get(_BUSY):
        return
    last = engine.events[-1] if engine.events else None
    owner = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if last is None or owner is None or not _active(owner, SOVEREIGN) or "disease" not in str(last.source_definition_id).lower():
        return
    if int((kwargs.get("payload") or {}).get("hp_damage") or 0) + int((kwargs.get("payload") or {}).get("temporary_hp_absorbed") or 0) <= 0:
        return
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        key = f"disease_sovereign_token:{target_id}"
        if target is None or target.team_id == owner.team_id or owner.turn_flags.get(key):
            continue
        owner.turn_flags[key] = True
        add_tokens(engine, owner, target, 1, f"passive:{SOVEREIGN}")


# ------------------------------------------------------------------------------------------------------------ Epidemic Surge, Eruption
@effect("disease_surge")
def surge(ctx: Any, eff: dict[str, Any]) -> None:
    """Epidemic Surge: choose up to your Proficiency Bonus creatures bearing your Contagion Tokens within 90 feet:
    one token spent from each; each makes a Constitution save (3d8, 4d8 at Nascent Soul, and Sickened; half and not Sickened)."""
    from ..typed_executor import Context, run_effects

    engine, owner = ctx.engine, ctx.actor
    bearers = [ctx.target] if ctx.target is not None and tokens(engine, owner, ctx.target) > 0 else []
    bearers += sorted([other for other in engine.state.actors.values() if other.active and other not in bearers and tokens(engine, owner, other) > 0
                       and engine.grid.distance_ft(owner.position, other.position) <= int(eff.get("range_ft") or 90)],
                      key=lambda o: (engine.grid.distance_ft(owner.position, o.position), o.entity_id))
    from .rider_choices import pick
    selected = pick(engine, owner, "disease_surge", "Epidemic Surge", [b.entity_id for b in bearers],
                    labels={b.entity_id: f"Spend a token and affect {b.display_name}" for b in bearers},
                    subject=ctx.target or owner, trigger=ctx.action.display_name,
                    preferred=[b.entity_id for b in bearers[:int(owner.proficiency_bonus or 2)]],
                    maximum=int(owner.proficiency_bonus or 2), intent=ctx.intent)
    chosen = [engine.state.actors[aid] for aid in selected]
    for bearer in chosen:
        spend_token(engine, owner, bearer, ctx.source)
    if chosen:
        run_effects(Context(engine, owner, ctx.action, ctx.intent, ctx.typed, chosen, None, ctx.damage_cache), list(eff.get("effects") or []))


@hook("after_save")
def eruption_tokens(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """Plague Eruption: a failed save by a creature bearing your token spends one for an additional 2d6 (3d6 at Nascent Soul)."""
    if not failed or subject is None or ERUPTION not in str(ctx.source) or tokens(ctx.engine, ctx.actor, subject) <= 0:
        return
    from ..gate2_runtime_models import DiceSpec
    from ..typed_executor import _deal

    from .rider_choices import pick
    if not pick(ctx.engine, ctx.actor, "disease_eruption_token", "Plague Eruption", ["spend"],
                labels={"spend": f"Spend one Contagion Token on {subject.display_name}"},
                subject=subject, trigger=f"{ctx.action.display_name}: failed {ability.upper()} save", intent=ctx.intent):
        return
    spend_token(ctx.engine, ctx.actor, subject, ctx.source)
    cl = int(ctx.numbers.get("cl") or 1)
    roll = ctx.engine.roller.roll(DiceSpec(count=3 if cl >= 15 else 2, sides=6, modifier=0), actor_id=ctx.actor.entity_id, reason=f"DAMAGE:{ctx.source}:token")
    ctx.engine._record_roll(roll)
    ctx.engine.__dict__["_disease_eruption_extra"] = (subject.entity_id, int(roll.total))
    _deal(ctx, subject, int(roll.total), "NECROTIC")


# ------------------------------------------------------------------------------------------------------------ Plague Cloud
def _cloud(ctx: Any) -> dict[str, Any] | None:
    """The compiled ability row when this use or save is a Plague Cloud Outbreak veil, else None (inert for anyone else:
    only a character who owns the talent compiles that modifier, and only the Outbreak Mode option carries its label)."""
    typed = ((getattr(getattr(ctx, "action", None), "parameters", None) or {}).get("typed") or {})
    if (typed.get("modifier") or {}).get("id") != CLOUD or typed.get("option_of") != VEIL:
        return None
    return typed if typed.get("option_label") == OUTBREAK else None


def _veil_now(ctx: Any) -> Any | None:
    """The veil this activation just made: creation events keep the order of one activation, the zone ids do not."""
    from .. import zones

    mine = {zone.zone_id: zone for zone in zones.typed_zones(ctx.engine)
            if zone.active and zone.owner_id == ctx.actor.entity_id and zone.source_definition_id == ctx.source}
    if not mine:
        return None
    created = next((event for event in reversed(ctx.engine.events)
                    if event.event_type == "ZONE_CREATED" and event.source_definition_id == ctx.source
                    and event.actor_id == ctx.actor.entity_id
                    and (ctx.intent is None or event.trigger_or_intent_id == getattr(ctx.intent, "intent_id", None))
                    and ((event.payload or {}).get("zone") or {}).get("zone_id") in mine), None)
    return mine.get(((created.payload or {}).get("zone") or {}).get("zone_id")) if created is not None else None


def _record(engine: Any, zone: Any) -> None:
    """Re-record the zone after changing it (ZONE_CREATED, as combat/zones.py does), so a saved fight replays the change."""
    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id, payload={"zone": zone.model_dump(mode="json")})


@hook("technique_used")
def cloud_obscures(ctx: Any) -> None:
    """"The area becomes lightly obscured": the Outbreak veil this Plague Cloud paid for starts lightly obscured."""
    if _cloud(ctx) is None:
        return
    zone = _veil_now(ctx)
    if zone is None or (zone.trigger_profile or {}).get("obscured"):
        return
    zone.trigger_profile = {**(zone.trigger_profile or {}), "obscured": "light"}
    _record(ctx.engine, zone)
    note(ctx.engine, ctx.source, ctx.actor, "Plague Cloud (2 extra CP): the veil's area is lightly obscured for as long as the veil lasts. "
         "Anyone standing in it is hard to see, and hiding there is easier.")


@hook("after_save_resolved")
def cloud_failed_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """"enemies that fail their saving throw against the veil also gain one Contagion Token"; at Core Formation those enemies
    "become unable to regain more than half the normal Hit Points from healing until the start of your next turn"."""
    from .. import zones

    if not failed or subject is None or subject.team_id == ctx.actor.team_id or _cloud(ctx) is None:
        return
    veil = next((zone for zone in zones.typed_zones(ctx.engine)
                 if zone.active and zone.owner_id == ctx.actor.entity_id
                 and zone.source_definition_id == str(getattr(ctx.action, "source_definition_id", ""))
                 and _inside(zone, subject)), None)
    if veil is None:  # some other save this ability also carries
        return
    engine = ctx.engine
    add_tokens(engine, ctx.actor, subject, 1, ctx.source)
    note(engine, ctx.source, ctx.actor, f"Plague Cloud: {subject.display_name} fails the veil's {ability.upper()} save and gains one Contagion Token.", (subject.entity_id,))
    if _core_formation(ctx.numbers.get("cl")):
        # "unable to regain more than half the normal Hit Points from healing until the start of your next turn": the
        # engine's one healing-halved representation -- a condition carrying the ``healing_halved`` rule, as
        # combat/ext/fate_riders.py and combat/zones.py's area conditions do. ``_apply_condition`` names the applier, so
        # the cap ends at the start of the veil-maker's next turn; a ``healing_reduction`` modifier would name whichever
        # creature the save resolved on (``_add_modifier`` stamps the current actor), here the enemy.
        engine._apply_condition(subject, HEALING_HALFED, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": f"Plague Cloud: {subject.display_name} regains only half the Hit Points it would "
                                               f"normally regain from healing, until the start of {ctx.actor.display_name}'s next turn.",
                                      "rule": {"healing_halved": True}})
        note(engine, ctx.source, ctx.actor, f"Plague Cloud: until the start of {ctx.actor.display_name}'s next turn, {subject.display_name} "
             f"regains only half the Hit Points it would normally regain from healing.")


def _core_formation(cl: Any) -> bool:
    """"At Core Formation": the veil-maker's Realm is Core Formation or better, read off the veil's own die-by-Realm bands."""
    from factory_authoring.typed_mechanics import dice_for_cl

    dice = dice_for_cl([list(row) for row in CLOUD_DICE], int(cl or 1)) or {}
    return int(dice.get("count") or 1) >= CLOUD_DICE[CORE_FORMATION_BAND][2]


# ------------------------------------------------------------------------------------------------------------ Cultivation Breath
@hook("event")
def breath_infection(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "RESOURCE_SPENT" or engine.__dict__.get(_BUSY):
        return
    from ..typed_executor import CP_POOLS

    payload = kwargs.get("payload") or {}
    spender = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if spender is None or payload.get("resource_id") not in CP_POOLS:
        return
    from .. import typed_reactions
    from ..typed_executor import Context, run_effects
    from .rider_choices import pick, intent_for, trigger_name

    for owner in engine.state.actors.values():
        if not owner.active or owner.team_id == spender.team_id or tokens(engine, owner, spender) < 2:
            continue
        if not any(BREATH in str(r.get("feature_id") or "") for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(owner.entity_id, [])):
            continue
        if not typed_reactions._can_react(engine, owner):
            continue
        chosen = pick(engine, owner, "disease_breath", "Infection of the Cultivation Breath", ["infect"],
                      labels={"infect": "Use Reaction and spend one Contagion Token"}, subject=spender,
                      trigger=f"{spender.display_name} spends CP for {trigger_name(engine)}")
        if not chosen:
            continue
        with activation(engine, owner, f"reaction:{BREATH}"):
            owner.reaction_available = False
            engine.__dict__[_BUSY] = True
            try:
                spend_token(engine, owner, spender, f"reaction:{BREATH}")
            finally:
                engine.__dict__.pop(_BUSY, None)
            action = next((engine.action_catalog[a] for a in owner.action_ids if a in engine.action_catalog), None)
            note(engine, f"reaction:{BREATH}", owner, f"Infection of the Cultivation Breath: {spender.display_name}'s cultivation falters.", (spender.entity_id,))
            run_effects(Context(engine, owner, action, intent_for(engine), {"numbers": {"save_dc": _dc(engine, owner)}}, [spender], spender, {}),
                        [{"type": "save", "ability": "con",
                          "on_fail": [{"type": "condition", "applies_to": "target", "condition": "no_cp_regain", "expires_on": "START_OF_SOURCE_NEXT_TURN"},
                                      {"type": "disadvantage", "applies_to": "target", "on": "concentration saving throws", "expires_on": "START_OF_SOURCE_NEXT_TURN"}],
                          "on_success": [{"type": "condition", "applies_to": "target", "condition": "no_cp_regain", "expires_on": "START_OF_SOURCE_NEXT_TURN"}]}])
            return


# ------------------------------------------------------------------------------------------------------------ Purging Breath
@effect("disease_purge")
def purge(ctx: Any, eff: dict[str, Any]) -> None:
    """Purging Breath's choice: remove one Contagion Token; suppress Sickened until the start of your next turn; Advantage on the next save
    against Disease."""
    subject = ctx.target if ctx.target is not None else ctx.actor
    engine, which = ctx.engine, str(eff.get("choice") or "")
    if which == "token":
        for owner in engine.state.actors.values():
            if tokens(engine, owner, subject) > 0:
                spend_token(engine, owner, subject, ctx.source)
                return
    elif which == "sickened":
        from .rider_support import remove_instance
        from .suppressed_effects import lifetime
        kept = []
        for iid, condition in list(subject.conditions.items()):
            if condition.condition_id == "condition:typed.sickened":
                kept.append({"original": condition.model_dump(mode="json"), "lifetime": lifetime(engine, subject, condition)})
                remove_instance(engine, subject, iid, ctx.source)
        engine._apply_condition(subject, "condition:typed.disease_sickened_suppressed", ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "Purging Breath: Sickened suppressed", "kept": kept,
                                      "rule": {"condition_immunities": ["sickened"]}})
    elif which == "next_save":
        engine._apply_condition(subject, NEXT_SAVE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "Purging Breath: Advantage on the next save against Disease"})


@hook("condition_immune")
def sickened_suppressed(engine: Any, actor: Any, name: str) -> bool | None:
    if name == "sickened" and any(c.condition_id == "condition:typed.disease_sickened_suppressed" for c in actor.conditions.values()):
        return True
    return None


# ------------------------------------------------------------------------------------------------------------ Living Plague
PLAGUE = "tianxia.talent.disease.living_plague"


def _summoner(engine: Any, creature: Any) -> Any | None:
    record = getattr(creature, "summon", None) or {}
    return engine.state.actors.get(str(record.get("owner") or "")) if record.get("group") == "living_plague" else None


@hook("event")
def living_plague(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Living Plague (a summon: combat/rules/summons.json "living_plague"): "Infected Strike ... On a hit, the target ... gains one Contagion Token"
    (the summoner's); "Contagious Body: When the Living Plague is destroyed, creatures of your choice within 5 feet make Constitution saving
    throws. On a failed save, a creature gains one Contagion Token." (the summoner's enemies within 5 feet)"""
    if engine.__dict__.get(_BUSY):
        return
    if event_type == "DAMAGE_COMMITTED":
        plague = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
        owner = _summoner(engine, plague) if plague is not None else None
        if owner is None or int((kwargs.get("payload") or {}).get("hp_damage") or 0) + int((kwargs.get("payload") or {}).get("temporary_hp_absorbed") or 0) <= 0:
            return
        for target_id in kwargs.get("target_ids") or ():
            target = engine.state.actors.get(target_id)
            if target is not None and target.team_id != owner.team_id:
                add_tokens(engine, owner, target, 1, f"passive:{PLAGUE}", origin=plague)
    elif event_type in ("ENTITY_DEFEATED", "ACTOR_DEFEATED"):
        plague = engine.state.actors.get(str(kwargs.get("actor_id") or next(iter(kwargs.get("target_ids") or ()), "")))
        owner = _summoner(engine, plague) if plague is not None else None
        if owner is None:
            return
        from ..typed_executor import Context, run_effects

        near = [other for other in engine.state.actors.values() if other.active and other.team_id != owner.team_id
                and engine.grid.distance_ft(other.position, plague.position) <= 5]
        if not near:
            return
        action = next((engine.action_catalog[a] for a in owner.action_ids if PLAGUE in a), None) or \
            next((engine.action_catalog[a] for a in owner.action_ids if a in engine.action_catalog), None)
        note(engine, f"passive:{PLAGUE}", owner, "Contagious Body: the Living Plague bursts.", tuple(n.entity_id for n in near))
        run_effects(Context(engine, owner, action, getattr(engine, "_active_intent", None), {"numbers": {"save_dc": _dc(engine, owner)}}, near, None, {}),
                    [{"type": "save", "ability": "con", "on_fail": [{"type": "disease_tokens", "applies_to": "target",
                      "count": 1, "spread_origin_id": plague.entity_id}], "on_success": []}])


@hook("compile_block")
def disease_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    return [{**row, "block": "disease", "kind": spec.get("kind")}] if block == "disease" else None


WOUND = "tianxia.talent.disease.contaminated_wound"


@hook("compile_block")
def wound_block(block, spec, row, numbers):
    if block == "disease_wound":
        return [{**row, "block": block, "policy": int(spec.get("policy") or 0), "numbers": {key: numbers[key] for key in ("cl", "pb", "key_mod")}}]
    return None


@hook("choice_reactors")
def wound_choice_reactors(engine: Any) -> tuple[str, ...]:
    """Enroll sealed Wound owners for off-turn choices during the AI-step probe.

    The service applies each owner's control mode: manual owners are asked;
    automatic owners answer through their controller. Policy-1 rows already
    saved before this hook are covered without recompiling their characters.
    Older bundles without the replacement Wound policy stay inert here.
    """
    return tuple(sorted(actor_id for actor_id, rows in
                        (getattr(engine, "typed_passive_rows", {}) or {}).items()
                        if actor_id in engine.state.actors and any(
                            row.get("block") == "disease_wound"
                            and row.get("feature_id") == WOUND and row.get("policy") == 1
                            for row in rows)))


@hook("compile_passives")
def wound_numbers(passives, info):
    return [{**row, "numbers": dict(info["numbers"])}
            if row.get("block") == "disease_wound" and row.get("feature_id") == WOUND
            else row for row in passives]


@hook("damage_dealt")
def contaminated_wound(ctx, target, amount):
    """One optional rider on actual Sow/weapon damage, not an unrelated spell."""
    from .weapon_hits import is_weapon_hit
    from .choice_costs import payable
    from .d20_rewrite import pool_id
    from .needle import ask, checkpoint_id, CHOICE
    from ..typed_executor import run_effects

    row = next((r for r in (getattr(ctx.engine, "typed_passive_rows", {}) or {}).get(ctx.actor.entity_id, [])
                if r.get("block") == "disease_wound" and r.get("feature_id") == WOUND and r.get("policy") == 1), None)
    if row is None or target is None or not target.active or int(amount or 0) <= 0 or ctx.source == WOUND:
        return
    if ctx.typed.get("source") != SOW and not is_weapon_hit(ctx, ctx.attack_effect):
        return
    stamp = int(ctx.engine.state.round_number) * 1000 + int(ctx.engine.state.current_slot_index)
    if ctx.actor.turn_flags.get("disease_wound_turn") == stamp:
        return
    pool = pool_id(ctx.actor, "cp")
    payment = payable(ctx.actor, pool, 1) if pool else None
    if payment is None:
        return
    numbers = row["numbers"]
    cl = int(numbers.get("cl") or 1)
    count = 3 if cl >= 15 else 2 if cl >= 10 else 1
    pb = int(numbers.get("pb") or 2)
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "contaminated_wound", target.entity_id),
                 ctx.actor, CHOICE + "contaminated_wound", ["WOUND"], allow_decline=True,
                 target_id=target.entity_id, name="Contaminated Wound", feature_id=WOUND, payment=payment,
                 labels={"WOUND": f"Pay {payment.quote()}: +{count}d6 Necrotic or Poison damage; healing reduced by {pb}"},
                 prompt=f"Contaminated Wound: {ctx.action.display_name} damaged {target.display_name}. "
                        f"Spend {payment.quote()} for {count}d6 extra Necrotic or Poison damage? "
                        f"The target makes a Constitution save; failure adds one of your Contagion Tokens "
                        f"(a disease marker used by your talents). On either result, healing it receives is "
                        f"reduced by {pb} until the start of your next turn. Once per turn; declining keeps the use.")
    if not picked:
        return
    ctx.actor.turn_flags["disease_wound_turn"] = stamp
    payment.pay(ctx.engine, ctx.actor, WOUND)
    child = ctx.on_hit_context(target, damage_cache={}, typed={"source": WOUND, "sphere": DISEASE_SPHERE,
                    "numbers": numbers, "duration": {"kind": "instant"}}, effect_source=WOUND)
    run_effects(child, [
        {"type": "damage", "applies_to": "target", "dice": {"count": count, "sides": 6},
         "damage_types": ["necrotic", "poison"]},
        {"type": "save", "ability": "con", "applies_to": "target", "on_fail": [
            {"type": "disease_tokens", "applies_to": "target", "count": 1}], "on_success": []},
        {"type": "healing_reduction", "applies_to": "target", "duration": "until_start_of_your_next_turn",
         "evidence": "Healing it receives is reduced by your Proficiency Bonus."}])
