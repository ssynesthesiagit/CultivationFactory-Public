"""Identical service regressions run on the exact base and final implementation.

These fixtures acquire only native source-bound automatic packages; missing
buttons are genuine failed native admission, never fabricated ownership/events.
"""
import pytest
from tests.h1_support import ROOT,sheet as raw_sheet
from tests.r1i_service_support import fixture,candidate,OWNER,FOE
from tests.test_r1i_round3 import resolve,reload


@pytest.fixture(autouse=True)
def acquire(monkeypatch):
    import tests.r1i_service_support as support
    from canonical_catalog import CanonicalCatalogAuthorityService
    catalog=CanonicalCatalogAuthorityService(ROOT)
    def native(mids,**kwargs):
        doc=raw_sheet(mids,**kwargs);block=doc.get('spheres_and_talents')
        if block:
            rows=[r for sphere in block['sphere_record_ids'] for r in catalog.get_sphere(sphere)['automatic_base_abilities']]
            block['automatic_sphere_component_record_ids']=[r['runtime_component_id'] for r in rows]
            block['learned_talent_record_ids']=[r for r in block['learned_talent_record_ids'] if r not in set(block['automatic_sphere_component_record_ids'])]
        return doc
    monkeypatch.setattr(support,'sheet',native)


def test_living_native_production(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,['INK_BASE_LIVING_INK'])
    resolve(combat,mid,send,candidate(table,mid,'Living Ink: from shadow'),{})
    e=reload(tmp_path,mid)
    assert any(c.data.get('origin')=='shadow' and c.data.get('saleable')==0 for c in e.state.actors[OWNER].conditions.values())


def test_lash_native_declaration(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,['INK_BASE_INK_LASH'])
    resolve(combat,mid,send,candidate(table,mid,'Ink Lash',FOE),{'choice:needle.ink_lash_type':'psychic','choice:needle.ink_lash_shape':'painted fang'})
    e=reload(tmp_path,mid)
    assert any(x.payload.get('damage_type')=='psychic' for x in e.events)


def test_press_native_surface(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,['INK_BASE_PRESS_MARK'])
    resolve(combat,mid,send,candidate(table,mid,'Press Mark: object or surface'),{'choice:needle.ink_surface':'$first'})
    assert any(c.data.get('surface') for c in reload(tmp_path,mid).state.actors[OWNER].conditions.values())


def test_adorn_native_aura(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,['BEAUTY_BASE_ADORN_THE_MOMENT'])
    resolve(combat,mid,send,candidate(table,mid,'Adorn the Moment: haunting',OWNER),{})
    assert any(c.data.get('aura')=='haunting' for c in reload(tmp_path,mid).state.actors[OWNER].conditions.values())


def test_foil_native_allied_target(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,['JESTER_BASE_SET_THE_SCENE'],allies=[FOE])
    resolve(combat,mid,send,candidate(table,mid,'Set the Scene: Come Closer',FOE),{})
    assert any('foil_come_closer' in c.condition_id for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())


def test_draw_native_qi_inside_mundane_range(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,['THREAD_BASE_DRAW_THE_LINE'])
    resolve(combat,mid,send,candidate(table,mid,'Draw the Line: Guide (Qi Thread)',FOE),{})
    e=reload(tmp_path,mid)
    assert any(c.data.get('thread_medium')=='qi' for c in e.state.actors[FOE].conditions.values())


def test_listen_has_no_native_button_without_line(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,['THREAD_BASE_LISTEN_THROUGH_TENSION'])
    names=[c.display_name for c in reload(tmp_path,mid).legal_candidates()]
    assert 'Listen Through Tension' not in names
