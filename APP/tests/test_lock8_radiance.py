"""C12 canonical Unclean clauses on the round6 base; explicit printed kinds only."""
import json
import pytest
from combat import typed_executor
from combat.ext import creature_kinds
from combat.factory_compiler import compile_character
import combat.factory_compiler as compiler
from combat.gate2_runtime_models import ActionIntent
from tests import lock8_support as C4
from tests.h1_support import ROOT, sheet as h1_sheet
ME, FOE, ALLY, FAIL, PASS = C4.ME, C4.FOE, C4.ALLY, C4.FAIL, C4.PASS

def mech(key):
    return json.loads(compiler.TYPED_AUTHORITY.read_bytes())["mechanics"][key]

def kind_bundle(mids, actor_id, kind=None, cl=10, dc=16, kit=None, ac=None):
    """A real compiled character whose printed creature type is ``kind`` (Factory identity creature_type)."""
    doc = h1_sheet(list(mids), cl=cl, dc=dc, kit=kit)
    if kind:
        doc["identity"]["creature_type"] = kind
    if ac is not None:
        doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = ac
    return compile_character(doc, actor_id=actor_id)

def sure_hit(engine):
    engine.state.actors[FOE].armor_class = -50

def damage_rolls(engine, before, source_part):
    return [r for r in engine.rolls[before:] if str(r.reason).startswith("DAMAGE") and source_part in str(r.reason)]

def test_unclean_follows_the_printed_radiance_list_and_never_guesses():
    engine = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE"), foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, "Undead"))
    foe = engine.state.actors[FOE]
    assert creature_kinds.is_unclean(foe) and creature_kinds.matches(foe, ["undead"])
    for label, unclean in (("Fiend", True), ("Demon", True), ("Possession Entity", True), ("Construct", False), ("Humanoid", False)):
        other = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE"), foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, label))
        assert creature_kinds.is_unclean(other.state.actors[FOE]) is unclean, label
    plain = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE"))
    assert not creature_kinds.labels(plain.state.actors[FOE]) and not creature_kinds.is_unclean(plain.state.actors[FOE])

def test_radiance_strike_adds_the_proficiency_bonus_once_per_turn_against_an_unclean_target():
    engine = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE", cl=10), foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, "Undead"))
    sure_hit(engine)
    before = len(engine.rolls)
    C4.use(engine, "Radiance Strike", target=FOE)
    (first,) = damage_rolls(engine, before, "RADIANCE_BASE_STRIKE")
    assert first.modifier == 4  # PB added to the one damage roll
    engine.state.actors[ME].action_available = True
    before = len(engine.rolls)
    C4.use(engine, "Radiance Strike", target=FOE)
    (second,) = damage_rolls(engine, before, "RADIANCE_BASE_STRIKE")
    assert second.modifier == 0  # once per turn
    C4.turn(engine, FOE)
    C4.turn(engine, ME)
    before = len(engine.rolls)
    C4.use(engine, "Radiance Strike", target=FOE)
    assert damage_rolls(engine, before, "RADIANCE_BASE_STRIKE")[0].modifier == 4

def test_radiance_strike_against_an_unlabelled_target_is_unchanged():
    engine = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE", cl=10))
    sure_hit(engine)
    before = len(engine.rolls)
    C4.use(engine, "Radiance Strike", target=FOE)
    assert damage_rolls(engine, before, "RADIANCE_BASE_STRIKE")[0].modifier == 0

