"""Printed Music Insight transactions: CombatService, execute_intent, cold reload and replay."""
import pytest
from tests.test_auto72_music import (_add_test_action, TABLE_ME as ME, TABLE_ALLY as ALLY,
                                    TABLE_FOE as FOE, TABLE_FOE2 as FOE2, M)
from combat.ext.music_insights import RESONANCE, ENSEMBLE, UNSHAKEN, RESONANCE_USED, MISS_USED


def insight_arena(tmp_path, talents, topic, *, ac=None, ask_actors=(ME,),
                maximum_rounds=4, bundle_transform=None, automatic=False, ally_talents=()):
    """The hunt-27 table with two extra levers: a chosen Armour Class for any fighter, and a
    scenario's own typed actions.

    ``ac`` picks the defender's Armour Class so a scenario can put the attacker's roll exactly on it --
    a hit without the bell and a miss with it, on the same seeded dice.

    ``bundle_transform(bundles)`` may give a creature a plain typed action (a fixture lever, the way
    tests/test_c15_healing_choices.py prepares a wound and a fixed heal), so a scenario spends and
    refuses a printed effect through real table transactions instead of by poking saved state.
    """
    import json
    import zipfile

    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT, sheet
    from tests.test_carry import KIT

    ids = [ME, ALLY, FOE, FOE2]
    docs = [sheet(talents, cl=20, dc=22, kit={"starting_kit": KIT})] + [sheet([], cl=20, kit={"starting_kit": KIT}) for _ in range(3)]
    if ally_talents:
        docs[1] = sheet(ally_talents, cl=20, dc=22, kit={"starting_kit": KIT})
    for aid, doc, name in zip(ids, docs, ("You", "Ally", "East foe", "West foe")):
        doc["identity"]["display_name"] = name
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 200
        doc["ability_scores_and_statistics"]["primary_resource"]["maximum"] = 100
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={"ask": True} if aid in ask_actors else None)
               for aid, doc in zip(ids, docs)]
    if bundle_transform is not None:
        bundle_transform(bundles)
    for aid, bundle in zip(ids, bundles):
        value = (ac or {}).get(aid)
        if value is not None:
            bundle["actor_template"]["armor_class"] = value
    mid = combat._finish_factory_match(
        bundles, ids,
        {ME: "team:factory", ALLY: "team:factory", FOE: "team:opponents", FOE2: "team:opponents"},
        {ME: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 7}, FOE: {"x": 4, "y": 6}, FOE2: {"x": 5, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME, ALLY], [FOE, FOE2],
        control_modes={ME: "LOCAL_AUTO" if automatic else "MANUAL", **{aid: "MANUAL" for aid in ask_actors}},
        match_seed=f"AUTO72-{topic}-0", maximum_rounds=maximum_rounds, display_name="AUTO72f1 regression")["match_id"]
    return combat, TabletopService(combat, tmp_path), mid



from combat.gate5_service import CombatService
from tests.h1_support import ROOT

def table_commit(combat, table, mid, tmp_path, cid=None, choose=None):
    view = table.state(mid)
    menu = view["menu"]
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    real_controller = combat.controller
    if cid and not menu.get("manual"):
        from combat.gate4_adapters import ManualControllerAdapter
        requested = next(c for c in combat._load_session(mid).engine.legal_candidates() if c.candidate_id == cid)

        class Controller:
            def choose_primary_action(self, context):
                # The ordinary AI context may retain only representative area
                # destinations. Select the same ability from that legal menu.
                selected = next((c for c in context.legal_candidates if c.candidate_id == cid), None)
                if selected is None:
                    selected = next(c for c in context.legal_candidates if c.source_definition_id == requested.source_definition_id
                                    and c.target_ids == requested.target_ids)
                return ManualControllerAdapter(lambda _context: (selected.candidate_id, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real_controller, name)

        combat.controller = Controller()
    answers = []
    for _ in range(40):
        result = (table.act(mid, cid or menu["end_turn"], menu["decision_id"], menu["state_version"], view["last_sequence"], answers)
                  if menu.get("manual") else table.auto_step(mid, view["last_sequence"], answers))
        if result["status"] != "REACTION_REQUIRED":
            break
        assert CombatService(ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode="json") == before
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "USE"}
        if not prompt.get("choice") and choose and choose(prompt)=="DECLINE":
            answer["selection"]="DECLINE"
        if prompt.get("choice"):
            choice = prompt["choice"]
            selected = (choose(prompt) if choose else
                        [o["id"] for o in choice["options"][:choice.get("minimum", 1)]])
            answer["option_ids"] = selected or []
            if selected is None:
                answer["selection"] = "DECLINE"
        assert answer not in answers
        answers.append(answer)
    assert result["status"] == "COMMITTED", result
    combat.controller = real_controller
    expected = combat._load_session(mid).engine.state.model_dump(mode="json")
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.engine.state.model_dump(mode="json") == expected
    assert fresh.mechanical.replay()["status"] == "PASS"
    return answers


