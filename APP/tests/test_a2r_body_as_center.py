"""Body as Center: the four printed gravity talents may be
centered on the body for one less Stamina, and a centered area
rides its owner only until the start of the owner's next turn --
through CombatService, the session's execute_intent flow and a
cold reload."""
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import (ALLY, FOE, OWNER, candidate, fixture,
                                    reload, settle, turn)
from tests.auto_worker1_support import cell_send, resolve

INSIGHT = 'insight.body-as-center'
GRAVITIC_PULL = 'tianxia.talent.gravity.gravitic_pull'
GRAVITY_WELL = 'TAL_GRAVITY_GRAVITY_WELL'
CRUSHING_FIELD = 'TAL_GRAVITY_CRUSHING_FIELD'
FLIGHT_SUPPRESSION = 'TAL_GRAVITY_FLIGHT_SUPPRESSION'
STAMINA = 'resource:core.stamina'


def _owner_bundle(talents, *, insight=True, cl=11):
    document = sheet(talents, cl=cl)
    # Each centered talent prints "Cost: N CP or Stamina", so the
    # character keeps a Stamina Path pool beside its Qi pool: the
    # compiler then publishes the Stamina way to pay beside the
    # Cultivation Points way, and Body as Center centers both.
    document['ability_scores_and_statistics']['primary_resource']['definitions'] = [
        {'name': 'Stamina', 'max': 30}]
    if insight:
        document['spheres_and_talents']['cultivation_insight_record_ids'] = [INSIGHT]
    return compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})


def _variant(bundle, name):
    return next(a for a in bundle['action_catalog']
                if a['display_name'] == name)


def _centered(bundle, base_label, costs):
    """The centered variant of one talent that pays exactly `costs` (identity, not display text)."""
    rows = [a for a in bundle['action_catalog'] if a.get('variant')
            and a['variant']['base_label'] == base_label
            and any(c['axis'] == 'centering' for c in a['variant']['choices'])
            and a['costs'] == costs]
    assert len(rows) == 1, rows
    return rows[0]


def test_centered_variants_cost_one_less_stamina(tmp_path):
    # "you may center the effect on your body. If you do, reduce
    # the Stamina actually paid by 1, minimum 1": each printed
    # way to pay gets a centered variant -- the Stamina way
    # costs one less (never less than one), the Cultivation
    # Points way keeps its printed cost.
    bundle = _owner_bundle([CRUSHING_FIELD])
    plain = _variant(bundle, 'Crushing Field')
    stamina_way = _variant(bundle, 'Crushing Field (4 Stamina)')
    centered_cp = _centered(bundle, 'Crushing Field', [['resource:core.qi', 4]])
    centered_stamina = _centered(bundle, 'Crushing Field', [[STAMINA, 3]])
    assert plain['costs'] == [['resource:core.qi', 4]]
    assert stamina_way['costs'] == [[STAMINA, 4]]
    assert centered_cp['costs'] == [['resource:core.qi', 4]]
    assert centered_stamina['costs'] == [[STAMINA, 3]]
    # a centered area is placed on the fighter's own body
    assert centered_stamina['target_kind'] == 'SELF'
    assert centered_stamina['range_ft'] is None
    zone_spec = centered_stamina['parameters']['typed']['zone_spec']
    assert zone_spec['centered_on_self'] and zone_spec['follows_owner']


def test_gravitic_pull_centered_keeps_its_minimum(tmp_path):
    # "reduce the Stamina actually paid by 1, minimum 1": a
    # one-Stamina pull cannot be reduced below one.
    bundle = _owner_bundle([GRAVITIC_PULL])
    centered = _centered(bundle, 'Gravitic Pull', [[STAMINA, 1]])
    assert centered['costs'] == [[STAMINA, 1]]
    # the pull travels toward the caster: every forced-movement
    # row of the centered variant names the caster as its anchor
    effects = centered['parameters']['typed']['effects']
    rows = [e for branch in ('on_fail', 'on_success')
              for e in effects[0].get(branch) or []]
    assert rows and all(row.get('direction') == 'toward' for row in rows
                        if row.get('type') == 'forced_movement')


