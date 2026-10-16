"""OPUS1 batch 1: Body-path martial Insights through the real table, with cold reloads.

Sword-Line Meridian, Avalanche Shoulder, Ashura Furnace and Iron Shirt Adept used to compile to
nothing (HUNT177 CONFIRMED 2). Each test drives the printed trigger through TabletopService, then
reloads the saved fight and reads the committed result. Four roster-owned Insights with no fight
effect are checked on the character sheet's Insight boundary instead.
"""
from types import SimpleNamespace

from combat.ext import martial_insights as mi
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import FOE, OWNER, candidate, fixture, prompt_turn, reload, settle


def _sturdy_foe(score=14):
    """Easy to hit, hard to drop: every strike lands and the creature stays up."""
    foe = sheet([], cl=15, score=score)
    foe['ability_scores_and_statistics']['armor_class']['base_value'] = 1
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 200
    return foe


def _move(table, combat, mid, actor, to):
    engine = combat._load_session(mid).engine
    row = next(c for c in engine.legal_candidates()
               if c.kind == 'MOVE' and c.actor_id == actor and c.destination and (c.destination.x, c.destination.y) == to
               and not c.destination.z)
    settle(table, mid, row.candidate_id)


def _passive(engine, feature):
    return [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED' and e.source_definition_id == f'passive:{feature}']


def _after(engine, source, event_type, target):
    """Damage committed to ``target`` after ``source`` paid or rolled for it (riders that are part of the hit
    commit under the striking action's own source id)."""
    start = next(i for i, e in enumerate(engine.events) if e.source_definition_id == source and e.event_type == event_type)
    return [e for e in engine.events[start:] if e.event_type == 'DAMAGE_COMMITTED' and target in e.target_ids]


def _damage(engine, source, target):
    return [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id == source
            and target in e.target_ids]


# ------------------------------------------------------------------------------------------ Sword-Line Meridian
def test_sword_line_meridian_run_up_hit_adds_pb_and_offers_a_free_step(tmp_path):
    combat, table, mid = fixture(tmp_path, [], owner_insights=[mi.SWORD_LINE], foe_sheet=_sturdy_foe(),
                                 positions={OWNER: {'x': 1, 'y': 6}, 'actor:factory.worker2-ally': {'x': 1, 'y': 9},
                                            FOE: {'x': 6, 'y': 6}})
    assert mi.owned(reload(tmp_path, mid), reload(tmp_path, mid).state.actors[OWNER], mi.SWORD_LINE)
    _move(table, combat, mid, OWNER, (5, 6))
    strike = candidate(combat, mid, 'Unarmed Strike', target=FOE)
    prompts = settle(table, mid, strike.candidate_id, picks={'choice:needle.insights8_step': 'first'})
    assert any('Sword-Line Meridian' in str(p) for p in prompts)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert len(_passive(engine, mi.SWORD_LINE)) == 1
    assert owner.turn_flags.get('martial_insights:' + mi.SWORD_LINE)  # once per turn, survives reload
    assert f"deals {owner.proficiency_bonus} extra damage" in _passive(engine, mi.SWORD_LINE)[0].payload['log']
    assert (owner.position.x, owner.position.y) != (5, 6)  # the free 5-foot step was taken


def test_sword_line_meridian_needs_the_run_up(tmp_path):
    combat, table, mid = fixture(tmp_path, [], owner_insights=[mi.SWORD_LINE], foe_sheet=_sturdy_foe(),
                                 foe_position={'x': 4, 'y': 6}, ally_position={'x': 1, 'y': 9})
    strike = candidate(combat, mid, 'Unarmed Strike', target=FOE)
    settle(table, mid, strike.candidate_id)
    engine = reload(tmp_path, mid)
    assert not _passive(engine, mi.SWORD_LINE)


# ------------------------------------------------------------------------------------------- Avalanche Shoulder
def test_avalanche_shoulder_spends_stamina_for_2d6_and_a_push_prone(tmp_path):
    combat, table, mid = fixture(tmp_path, [], owner_insights=[mi.AVALANCHE], foe_sheet=_sturdy_foe(score=1),
                                 primary='Stamina',
                                 positions={OWNER: {'x': 1, 'y': 6}, 'actor:factory.worker2-ally': {'x': 1, 'y': 9},
                                            FOE: {'x': 6, 'y': 6}})
    _move(table, combat, mid, OWNER, (5, 6))
    stamina = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.stamina']
    strike = candidate(combat, mid, 'Unarmed Strike', target=FOE)
    prompts = settle(table, mid, strike.candidate_id, picks={'choice:needle.martial_insights': 'use',
                                                              'choice:needle.displacement_distance': '10'})
    asked = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.martial_insights')
    assert 'Avalanche Shoulder' in str(asked) and '1 Stamina' in str(asked)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert owner.resources['resource:core.stamina'] == stamina - 1
    extra = _after(engine, mi.AVALANCHE, 'RESOURCE_SPENT', FOE)
    assert extra and extra[0].payload.get('damage_type') == 'BLUDGEONING'
    assert any(e.event_type == 'SAVE_ROLLED' and e.source_definition_id == mi.AVALANCHE for e in engine.events)
    assert any(c.condition_id.endswith('prone') for c in foe.conditions.values())
    assert foe.position.x > 6


def test_avalanche_shoulder_declined_costs_nothing(tmp_path):
    combat, table, mid = fixture(tmp_path, [], owner_insights=[mi.AVALANCHE], foe_sheet=_sturdy_foe(score=1),
                                 primary='Stamina',
                                 positions={OWNER: {'x': 1, 'y': 6}, 'actor:factory.worker2-ally': {'x': 1, 'y': 9},
                                            FOE: {'x': 6, 'y': 6}})
    _move(table, combat, mid, OWNER, (5, 6))
    stamina = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.stamina']
    settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=FOE).candidate_id,
           picks={'choice:needle.martial_insights': None})  # the player declines
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources['resource:core.stamina'] == stamina
    assert not any(e.source_definition_id == mi.AVALANCHE for e in engine.events)


