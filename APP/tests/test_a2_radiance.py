"""A2RADIANCE: real table commits, saved choices and fresh-service replay."""
import pytest
from combat import ext
from combat.factory_compiler import RESOURCE_IDS
from combat.ext.benefit_suppression import SUPPRESSED
from combat.ext.radiance_rescue import FEATURE, PENDING
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import fixture, OWNER, ALLY, FOE, settle, reload, turn
from tests.test_auto125_radiance import pick, next_owner_turn

GENTLE = 'tianxia.talent.radiance.gentle_dawn'
CP = RESOURCE_IDS['qi']


def condition_metadata(monkeypatch):
    def state(ctx, subject, effect):
        if 'test_data' in effect:
            return {'data': effect['test_data']}
    monkeypatch.setitem(ext._HOOKS, 'condition_state', [*ext._HOOKS.get('condition_state', []), state])


def affliction(name, *, ordinary=True, duration='one_minute'):
    return {'type': 'condition', 'condition': name, 'applies_to': 'target', 'duration': duration,
            'test_data': {'ordinary': ordinary, 'rule': {'attacks_have': 'DISADVANTAGE'}, 'label': name.replace('_', ' ').title()}}


def test_gentle_data_has_all_four_printed_categories():
    from tests.test_auto125_radiance import mech
    m = mech(GENTLE)
    assert m['coverage'] == 'FULL' and m['riders'] == []
    e = m['options'][2]['effects'][0]
    assert set(e['conditions']) == {'frightened', 'fear', 'despair', 'nausea', 'spiritual_chill'}