def test_a_centered_area_is_placed_on_the_body(tmp_path):
    combat, table, mid = fixture(tmp_path, [CRUSHING_FIELD], owner_insights=[INSIGHT])
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    settle(table, mid, candidate(
        combat, mid, 'Crushing Field + centered on you').candidate_id)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    zones = [zone for zone in engine.state.zones.values()
             if CRUSHING_FIELD in zone.source_definition_id]
    assert zones
    zone = zones[-1]
    assert (zone.center.x, zone.center.y) == (owner.position.x, owner.position.y)


def test_the_centered_area_rides_until_the_next_turn(tmp_path):
    # "The area moves with you only until the start of your next
    # turn ... After that point it remains at its current
    # location for the rest of its duration."
    combat, table, mid = fixture(tmp_path, [CRUSHING_FIELD], owner_insights=[INSIGHT])
    engine = reload(tmp_path, mid)
    settle(table, mid, candidate(
        combat, mid, 'Crushing Field + centered on you').candidate_id)
    engine = reload(tmp_path, mid)
    zone = next(zone for zone in engine.state.zones.values()
                if CRUSHING_FIELD in zone.source_definition_id)
    # the area rides the owner who walks away from it
    owner = engine.state.actors[OWNER]
    start = (owner.position.x, owner.position.y)
    resolve(cell_send(table, mid, 'Move', (start[0], start[1] + 2)))
    engine = reload(tmp_path, mid)
    zone = next(zone for zone in engine.state.zones.values()
                if CRUSHING_FIELD in zone.source_definition_id)
    owner = engine.state.actors[OWNER]
    assert (zone.center.x, zone.center.y) == (owner.position.x, owner.position.y)
    # ... but only until the start of the owner's next turn:
    # end this turn and advance the initiative back to the
    # owner, whose turn count has now moved past the turn
    # the area was centered on.
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    parked = (zone.center.x, zone.center.y)
    resolve(cell_send(table, mid, 'Move', (owner.position.x, owner.position.y + 2)))
    engine = reload(tmp_path, mid)
    zone = next(zone for zone in engine.state.zones.values()
                if CRUSHING_FIELD in zone.source_definition_id)
    owner = engine.state.actors[OWNER]
    assert (zone.center.x, zone.center.y) == parked
    assert (owner.position.x, owner.position.y) != parked


def test_a_centered_gravitic_pull_pulls_toward_the_body(tmp_path):
    # "center the effect on your body": the pull's point is the
    # caster's own body, so the target travels toward the
    # caster whether it saves or not.
    combat, table, mid = fixture(tmp_path, [GRAVITIC_PULL], owner_insights=[INSIGHT])
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    foe = engine.state.actors[FOE]
    before = abs(foe.position.x - owner.position.x) + abs(foe.position.y - owner.position.y)
    settle(table, mid, candidate(
        combat, mid, 'Gravitic Pull + centered on you',
        target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    foe = engine.state.actors[FOE]
    after = abs(foe.position.x - owner.position.x) + abs(foe.position.y - owner.position.y)
    assert after < before


def test_the_talents_are_unchanged_without_the_insight(tmp_path):
    # A fighter without the Insight gets no centered variants.
    bundle = _owner_bundle([CRUSHING_FIELD, GRAVITY_WELL,
                              FLIGHT_SUPPRESSION, GRAVITIC_PULL], insight=False)
    assert not [a for a in bundle['action_catalog']
                if 'centered on you' in a['display_name']]


def test_centering_is_structured_variant_identity_not_a_name(tmp_path):
    # VARIANTS22: the centered way is data -- one centering axis on the talent's
    # own base key, with the Stamina reduction as a signed delta on the paid pool.
    bundle = _owner_bundle([CRUSHING_FIELD])
    plain = _variant(bundle, 'Crushing Field')
    centered = _centered(bundle, 'Crushing Field', [[STAMINA, 3]])
    base = plain['source_definition_id']
    assert centered['variant']['base_key'] == base
    assert centered['source_definition_id'] == base + '#body_center'
    assert centered['variant']['choices'][-1] == {
        'axis': 'centering', 'key': 'self', 'label': 'centered on you',
        'costs': [[STAMINA, -1]]}
