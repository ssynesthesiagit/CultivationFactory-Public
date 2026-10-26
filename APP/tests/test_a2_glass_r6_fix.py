"""GLASSR6: table-level regressions for the eight GLASSR6 pre-merge findings.

Each test drives the printed Faultline Mark lines (or Glass-Bone Guard, or the reviewed authority records) through
``TabletopService``/real data and asserts a committed consequence after a cold reload, the same style as
``test_auto2_glass.py`` and ``test_a2_glass_p1_fix.py``.
"""
import json
from pathlib import Path

from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import ActionDefinition
from hashlib import sha256

from tests.cw2_service_support import add_action, seal
from tests.test_a2_glass_faults_fix import forced_save
from tests.test_auto2_glass import AUTO_SAVE, BASES, FEATURE_LOCKED, FLAW, RESIST_EFFECT, conditions, foe_turn, glass, owner_setup, prepare
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle


def _area_action(bundle, name, effects, *, size_ft=15, typed=None):
    """A CELL-aimed area action, the shape ``test_area_shapes.py``'s full-engine tests use.

    ``cw2_service_support.add_action`` only builds single-target actions; proving the fixed recipient discovery needs
    a real area whose ``target_ids`` is empty, the way a cell-aimed printed spell actually works.
    """
    owner = sha256(bundle['actor_id'].encode()).hexdigest()[:10]
    source = 'action:test.cw2area.' + owner + '.' + name.lower().replace(' ', '_')
    action = ActionDefinition(source_definition_id=source, display_name=name, owner_id=bundle['actor_id'],
                              economy='ACTION', resolution_kind='TYPED', target_kind='CELL', range_ft=60,
                              parameters={'typed': {'source': source, 'effects': effects,
                                  'numbers': {'pb': 4, 'key_mod': 2, 'save_dc': 16, 'cl': 15},
                                  'duration': {'kind': 'instant'}, 'riders': [],
                                  'area': {'shape': 'sphere', 'size_ft': size_ft}, **(typed or {})},
                                  'player_only': True})
    bundle['action_catalog'].append(action.model_dump(mode='json'))
    bundle['actor_template']['action_ids'].append(source)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


# ------------------------------------------------------------------------------------- 1. competing reactions
def test_owning_both_talents_offers_a_choice_instead_of_spell_line_preempting_flaw(tmp_path, monkeypatch):
    """A caster who owns both talents, with both triggers legal, is asked which one answers -- not whichever runs first.

    Before the fix the two technique_start hooks shared one answered-set keyed without the reaction kind, so Spell-Line
    Crack (registered first) always took the only answer and Flaw was never reachable.  This settles the combined
    choice toward Flaw and asserts a Flaw-only consequence landed, with no Spell-Line-only prompt ever raised.
    """
    forced_save(monkeypatch, {"WIS": 1})   # a failed Wisdom save reaches the Failed Save answers either line offers
    combat, table, mid = glass(tmp_path, ["SPELL_LINE_CRACK", "FLAW_WITHIN_THE_GOLDEN_TECHNIQUE"], ask=False)
    owner_setup(combat, table, mid)   # tempers the owner's own body: Spell-Line's through-glass trigger is also legal
    foe_turn(table, mid)
    prompts = settle(table, mid, candidate(combat, mid, "Foe Technique", target=OWNER).candidate_id,
                     {"choice:needle.glass_crack_choice": "flaw", "choice:needle.glass_flaw_outcome": "lock_feature"})
    engine = reload(tmp_path, mid)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.glass_crack_choice" for p in prompts), \
        "both legal reactions must be offered as one combined choice"
    assert not any(p["context"]["reaction_source_id"] == "choice:needle.glass_spell_line_outcome" for p in prompts), \
        "Spell-Line must not silently answer once Flaw was chosen"
    assert conditions(engine, FOE, FEATURE_LOCKED), "the chosen line (Flaw) must be the one that actually answered"


# ------------------------------------------------------------------------------------- 2. manual ally choice
def test_manual_owner_is_asked_for_the_ally_saves_recipient(tmp_path, monkeypatch):
    """A manual owner is really asked which ally gets the auto-save; it is not silently ``pool[0]``.

    Before the fix ``ally_saves`` always took ``pool[0]`` directly, with no call into ``_ask_recipient`` at all, so no
    question was ever raised -- unlike the parallel ``target_advantage`` branch, which already asked.
    """
    forced_save(monkeypatch, {"WIS": 1})
    combat, table, mid = glass(tmp_path, ["FLAW_WITHIN_THE_GOLDEN_TECHNIQUE"], ask=True)
    owner_setup(combat, table, mid)
    foe_turn(table, mid)
    prompts = settle(table, mid, candidate(combat, mid, "Foe Technique", target=ALLY).candidate_id,
                     {"choice:needle.glass_flaw": "use", "choice:needle.glass_flaw_outcome": "ally_saves"})
    engine = reload(tmp_path, mid)
    assert any("_auto" in p["context"]["reaction_source_id"] for p in prompts), \
        "a manual owner must be asked which ally gets the auto-save, not have pool[0] silently chosen"
    assert conditions(engine, ALLY, AUTO_SAVE), "the only eligible ally must still receive the benefit once asked"