@pytest.mark.parametrize('name', ['frightened', 'fear', 'despair', 'nausea', 'spiritual_chill'])
def test_gentle_suppresses_chosen_affliction_and_restores_original_instance(tmp_path, monkeypatch, name):
    condition_metadata(monkeypatch)
    def prepare(b):
        add_action(b[0], 'Apply Affliction', [affliction(name)])
    combat, table, mid = fixture(tmp_path, [GENTLE], bundle_transform=prepare, seed='A2RADIANCE-GENTLE-'+name)
    settle(table, mid, pick(combat, mid, 'Apply Affliction', target=ALLY).candidate_id)
    e = reload(tmp_path, mid); c = next(c for c in e.state.actors[ALLY].conditions.values() if c.condition_id == 'condition:typed.'+name)
    iid, data = c.instance_id, dict(c.data)
    before = e.state.actors[OWNER].resources[CP]
    prompts = settle(table, mid, pick(combat, mid, 'Gentle Dawn: Suppress an Ordinary Affliction', target=ALLY).candidate_id,
                     picks={'choice:needle.named_suppression': iid})
    assert any("next turn starts" in str(p) and 'original duration keeps running' in str(p) for p in prompts)
    e = reload(tmp_path, mid); holder = e.state.actors[ALLY]
    assert iid not in holder.conditions
    assert len([c for c in holder.conditions.values() if c.condition_id == SUPPRESSED]) == 1
    assert e.state.actors[OWNER].resources[CP] == before - 1
    assert not e.state.actors[OWNER].action_available
    # It remains paused for intervening turns, then comes back at caster START.
    next_owner_turn(table, mid)
    restored = reload(tmp_path, mid).state.actors[ALLY].conditions[iid]
    assert restored.source_actor_id == OWNER and restored.data == data
    assert not any(c.condition_id == SUPPRESSED for c in reload(tmp_path, mid).state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('ordinary', [True, False])
def test_gentle_one_exact_instance_and_nonordinary_exclusion(tmp_path, monkeypatch, ordinary):
    condition_metadata(monkeypatch)
    def prepare(b):
        add_action(b[0], 'Apply Afflictions', [affliction('nausea', ordinary=ordinary), affliction('despair')])
    combat, table, mid = fixture(tmp_path, [GENTLE], bundle_transform=prepare)
    settle(table, mid, pick(combat, mid, 'Apply Afflictions', target=ALLY).candidate_id)
    e = reload(tmp_path, mid); h = e.state.actors[ALLY]
    nausea = next(c for c in h.conditions.values() if c.condition_id.endswith('.nausea'))
    despair = next(c for c in h.conditions.values() if c.condition_id.endswith('.despair'))
    prompts = settle(table, mid, pick(combat, mid, 'Gentle Dawn: Suppress an Ordinary Affliction', target=ALLY).candidate_id,
                     picks={'choice:needle.named_suppression': despair.instance_id})
    e = reload(tmp_path, mid); h = e.state.actors[ALLY]
    assert nausea.instance_id in h.conditions and despair.instance_id not in h.conditions
    options = next(p['choice']['options'] for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.named_suppression')
    assert (nausea.instance_id in [o['id'] for o in options]) is ordinary


def test_gentle_hidden_original_duration_expires_without_resurrection(tmp_path, monkeypatch):
    condition_metadata(monkeypatch)
    def prepare(b):
        add_action(b[0], 'Apply Affliction', [affliction('nausea', duration={'kind':'until_end_of_your_turn'})])
    combat, table, mid = fixture(tmp_path, [GENTLE], bundle_transform=prepare)
    settle(table, mid, pick(combat, mid, 'Apply Affliction', target=ALLY).candidate_id)
    iid = next(c.instance_id for c in reload(tmp_path, mid).state.actors[ALLY].conditions.values() if c.condition_id.endswith('.nausea'))
    settle(table, mid, pick(combat, mid, 'Gentle Dawn: Suppress an Ordinary Affliction', target=ALLY).candidate_id)
    next_owner_turn(table, mid)
    assert iid not in reload(tmp_path, mid).state.actors[ALLY].conditions


def test_gentle_temp_hp_once_per_recipient_and_actual_repeat_save(tmp_path, monkeypatch):
    condition_metadata(monkeypatch)
    def prepare(b):
        eff = affliction('poisoned'); eff['test_data']['origin_save'] = {'ability':'CON','dc':1}
        add_action(b[0], 'Apply Poison', [eff])
        b[1]['actor_template']['saving_throws']['CON'] = 50; seal(b[1])
    combat, table, mid = fixture(tmp_path, [GENTLE], bundle_transform=prepare)
    settle(table, mid, pick(combat, mid, 'Apply Poison', target=ALLY).candidate_id)
    settle(table, mid, pick(combat, mid, 'Gentle Dawn: Repeat Save vs Poisoned', target=ALLY).candidate_id)
    assert not any(c.condition_id.endswith('.poisoned') for c in reload(tmp_path, mid).state.actors[ALLY].conditions.values())
    next_owner_turn(table, mid)
    settle(table, mid, pick(combat, mid, 'Gentle Dawn: Temporary HP', target=ALLY).candidate_id)
    e = reload(tmp_path, mid)
    action = next(a for a in e.action_catalog.values() if a.owner_id == OWNER and a.display_name == 'Gentle Dawn: Temporary HP')
    n = action.parameters['typed']['numbers']
    assert e.state.actors[ALLY].temporary_hp == n['pb'] + n['key_mod']
    next_owner_turn(table, mid)
    assert not any(c.target_ids == (ALLY,) and 'Gentle Dawn: Temporary HP' == c.display_name for c in combat._load_session(mid).engine.legal_candidates())


def rescue_fixture(tmp_path, *, owned=True, enabled=True, immobile=False):
    def prepare(b):
        add_action(b[0], 'Lethal Necrotic', [{'type':'damage','applies_to':'target','flat':1000,'damage_types':['necrotic']}])
        if immobile:
            b[1]['actor_template']['speed_ft'] = 0
        if not enabled:
            for row in b[0]['typed_reactions'] if 'typed_reactions' in b[0] else b[0].get('typed_reaction_rows', []):
                for effect in row.get('effects') or []:
                    effect.pop('rescue_movement', None)
        seal(b[1]); seal(b[0])
    return fixture(tmp_path, [FEATURE] if owned else [], bundle_transform=prepare, seed='A2RADIANCE-RESCUE')


@pytest.mark.parametrize('who', [ALLY, OWNER])
@pytest.mark.parametrize('move', [True, False])
def test_morning_breath_movement_is_player_chosen_saved_and_free(tmp_path, who, move):
    combat, table, mid = rescue_fixture(tmp_path)
    initial = reload(tmp_path, mid); before = initial.state.actors[who].position
    budget = initial.state.actors[who].movement_remaining_ft
    cp = initial.state.actors[OWNER].resources[CP]
    cid = pick(combat, mid, 'Lethal Necrotic', target=who).candidate_id
    selected = 'step:5,6' if who == ALLY else 'step:3,5'
    prompts = settle(table, mid, cid, picks={'choice:needle.morning_breath':'move',
                     'choice:needle.morning_breath_move':selected if move else None})
    assert any('20 feet' in str(p) for p in prompts)
    e = reload(tmp_path, mid); target = e.state.actors[who]
    assert target.current_hp == 1
    assert (target.position != before) is move
    if move:
        assert (target.position.x, target.position.y) == ((5,6) if who == ALLY else (3,5))
    assert target.movement_remaining_ft == budget
    assert e.state.actors[OWNER].resources[CP] == cp - 8
    assert not e.state.actors[OWNER].reaction_available
    assert not any(c.condition_id == PENDING for c in target.conditions.values())
    assert not any(event.event_type == 'OPPORTUNITY_ATTACK_RESOLVED' for event in e.events)


def test_morning_breath_decline_and_unowned_do_not_move_or_spend(tmp_path):
    for owned in (True, False):
        root = tmp_path / str(owned)
        combat, table, mid = rescue_fixture(root, owned=owned)
        before = reload(root, mid).state.actors[OWNER].resources[CP]
        pos = reload(root, mid).state.actors[ALLY].position
        settle(table, mid, pick(combat, mid, 'Lethal Necrotic', target=ALLY).candidate_id,
               picks={'choice:needle.morning_breath':None})
        e = reload(root, mid)
        assert e.state.actors[ALLY].current_hp == 0 and e.state.actors[ALLY].position == pos
        assert e.state.actors[OWNER].resources[CP] == before


def test_morning_breath_legacy_saved_row_has_no_new_choice(tmp_path):
    combat, table, mid = rescue_fixture(tmp_path, enabled=False)
    prompts = settle(table, mid, pick(combat, mid, 'Lethal Necrotic', target=ALLY).candidate_id,
                     picks={'choice:needle.morning_breath':'manual'})
    first = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.morning_breath')
    assert 'move' not in [o['id'] for o in first['choice']['options']]
    assert reload(tmp_path, mid).state.actors[ALLY].current_hp == 1


def test_morning_breath_preview_rolls_back_before_any_cost_or_damage(tmp_path):
    from tests.worker2_support import act
    combat, table, mid = rescue_fixture(tmp_path)
    e = reload(tmp_path, mid); original = e.state.model_dump(mode='json')
    cid = pick(combat, mid, 'Lethal Necrotic', target=ALLY).candidate_id
    first = act(table, mid, cid, [])
    assert first['status'] == 'REACTION_REQUIRED'
    assert reload(tmp_path, mid).state.model_dump(mode='json') == original
    answer = {**first['reaction']['context'], 'selection':'USE','option_ids':['move']}
    second = act(table, mid, cid, [answer])
    assert second['status'] == 'REACTION_REQUIRED'
    assert second['reaction']['context']['reaction_source_id'] == 'choice:needle.morning_breath_move'
    assert reload(tmp_path, mid).state.model_dump(mode='json') == original
    assert 'No additional cost' in str(second['reaction'])
    destination = next(o['id'] for o in second['reaction']['choice']['options'])
    answer2 = {**second['reaction']['context'],'selection':'USE','option_ids':[destination]}
    assert act(table, mid, cid, [answer, answer2])['status'] == 'COMMITTED'
    assert reload(tmp_path, mid).state.actors[ALLY].current_hp == 1


def test_gentle_suppression_changes_actual_save_modes(tmp_path, monkeypatch):
    condition_metadata(monkeypatch)
    def prepare(b):
        eff = affliction('nausea'); eff['test_data']['rule'] = {'save_mode': {'WIS':'DISADVANTAGE'}}
        add_action(b[0], 'Apply Nausea', [eff])
        add_action(b[0], 'Probe Save', [{'type':'save','ability':'wis','applies_to':'target','on_fail':[],'on_success':[]}])
    combat, table, mid = fixture(tmp_path, [GENTLE], bundle_transform=prepare)
    settle(table, mid, pick(combat, mid, 'Apply Nausea', target=ALLY).candidate_id)
    def probe():
        settle(table, mid, pick(combat, mid, 'Probe Save', target=ALLY).candidate_id)
        e = reload(tmp_path, mid)
        return [event.payload['roll']['mode'] if 'roll' in event.payload else event.payload.get('mode')
                for event in e.events if event.event_type == 'SAVE_ROLLED'][-1]
    assert probe() == 'DISADVANTAGE'
    settle(table, mid, pick(combat, mid, 'Gentle Dawn: Suppress an Ordinary Affliction', target=ALLY).candidate_id)
    assert probe() == 'NORMAL'
    next_owner_turn(table, mid)
    assert probe() == 'DISADVANTAGE'


BLESSING = 'insight.radiance-s-blessing'


def blessing_fixture(tmp_path, *, primary='Qi', owned=True, legacy=False, spent=5):
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    def prepare(b):
        doc = sheet(['RADIANCE_BASE_STRIKE'], cl=15, primary=primary)
        doc['identity']['path'] = {'Qi':'Qi Cultivation','Stamina':'Body Refining','Resonance':'Spirit Awakening'}[primary]
        doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
        if owned:
            doc['spheres_and_talents']['cultivation_insight_record_ids'] = [BLESSING]
        b[0] = compile_character(doc, actor_id=OWNER, reaction_plan={'ask':True})
        if legacy:
            b[0]['typed_passives'] = [r for r in b[0]['typed_passives'] if r.get('block') != 'radiance_blessing']
        add_action(b[0], 'Spend CP', [{'type':'spend_resource','applies_to':'self','resource_id':RESOURCE_IDS[primary.lower()], 'flat':spent}], target='SELF')
        add_action(b[0], 'Block Recovery', [{'type':'condition','condition':'no_cp_regain','applies_to':'self','expires_on':'UNTIL_REMOVED'}], target='SELF')
        add_action(b[1], 'End Recovery Block', [{'type':'remove_condition','condition':'no_cp_regain','applies_to':'target'}])
        add_action(b[0], 'Prevent Circulation', [{'type':'condition','condition':'frightened','applies_to':'self','expires_on':'UNTIL_REMOVED',
            'test_data':{'rule':{'radiance_circulation_blocked':True}}}], target='SELF')
        add_action(b[1], 'End Circulation Block', [{'type':'remove_condition','condition':'frightened','applies_to':'target'}])
        add_action(b[0], 'Become Unconscious', [{'type':'condition','condition':'unconscious','applies_to':'self','expires_on':'UNTIL_REMOVED'}], target='SELF')
        add_action(b[1], 'Awaken', [{'type':'remove_condition','condition':'unconscious','applies_to':'target'}])
        for condition in ('incapacitated', 'paralyzed', 'life_unconscious'):
            add_action(b[0], 'Become ' + condition, [{'type':'condition','condition':condition,
                'applies_to':'self','expires_on':'UNTIL_REMOVED'}], target='SELF')
        seal(b[0])
    return fixture(tmp_path, ['RADIANCE_BASE_STRIKE'], bundle_transform=prepare, primary=primary, seed='A2RADIANCE-BLESSING')


def blessing_next_turn(combat, table, mid, *, decline=False):
    assert table.state(mid)['menu']['actor_id'] == OWNER
    prompts = settle(table, mid, table.state(mid)['menu']['end_turn'], picks={'choice:needle.radiance_blessing':None if decline else 'recover'})
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == OWNER:
            return prompts
        prompts += settle(table, mid, table.state(mid)['menu']['end_turn'], picks={'choice:needle.radiance_blessing':None if decline else 'recover'})
    raise AssertionError('no owner turn')


@pytest.mark.parametrize('condition,block,eligible', [
    ('incapacitated', None, True),
    ('paralyzed', None, True),
    ('unconscious', None, False),
    ('life_unconscious', None, False),
    ('incapacitated', 'Block Recovery', False),
    ('paralyzed', 'Prevent Circulation', False),
])
def test_blessing_conscious_action_denial_vs_recovery_blocks(tmp_path, monkeypatch, condition, block, eligible):
    """Commit real conditions, resolve the next-turn choice, then cold-load/replay."""
    from combat.ext.radiance_blessing import USED
    condition_metadata(monkeypatch)
    combat, table, mid = blessing_fixture(tmp_path)
    settle(table, mid, pick(combat, mid, 'Spend CP').candidate_id)
    if block:
        settle(table, mid, pick(combat, mid, block).candidate_id)
    label = 'Become Unconscious' if condition == 'unconscious' else 'Become ' + condition
    settle(table, mid, pick(combat, mid, label).candidate_id)
    before = reload(tmp_path, mid).state.actors[OWNER]
    assert before.current_hp > 0 and before.resources[CP] == 95
    assert any(c.condition_id == 'condition:typed.' + condition for c in before.conditions.values())
    prompts = blessing_next_turn(combat, table, mid)
    choices = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.radiance_blessing']
    assert bool(choices) is eligible
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.resources[CP] == (99 if eligible else 95)
    assert bool(actor.turn_flags.get(USED)) is eligible
    gains = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED' and e.source_definition_id == BLESSING]
    assert len(gains) == int(eligible)
    if eligible:
        assert choices[0]['context']['reactor_id'] == OWNER
        assert 'No action or resource cost' in str(choices[0])
        assert gains[0].payload['gained'] == 4
    # Neither accepting recovery nor rejecting eligibility clears the condition;
    # the once-scene flag and resource result also survive another committed turn.
    assert any(c.condition_id == 'condition:typed.' + condition for c in actor.conditions.values())
    blessing_next_turn(combat, table, mid)
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert actor.resources[CP] == (99 if eligible else 95)
    assert bool(actor.turn_flags.get(USED)) is eligible


@pytest.mark.parametrize('primary', ['Qi', 'Stamina', 'Resonance'])
def test_blessing_real_path_pool_once_scene_no_action_and_cold_reload(tmp_path, primary):
    from combat.ext.radiance_blessing import USED
    combat, table, mid = blessing_fixture(tmp_path, primary=primary)
    pool = RESOURCE_IDS[primary.lower()]
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].resources[pool] == 100 and not e.state.actors[OWNER].turn_flags.get(USED)
    settle(table, mid, pick(combat, mid, 'Spend CP').candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[pool] == 95
    prompts = blessing_next_turn(combat, table, mid)
    e = reload(tmp_path, mid); a = e.state.actors[OWNER]
    assert a.resources[pool] == 99 and a.turn_flags[USED] == 1
    assert a.action_available and a.bonus_action_available and a.reaction_available
    assert any('once this scene' in str(p) and 'No action or resource cost' in str(p) for p in prompts)
    gains = [x for x in e.events if x.event_type == 'RESOURCE_GAINED' and x.source_definition_id == BLESSING]
    assert len(gains) == 1 and gains[0].payload['gained'] == 4
    settle(table, mid, pick(combat, mid, 'Spend CP').candidate_id)
    blessing_next_turn(combat, table, mid)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[pool] == 94


@pytest.mark.parametrize('control', ['unowned','legacy','decline','blocked','unconscious','circulation'])
def test_blessing_does_not_consume_while_ineligible_or_declined(tmp_path, monkeypatch, control):
    condition_metadata(monkeypatch)
    from combat.ext.radiance_blessing import USED
    combat, table, mid = blessing_fixture(tmp_path, owned=control!='unowned', legacy=control=='legacy')
    settle(table, mid, pick(combat, mid, 'Spend CP').candidate_id)
    if control in ('blocked','unconscious','circulation'):
        label = {'blocked':'Block Recovery','unconscious':'Become Unconscious','circulation':'Prevent Circulation'}[control]
        settle(table, mid, pick(combat, mid, label).candidate_id)
    prompts = blessing_next_turn(combat, table, mid, decline=control=='decline')
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].resources[CP] == 95 and not e.state.actors[OWNER].turn_flags.get(USED)
    assert bool([p for p in prompts if p['context']['reaction_source_id']=='choice:needle.radiance_blessing']) is (control=='decline')
    if control in ('blocked','unconscious','circulation'):
        turn(table, mid, ALLY)
        label={'blocked':'End Recovery Block','unconscious':'Awaken','circulation':'End Circulation Block'}[control]
        settle(table, mid, pick(combat, mid, label, target=OWNER).candidate_id)
        turn(table, mid, OWNER)
    elif control=='decline':
        blessing_next_turn(combat, table, mid)
    else:
        return
    assert reload(tmp_path, mid).state.actors[OWNER].resources[CP] == 99


def test_blessing_caps_recovery_and_uses_no_full_pool_turn(tmp_path):
    from combat.ext.radiance_blessing import USED
    combat, table, mid = blessing_fixture(tmp_path, spent=1)
    blessing_next_turn(combat, table, mid)
    assert not reload(tmp_path, mid).state.actors[OWNER].turn_flags.get(USED)
    settle(table, mid, pick(combat, mid, 'Spend CP').candidate_id)
    blessing_next_turn(combat, table, mid)
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].resources[CP] == 100
    gain = next(e for e in e.events if e.event_type=='RESOURCE_GAINED' and e.source_definition_id==BLESSING)
    assert gain.payload['requested'] == 4 and gain.payload['gained'] == 1