def table_next(combat, table, mid, tmp_path, choose=None):
    """Let whoever's turn it is end, until a foe with a live attack at the ally is the actor."""
    engine = combat._load_session(mid).engine
    candidates = engine.legal_candidates()
    cid = next((c.candidate_id for c in candidates if c.kind.value == "END_TURN"), candidates[0].candidate_id)
    table_commit(combat, table, mid, tmp_path, cid, choose=choose)


def _act_when(combat, table, mid, root, wanted, *, choose=None, limit=48):
    """Advance the table until ``wanted(engine, candidate)`` names a live action, then commit it.

    Every commit is a real transaction followed by a fresh load that must match and replay PASS
    (tests/test_hunt27_table.py), so anything this helper observes afterwards is read back off disk.
    """
    for _ in range(limit):
        engine = combat._load_session(mid).engine
        found = next((c for c in engine.legal_candidates() if wanted(engine, c)), None)
        if found is not None:
            return table_commit(combat, table, mid, root, found.candidate_id, choose=choose)
        table_next(combat, table, mid, root, choose=choose)
    raise AssertionError("the table never offered that action")



def perform(combat, table, mid, root, name, target=None, choose=None):
    return _act_when(combat, table, mid, root,
                     lambda engine, c: c.actor_id == ME and c.display_name == name
                     and (target is None or target in c.target_ids), choose=choose)


def setup(root, talents, name, **kw):
    root.mkdir()
    return insight_arena(root, talents, name, maximum_rounds=8, **kw)


def engine(combat, mid):
    return combat._load_session(mid).engine


@pytest.mark.parametrize('automatic', [False, True])
def test_resonance_only_hearing_allies_receive_round_limited_temp_hp(tmp_path, automatic):
    root = tmp_path / 'resonance'
    combat, table, mid = setup(root, [RESONANCE, M+'dissonant_note', M+'shared_measure'], 'resonance')
    # Owner's automatic mode is sealed at creation; the controller adapter chooses
    # a primary ability from its real legal AI menu; subchoices use real AI policy.
    if automatic:
        root2 = tmp_path / 'resonance-auto'
        def transform(bundles):
            bundles[0]['reaction_plan'] = {'ask': False}
        combat, table, mid = setup(root2, [RESONANCE, M+'dissonant_note'], 'resonance-auto', ask_actors=(), bundle_transform=transform, automatic=True)
        root = root2
    seen = []
    def choose(prompt):
        seen.append(prompt)
        if prompt['context'].get('reaction_source_id') == 'choice:needle.music_resonance':
            assert 'Dissonant Note' in prompt['moment']
            assert prompt['action'] == 'Dissonant Note'
            ids = [o['id'] for o in prompt['choice']['options']]
            assert ids == [ALLY], ids
            return [ALLY]
        return None
    perform(combat, table, mid, root, 'Dissonant Note', target=FOE, choose=choose)
    e = engine(combat, mid)
    assert e.state.actors[ALLY].temporary_hp == e.state.actors[ME].proficiency_bonus
    assert e.state.actors[ALLY].turn_flags[RESONANCE_USED] == e.state.round_number
    assert all(e.state.actors[a].temporary_hp == 0 for a in (ME, FOE, FOE2))
    if not automatic:
        assert any(p['context'].get('reaction_source_id') == 'choice:needle.music_resonance' for p in seen)
    if not automatic:
        spent_round=e.state.round_number
        perform(combat, table, mid, root, 'Shared Measure', choose=choose)
        e=engine(combat,mid)
        assert e.state.round_number==spent_round
        grants=[ev for ev in e.events if ev.event_type=='TEMP_HP_GRANTED' and ev.source_definition_id==RESONANCE]
        assert len(grants)==1, 'a second paid Music talent cannot grant the same ally the round benefit twice'
    # Next round resets recipient allowance; a second real paid Music use grants
    # its benefit again, with enemies in the same range throughout.
    perform(combat, table, mid, root, 'Dissonant Note', target=FOE, choose=choose)
    assert engine(combat, mid).state.actors[ALLY].turn_flags[RESONANCE_USED] == engine(combat, mid).state.round_number


