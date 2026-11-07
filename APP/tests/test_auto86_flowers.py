"""Flowers sphere (AUTO86, review fixes AUTO86f1): the printed words of the Flowers talents are the table's own, not the
GM's.

Every test here is at the table or service level (a real TabletopService commit, then a reload from disk), because that is
where the Flowers rules used to stop: a Drowsy condition that was never applied, a damage type the owner was never asked
for, a first Petal Dart that rolled straight, and three GM lines about Concentration that the table had already settled.
The printed text is authority/typed_mechanics/rules_text.json (TAL_FLOWERS_*, FLOWERS_BASE_FRAGRANCE); the answers live in
APP/combat/ext/flowers_sphere.py, the shared Drowsy condition (combat/ext/dreams_core.py), the shared "keep it without
Concentration" augment (combat/ext/persist_augment.py) and the reviewed rows of
APP/authority/typed_mechanics/reviewed_final.d/.

AUTO86f1 (the pre-merge review) added the regressions AUTO86's own tests could not see:
  * the Drowsy a Soporific Pollen leaves is Flowers' own list -- Speed -10, no Reactions, Disadvantage on Wisdom (Perception)
    checks, and no Concentration penalty -- and it ends at the start of the *creature's* next turn;
  * Fragrant Mirage is read from the caster's own rows and only while its own Mirage is up;
  * the first Petal Dart of a turn is spent wherever the caster stands;
  * an Opportunity Attack made against a Mirage wearer is rolled with Disadvantage;
  * the 2 CP Lingering Fragrance augment paid after the Fragrance exists is a real button that outlives Concentration;
  * the printed damage-type prompt names the creature the strike is made against.
"""
import json

from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import script, sheet
from tests.hunt12_support import ME, FOE, candidate, fight, hit_dice, reload, send

FRAGRANCE = "FLOWERS_BASE_FRAGRANCE"
POLLEN = "TAL_FLOWERS_SOPORIFIC_POLLEN"
DART = "TAL_FLOWERS_PETAL_DART"
MIRAGE = "TAL_FLOWERS_FRAGRANT_MIRAGE"
STORM = "TAL_FLOWERS_THOUSAND_PETAL_STORM"
LINGERING = "TAL_FLOWERS_LINGERING_FRAGRANCE"
STAMINA = "resource:core.stamina"


