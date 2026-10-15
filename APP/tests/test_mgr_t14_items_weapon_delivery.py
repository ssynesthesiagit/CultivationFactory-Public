"""Acquisition-to-table regressions for the five assigned item delivery rows."""
import pytest
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat import table_advance
from combat.factory_compiler import compile_character
from combat.tabletop_service import TabletopService
from combat.tabletop import TabletopError
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, FOE, fixture, reload
from tests.test_auto2_talismans import take

SWORD = 'tianxia.sphere.sword'
WAVE = 'SWORD_BASE_SWORD_BEYOND_HAND'


def acquire(tmp_path, sphere, *, choices=None, primary='Qi', talents=(), gm=False, background=None):
    """Use the shipped table grant validator and durable ButtonStore overlay."""
    original = sheet([], primary=primary)
    path = 'tianxia.path.body_refining' if primary == 'Stamina' else 'tianxia.path.qi_cultivation'
    original['identity']['path_ids'] = [path]
    original['path_and_subpath'] = {'path_record_id': path, 'path_record_ids': [path]}
    if background:
        from factory_authoring.starting_kits import resolve_starting_kit
        original['equipment'] = [{'starting_kit': resolve_starting_kit(background,path,seed='MGR-T14')}]
    service = TabletopService(None, tmp_path / 'acquisition')
    class Source:
        userdata_root = tmp_path / 'acquisition'
        def _factory_owner_sheet(self, project_id):
            return table_advance.apply(original, service.buttons.get(project_id).get('advancement'))
    service.combat = Source()
    service.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    pid = '00000000-0000-4000-8000-000000000014'
    kwargs = {} if choices is None else {'choices': choices}
    service.add_advancement(pid, 'sphere', sphere, gm=gm, **kwargs)
    for talent in talents:
        service.add_advancement(pid, 'talent', talent, gm=gm)
    return service.combat._factory_owner_sheet(pid)


def native(tmp_path, document, **kwargs):
    return fixture(tmp_path / 'fight', [], owner_bundle=compile_character(document, actor_id=OWNER), **kwargs)


def test_sword_learning_requires_one_choice(tmp_path):
    with pytest.raises(TabletopError, match='Practice'):
        acquire(tmp_path, SWORD)


def test_hand_learning_does_not_grant_wave(tmp_path):
    doc = acquire(tmp_path, SWORD, choices={'practice': 'hand'})
    combat, table, mid = native(tmp_path, doc)
    engine = reload(tmp_path / 'fight', mid)
    assert not any(a.parameters.get('typed', {}).get('source') == WAVE for a in engine.action_catalog.values())
    assert 'SWORD_BASE_SWORD_IN_HAND' in doc['spheres_and_talents']['automatic_sphere_component_record_ids']


@pytest.mark.parametrize('kind', ['SLASHING', 'FORCE'])
def test_wave_asks_type_before_attack_and_cold_replays(tmp_path, kind):
    doc = acquire(tmp_path, SWORD, choices={'practice': 'beyond_hand'})
    combat, table, mid = native(tmp_path, doc, foe_position={'x': 9, 'y': 6}, named=True)
    engine = reload(tmp_path / 'fight', mid)
    action = next(a for a in engine.action_catalog.values() if a.parameters.get('typed', {}).get('source') == WAVE)
    before = dict(engine.state.actors[OWNER].resources)
    prompts = take(combat, table, mid, action.display_name, FOE, {'choice:needle.sword_wave_type': kind})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.sword_wave_type' for p in prompts)
    engine = reload(tmp_path / 'fight', mid)
    assert dict(engine.state.actors[OWNER].resources) == before
    assert not engine.state.actors[OWNER].action_available
    assert any(e.event_type == 'ATTACK_ROLLED' for e in engine.events)


def test_body_projection_needs_explicit_source(tmp_path):
    with pytest.raises(TabletopError, match='Body Refiner'):
        acquire(tmp_path, SWORD, choices={'practice': 'beyond_hand'}, primary='Stamina')


def test_body_hand_and_explicit_inheritance_remain_native_choices(tmp_path):
    hand=acquire(tmp_path/'hand',SWORD,choices={'practice':'hand'},primary='Stamina')
    assert 'SWORD_BASE_SWORD_IN_HAND' in hand['spheres_and_talents']['automatic_sphere_component_record_ids']
    grant={'source_kind':'inheritance','source_id':'inheritance:owner-sword-qi',
           'rule_text':'This inheritance explicitly permits this Body Refiner to learn projected Sword techniques.',
           'permission':'projected_sword'}
    doc=acquire(tmp_path/'projected',SWORD,choices={'practice':'beyond_hand','projection_grant':grant},primary='Stamina',gm=True)
    combat,table,mid=native(tmp_path/'projected',doc,foe_position={'x':9,'y':6})
    engine=reload(tmp_path/'projected'/'fight',mid)
    assert any(a.parameters.get('typed',{}).get('source')==WAVE for a in engine.action_catalog.values())
    assert doc['table_acquisitions'][0]['choices']['projection_grant']==grant


def test_actor_cannot_self_approve_external_projected_grant(tmp_path):
    grant={'source_kind':'inheritance','source_id':'inheritance:unadmitted',
           'rule_text':'A proposed inheritance, requiring actual GM source admission.', 'permission':'projected_sword'}
    with pytest.raises(TabletopError,match='GM'):
        acquire(tmp_path,SWORD,choices={'practice':'beyond_hand','projection_grant':grant},primary='Stamina')