@pytest.mark.parametrize('automatic', [False, True])
@pytest.mark.parametrize('native', [False, True])
def test_ensemble_selects_extra_willing_recipient_and_steps_on_actual_miss(tmp_path, automatic, native):
    root = tmp_path / 'ensemble'
    # Manual PB=1 proves the added slot; AI PB=4 exceeds the allied group.
    def transform(bundles):
        for action in bundles[0]['action_catalog']:
            if not automatic and (action['parameters'].get('typed') or {}).get('source') == M+'shared_measure':
                action['parameters']['typed']['numbers']['pb'] = 1
        for b in bundles:
            if b['actor_id'] == ALLY:
                _add_test_action(b, name='Test Miss', source_id='action:test.music_miss', target_kind='HOSTILE_ENTITY', range_ft=30,
                                effects=[{'type':'attack', 'attack_kind':'ranged', 'attack_bonus':-100,
                                          'dice':{'count':1,'sides':4}, 'damage_types':['piercing'], 'applies_to':'target'}])
                _add_test_action(b, name='Test Miss Again', source_id='action:test.music_miss_again', target_kind='HOSTILE_ENTITY', range_ft=30, economy='BONUS_ACTION',
                                effects=[{'type':'attack', 'attack_kind':'ranged', 'attack_bonus':-100,
                                          'dice':{'count':1,'sides':4}, 'damage_types':['piercing'], 'applies_to':'target'}])
        if native:
            for bundle in bundles:
                for action in bundle['action_catalog']:
                    if action['source_definition_id'] in ('action:test.music_miss','action:test.music_miss_again'):
                        action.update(resolution_kind='ATTACK', parameters={}, attack_bonus=-100,
                                      damage={'count':1,'sides':4,'modifier':0}, damage_type='PIERCING')
    combat, table, mid = setup(root, [M+'shared_measure', ENSEMBLE], 'ensemble',
                              ask_actors=((ALLY, FOE, FOE2) if automatic else (ME, ALLY, FOE, FOE2)),
                              ac={FOE:1000}, bundle_transform=transform, automatic=automatic)
    seen=[]
    def choose(prompt):
        seen.append(prompt)
        src=prompt['context'].get('reaction_source_id','')
        if src=='choice:needle.music_audience': return [ME, ALLY]
        if src=='choice:willing.consent': return ['accept']
        if src=='choice:needle.music_ensemble_target':
            assert 'Test Miss' in prompt['moment']
            assert prompt['action'] == 'Test Miss'
            return [ME]
        if src=='choice:needle.music_ensemble_step':
            assert 'Test Miss' in prompt['moment']
            assert prompt['action'] == 'Test Miss'
            options=prompt['choice']['options']
            return [next(o['id'] for o in options if 'Stay where you are' not in o.get('label', ''))]
        return None
    perform(combat, table, mid, root, 'Shared Measure', choose=choose)
    e=engine(combat,mid)
    assert all(any(c.condition_id=='condition:typed.music_shared_measure' for c in e.state.actors[a].conditions.values()) for a in (ME,ALLY))
    if not automatic:
        audience=next(p for p in seen if p['context'].get('reaction_source_id')=='choice:needle.music_audience')
        assert audience['choice']['maximum']==2
        assert 'Choose up to 2 willing creatures' in audience['moment']
    assert not any(c.condition_id=='condition:typed.music_shared_measure' for a in (FOE,FOE2) for c in e.state.actors[a].conditions.values())
    before=e.state.actors[ME].position
    _act_when(combat, table, mid, root, lambda e,c:c.actor_id==ALLY and c.display_name=='Test Miss' and FOE in c.target_ids, choose=choose)
    e=engine(combat,mid)
    assert any(ev.event_type=='ATTACK_ROLLED' and not ev.payload['provisional_hit'] for ev in e.events if ev.source_definition_id=='action:test.music_miss')
    assert e.state.actors[ME].position != before
    assert e.state.actors[ME].turn_flags[MISS_USED]==e.state.round_number
    assert not e.state.actors[ME].turn_flags.get('_round_music_shared'), 'miss clock is separate from the base hit clock'
    after=e.state.actors[ME].position
    spent_round=e.state.round_number
    _act_when(combat,table,mid,root,lambda e,c:c.actor_id==ALLY and c.display_name=='Test Miss Again' and FOE in c.target_ids,choose=choose)
    e=engine(combat,mid)
    assert e.state.round_number==spent_round and e.state.actors[ME].position==after
    assert len([ev for ev in e.events if ev.event_type=='PASSIVE_TRIGGERED' and ev.source_definition_id==ENSEMBLE])==1