def flowers_fight(tmp_path, mids, *, cl=18, dc=18, foe_mids=(), ask_reactions=True, **overrides):
    """The same table a hunt-12 fight builds (a real TabletopService over a compiled pair), with the attack bonus the
    tests need so a printed attack actually lands. ``foe_mids`` gives the other fighter talents of its own (the
    mixed-fighters case Fragrant Mirage's ownership reading needs); ``ask_reactions=False`` lets this fighter's own
    Reactions resolve by themselves, so the other fighter's walk past it does not stop for a question."""
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT
    from tests.test_lock2_persistence import act

    doc = sheet(list(mids), cl=cl, dc=dc, primary="Stamina", score=18)
    doc["ability_scores_and_statistics"].update(overrides)
    foe = sheet(list(foe_mids), cl=cl, primary="Stamina")
    foe["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1000
    bundles = [compile_character(doc, actor_id=ME, **({"reaction_plan": {"ask": True}} if ask_reactions else {})),
               compile_character(foe, actor_id=FOE)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [ME, FOE], {ME: "team:factory", FOE: "team:opponents"},
        {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [FOE],
        control_modes={ME: "MANUAL", FOE: "MANUAL"}, match_seed="AUTO86",
        display_name="AUTO86 Flowers regression", maximum_rounds=20)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != ME:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid


# ================================================================================================================ small real-fight helpers
def _engine(combat, mid):
    return combat._load_session(mid).engine


def _square(candidate_) -> tuple[int, int]:
    x, y = candidate_.display_name.rsplit(" ", 1)[-1].split(",")
    return int(x), int(y)


def _commit_step(combat, table, mid, chosen):
    """Commit a step, declining any Reaction this fighter's own "Ask me" plan raises on the way (the other fighter
    walking out of its reach), so a test can move either fighter freely."""
    result = send(combat, table, mid, chosen)
    for _ in range(4):
        if result["status"] != "REACTION_REQUIRED":
            return result["status"]
        prompt = result["reaction"]
        if prompt.get("choice"):
            return result["status"]          # a real choice (a strike's damage type) is not this helper's to answer
        result = send(combat, table, mid, chosen, [{**prompt["context"], "selection": "DECLINE"}])
    return result["status"]


def _walk(combat, table, mid, x, y, *, limit=8):
    """Walk whoever's turn it is to that square, one real 5-foot step at a time (the table's own move candidates)."""
    for _ in range(limit):
        engine = _engine(combat, mid)
        actor = engine.state.actors[engine.state.current_actor_id]
        here = (actor.position.x, actor.position.y)
        if here == (x, y):
            return True
        gap = lambda candidate_: max(abs(a - b) for a, b in zip(_square(candidate_), (x, y)))  # noqa: E731
        options = sorted((c for c in engine.legal_candidates()
                          if c.display_name.startswith("Move to ")
                          and max(abs(a - b) for a, b in zip(_square(c), here)) == 1), key=gap)
        if not options or gap(options[0]) >= max(abs(a - b) for a, b in zip(here, (x, y))):
            return False
        assert _commit_step(combat, table, mid, options[0]) == "COMMITTED", options[0].display_name
    return False


def next_turn(combat, table, mid):
    """Hand the turn over (this caster's own action may still be spent) and stop on its next turn."""
    if _engine(combat, mid).state.current_actor_id == ME:
        end_turn(combat, table, mid)
    while _engine(combat, mid).state.current_actor_id != ME:
        end_turn(combat, table, mid)
    return _engine(combat, mid)


def end_turn(combat, table, mid):
    assert send(combat, table, mid, candidate(combat, mid, lambda c: c.kind.value == "END_TURN"))["status"] == "COMMITTED"


def failing_save(monkeypatch, roll=3):
    """Every saving throw this engine rolls is a failure (a printed save the creature fails)."""
    original = Gate4ControllerEngine._roll_save

    def roll_save(engine, *args, **kwargs):
        script(engine, [roll])
        return original(engine, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, "_roll_save", roll_save)


def shape(combat, table, mid, label):
    assert send(combat, table, mid, candidate(combat, mid, lambda c: c.display_name == label))["status"] == "COMMITTED"


def cast(combat, table, mid, prefix):
    chosen = candidate(combat, mid, lambda c: c.display_name.startswith(prefix))
    assert send(combat, table, mid, chosen)["status"] == "COMMITTED", prefix
    return chosen


def at(combat, mid, action_name, x, y):
    """That action aimed at that square: "Fragrance at 3,6", never "Fragrance + Lingering Fragrance at 3,6"."""
    return candidate(combat, mid, lambda c: c.display_name.startswith(f"{action_name} at {x},{y}"))


def dart(combat, table, mid, answer="SLASHING"):
    """Make this character's Petal Dart, answering the printed damage-type question the way its owner would."""
    chosen = candidate(combat, mid, lambda c: c.display_name.startswith("Petal Dart"))
    result = send(combat, table, mid, chosen)
    if result["status"] == "REACTION_REQUIRED":
        assert result["reaction"]["context"]["reaction_source_id"].endswith("petal_dart_damage_type"), result["reaction"]
        result = send(combat, table, mid, chosen, [{**result["reaction"]["context"], "selection": "USE", "option_ids": [answer]}])
    assert result["status"] == "COMMITTED", result
    return result


def _dart_advantage(engine, since=0):
    """The Advantage the engine installed on this character's own Petal Dart strikes after event ``since``."""
    return "ADVANTAGE" in [e.payload.get("value") for e in engine.events
                           if e.event_type == "MODIFIER_APPLIED" and e.payload.get("target_field") == "attack_mode"
                           and DART in str(e.payload.get("modifier_id")) and int(e.sequence) > int(since)]


def _fragrance_at_me(combat, table, mid):
    me = _engine(combat, mid).state.actors[ME]
    assert send(combat, table, mid, at(combat, mid, "Fragrance", me.position.x, me.position.y))["status"] == "COMMITTED"


def _fragrance_zone(engine):
    return next(z for z in engine.state.zones.values() if (z.trigger_profile or {}).get("name") == "Fragrance")


def _inside_fragrance(engine, zone, actor):
    cells = {(c.x, c.y) for c in zone.affected_cells}
    return (actor.position.x, actor.position.y) in cells


def _mirage_conditions(engine, actor):
    return [c for c in actor.conditions.values()
            if c.source_definition_id.split(".")[-1] == MIRAGE and (c.data or {}).get("rule")]


def _dart_ctx(engine, actor, target):
    """A real attack Context for this fight's own Petal Dart action, as the executor builds it."""
    from combat.typed_executor import Context

    action = next(a for a in engine.action_catalog.values()
                  if str(((a.parameters or {}).get("typed") or {}).get("source") or "") == DART)
    return Context(engine, actor, action, None, dict((action.parameters or {}).get("typed") or {}), [target], target)


def flower_lines(document):
    """Every GM reminder line a compiled Flowers fighter would show, with the action that carries it."""
    out = []
    for action in document["action_catalog"]:
        typed = (action.get("parameters") or {}).get("typed") or {}
        for line in typed.get("riders") or []:
            out.append((action["display_name"], str(line)))
    return out


# ================================================================================================================ Soporific Pollen
def test_soporific_pollen_gives_the_printed_drowsy_until_the_creature_s_own_next_turn(tmp_path, monkeypatch):
    """"Failed Save: Become Drowsy until the start of its next turn. While Drowsy: Speed is reduced by 10 feet; cannot
    take Reactions; has Disadvantage on Wisdom (Perception) checks." The typing used to hand out the three consequences
    with no condition at all, and the shared Drowsy condition it moved to printed the Dreams core list instead: a
    Concentration penalty this talent does not grant, whose expiry followed the caster, and a Perception disadvantage that
    was only words. This reads the three printed consequences off the creature after a real commit and a reload."""
    from combat.ext import effect_durations
    from combat.typed_executor import check_modes, condition_rules
    from combat.typed_reactions import _can_react

    combat, table, mid = fight(tmp_path, [FRAGRANCE, POLLEN], dc=18)
    shape(combat, table, mid, "Shape Fragrance: Soporific Pollen")
    foe = _engine(combat, mid).state.actors[FOE]
    assert send(combat, table, mid, at(combat, mid, "Fragrance", foe.position.x, foe.position.y))["status"] == "COMMITTED"
    failing_save(monkeypatch)
    end_turn(combat, table, mid)

    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    drowsy = [c for c in foe.conditions.values() if c.condition_id == "condition:typed.drowsy"]
    assert len(drowsy) == 1, "the failed Constitution save inside the Fragrance leaves no Drowsy on the creature"
    # While Drowsy, the three printed consequences, each one read by the engine and not only printed on the pill:
    assert engine._effective_speed(foe) == foe.speed_ft - 10, engine._effective_speed(foe)
    assert not _can_react(engine, foe) and any(rule.get("no_reactions") for rule in condition_rules(foe))
    assert check_modes(foe, "WIS", "Perception", engine=engine) == {"DISADVANTAGE"}
    # ... and nothing else: this talent does not print a Concentration penalty.
    assert not [c for c in foe.conditions.values() if c.condition_id == "condition:typed.concentration_mode"]
    label = str((drowsy[0].data or {}).get("label") or "")
    assert "Speed -10" in label and "no Reactions" in label and "Perception" in label  # the printed While Drowsy list
    assert "Concentration" not in label, label
    assert drowsy[0].expires_on == effect_durations.token("start", FOE, foe.turns_started + 1), drowsy[0].expires_on
    assert drowsy[0].source_actor_id == ME
    # the trigger is the area the caster made, not the talent row
    assert any(e.event_type == "PASSIVE_TRIGGERED" and (e.payload or {}).get("trigger") == "Soporific Pollen"
               for e in engine.events)


def test_the_drowsy_from_pollen_ends_at_the_start_of_the_creature_s_own_next_turn(tmp_path, monkeypatch):
    """Its own turn is the clock the printed words name: once the affected creature is out of the Fragrance (so no new
    save lands on it), the Drowsy is gone when that creature starts its next turn."""
    combat, table, mid = fight(tmp_path, [FRAGRANCE, POLLEN], dc=18)
    shape(combat, table, mid, "Shape Fragrance: Soporific Pollen")
    foe = _engine(combat, mid).state.actors[FOE]
    assert send(combat, table, mid, at(combat, mid, "Fragrance", foe.position.x, foe.position.y))["status"] == "COMMITTED"
    failing_save(monkeypatch)
    end_turn(combat, table, mid)                      # the foe's turn starts inside and it fails the save

    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    assert [c for c in foe.conditions.values() if c.condition_id == "condition:typed.drowsy"]
    # every consequence of that save is timed by the creature that failed it, not by the caster: "until the start of
    # its next turn" is the affected creature's own turn
    from combat.ext import effect_durations

    turn = effect_durations.token("start", FOE, foe.turns_started + 1)
    assert [c.condition_id for c in foe.conditions.values()
            if c.source_definition_id.endswith(FRAGRANCE) and c.expires_on != turn] == []
    zone = _fragrance_zone(engine)
    cells = {(c.x, c.y) for c in zone.affected_cells}
    outside = [c for c in engine.legal_candidates()
               if c.display_name.startswith("Move to ") and _square(c) not in cells]
    assert _commit_step(combat, table, mid, outside[0]) == "COMMITTED"  # it walks out of the Fragrance
    engine = reload(tmp_path, mid)
    assert [c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == "condition:typed.drowsy"]

    end_turn(combat, table, mid)                      # that creature's own turn ends
    while _engine(combat, mid).state.current_actor_id != FOE:
        end_turn(combat, table, mid)                  # ... and its next turn starts
    engine = reload(tmp_path, mid)
    assert not [c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == "condition:typed.drowsy"]
    assert not [c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == "condition:typed.concentration_mode"]


def test_a_fragrance_without_soporific_pollen_leaves_no_drowsy(tmp_path, monkeypatch):
    """The condition belongs to the talent: a plain Fragrance (or one shaped as another Fragrance talent) must not
    hand out Drowsy."""
    combat, table, mid = fight(tmp_path, [FRAGRANCE], dc=18)
    foe = _engine(combat, mid).state.actors[FOE]
    assert send(combat, table, mid, at(combat, mid, "Fragrance", foe.position.x, foe.position.y))["status"] == "COMMITTED"
    failing_save(monkeypatch)
    end_turn(combat, table, mid)

    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == "condition:typed.drowsy" for c in engine.state.actors[FOE].conditions.values())


# ================================================================================================================ one Drowsy, and the consequences that belong to it
DREAMS_BASE = "DREAMS_BASE_DREAMSCAPE"
STAGGERING_BREAK = "tianxia.talent.destruction.staggering_break"
CONCENTRATION_SAVE = "SAVE:system:combat.concentration:CON"


def _scripted_saves(monkeypatch, value=3):
    """Every saving throw this engine rolls answers with ``value``; the returned list changes as the fight moves on."""
    original = Gate4ControllerEngine._roll_save
    answers = [value]

    def roll_save(engine, *args, **kwargs):
        script(engine, [answers[0]])
        return original(engine, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, "_roll_save", roll_save)
    return answers


def _drowsy_of(actor):
    return [c for c in actor.conditions.values() if c.condition_id == "condition:typed.drowsy"]


def _concentration_penalties(actor):
    return [c for c in actor.conditions.values() if c.condition_id == "condition:typed.concentration_mode"]


def _modes_of(actor):
    return [(c.data.get("rule") or {}).get("concentration_mode") for c in _concentration_penalties(actor)]


def _square_of(combat, mid, who):
    actor = _engine(combat, mid).state.actors[who]
    return actor.position.x, actor.position.y


def _concentration_saves(engine):
    return [e.payload or {} for e in engine.events
            if e.event_type == "SAVE_ROLLED" and str((e.payload or {}).get("reason") or "") == CONCENTRATION_SAVE]


def _pollen_round(combat, table, mid):
    """One Pollen round: shape the Fragrance as Soporific Pollen and lay it over the other fighter's square."""
    shape(combat, table, mid, "Shape Fragrance: Soporific Pollen")
    send(combat, table, mid, at(combat, mid, "Fragrance", *_square_of(combat, mid, FOE)))


def _dreams_drowsy(tmp_path, combat, table, mid):
    """The creature concentrates and this fighter seeds it with the Dreams core list, so it stands there Drowsy with
    that Drowsy's own Concentration penalty on it. Every step is a real committed table step, reloaded from disk.
    Returns the reloaded engine, the Drowsy, the penalty it recorded, and the creature's condition/modifier ids read
    at that moment."""
    send(combat, table, mid, at(combat, mid, "Dreamscape", *_square_of(combat, mid, FOE)))
    next_turn(combat, table, mid)
    cast(combat, table, mid, "Dream Seed")            # Drowsy Thought: the Dreams list, its penalty included
    engine = reload(tmp_path, mid)
    granted = _drowsy_of(engine.state.actors[FOE])
    assert len(granted) == 1 and "Concentration" in str((granted[0].data or {}).get("label") or ""), granted[0].data
    penalty = _concentration_penalties(engine.state.actors[FOE])
    assert _modes_of(engine.state.actors[FOE]) == ["DISADVANTAGE"], _modes_of(engine.state.actors[FOE])
    assert (granted[0].data or {}).get("consequences") == [c.instance_id for c in penalty], (
        "the Concentration penalty is recorded as a consequence of the Drowsy that granted it", granted[0].data)
    foe = engine.state.actors[FOE]
    before = {"conditions": set(foe.conditions), "modifiers": set(foe.modifiers),   # the last look before the swap
              "sequence": int(engine.state.event_sequence)}
    return engine, granted[0], penalty[0], before


def _dreams_then_pollen(tmp_path, combat, table, mid):
    """``_dreams_drowsy`` and then Pollen's Drowsy replacing that one on the creature's next turn -- the printed swap,
    committed and reloaded at every step. Returns the reloaded engine, the Drowsy that was replaced, the penalty that
    Drowsy granted, and the snapshot taken immediately before the replacement."""
    engine, granted, penalty, before = _dreams_drowsy(tmp_path, combat, table, mid)
    end_turn(combat, table, mid)                      # inside the Fragrance again: Pollen replaces that Drowsy
    engine = reload(tmp_path, mid)
    replaced = _drowsy_of(engine.state.actors[FOE])
    assert len(replaced) == 1
    label = str((replaced[0].data or {}).get("label") or "")
    assert "Perception" in label and "Concentration" not in label, label             # Pollen's own printed list
    assert not (replaced[0].data or {}).get("consequences"), "Pollen grants no extra consequence to carry"
    assert not _concentration_penalties(engine.state.actors[FOE]), (
        "the Concentration penalty of the Drowsy it replaced went with that Drowsy")
    return engine, granted, penalty, before


def _replaced_by_replacement(engine, since=0):
    """Every instance a Drowsy replacement removed after event ``since``, read off the events it recorded. ``since``
    matters: an engine's event log is the whole fight, and an earlier Pollen replacement in the same fight would
    otherwise be counted against the one under test."""
    return {(e.payload or {}).get("instance_id") for e in engine.events
            if e.event_type == "CONDITION_REMOVED" and (e.payload or {}).get("reason") == "DROWSY_REPLACED"
            and int(e.sequence) > int(since)}


def _apply_pollen_drowsy(engine):
    """Run the production ``drowsy`` effect for Soporific Pollen against the other fighter, on this engine.

    The row is Flowers' own, read out of the reviewed authority data
    (``authority/typed_mechanics/reviewed_final.d/zzz_auto86_flowers.json``) rather than copied into this test, so
    the empty ``while_drowsy`` list that makes Pollen grant no Concentration penalty is the real one. The executor's
    ``run_effects`` dispatches it to the same registered effect the table would use.
    """
    import json
    from pathlib import Path

    from combat.typed_executor import Context, run_effects

    root = Path(__file__).resolve().parent.parent
    mechanics = json.loads((root / "authority/typed_mechanics/reviewed_final.d/zzz_auto86_flowers.json"
                            ).read_text())["mechanics"][POLLEN]
    row = next(effect for effect in mechanics["effects"][0]["on_fail"] if effect["type"] == "drowsy")
    assert row["while_drowsy"] == [], "Soporific Pollen's own row grants no extra consequence"
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    action = next(a for a in engine.action_catalog.values() if a.source_definition_id.endswith(FRAGRANCE))
    ctx = Context(engine, me, action, None, {}, [foe], foe, effect_source=POLLEN)
    run_effects(ctx, [row])


def _blow_that_calls_for_the_save(monkeypatch, combat, table, mid, rolls):
    """A hit that lands while the creature still concentrates: the real Concentration save this section is about."""
    rolls[0] = 20
    hit_dice(monkeypatch)
    strike = candidate(combat, mid, lambda c: c.display_name.startswith("Unarmed Strike"))
    result = send(combat, table, mid, strike)
    if result["status"] == "REACTION_REQUIRED":
        result = send(combat, table, mid, strike, [{**result["reaction"]["context"], "selection": "USE"}])
    assert result["status"] == "COMMITTED", result


def test_a_replaced_drowsy_takes_its_own_concentration_penalty_with_it(tmp_path, monkeypatch):
    """One Drowsy at a time, and what belongs to a Drowsy ends with it.

    Drowsy Thought (the Dreams core list) makes a creature Drowsy and presses "Disadvantage on its next
    Concentration saving throw"; Soporific Pollen replaces that condition with its own list, which prints no
    Concentration penalty at all. The penalty used to stay behind on the creature, so it kept pressing its saving
    throws after the rules that printed it had been taken away. Every Drowsy now records the consequences it granted
    and a Drowsy that replaces another takes exactly those with it -- which is what this test checks after a table
    commit and a reload, then reads through the Concentration save the creature really has to make.
    """
    combat, table, mid = flowers_fight(tmp_path, [FRAGRANCE, POLLEN, DREAMS_BASE], dc=18,
                                       foe_mids=[DREAMS_BASE], ask_reactions=False)
    rolls = _scripted_saves(monkeypatch, 3)
    _pollen_round(combat, table, mid)
    end_turn(combat, table, mid)                      # inside the Fragrance: Pollen's own Drowsy lands
    engine = reload(tmp_path, mid)
    assert len(_drowsy_of(engine.state.actors[FOE])) == 1
    engine, granted, penalty, before = _dreams_then_pollen(tmp_path, combat, table, mid)
    assert _replaced_by_replacement(engine, before["sequence"]) == {granted.instance_id, penalty.instance_id}, (
        "the replacement removed exactly the Drowsy and the one consequence it recorded")

    next_turn(combat, table, mid)
    _blow_that_calls_for_the_save(monkeypatch, combat, table, mid, rolls)
    engine = reload(tmp_path, mid)
    saves = _concentration_saves(engine)
    assert len(saves) == 1, saves
    assert saves[0]["mode"] == "NORMAL", (
        "the replacement Drowsy prints no Concentration penalty, so the save is a plain one", saves[0])
    assert saves[0]["success"] is True, saves[0]
    assert engine.state.actors[FOE].concentration is not None, "the saved throw held, so the Dreamscape is still up"


def test_a_replaced_drowsy_leaves_what_it_never_granted_alone(tmp_path, monkeypatch):
    """Only the Drowsy's own consequences go with it; what the creature earned from something else stays.

    The creature carries the Concentration penalty the Dreams list printed -- a consequence of that Drowsy, so it must
    end with it -- and everything else it accumulated on the way: the deadline on the Dreamscape it concentrates on,
    the Dream Seed mark, and a reaction denial from an earlier Soporific Pollen save. This reads the creature's whole
    condition list *immediately before* the replacing step, then asserts after a commit and a reload that the
    replacement removed exactly the Drowsy and its own penalty, that nothing else vanished without a recorded reason,
    and that what did not expire on its own is still there. An earlier draft snapshotted the creature before the
    Dreamscape and the Seed even existed, which made the preservation claim vacuous; the snapshot here is the last look
    before the step under test. The reaction denial is the one thing that legitimately does not survive: its own
    printed duration ("until the start of its next turn") runs out at exactly this step, so the log records an ordinary
    expiry rather than the replacement touching it -- which is the distinction this test now checks.
    """
    combat, table, mid = flowers_fight(tmp_path, [FRAGRANCE, POLLEN, DREAMS_BASE], dc=18,
                                       foe_mids=[DREAMS_BASE], ask_reactions=False)
    rolls = _scripted_saves(monkeypatch, 20)          # that first Pollen save is made
    _pollen_round(combat, table, mid)
    end_turn(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert not _drowsy_of(engine.state.actors[FOE]), "a made Pollen save leaves no Drowsy behind"
    denial = [c for c in engine.state.actors[FOE].conditions.values()
              if c.condition_id == "condition:typed.reaction_denied"]
    assert len(denial) == 1, "the made save's own consequence is what the creature carries into the swap"

    rolls[0] = 3
    engine, granted, penalty, before = _dreams_then_pollen(tmp_path, combat, table, mid)
    after = set(engine.state.actors[FOE].conditions)
    replaced_by_it = _replaced_by_replacement(engine, before["sequence"])
    # What went missing across the replacing step, split by *why*. A condition whose own printed duration ran out at
    # this step is not the replacement's business; anything else that vanished would be.
    expired = {iid for iid in before["conditions"] - after
               if iid not in replaced_by_it
               and any(e.event_type == "CONDITION_REMOVED" and (e.payload or {}).get("instance_id") == iid
                       and (e.payload or {}).get("reason") != "DROWSY_REPLACED"
                       and int(e.sequence) > before["sequence"] for e in engine.events)}
    unrelated = before["conditions"] - {granted.instance_id, penalty.instance_id}
    assert unrelated, "the snapshot has to name real conditions for the preservation claim to mean anything"
    assert denial[0].instance_id in unrelated, "the reaction denial really is one of them"
    assert before["modifiers"] <= set(engine.state.actors[FOE].modifiers), (
        "the replacement took off no modifier the creature was holding")
    assert before["conditions"] - after == replaced_by_it | expired, (
        "every condition the creature lost was lost for a reason the log records: the Drowsy's own, or its own "
        f"printed expiry ({sorted(expired)}), and nothing vanished silently")
    assert replaced_by_it == {granted.instance_id, penalty.instance_id}, (
        "the replacement removed the Drowsy and its own recorded consequence, and nothing else")
    assert (unrelated - expired) <= after, (
        "everything else the creature carried and that did not expire on its own -- the Dreamscape deadline, the seed "
        "mark -- survived the replacement untouched")
    assert denial[0].instance_id in expired, (
        "the reaction denial ended because its own printed duration ran out at this step, not because of the swap")
    assert engine.state.actors[FOE].concentration is not None, "the Dreamscape it concentrates on is still up"

    next_turn(combat, table, mid)
    _blow_that_calls_for_the_save(monkeypatch, combat, table, mid, rolls)
    engine = reload(tmp_path, mid)
    saves = _concentration_saves(engine)
    assert len(saves) == 1, saves
    assert saves[0]["mode"] == "NORMAL", (
        "the penalty that went with the replaced Drowsy is not pressing this save either", saves[0])


def test_a_drowsy_replacement_leaves_another_sources_concentration_penalty_alone(tmp_path, monkeypatch):
    """The printed rule, narrowed to the case it is easiest to get wrong: a penalty of the very same kind that some
    other source granted.

    Two ``concentration_mode`` conditions stand on the creature -- the one Drowsy Thought printed, which that Drowsy
    recorded as its own consequence, and one from Staggering Break's own printed rider (the same condition row and the
    same ``next`` Disadvantage, from a source that knows nothing about Drowsy). Replacing the Drowsy must take its own
    penalty and leave the other alone. The two table-level tests above cannot see this: a replacement that simply
    dropped *every* Concentration penalty would pass both of them, and would leave the creature unable to concentrate
    for a reason no printed rule gave.

    Scope, stated honestly: this one runs the real ``drowsy`` effect on a real reloaded fight rather than committing
    the replacing step through the table. Staging a second penalty inside that table step is not reachable from this
    harness -- the ability that prints it (Destructive Blast) spends the same action as Dream Seed, and its penalty
    expires at the start of this fighter's next turn, a turn the swap has already passed. What is real here: the fight
    state is a committed, reloaded table fight; the staged penalty is a real saved condition of the same type, written
    through the same engine seam ``typed_executor`` writes it through for Staggering Break; and the code under test is
    the production effect itself, not a stand-in.
    """
    combat, table, mid = flowers_fight(tmp_path, [FRAGRANCE, POLLEN, DREAMS_BASE], dc=18,
                                       foe_mids=[DREAMS_BASE], ask_reactions=False)
    _pollen_round(combat, table, mid)
    end_turn(combat, table, mid)
    engine, granted, penalty, before = _dreams_drowsy(tmp_path, combat, table, mid)

    # Staggering Break's own printed rider, written the way typed_executor writes it for that talent.
    engine._apply_condition(engine.state.actors[FOE], "condition:typed.concentration_mode", STAGGERING_BREAK,
                            engine.state.actors[FOE].entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"rule": {"concentration_mode": "DISADVANTAGE", "next": True},
                                  "label": "Disadvantage on its next Concentration saving throw"})
    assert len(_concentration_penalties(engine.state.actors[FOE])) == 2, (
        "the creature now carries two Concentration penalties of the same kind, from two different sources")
    assert all(c.source_definition_id == STAGGERING_BREAK
               for c in _concentration_penalties(engine.state.actors[FOE])
               if c.instance_id != penalty.instance_id), (
        "the staged penalty is a different instance from the one the Drowsy recorded")

    since = int(engine.state.event_sequence)
    _apply_pollen_drowsy(engine)
    foe = engine.state.actors[FOE]
    survivors = {c.instance_id for c in _concentration_penalties(foe)}
    assert survivors and all(foe.conditions[iid].source_definition_id == STAGGERING_BREAK for iid in survivors), (
        "the only Concentration penalty left is the one Staggering Break's own printed rule granted")
    assert penalty.instance_id not in survivors, "the Drowsy's own penalty went with the Drowsy that printed it"
    assert _replaced_by_replacement(engine, since) == {granted.instance_id, penalty.instance_id}, (
        "the replacement removed the Drowsy and its own recorded consequence, and nothing else")
    assert len(_drowsy_of(foe)) == 1, "Pollen's own Drowsy is the one standing now"

# ================================================================================================================ Petal Dart
def test_petal_dart_asks_the_owner_which_damage_type(tmp_path):
    """"Choose the damage type when attacking." The owner picks Slashing or Poison, the question names the ability, the
    strike and the creature it is made against, and the printed damage lands with the type they chose."""
    combat, table, mid = flowers_fight(tmp_path, [DART], dc=18, cl=17, technique_attack_bonus=30)
    foe = _engine(combat, mid).state.actors[FOE].display_name
    chosen = candidate(combat, mid, lambda c: c.display_name.startswith("Petal Dart"))
    result = send(combat, table, mid, chosen)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == ME
    assert [o["id"] for o in prompt["choice"]["options"]] == ["SLASHING", "POISON"]
    moment = prompt["moment"]
    assert "Petal Dart" in moment, moment
    assert foe in moment, moment  # the creature the strike is made against, by its display name
    assert "Slashing or Poison" not in moment  # the printed sentence is now the question, not a GM line
    answer = {**prompt["context"], "selection": "USE", "option_ids": ["POISON"]}
    assert send(combat, table, mid, chosen, [answer])["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    committed = [e.payload.get("damage_type") for e in engine.events if e.event_type == "DAMAGE_COMMITTED"]
    assert committed == ["POISON"], committed


def test_an_ai_owner_answers_the_damage_type_question_itself(tmp_path):
    """An AI fighter is asked nothing: it keeps the table's own automatic pick (the type that lands hardest), so its
    whole turn commits without a prompt and the printed choice is still resolved."""
    combat, table, mid = flowers_fight(tmp_path, [DART], dc=18, cl=17, technique_attack_bonus=30)
    combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    result = send(combat, table, mid, candidate(combat, mid, lambda c: c.display_name.startswith("Petal Dart")), auto=True)
    assert result["status"] == "COMMITTED", result
    engine = reload(tmp_path, mid)
    committed = [e.payload.get("damage_type") for e in engine.events if e.event_type == "DAMAGE_COMMITTED"]
    assert committed and set(committed) <= {"SLASHING", "POISON"}, committed


def test_petal_dart_damage_type_question_is_only_asked_of_its_owner(tmp_path):
    """No Petal Dart, no question. A character that owns Fragrant Mirage but not Petal Dart compiles no Petal Dart
    action at all, and a whole turn of its fighting never puts the question."""
    document = compile_character(sheet([MIRAGE], cl=18, dc=100, primary="Stamina", score=18), actor_id=ME)
    assert not [a for a in document["action_catalog"] if "Petal Dart" in a["display_name"]]

    combat, table, mid = fight(tmp_path, [MIRAGE], dc=18)
    assert send(combat, table, mid, candidate(combat, mid, lambda c: c.display_name == "Fragrant Mirage"))["status"] == "COMMITTED"
    combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    end = candidate(combat, mid, lambda c: c.kind.value == "END_TURN")
    assert send(combat, table, mid, end, auto=True)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert "petal_dart" not in json.dumps(engine.gate4_reaction_decision_records, default=str)
    assert not [e for e in engine.events if e.event_type == "REACTION_RESOLVED" and "petal" in str(e.source_definition_id)]


# ================================================================================================================ Fragrant Mirage
def test_fragrant_mirage_advantages_only_its_own_first_dart_while_it_is_up(tmp_path, monkeypatch):
    """"the first Petal Dart you make each turn has Advantage while you stand inside one of your Fragrances" --
    "For the duration". The dart rolled before the Bonus Action that starts the Mirage gets nothing, the dart after it
    does, and once the caster stops concentrating the printed benefit is gone with the condition."""
    combat, table, mid = flowers_fight(tmp_path, [DART, MIRAGE, FRAGRANCE], dc=18, technique_attack_bonus=30,
                                       ask_reactions=False)
    _fragrance_at_me(combat, table, mid)              # the caster stands inside its own Fragrance
    end_turn(combat, table, mid)
    assert _walk(combat, table, mid, 6, 6), "the other fighter walks out of reach (adjacent fights cancel a mode)"
    next_turn(combat, table, mid)

    dart(combat, table, mid)                          # not under the Mirage yet
    engine = reload(tmp_path, mid)
    assert not _dart_advantage(engine), "the Petal Dart rolled with Advantage before Fragrant Mirage was ever used"
    assert not _mirage_conditions(engine, engine.state.actors[ME])

    next_turn(combat, table, mid)
    cast(combat, table, mid, "Fragrant Mirage")
    dart(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert _dart_advantage(engine), [e.payload.get("value") for e in engine.events if e.event_type == "MODIFIER_APPLIED"]
    assert len(_mirage_conditions(engine, engine.state.actors[ME])) == 1

    next_turn(combat, table, mid)
    mark = reload(tmp_path, mid).state.event_sequence
    dart(combat, table, mid)                          # a new turn: the printed first Dart again
    assert _dart_advantage(reload(tmp_path, mid), mark)

    # the other fighter's blow costs the caster its Concentration (the printed saving throw fails), and the Mirage with it
    hit_dice(monkeypatch, save_roll=1)
    next_turn(combat, table, mid)
    end_turn(combat, table, mid)
    assert _walk(combat, table, mid, 4, 6)          # back into reach
    assert send(combat, table, mid, candidate(combat, mid, lambda c: c.display_name == "Unarmed Strike"))["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert not _mirage_conditions(engine, engine.state.actors[ME]), "the Mirage outlived the Concentration that held it"
    next_turn(combat, table, mid)
    mark = reload(tmp_path, mid).state.event_sequence
    dart(combat, table, mid)
    assert not _dart_advantage(reload(tmp_path, mid), mark), "the Petal Dart rolled with Advantage after the Mirage ended"


def test_fragrant_mirage_is_never_read_from_another_fighters_talents(tmp_path):
    """The catalog holds every fighter's bundles, so the talent has to be read from the caster's own rows: the Petal
    Dart user inside its own Fragrance gets nothing from the Mirage the *other* fighter is wearing."""
    combat, table, mid = flowers_fight(tmp_path, [DART, FRAGRANCE], dc=18, technique_attack_bonus=30,
                                       foe_mids=[MIRAGE], ask_reactions=False)
    _fragrance_at_me(combat, table, mid)
    end_turn(combat, table, mid)
    cast(combat, table, mid, "Fragrant Mirage")       # the other fighter's own Bonus Action, on its own turn
    engine = reload(tmp_path, mid)
    assert len(_mirage_conditions(engine, engine.state.actors[FOE])) == 1
    assert not _mirage_conditions(engine, engine.state.actors[ME])

    next_turn(combat, table, mid)
    end_turn(combat, table, mid)
    assert _walk(combat, table, mid, 6, 6)
    next_turn(combat, table, mid)
    mark = reload(tmp_path, mid).state.event_sequence
    dart(combat, table, mid)
    assert not _dart_advantage(reload(tmp_path, mid), mark), "another fighter's Fragrant Mirage granted the Advantage"


def test_the_first_petal_dart_of_a_turn_is_spent_wherever_the_caster_stands(tmp_path):
    """The printed line gives the first Petal Dart of the turn the Advantage, not the first one made from inside the
    Fragrance: a dart from outside spends it, so the same turn's dart from inside rolls straight. Asked of the same
    fight's own action through the plug-in's own entry point, twice in one turn, which is the boundary the engine calls
    before every strike (a Petal Dart is one Action, so the table cannot roll two of them in one turn)."""
    from combat.ext import flowers_sphere

    combat, table, mid = flowers_fight(tmp_path, [DART, MIRAGE, FRAGRANCE], dc=18, technique_attack_bonus=30,
                                       ask_reactions=False)
    _fragrance_at_me(combat, table, mid)
    cast(combat, table, mid, "Fragrant Mirage")

    next_turn(combat, table, mid)                     # inside the Fragrance, under the Mirage
    engine = reload(tmp_path, mid)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert flowers_sphere.fragrant_mirage_first_dart(_dart_ctx(engine, me, foe), foe) == "ADVANTAGE"
    assert flowers_sphere.fragrant_mirage_first_dart(_dart_ctx(engine, me, foe), foe) is None, "the second dart of the turn"

    next_turn(combat, table, mid)                     # walk out, strike, walk back in, strike again
    zone = _fragrance_zone(reload(tmp_path, mid))
    north = (zone.center.x, zone.center.y - 4)          # clear of the other fighter, who stands east
    assert _walk(combat, table, mid, *north)
    assert not _inside_fragrance(_engine(combat, mid), zone, _engine(combat, mid).state.actors[ME])

    # both strikes of this one turn are asked of one live engine, the way the executor asks before each roll: the first
    # from outside the Fragrance, then the caster steps back in (the same turn, no new commit) and asks again
    engine = _engine(combat, mid)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert flowers_sphere.fragrant_mirage_first_dart(_dart_ctx(engine, me, foe), foe) is None, "from outside the Fragrance"
    me.position = zone.center
    assert _inside_fragrance(engine, zone, me)
    assert flowers_sphere.fragrant_mirage_first_dart(_dart_ctx(engine, me, foe), foe) is None, \
        "the first Petal Dart of the turn was spent outside the Fragrance"

    next_turn(combat, table, mid)                     # a new turn has its own first Petal Dart
    assert _walk(combat, table, mid, zone.center.x, zone.center.y - 2)
    engine = reload(tmp_path, mid)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert _inside_fragrance(engine, zone, me)
    assert flowers_sphere.fragrant_mirage_first_dart(_dart_ctx(engine, me, foe), foe) == "ADVANTAGE"


def test_an_opportunity_attack_against_a_mirage_wearer_is_rolled_with_disadvantage(tmp_path):
    """"opportunity attacks against you have Disadvantage." A real Opportunity Attack, made by the other fighter as this
    one walks out of reach, rolls its d20 with Disadvantage (one die dropped) -- and with a normal roll when the target
    wears no Mirage."""
    combat, table, mid = flowers_fight(tmp_path, [DART, MIRAGE], dc=18, technique_attack_bonus=30)
    cast(combat, table, mid, "Fragrant Mirage")
    assert _walk(combat, table, mid, 1, 1)
    engine = reload(tmp_path, mid)
    rolls = [e.payload for e in engine.events if e.event_type == "ATTACK_ROLLED"]
    assert [row.get("mode") for row in rolls] == ["DISADVANTAGE"], rolls
    assert len(rolls[0].get("discarded") or []) == 1, rolls[0]  # the dropped die is what Disadvantage is
    assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == "system:combat.opportunity_attack"
               for e in engine.events)

    # the control: the same strike against a fighter who wears no Mirage is a normal roll
    other = tmp_path / "without-mirage"
    other.mkdir()
    combat2, table2, mid2 = flowers_fight(other, [DART], dc=18, technique_attack_bonus=30)
    assert _walk(combat2, table2, mid2, 1, 1)
    rolls = [e.payload for e in reload(other, mid2).events if e.event_type == "ATTACK_ROLLED"]
    assert [row.get("mode") for row in rolls] == ["NORMAL"], rolls


# ================================================================================================================ Lingering Fragrance
def test_the_augmented_fragrance_costs_2_cp_and_stands_for_its_own_minute(tmp_path):
    """"Augment - 2 CP: The Fragrance persists for its remaining duration without Concentration." The augmented
    Fragrance is its own action: 2 CP is paid, its area stands for the printed 1 minute and is not tied to Concentration."""
    combat, table, mid = fight(tmp_path, [FRAGRANCE, LINGERING], dc=18)
    me = _engine(combat, mid).state.actors[ME]
    created = at(combat, mid, "Fragrance + Lingering Fragrance", me.position.x, me.position.y)
    assert send(combat, table, mid, created)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    zone = _fragrance_zone(engine)
    assert not zone.concentration_link and zone.duration_rounds == 10  # the printed minute, no Concentration
    assert engine.state.actors[ME].resources[STAMINA] == 30 - 2      # the printed 2 CP

    # the same Fragrance without the augment: the printed Concentration, up to 1 minute
    plain = tmp_path / "plain"
    plain.mkdir()
    combat2, table2, mid2 = fight(plain, [FRAGRANCE, LINGERING], dc=18)
    me2 = _engine(combat2, mid2).state.actors[ME]
    assert send(combat2, table2, mid2, at(combat2, mid2, "Fragrance", me2.position.x, me2.position.y))["status"] == "COMMITTED"
    zone2 = _fragrance_zone(reload(plain, mid2))
    assert zone2.concentration_link and zone2.duration_rounds == 10
    assert reload(plain, mid2).state.actors[ME].resources[STAMINA] == 30


def test_a_fragrance_that_already_exists_can_be_kept_without_concentration_for_2_cp(tmp_path):
    """"You may apply this augment after creating the Fragrance on your turn without spending an Action." The printed 2 CP
    is charged by the free "keep ... without Concentration" button (combat/ext/persist_augment.py) on the caster's own
    turn, the Concentration ends, and the Fragrance outlives it -- a real commit and reload at every step."""
    combat, table, mid = fight(tmp_path, [FRAGRANCE, LINGERING, MIRAGE], dc=18)
    me = _engine(combat, mid).state.actors[ME]
    assert send(combat, table, mid, at(combat, mid, "Fragrance", me.position.x, me.position.y))["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    zone = _fragrance_zone(engine)
    assert zone.concentration_link and engine.state.actors[ME].concentration is not None

    keep = candidate(combat, mid, lambda c: c.display_name == "Lingering Fragrance: keep Fragrance without Concentration (2 CP)")
    before = engine.state.actors[ME].resources[STAMINA]
    assert send(combat, table, mid, keep)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    zone = _fragrance_zone(engine)
    assert zone.active and not zone.concentration_link and zone.duration_rounds == 10
    assert engine.state.actors[ME].resources[STAMINA] == before - 2   # the printed 2 CP
    assert engine.state.actors[ME].concentration is None
    # nothing concentrates on it any more: a later Concentration effect does not take it away
    cast(combat, table, mid, "Fragrant Mirage")
    engine = reload(tmp_path, mid)
    zone = _fragrance_zone(engine)
    assert zone.active and not zone.concentration_link
    assert len([z for z in engine.state.zones.values() if (z.trigger_profile or {}).get("name") == "Fragrance"]) == 1


def test_the_printed_fragrance_options_are_buttons_not_reminder_lines():
    """The printed Fragrance options each carry their own button and cost, so no Flowers reminder line has to say so
    again -- in particular the 2 CP augment, which used to be a reminder (review finding 4)."""
    document = compile_character(sheet([FRAGRANCE, LINGERING, POLLEN, DART, MIRAGE], cl=18, dc=100,
                                       primary="Stamina", score=18), actor_id=ME)
    names = [a["display_name"] for a in document["action_catalog"]]
    assert "Fragrance + Lingering Fragrance" in names
    assert "Lingering Fragrance: keep Fragrance without Concentration (2 CP)" in names
    lines = flower_lines(document)
    assert not [text for _name, text in lines
                if "Augment - 2 CP" in text or "Choose one Fragrance talent" in text
                or "without spending an Action" in text or "still needs Concentration" in text], lines


# ================================================================================================================ the printed CL table, and two lines that are never the GM's
def test_thousand_petal_storm_deals_its_cultivation_level_damage(tmp_path, monkeypatch):
    """| Cultivation Level | Damage | 10-16 | 6d6; 17-20 | 8d6." The CL table is the engine's own dice_by_cl, which is
    why the printed restatement of it is no longer a GM line: at CL 17 the storm rolls 8d6."""
    combat, table, mid = flowers_fight(tmp_path, [STORM], dc=18, cl=17)
    failing_save(monkeypatch)
    foe = _engine(combat, mid).state.actors[FOE]
    chosen = candidate(combat, mid, lambda c: c.display_name.startswith("Thousand-Petal Storm")
                       and f"at {foe.position.x},{foe.position.y}" in c.display_name)
    assert send(combat, table, mid, chosen)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    rolled = [e.payload.get("expression") for e in engine.events if e.event_type == "DAMAGE_ROLLED"]
    assert [text for text in rolled if text and "8d6" in text], rolled


def test_flowers_shows_no_printed_prerequisite_and_no_cl_damage_restatement():
    """Two printed lines are never the GM's to apply in a fight: a Prerequisite (character creation settled it long ago)
    and a restatement of damage the engine already scales by Cultivation Level. Neither is a GM reminder line for any
    Flowers ability, and every other Flowers line the table does run is untouched."""
    from tests.h1_support import mechanics as all_mechanics

    sphere = sorted(key for key, value in all_mechanics().items() if value.get("sphere_id") == "tianxia.sphere.flowers")
    document = compile_character(sheet(sphere, cl=18, dc=100, primary="Stamina", score=18), actor_id=ME)
    lines = flower_lines(document)
    assert not [text for _name, text in lines if text.strip().lower().startswith("prerequisite")], lines
    assert not [text for _name, text in lines if "Cultivation Level" in text and "scales" in text], lines
    # the sphere's own abilities are still described, not blanked out
    assert [text for _name, text in lines if text.strip()], "the Flowers fight should still say what it cannot do"