# ----------------------------------------------------------------------------------------------- Ashura Furnace
def _crushing_foe(bundles):
    """The foe carries one heavy native blow, so the owner is below half Hit Points after a real hit."""
    from tests.worker2_support import sealed_native_attack
    sealed_native_attack(bundles[2], 'Crush', damage_type='BLUDGEONING', count=1, sides=2, modifier=33,
                         attack_bonus=40, range_ft=5)


def test_ashura_furnace_below_half_adds_chosen_necrotic_once_per_turn(tmp_path):
    combat, table, mid = fixture(tmp_path, [], owner_insights=[mi.ASHURA], foe_sheet=_sturdy_foe(),
                                 foe_position={'x': 4, 'y': 6}, ally_position={'x': 1, 'y': 9}, bundle_transform=_crushing_foe)
    prompt_turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Crush', target=OWNER).candidate_id)
    prompt_turn(table, mid, OWNER)
    wounded = reload(tmp_path, mid).state.actors[OWNER]
    assert wounded.current_hp * 2 < wounded.maximum_hp
    prompts = settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=FOE).candidate_id,
                     picks={'choice:needle.martial_insights': 'NECROTIC'})
    assert any('Ashura Furnace' in str(p) for p in prompts)
    engine = reload(tmp_path, mid)
    pb = engine.state.actors[OWNER].proficiency_bonus
    extra = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and FOE in e.target_ids
             and e.payload.get('damage_type') == 'NECROTIC']
    assert len(extra) == 1 and int(extra[0].payload.get('hp_damage') or 0) == pb
    owner = engine.state.actors[OWNER]
    assert owner.turn_flags.get('martial_insights:' + mi.ASHURA)
    assert mi.ashura_courage(SimpleNamespace(engine=engine), owner, 'WIS', {'frightened'}) == {'bonus': 0, 'modes': ['ADVANTAGE']}


def test_ashura_furnace_is_dark_above_half_hit_points(tmp_path):
    combat, table, mid = fixture(tmp_path, [], owner_insights=[mi.ASHURA], foe_sheet=_sturdy_foe(),
                                 foe_position={'x': 4, 'y': 6}, ally_position={'x': 1, 'y': 9})
    prompts = settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=FOE).candidate_id)
    assert not any('Ashura Furnace' in str(p) for p in prompts)
    engine = reload(tmp_path, mid)
    assert not _damage(engine, mi.ASHURA, FOE)
    owner = engine.state.actors[OWNER]
    assert mi.ashura_courage(SimpleNamespace(engine=engine), owner, 'WIS', {'frightened'}) is None
    assert mi.ashura_footing(engine, owner) is None


# --------------------------------------------------------------------------------------------- Iron Shirt Adept
def test_iron_shirt_adept_rebounds_a_hostile_unarmed_strike(tmp_path):
    combat, table, mid = fixture(tmp_path, [], owner_insights=[mi.IRON_SHIRT], foe_position={'x': 4, 'y': 6},
                                 ally_position={'x': 1, 'y': 9}, owner_ac=1)
    prompt_turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    pb = engine.state.actors[OWNER].proficiency_bonus
    rebound = _damage(engine, mi.IRON_SHIRT, FOE)
    assert len(rebound) == 1 and rebound[0].payload.get('damage_type') == 'BLUDGEONING'
    assert int(rebound[0].payload.get('hp_damage') or 0) + int(rebound[0].payload.get('temporary_hp_absorbed') or 0) == pb
    owner = engine.state.actors[OWNER]
    assert mi.iron_shirt_fall(engine, owner, 30, None, None) == {'amount': max(0, 30 - 5 * pb)}
    ctx = SimpleNamespace(engine=engine, intent=None, actor=engine.state.actors[FOE],
                          action=SimpleNamespace(display_name='Venom Spit'))
    assert mi.iron_shirt_save(ctx, owner, 'CON', {'poisoned'}) == {'bonus': 0, 'modes': ['ADVANTAGE']}
    assert mi.iron_shirt_save(ctx, owner, 'CON', {'poisoned'}) is None  # once per scene
    owner.resources[mi.FOCUS] = 0
    assert mi.iron_shirt_fall(engine, owner, 30, None, None) is None  # no Martial Focus, no benefit


# ---------------------------------------------------------------------------- roster Insights with no fight effect
def test_roster_insights_without_fight_effects_read_as_checked_not_missing():
    document = sheet([], cl=12)
    document.setdefault('spheres_and_talents', {})['cultivation_insight_record_ids'] = [
        'insight.butcher-s-mercy', 'insight.guardian-body-adept', 'insight.clean-quarantine-reputation',
        'insight.clean-tongued-disciple', mi.SWORD_LINE]
    bundle = compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})
    rows = {row['id']: row for row in bundle['diagnostics']['insights']}
    for key in ('insight.butcher-s-mercy', 'insight.guardian-body-adept', 'insight.clean-quarantine-reputation',
                'insight.clean-tongued-disciple'):
        assert rows[key]['status'] == 'partial' and 'has been checked' in rows[key]['explanation'], rows[key]
        assert 'insight.' not in rows[key]['explanation']
    assert rows[mi.SWORD_LINE]['status'] == 'automated', rows[mi.SWORD_LINE]