@pytest.mark.parametrize('answer', ['accept', 'decline', 'nonmusic'])
def test_unshaken_forces_music_concentration_success_and_free_self_phrase(tmp_path, answer):
    root=tmp_path/'unshaken'
    def transform(bundles):
        bundles[0]['actor_template']['saving_throws']['CON']=-100
        if answer=='nonmusic':
            for action in bundles[0]['action_catalog']:
                typed=action['parameters'].get('typed') or {}
                if typed.get('source')==M+'war_song': typed['sphere']='tianxia.sphere.air'
        for b in bundles:
            if b['actor_id']==FOE:
                _add_test_action(b,name='Test Break Concentration',source_id='action:test.music_damage',target_kind='HOSTILE_ENTITY',range_ft=30,
                                effects=[{'type':'damage','flat':1,'damage_type':'force','applies_to':'target'}])
    combat,table,mid=setup(root,[UNSHAKEN,M+'war_song'], 'unshaken',ask_actors=(ME,ALLY,FOE,FOE2),bundle_transform=transform)
    def choose(prompt):
        src=prompt['context'].get('reaction_source_id','')
        if src=='choice:needle.music_unshaken_phrase':
            return [next(o['id'] for o in prompt['choice']['options'] if 'Temporary' in o.get('label','') or 'Temporary' in o.get('name',''))]
        if 'unshaken' in src: return 'USE' if answer=='accept' else 'DECLINE'
        return None
    perform(combat,table,mid,root,'Keep the Measure',choose=choose)
    perform(combat,table,mid,root,'War Song',choose=choose)
    _act_when(combat,table,mid,root,lambda e,c:c.actor_id==FOE and c.display_name=='Test Break Concentration' and ME in c.target_ids,choose=choose)
    e=engine(combat,mid)
    if answer!='accept':
        assert e.state.actors[ME].concentration is None
        assert e.state.actors[ME].temporary_hp==0
        assert not any(ev.source_definition_id==UNSHAKEN and ev.event_type=='PASSIVE_TRIGGERED' for ev in e.events)
        return
    assert e.state.actors[ME].concentration is not None
    save=next(ev for ev in reversed(e.events) if ev.event_type=='SAVE_ROLLED' and ev.source_definition_id=='system:combat.concentration')
    assert save.payload['total'] < save.payload['dc'] and save.payload['success'] is True
    assert e.state.actors[ME].temporary_hp==e.state.actors[ME].proficiency_bonus
    assert any(ev.source_definition_id==UNSHAKEN and ev.event_type=='PASSIVE_TRIGGERED' for ev in e.events)
    assert not getattr(e,'_typed_roll_outcome',{}), 'native concentration consumed the forced result'
    # Same fight, fresh service reload, next real damaging activation: allowance is spent.
    _act_when(combat,table,mid,root,lambda e,c:c.actor_id==FOE and c.display_name=='Test Break Concentration' and ME in c.target_ids,choose=choose)
    assert engine(combat,mid).state.actors[ME].concentration is None


def test_opening_phrase_round_limit_belongs_to_recipient_across_singers(tmp_path):
    root=tmp_path/'two-singers'
    combat,table,mid=setup(root, ['MUSIC_BASE_KEEP_THE_MEASURE'], 'two-singers',
                         ally_talents=['MUSIC_BASE_KEEP_THE_MEASURE'], ask_actors=(ME,ALLY,FOE,FOE2))
    for singer in (ME,ALLY):
        _act_when(combat,table,mid,root,lambda e,c:c.actor_id==singer and c.display_name=='Keep the Measure')
    start_round=engine(combat,mid).state.round_number
    while engine(combat,mid).state.round_number <= start_round:
        table_next(combat,table,mid,root)
    while engine(combat,mid).state.current_actor_id not in (ME,ALLY):
        table_next(combat,table,mid,root)
    e=engine(combat,mid)
    singer=e.state.current_actor_id
    other=ALLY if singer==ME else ME
    candidate=next(c for c in e.legal_candidates() if 'Opening Phrase' in c.display_name and 'Temporary' in c.display_name and ALLY in c.target_ids)
    table_commit(combat,table,mid,root,candidate.candidate_id)
    received_round=engine(combat,mid).state.round_number
    while engine(combat,mid).state.current_actor_id!=other:
        table_next(combat,table,mid,root)
    e=engine(combat,mid)
    assert e.state.round_number==received_round
    assert not any(c for c in e.legal_candidates() if c.actor_id==other and 'Opening Phrase' in c.display_name and ALLY in c.target_ids)
    assert any(c for c in e.legal_candidates() if c.actor_id==other and 'Opening Phrase' in c.display_name and ME in c.target_ids)