def test_dawnlit_rebuke_stops_an_unclean_creature_regaining_hp():
    for kind, denied in (("Fiend", True), (None, False)):
        engine = C4.fight(C4.bundle("RADIANCE_TAL_DAWNLIT_REBUKE"), foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, kind))
        source = next(a for a in engine.state.actors[ME].reaction_ids + engine.state.actors[ME].action_ids if "DAWNLIT_REBUKE" in a) \
            if any("DAWNLIT_REBUKE" in a for a in engine.state.actors[ME].reaction_ids + engine.state.actors[ME].action_ids) else None
        rows = mech("RADIANCE_TAL_DAWNLIT_REBUKE")["effects"]
        action = engine.action_catalog.get(source) if source else next(iter(engine.action_catalog.values()))
        typed = {"numbers": {"pb": 4, "cl": 10, "key_mod": 2, "save_dc": 16}, "effects": rows, "riders": []}
        ctx = typed_executor.Context(engine, engine.state.actors[ME], action, None, typed, [engine.state.actors[FOE]], engine.state.actors[FOE], {})
        typed_executor.run_effects(ctx, rows)
        held = [m for m in engine.state.actors[FOE].modifiers.values() if m.target_field == "healing_reduction"]
        assert bool(held) is denied, kind
        if held:
            assert held[0].expires_on == "START_OF_SELF_NEXT_TURN"

def test_sun_white_judgment_spear_makes_an_unclean_target_save():
    engine = C4.fight(C4.bundle("RADIANCE_TAL_SUN_WHITE_JUDGMENT_SPEAR", cl=17, dc=FAIL), foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, "Undead"))
    sure_hit(engine)
    events = C4.use(engine, "Sun-White Judgment Spear", target=FOE)
    foe = engine.state.actors[FOE]
    assert [e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
    assert C4.held(foe, "blinded") and [m for m in foe.modifiers.values() if m.target_field == "healing_reduction"]
    passed = C4.fight(C4.bundle("RADIANCE_TAL_SUN_WHITE_JUDGMENT_SPEAR", cl=17, dc=PASS), foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, "Undead"))
    sure_hit(passed)
    C4.use(passed, "Sun-White Judgment Spear", target=FOE)
    assert C4.held(passed.state.actors[FOE], "reaction_denied") and not C4.held(passed.state.actors[FOE], "blinded")
    plain = C4.fight(C4.bundle("RADIANCE_TAL_SUN_WHITE_JUDGMENT_SPEAR", cl=17, dc=FAIL))
    sure_hit(plain)
    events = C4.use(plain, "Sun-White Judgment Spear", target=FOE)
    assert not [e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]

