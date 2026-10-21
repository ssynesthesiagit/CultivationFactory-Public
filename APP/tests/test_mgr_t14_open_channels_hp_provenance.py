"""Stage2's source-bound HP contribution reaches the real combat table once."""
from copy import deepcopy
import socket
import pytest

from app.core import Database, Settings
from non_sphere_authority.service import NonSphereAuthorityService
from stage2.service import RulesCausalStage2Service, _state
from combat.factory_compiler import compile_character
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, fixture, reload

FID = 'origin_spirit_body_v0_2B'


@pytest.fixture(scope='session', autouse=True)
def no_live_network():
    """Every build/model transport stays offline, including fixture setup.

    Refusals are OSError, as in tests/conftest.py: concept_index degrades on
    OSError, so a blocked live embedding call must not abort fixture setup.
    """
    original = socket.socket.connect
    def connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise OSError('HP acceptance must not contact any live server')
        return original(sock, address)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(socket.socket, 'connect', connect)
        yield


def test_real_stage2_contribution_is_replaced_not_added_twice(tmp_path, monkeypatch):
    # Public installed source, not a Factory catalog/archive or owner project.
    record = NonSphereAuthorityService(root_dir=ROOT).project_locked_foundation_catalog_record(
        FID, mechanical=True)
    data = tmp_path / 'stage2'
    settings = Settings(
        root_dir=ROOT, data_dir=data, db_path=data / 'foundry.sqlite3',
        inbox_dir=data / 'inbox', exports_dir=data / 'exports',
        packs_dir=data / 'packs', vendor_dir=ROOT / 'vendor',
        logs_dir=data / 'logs', backups_dir=data / 'backups',
        security_dir=data / 'security')
    stage2 = RulesCausalStage2Service(Database(settings))
    state = _state('public-hp')
    state['paths'] = ['tianxia.path.body_refining', 'tianxia.path.spirit_awakening']
    state['foundation'] = {'state': 'active', 'record_id': FID, 'stage': 'Awakened'}
    state['pb'] = 3
    # Only source lookup is synthetic: execute the real Stage2 HP calculator.
    # No catalog proof/selection behavior is under test at this boundary.
    monkeypatch.setattr(stage2, '_resolve_record_after_proof',
                        lambda conn, project_id, record_id: record if record_id == FID else None)
    hp, bindings, traces = stage2._foundation_hp_adjustment(
        None, 'public-hp', state, {'total': 48, 'components': []}, cl=5, pb=3)
    assert hp['foundation_delta'] == 3
    assert hp['total'] == 51
    assert bindings and traces
    # Stage2 rows expose these calculator fields as hp.total,
    # hp.foundation_delta and hp.authority_components; the sheet publishes
    # them as advancement_history.levels. Refinement is explicit, not CL-based.
    rows = [{'cl': 5, 'hp': {
        'total': hp['total'], 'foundation_delta': hp['foundation_delta'],
        'authority_components': deepcopy(hp['components'])}}]
    included = hp['foundation_delta']
    document = sheet(['foundation.' + FID + '.generate_spirit_source_dew'], cl=5,
        foundation={'foundation_id': FID, 'record_id': FID, 'record_hash': record['record_hash'],
                    'stage': 'Refined'})
    document['identity']['proficiency_bonus'] = state['pb']
    document['ability_scores_and_statistics']['hit_points']['maximum'] = hp['total']
    document['advancement_history'] = {'levels': rows}
    bundle = compile_character(document, actor_id=OWNER)
    expected = hp['total'] - included + 2 * state['pb']
    assert bundle['actor_template']['maximum_hp'] == expected
    assert compile_character(document, actor_id=OWNER)['actor_template']['maximum_hp'] == expected
    combat, table, mid = fixture(tmp_path / 'combat', [], owner_bundle=bundle)
    engine = reload(tmp_path / 'combat', mid)
    assert engine.state.actors[OWNER].maximum_hp == expected


def test_hp_regressions_have_no_private_catalog_fixture_dependency(request):
    """Keep all HP cases runnable when the private Factory ZIP is absent."""
    private = {'factory_zip', 'catalog_environment', 'foundation_project'}
    cases = [item for item in request.session.items if item.path == request.node.path]
    assert cases
    for item in cases:
        assert not private.intersection(item.fixturenames), item.nodeid


@pytest.mark.parametrize('maximum', [60, 68])
def test_unknown_hp_breakdown_keeps_the_declared_total(tmp_path, maximum):
    document = sheet(['foundation.' + FID + '.generate_spirit_source_dew'],
        foundation={'foundation_id': FID, 'stage': 'Refined'})
    document['ability_scores_and_statistics']['hit_points']['maximum'] = maximum
    bundle = compile_character(document, actor_id=OWNER)
    assert bundle['actor_template']['maximum_hp'] == maximum
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle)
    assert reload(tmp_path, mid).state.actors[OWNER].maximum_hp == maximum