# ------------------------------------------------------------------------------------- 3. area recipients
def test_flaw_finds_area_recipients_through_the_real_action_geometry(tmp_path, monkeypatch):
    """A cell-aimed area's recipients are found from the action's real typed area and the intent's real destination.

    Before the fix the code read ``target_position``/``aim``/``area`` off ``ActionIntent``, none of which exist on that
    model, so a cell-aimed effect with empty ``target_ids`` found nobody and every recipient-dependent answer failed
    silently.
    """
    def prepare_area(bundles):
        prepare(bundles)
        _area_action(bundles[2], "Foe Area Technique",
                     [{"type": "damage", "applies_to": "creatures_in_area", "flat": 1, "damage_types": ["slashing"],
                       "duration": "instant"}],
                     size_ft=10, typed={"costs": [["resource:core.cp", 1]]})
        for bundle in bundles:
            seal(bundle)

    forced_save(monkeypatch, {"WIS": 1})
    combat, table, mid = fixture(tmp_path, list(BASES) + [FLAW], cl=15, ask=False, bundle_transform=prepare_area,
                                 foe_position={"x": 4, "y": 5})
    owner_setup(combat, table, mid)
    foe_turn(table, mid)
    cand = candidate(combat, mid, "Foe Area Technique", at=(4, 6))   # ALLY's own cell, never a declared target id
    assert cand.target_ids == (), "a cell-aimed area must carry no declared target ids -- this is the bug's precondition"
    settle(table, mid, cand.candidate_id,
          {"choice:needle.glass_flaw": "use", "choice:needle.glass_flaw_outcome": "ally_saves"})
    engine = reload(tmp_path, mid)
    assert conditions(engine, ALLY, AUTO_SAVE), \
        "the ally standing in the area, found through the real geometry, must be offered the benefit"


# ------------------------------------------------------------------------------------- 4. Resistance damage types
def test_successful_save_resistance_is_limited_to_damage_the_effect_actually_dealt(tmp_path, monkeypatch):
    """Resistance only offers the damage type(s) the triggering effect actually dealt, never the whole vocabulary.

    Before the fix every one of the engine's thirteen damage types was offered and the AI default was always Acid,
    regardless of what the interrupted effect dealt -- "Foe Technique" deals only Slashing.
    """
    forced_save(monkeypatch, {"WIS": 20})   # a successful Wisdom save reaches the Successful Save (Resistance) branch
    combat, table, mid = glass(tmp_path, ["FLAW_WITHIN_THE_GOLDEN_TECHNIQUE"], ask=False)
    owner_setup(combat, table, mid)
    foe_turn(table, mid)
    settle(table, mid, candidate(combat, mid, "Foe Technique", target=ALLY).candidate_id,
          {"choice:needle.glass_flaw": "use"})
    engine = reload(tmp_path, mid)
    resist = conditions(engine, ALLY, RESIST_EFFECT)
    assert resist, "the Successful Save must still grant Resistance to the one ally the effect reached"
    kinds = (resist[0].data or {}).get("rule", {}).get("damage_resistances") or []
    assert kinds == ["SLASHING"], f"the effect only dealt Slashing damage, so Resistance must be to Slashing, not {kinds}"


# ------------------------------------------------------------------------------------- 5. duplicate authority records
def test_no_duplicate_reviewed_authority_records_for_glass_reactions():
    """Proud Weapon, Spell-Line Crack and Flaw each have exactly one owning ``reviewed_final.d`` record.

    Before the fix ``a2_glass.json`` duplicated Proud Weapon (also in ``review_sw-force.json``) and Flaw (also in
    ``riders_c14.json``), so the builder logged "reviewed twice" and future reviewed edits to either owning record
    could be silently discarded by file-load order.
    """
    root = Path(__file__).resolve().parents[1] / "authority" / "typed_mechanics" / "reviewed_final.d"
    owners: dict[str, list[str]] = {}
    for path in sorted(root.glob("*.json")):
        data = json.loads(path.read_text())
        for mechanic_id in (data.get("mechanics") or {}):
            owners.setdefault(mechanic_id, []).append(path.name)
    for mechanic_id in ("TAL_GLASS_BREAK_THE_PROUD_WEAPON", "TAL_GLASS_SPELL_LINE_CRACK",
                       "TAL_GLASS_FLAW_WITHIN_THE_GOLDEN_TECHNIQUE"):
        assert len(owners.get(mechanic_id) or []) == 1, \
            f"{mechanic_id} must have exactly one owning reviewed_final.d record, found {owners.get(mechanic_id)}"