def test_disadvantage_if_kind_on_a_save_row():
    for kind, mode in (("Undead", "DISADVANTAGE"), (None, "NORMAL")):
        engine = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE"), foe=kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, kind))
        ctx = C4.ctx_of(engine, ME, FOE, C4.action_id(engine, ME, "Radiance Strike"))
        before = len(engine.events)
        typed_executor.block_save(ctx, {"type": "save", "ability": "wis", "dc": "technique_save_dc", "disadvantage_if_kind": ["unclean"],
                                        "applies_to": "target", "on_fail": [], "on_success": []})
        (save,) = [e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED"]
        assert save.payload["mode"] == mode, kind

def test_once_per_turn_kind_flag_survives_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    me = C4.bundle("RADIANCE_BASE_STRIKE", cl=10)
    foe = kind_bundle(["SAND_BASE_SCOURING_HAND"], FOE, "Undead", ac=0)  # printed AC 0: the strike hits unless a natural 1
    session = persistence.create_match(match_seed="C12-KIND", typed_bundles=(me, foe), roster_setup={
        "primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
        "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}}})
    while session.engine.state.current_actor_id != ME:
        c = next(c for c in session.engine.legal_candidates() if c.display_name == "End turn")
        session.submit_intent(ActionIntent(intent_id=f"end-{c.state_version}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                           state_version=c.state_version, actor_id=c.actor_id, target_ids=c.target_ids),
                              primary_decision_record=None, reaction_provider=None)
    assert creature_kinds.is_unclean(session.engine.state.actors[FOE])
    c = next(c for c in session.engine.legal_candidates() if c.display_name == "Radiance Strike" and FOE in (c.target_ids or ()))
    before = len(session.engine.rolls)
    session.submit_intent(ActionIntent(intent_id="strike", decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
                                       actor_id=ME, target_ids=c.target_ids), primary_decision_record=None, reaction_provider=None)
    (hit,) = [r for r in session.engine.rolls[before:] if str(r.reason).startswith("DAMAGE")]
    assert hit.modifier == 4  # the PB rides the strike's damage roll
    loaded = persistence.load_match(session.match_id)
    assert loaded.engine.state.actors[ME].turn_flags.get("creature_kind_once:radiance_strike_unclean") is True
    assert creature_kinds.is_unclean(loaded.engine.state.actors[FOE])
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('natural,prevent_damage', [(1, False), (10, True)])
def test_strike_keeps_once_per_turn_bonus_after_miss_or_prevented_damage(monkeypatch, natural, prevent_damage):
    from tests.test_lock_choices import install
    install(monkeypatch, 'd20_result', lambda *args: {'source_id': 'test:roll', 'operation': 'replace', 'natural_result': natural})
    if prevent_damage:
        install(monkeypatch, 'final_damage', lambda *args: {'amount': 0})
    engine = C4.fight(C4.bundle('RADIANCE_BASE_STRIKE'), foe=kind_bundle(['SAND_BASE_SCOURING_HAND'], FOE, 'Undead'))
    sure_hit(engine)
    C4.use(engine, 'Radiance Strike', target=FOE)
    assert not engine.state.actors[ME].turn_flags.get('creature_kind_once:radiance_strike_unclean')


@pytest.mark.parametrize('kind,bonus', [('Undead', 4), (None, 0)])
def test_strike_portable_table_roundtrip_and_second_attack_same_turn(monkeypatch, tmp_path, kind, bonus):
    import zipfile
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.test_hidden_targeting import turn
    from tests.r10_fixup_support import cast_sender, commit
    from tests.test_lock2_persistence import act
    from tests.test_lock_choices import install
    owner, foe = 'actor:factory.aaaaaaaa', 'actor:factory.ffffffff'
    for pid in ('aaaaaaaa', 'ffffffff'):
        doc = h1_sheet(['RADIANCE_BASE_STRIKE'] if pid == 'aaaaaaaa' else ['SAND_BASE_SCOURING_HAND'])
        doc['identity']['display_name'] = 'Lightkeeper' if pid == 'aaaaaaaa' else 'Training opponent'
        if pid == 'ffffffff' and kind:
            doc['identity']['creature_type'] = kind
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    install(monkeypatch, 'd20_result', lambda *args: {'source_id': 'test:roll', 'operation': 'replace', 'natural_result': 10})
    def restore_action(engine, event, kwargs):
        if event == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == owner:
            engine.state.actors[owner].action_available = True
    install(monkeypatch, 'event', restore_action)
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'Radiance yard', 'width_squares': 12, 'height_squares': 8,
        'walls': [], 'starts': {'team1': [[3, 4]], 'team2': [[6, 4]]}})
    mid = combat.create_factory_match(project_ids=['aaaaaaaa'], opponent_actor_ids=[foe],
        control_modes={owner: 'MANUAL', foe: 'MANUAL'}, arena_id='battlefield:map.radiance-yard', match_seed='L8-RADIANCE')['match_id']
    table = TabletopService(combat, tmp_path)
    turn(table, mid, owner)
    commit(cast_sender(combat, table, mid, 'Radiance Strike', target=foe))
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    rolls = [r for r in loaded.engine.rolls if r.reason.startswith('DAMAGE') and 'RADIANCE_BASE_STRIKE' in r.reason]
    assert len(rolls) == 1 and rolls[0].modifier == bonus
    assert bool(loaded.engine.state.actors[owner].turn_flags.get('creature_kind_once:radiance_strike_unclean')) is bool(bonus)
    assert typed_executor.bears_mark(loaded.engine.state.actors[foe], owner, 'Dawnmark')
    assert not typed_executor.bears_mark(loaded.engine.state.actors[foe], foe, 'Dawnmark')
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    commit(cast_sender(combat, table, mid, 'Radiance Strike', target=foe))
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    assert [r for r in loaded.engine.rolls if r.reason.startswith('DAMAGE') and 'RADIANCE_BASE_STRIKE' in r.reason][-1].modifier == 0
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.current_actor_id == foe
    assert typed_executor.bears_mark(loaded.engine.state.actors[foe], owner, 'Dawnmark')
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.current_actor_id == owner
    assert not typed_executor.bears_mark(loaded.engine.state.actors[foe], owner, 'Dawnmark')
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


# ---------------------------------------------------------------- RADIANCE_BASE_STRIKE printed clauses not covered above
# The base row's own printed header and body: 60-foot reach, a Radiant Cultivation
# Attack whose damage scales by Cultivation Level, the Dawnmark the hit applies, and
# the row staying a non-owner ability. Each reads the real compiled action the player
# is offered, so a dropped ``range_ft``, ``dice_by_cl`` band or ``mark`` row fails here.

def strike_action(engine, actor_id=ME):
    return engine.action_catalog[C4.action_id(engine, actor_id, "Radiance Strike")]


@pytest.mark.parametrize("squares,targetable", [(12, True), (13, False)])
def test_strike_reaches_exactly_sixty_feet_and_no_further(squares, targetable):
    """Range: 60 feet -- the engine offers the target at 60 ft and withholds it at 65 ft."""
    from combat.gate2_runtime_models import Position

    engine = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE"))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert strike_action(engine).range_ft == 60  # the reach the engine actually enforces
    foe.position = Position(x=me.position.x + squares, y=me.position.y, z=0)
    assert engine._distance_actor_to_actor(me, foe) == squares * 5
    offered = {c.display_name: c.target_ids for c in engine.legal_candidates() if c.display_name == "Radiance Strike"}
    assert bool(FOE in (offered.get("Radiance Strike") or ())) is targetable


@pytest.mark.parametrize("cl,dice", [(1, (8,)), (4, (8,)), (5, (8, 8)), (10, (8, 8)),
                                     (11, (8, 8, 4)), (16, (8, 8, 4)), (17, (8, 8, 4, 4)), (20, (8, 8, 4, 4))])
def test_strike_damage_scales_on_the_printed_cultivation_level_bands(cl, dice):
    """Cultivation Level 1-4 1d8; 5-10 2d8; 11-16 3d8; 17-20 4d8 -- every band boundary."""
    engine = C4.fight(compile_character(h1_sheet(["RADIANCE_BASE_STRIKE"], cl=cl), actor_id=ME))
    sure_hit(engine)
    before = len(engine.rolls)
    C4.use(engine, "Radiance Strike", target=FOE)
    (roll,) = damage_rolls(engine, before, "RADIANCE_BASE_STRIKE")
    assert roll.dice == dice and roll.modifier == 0


def test_strike_hit_marks_the_target_with_your_dawnmark_until_the_start_of_your_next_turn():
    """Hit: 'apply your Dawnmark until the start of your next turn' -- and only on a hit."""
    engine = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE"))
    sure_hit(engine)
    me = engine.state.actors[ME]
    C4.use(engine, "Radiance Strike", target=FOE)
    (mark,) = [c for c in engine.state.actors[FOE].conditions.values() if "mark.dawnmark" in c.condition_id]
    assert mark.condition_id == typed_executor.mark_condition_id("Dawnmark", me.entity_id)
    assert mark.source_actor_id == me.entity_id
    assert "RADIANCE_BASE_STRIKE" in mark.source_definition_id
    assert mark.expires_on == "START_OF_MARKER_NEXT_TURN"  # an expiry name the engine removes

    missed = C4.fight(C4.bundle("RADIANCE_BASE_STRIKE"))
    missed.state.actors[FOE].armor_class = FAIL
    C4.use(missed, "Radiance Strike", target=FOE)
    assert not [c for c in missed.state.actors[FOE].conditions.values() if "mark.dawnmark" in c.condition_id]


def test_radiance_strike_is_a_non_owner_ability():
    """Without the base row nobody is offered Radiance Strike, so no mark and no damage reach out."""
    engine = C4.fight(kind_bundle(["SAND_BASE_SCOURING_HAND"], ME, cl=10))
    assert not [a for a in engine.state.actors[ME].action_ids if "RADIANCE" in a]
    assert "Radiance Strike" not in C4.legal(engine)
