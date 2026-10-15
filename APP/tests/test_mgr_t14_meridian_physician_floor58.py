"""Clinical Source CL producer guards; these do not certify whole Physician rows.

Externally authored ailments use the trusted GM boundary, a committed journey,
encounter import, cold load and mechanical replay. No fabricated diagnosis or
successful procedure is supplied. Unknown source authority remains unknown.
"""
import pytest

# Runtime catalog lookup assembles this filename from constants. Declare the
# real source dependency for the public export's static closure; never replace
# the authority service or supply a fake acquisition gate to avoid exporting it.
NATIVE_TEST_RESOURCES = ('authority/Tianxia_Sphere_Path_Access_R1.json',)

from tests.test_mgr_t14_clinical_native import (
    A, B, game, start, engine, clinical, anatomy, use, next_round,
)


def ailment(source_cl=None):
    result = {'label': 'Cultivated toxin', 'category': 'poison',
              'conditions': ['poisoned'], 'ongoing': 0, 'excluded': [], 'dc': 15}
    if source_cl is not None:
        result['source_cl'] = source_cl
    return result


@pytest.mark.parametrize('source_cl', [3, 18, 21, None])
def test_external_source_cl_survives_commit_encounter_and_cold_replay(tmp_path, monkeypatch, source_cl):
    cold, table, jid, command, world = game(tmp_path, monkeypatch, spheres=('life',))
    declared = world('clinical_source', ailment(source_cl), scope='Cultivated toxin')
    receipt = declared['fact_consent_admission'][-1]['receipt_id']
    mid = start(cold, jid)
    loaded = engine(cold, mid)
    records = clinical(loaded.state.actors[B], 'poison')
    assert len(records) == 1
    facts = records[0].data['clinical']
    assert facts['source_instance'] == receipt
    assert facts.get('source_cl') == source_cl
    assert ('source_cl' in facts) == (source_cl is not None)
    assert facts['readers'] == [A]
    assert facts['dc'] == 15
    assert cold()._load_session(mid).mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('source_cl', [0, -1, True, '18', 1.5])
def test_gm_source_cl_rejects_untyped_or_nonpositive_input_atomically(tmp_path, monkeypatch, source_cl):
    cold, table, jid, command, world = game(tmp_path, monkeypatch, spheres=('life',))
    before = cold().journey_state(jid)
    with pytest.raises(ValueError):
        world('clinical_source', ailment(source_cl))
    assert cold().journey_state(jid) == before


def test_annotation_cannot_replace_known_source_cl(tmp_path, monkeypatch):
    cold, table, jid, command, world = game(tmp_path, monkeypatch, spheres=('life',))
    world('clinical_source', ailment(18))
    mid = start(cold, jid)
    loaded = engine(cold, mid)
    condition = clinical(loaded.state.actors[B], 'poison')[0]
    before = loaded.state.model_dump(mode='json')
    with pytest.raises(ValueError, match='known native Source CL'):
        cold().world_fact(mid, loaded.state.state_version, {
            'source': 'clinical_source', 'subject': B, 'kind': 'clinical_annotation',
            'scope': 'misclassified source', 'value': {
                'condition_instances': [condition.instance_id], 'label': 'Cultivated toxin',
                'category': 'poison', 'ongoing': 0, 'excluded': [], 'dc': 15, 'source_cl': 3,
            }, 'expires_at': 100000, 'readers': [A],
        })
    assert engine(cold, mid).state.model_dump(mode='json') == before


def test_unknown_existing_source_accepts_validated_source_cl_without_new_ailment(tmp_path, monkeypatch):
    cold, table, jid, command, world = game(tmp_path, monkeypatch, spheres=('life',))
    world('clinical_source', ailment())
    mid = start(cold, jid)
    loaded = engine(cold, mid)
    condition = clinical(loaded.state.actors[B], 'poison')[0]
    before_hp = loaded.state.actors[B].current_hp
    before_resources = dict(loaded.state.actors[B].resources)
    cold().world_fact(mid, loaded.state.state_version, {
        'source': 'clinical_source', 'subject': B, 'kind': 'clinical_annotation',
        'scope': 'identified authority', 'value': {
            'condition_instances': [condition.instance_id], 'label': 'Cultivated toxin',
            'category': 'poison', 'ongoing': 0, 'excluded': [], 'dc': 15, 'source_cl': 18,
        }, 'expires_at': 100000, 'readers': [A],
    })
    after = engine(cold, mid)
    records = clinical(after.state.actors[B], 'poison')
    assert len(records) == 1
    assert records[0].instance_id == condition.instance_id
    assert records[0].data['clinical']['source_cl'] == 18
    assert after.state.actors[B].current_hp == before_hp
    assert after.state.actors[B].resources == before_resources
    assert cold()._load_session(mid).mechanical.replay()['status'] == 'PASS'


def test_actual_paid_native_toxin_retains_its_exact_source_cl_after_reload(tmp_path, monkeypatch):
    from combat.clinical_sources import metadata
    from combat.ext.stacking_marks import count
    cold, table, jid, command, world = game(tmp_path, monkeypatch, spheres=('poison',), cl=10)
    anatomy(world)
    mid = start(cold, jid)
    for _ in range(10):
        loaded = engine(cold, mid)
        if count(loaded, loaded.state.actors[A], loaded.state.actors[B], 'Dose Mark') >= 2:
            break
        use(cold, table, mid, 'Deliver the Dose')
        next_round(cold, table, mid)
    use(cold, table, mid, 'Ingrain the Toxin: Numb Channels',
        choose=lambda p, ids: ['Numb Channels'] if 'Numb Channels' in ids else ids[:1])
    loaded = engine(cold, mid)
    toxins = [c for c in loaded.state.actors[B].conditions.values()
              if (c.data.get('clinical') or {}).get('rule') == 'POISON_BASE_INGRAIN_THE_TOXIN']
    assert toxins
    facts = metadata(loaded, loaded.state.actors[B], toxins[0])
    assert facts['owner'] == A
    assert facts['source_cl'] == 10
    assert cold()._load_session(mid).mechanical.replay()['status'] == 'PASS'