# ------------------------------------------------------------------------------------- 6. Glass-Bone Guard label
def test_glass_bone_guard_label_names_the_benefits_not_the_option_keys(tmp_path):
    """Glass-Bone Guard's persisted label reads the printed benefits, never the internal option ids.

    Before the fix the label was ``"Glass-Bone Guard: " + ", ".join(chosen)``, joining raw option ids like ``reduce``
    and ``mark`` -- implementation keys, not anything a player who only knows basic D&D could read.
    """
    from combat.ext.glass_body import CONDITION

    combat, table, mid = fixture(tmp_path, list(BASES) + ["TAL_GLASS_GLASS_BONE_GUARD", "TAL_GLASS_WALKING_PANE_BODY"],
                                 cl=15, foe_position={"x": 4, "y": 5})
    settle(table, mid, candidate(combat, mid, "Temper Glass Surface").candidate_id,
          {"choice:needle.glass_body_guard": ["reduce", "mark"]})
    engine = reload(tmp_path, mid)
    guard = conditions(engine, OWNER, CONDITION)
    assert guard, "the guard condition must be applied"
    label = str(guard[0].data.get("label") or "")
    assert "reduce" not in label and "mark" not in label, f"the label must not print raw option keys, got {label!r}"
    assert "Reduce the first physical damage each round by your Proficiency Bonus" in label
    assert "Mark a hostile creature when it hits you with a melee attack" in label


# ------------------------------------------------------------------------------------- 7. through-glass sight crossing
def test_through_glass_requires_the_sight_path_to_actually_cross_a_surface(tmp_path, monkeypatch):
    """A Glass Surface off the caster's sight path to the target does not qualify Spell-Line Crack's trigger.

    Before the fix the check was "does the caster own any Glass Surface, and can the caster see the creature" -- two
    ordinary questions answered independently, so a pane behind or beside the caster qualified a creature standing in
    front of them.  This isolates the fixed geometry predicate against the real committed engine and its real line-of-
    sight code; only the surface-cell source is stubbed, because raising a pane through the table changes none of the
    geometry math under test.
    """
    from combat.ext import glass_faults, glass_refraction

    combat, table, mid = glass(tmp_path, ["SPELL_LINE_CRACK"], ask=False)
    owner_setup(combat, table, mid, temper=False)
    foe_turn(table, mid)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]   # OWNER (3,6) and FOE (4,5) by fixture default
    monkeypatch.setattr(glass_refraction, "surface_cells", lambda e, c: {(0, 0)})
    assert not glass_faults._through_glass(engine, owner, foe), \
        "a Glass Surface off the sight path must not qualify the trigger"
    monkeypatch.setattr(glass_refraction, "surface_cells", lambda e, c: {(3, 6), (4, 5)})
    assert glass_faults._through_glass(engine, owner, foe), \
        "a Glass Surface the sight path actually crosses (here, the caster's own cell) must qualify the trigger"


# ------------------------------------------------------------------------------------- 8. duration shortening (zones)
def test_flaw_shortening_also_shortens_the_zone_the_triggering_effect_created(tmp_path, monkeypatch):
    """Flaw's duration-shortening answer reaches a zone the triggering effect created, not only conditions.

    Before the fix ``_shorten_activation`` only ever touched round-counted *conditions* already on the actor; a
    duration-bearing zone (a Domain, for instance) was never shortened at all, even though the printed line promises
    the triggering effect itself lasts one round less.
    """
    def prepare_zone(bundles):
        prepare(bundles)
        add_action(bundles[2], "Foe Zone Technique",
                  [{"type": "condition", "condition": "frightened", "applies_to": "self",
                    "duration": {"kind": "minutes", "amount": 1}}],
                  target="SELF",
                  typed={"costs": [["resource:core.cp", 1]],
                         "zone_spec": {"name": "Foe Zone", "centered_on_self": True, "shape": "radius",
                                       "size_ft": 5, "height_ft": 5, "duration": {"kind": "minutes", "amount": 1}}})
        for bundle in bundles:
            seal(bundle)

    forced_save(monkeypatch, {"WIS": 1})
    combat, table, mid = fixture(tmp_path, list(BASES) + [FLAW], cl=15, ask=False, bundle_transform=prepare_zone,
                                 foe_position={"x": 4, "y": 5})
    owner_setup(combat, table, mid)
    foe_turn(table, mid)
    settle(table, mid, candidate(combat, mid, "Foe Zone Technique").candidate_id,
          {"choice:needle.glass_flaw": "use", "choice:needle.glass_flaw_outcome": "shorten"})
    engine = reload(tmp_path, mid)   # reload asserts the committed fight replays clean -- the direct proof this is replay-safe
    zones = [z for z in engine.state.zones.values() if z.owner_id == FOE and z.active]
    assert zones, "the foe's high-cost technique must create a real zone"
    assert zones[0].duration_rounds == 9, \
        f"the printed 'lasts 1 round less' must shorten the zone's own round clock (10 -> 9), got {zones[0].duration_rounds}"
    frightened = [c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == "condition:typed.frightened"]
    assert frightened, "the foe's high-cost technique must also apply a real round-counted condition"
    from combat.ext.effect_durations import parse_round
    parsed = parse_round(frightened[0].expires_on)
    assert parsed and parsed[0] - engine.state.round_number == 9, \
        "the same answer must shorten the condition's own round clock (10 -> 9) exactly as it shortens the zone"