@pytest.mark.parametrize('owner_auto', [False, True])
def test_morning_breath_owner_choice_during_actual_ai_attack(tmp_path, owner_auto):
    import json
    def prepare(b):
        add_action(b[2], 'Enemy Lethal', [{'type':'damage','applies_to':'target','flat':1000,'damage_types':['necrotic']}], target='HOSTILE_ENTITY')
        b[2]['action_catalog'][-1]['parameters'].update(player_only=False, expected_damage=1000)
        seal(b[2])
    combat, table, mid = fixture(tmp_path, [FEATURE], bundle_transform=prepare,
                                positions={OWNER:{'x':3,'y':5}, ALLY:{'x':4,'y':5}, FOE:{'x':17,'y':5}},
                                seed='A2RADIANCE-AI-RESCUE')
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO' if owner_auto else 'MANUAL')
    e = reload(tmp_path, mid); cp = e.state.actors[OWNER].resources[CP]
    before = {a: e.state.actors[a].position for a in (OWNER, ALLY)}
    prompts = settle(table, mid, None, auto=True, picks={'choice:needle.morning_breath':'move', 'choice:needle.morning_breath_move':'first'})
    e = reload(tmp_path, mid)
    rescued = [a for a in (OWNER, ALLY) if e.state.actors[a].current_hp == 1]
    assert len(rescued) == 1
    target = rescued[0]
    assert e.state.actors[target].position != before[target]
    assert e.state.actors[OWNER].resources[CP] == cp-8
    assert bool(prompts) is (not owner_auto)
    if not owner_auto:
        initial = next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.morning_breath')
        destination = next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.morning_breath_move')
        assert initial['context']['reactor_id'] == OWNER and destination['context']['reactor_id'] == OWNER
        assert initial['cost'] == '8 Cultivation Points and your Reaction; once per long rest'
        assert initial['action'] == 'Enemy Lethal'
        assert initial['trigger_actor'] == e.state.actors[FOE].display_name
        assert destination['cost'] == 'No additional cost'
        (tmp_path/'rescue-prompts.json').write_text(json.dumps(prompts,indent=2))