@pytest.mark.parametrize('followup', ['consume', 'expire'])
def test_unshaken_concentration_phrase_survives_granting_save_and_reload(tmp_path, followup):
    """Mid-save grant survives commit; exact instance is used once, or expires unused."""
    from combat.ext.music import OPENING_SAVE
    root = tmp_path / 'concentration-phrase'
    def transform(bundles):
        bundles[0]['actor_template']['saving_throws']['CON'] = 10
        for bundle in bundles:
            if bundle['actor_id'] == FOE:
                for name, source, economy, amounts in (
                    ('Break Concentration', 'action:test.phrase_break', 'ACTION', [100]),
                    ('Probe Concentration', 'action:test.phrase_probe', 'BONUS_ACTION', [1, 1]),
                ):
                    _add_test_action(bundle, name=name, source_id=source, economy=economy,
                                     target_kind='HOSTILE_ENTITY', range_ft=30,
                                     effects=[{'type':'damage', 'flat':amount, 'damage_type':'force',
                                               'applies_to':'target'} for amount in amounts])
    combat, table, mid = setup(root, [UNSHAKEN, M+'war_song'], 'phrase-receipt',
                              ask_actors=(ME, ALLY, FOE, FOE2), bundle_transform=transform)
    def choose(prompt):
        src = prompt['context'].get('reaction_source_id', '')
        if src == 'choice:needle.music_unshaken_phrase':
            return [next(o['id'] for o in prompt['choice']['options']
                         if 'Concentration' in o.get('label', o.get('name', '')))]
        if 'unshaken' in src:
            return 'USE'
        return None
    perform(combat, table, mid, root, 'Keep the Measure', choose=choose)
    perform(combat, table, mid, root, 'War Song', choose=choose)
    _act_when(combat, table, mid, root,
              lambda e,c: c.actor_id == FOE and c.display_name == 'Break Concentration' and ME in c.target_ids,
              choose=choose)
    # table_commit already verifies cold state equivalence and mechanical replay.
    combat = CombatService(ROOT, root)
    from combat.tabletop_service import TabletopService
    table = TabletopService(combat, root)
    e = engine(combat, mid)
    actor = e.state.actors[ME]
    held = next(c for c in actor.conditions.values()
                if c.condition_id == OPENING_SAVE and c.data.get('concentration'))
    iid, pb = held.instance_id, actor.proficiency_bonus
    saves = [ev for ev in e.events if ev.event_type == 'SAVE_ROLLED'
             and ev.source_definition_id == 'system:combat.concentration']
    assert len(saves) == 1 and saves[0].payload['success'] is True
    assert saves[0].payload['modifier'] == 10
    assert actor.concentration is not None
    if followup == 'expire':
        # End foe turn and cross the source's next turn before using the probe.
        while engine(combat, mid).state.current_actor_id != ME:
            table_next(combat, table, mid, root, choose=choose)
        assert iid not in engine(combat, mid).state.actors[ME].conditions
    _act_when(combat, table, mid, root,
              lambda e,c: c.actor_id == FOE and c.display_name == 'Probe Concentration' and ME in c.target_ids,
              choose=choose)
    e = engine(combat, mid)
    saves = [ev for ev in e.events if ev.event_type == 'SAVE_ROLLED'
             and ev.source_definition_id == 'system:combat.concentration']
    assert len(saves) == 3
    assert [ev.payload['modifier'] for ev in saves] == [10, 10 + (pb if followup == 'consume' else 0), 10]
    assert iid not in e.state.actors[ME].conditions
    removed = [ev for ev in e.events if ev.event_type == 'CONDITION_REMOVED'
               and ev.payload.get('instance_id') == iid]
    assert len(removed) == 1
    if followup == 'consume':
        assert removed[0].payload['reason'] == 'CONSUMED'
    else:
        assert removed[0].payload['checkpoint'] == 'START_OF_TURN'
    assert e.state.actors[ME].concentration is not None
