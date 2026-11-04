"""Printed creature types persist without reclassifying old saved fighters."""
import copy
import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActorState, ActorTemplate
from combat.gate3_reducer import canonical_state_sha256
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_summons import ROOT, OWNER, _sheet
from tests.test_lock2_persistence import act
from tests.test_c3ar_runtime_executability import runtime_package, adapter, bundle, runtime_engine


def test_factory_carries_only_explicit_printed_types():
    sheet = _sheet([])
    sheet['identity'].update(creature_type=' Humanoid ', creature_types=['Unclean', 'humanoid'])
    template = compile_character(sheet, actor_id=OWNER)['actor_template']
    assert template['creature_types'] == ['Humanoid', 'Unclean']
    sheet['identity'] = {'name': 'Undead Beast', 'race': 'Dragon', 'description': 'An Unclean spirit'}
    assert 'creature_types' not in compile_character(sheet, actor_id=OWNER)['actor_template']


def test_factory_summon_and_roster_types_survive_table_commit_reload(tmp_path):
    from combat.creature_types import types_for, has_type
    project = 'aaaaaaaa'
    owner = FACTORY_ACTOR_PREFIX + project
    sheet = _sheet(['tianxia.talent.ink.painted_beast', 'TAL_DEATH_CORPSE_SERVANT'])
    sheet['identity']['creature_type'] = 'Humanoid'
    archive = tmp_path / 'portable_characters' / project / 'current.zip'
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(sheet))
    service = CombatService(ROOT, tmp_path)
    mid = service.create_factory_match(project_ids=[project], opponent_actor_ids=[AN],
        control_modes={owner: 'MANUAL', AN: 'MANUAL'}, match_seed='LOCK4-TYPES')['match_id']
    table = TabletopService(service, tmp_path)
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    session = service._load_session(mid)
    actors = session.engine.state.actors
    assert types_for(actors[owner]) == ('Humanoid',)
    assert types_for(actors[AN]) == ()  # The sample roster has no printed type.
    summons = [a for a in actors.values() if a.summon]
    beast = next(a for a in summons if a.summon['group'] == 'painted_beast')
    assert has_type(beast, 'construct') and not has_type(beast, 'Beast')
    assert all(types_for(a) == () for a in summons if a.summon['group'] == 'corpse_servant')
    digest = canonical_state_sha256(session.engine.state)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert canonical_state_sha256(fresh.engine.state) == digest
    assert fresh.verify()['status'] == 'PASS'


@pytest.mark.parametrize('encoded', ['no', '1', '0'])
def test_summon_physiology_ingestion_rejects_conflicts_or_persists_reconciled_traits(tmp_path, monkeypatch, encoded):
    from combat import summons
    from combat.creature_types import types_for
    from combat.physiology import trait
    table_rules = summons.rules()
    table_rules['creatures']['corpse_servant'].update(
        creature_type='Humanoid', creature_types=[f'physiology:breath_dependent:{encoded}'],
        physiology={'breath_dependent': False})
    rules_path = tmp_path / 'summon-rules.json'
    rules_path.write_text(json.dumps(table_rules))
    monkeypatch.setattr(summons, 'RULES_PATH', rules_path)
    sheet = _sheet(['TAL_DEATH_CORPSE_SERVANT'])
    if encoded != '0':
        with pytest.raises(ValueError, match='physiology'):
            compile_character(sheet, actor_id=OWNER)
        return
    project = 'physiology-summoner'
    owner = FACTORY_ACTOR_PREFIX + project
    archive = tmp_path / 'portable_characters' / project / 'current.zip'
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(sheet))
    service = CombatService(ROOT, tmp_path)
    mid = service.create_factory_match(project_ids=[project], opponent_actor_ids=[AN],
        control_modes={owner: 'MANUAL', AN: 'MANUAL'}, match_seed='SOL94R-SUMMON')['match_id']
    table = TabletopService(service, tmp_path)
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    servants = [a for a in fresh.engine.state.actors.values() if a.summon]
    assert servants
    for servant in servants:
        assert servant.creature_types == ('Humanoid', 'physiology:breath_dependent:0')
        assert types_for(servant) == ('Humanoid',)
        assert trait(servant, 'breath_dependent') is False
    assert fresh.verify()['status'] == 'PASS'


def test_old_bundles_are_not_backfilled_and_empty_fields_keep_exact_bytes():
    from combat.creature_types import types_for
    saved = compile_character(_sheet(['tianxia.talent.ink.painted_beast']), actor_id=OWNER)
    saved = copy.deepcopy(saved)
    saved['actor_template'].pop('creature_types', None)
    for record in saved['summons']:
        record['actor_template'].pop('creature_types', None)
    template = saved['actor_template']
    assert ActorTemplate.model_validate(template).model_dump(mode='json') == template
    engine = Gate2Engine(ROOT, match_seed='OLD-TYPES', typed_bundles=(saved,),
        roster_setup={'primary_actor_ids': [OWNER, AN]})
    for actor in engine.state.actors.values():
        assert types_for(actor) == ()
        old = actor.model_dump(mode='json')
        assert 'creature_types' not in old
        assert ActorState.model_validate(old).model_dump_json() == actor.model_dump_json()


def test_portable_roster_adapter_and_runtime_preserve_explicit_sheet_type(bundle, adapter):
    from combat.creature_types import types_for
    expected = (adapter.sheet.combatant_stats.creature_type.strip(),)
    assert types_for(bundle.actor_template) == expected
    engine = runtime_engine(bundle)
    assert types_for(engine.state.actors[bundle.actor_template.entity_id]) == expected
    payload = bundle.model_dump(mode='json')
    assert type(bundle).model_validate(payload).model_dump(mode='json') == payload


def test_legacy_portable_bundle_keeps_its_hash_and_unknown_type(bundle):
    from combat.canonical import canonical_sha256
    from combat.creature_types import types_for
    payload = bundle.model_dump(mode='json', by_alias=True)
    payload['actor_template'].pop('creature_types')
    payload.pop('bundle_sha256')
    payload['bundle_sha256'] = canonical_sha256(payload)
    old = type(bundle).model_validate(payload)
    assert old.model_dump(mode='json', by_alias=True) == payload
    assert types_for(runtime_engine(old).state.actors[old.actor_template.entity_id]) == ()


@pytest.mark.parametrize('value', [42, {'type': 'Humanoid'}, ['Humanoid', 3]])
def test_invalid_explicit_types_are_rejected(value):
    sheet = _sheet([])
    sheet['identity']['creature_types'] = value
    with pytest.raises(ValueError, match='creature type'):
        compile_character(sheet, actor_id=OWNER)