def test_gentle_protected_source_and_duplicate_instance_labels(tmp_path, monkeypatch):
    condition_metadata(monkeypatch)
    def prepare(b):
        add_action(b[0], 'Secret Fear', [affliction('fear')], typed={'source_category':'Secret Inheritance'})
        add_action(b[0], 'Nausea Copies', [affliction('nausea'), affliction('nausea')])
    combat, table, mid = fixture(tmp_path, [GENTLE], bundle_transform=prepare)
    settle(table, mid, pick(combat, mid, 'Secret Fear', target=ALLY).candidate_id)
    settle(table, mid, pick(combat, mid, 'Nausea Copies', target=ALLY).candidate_id)
    e=reload(tmp_path,mid);secret=next(c.instance_id for c in e.state.actors[ALLY].conditions.values() if c.condition_id.endswith('.fear'))
    prompts=settle(table,mid,pick(combat,mid,'Gentle Dawn: Suppress an Ordinary Affliction',target=ALLY).candidate_id)
    choice=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.named_suppression')
    assert secret not in [o['id'] for o in choice['choice']['options']]
    assert 'copy 1 of 2' in str(choice) and 'copy 2 of 2' in str(choice)
    e=reload(tmp_path,mid)
    assert secret in e.state.actors[ALLY].conditions
    assert len([c for c in e.state.actors[ALLY].conditions.values() if c.condition_id.endswith('.nausea')])==1
