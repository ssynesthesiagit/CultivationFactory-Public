"""Merged authority and fixture compatibility through the real table."""
import json
from pathlib import Path
import pytest
from tests.test_a2_group_insights6 import fight
from tests.auto_worker1_support import LEFT, act, reload, resolve
from combat.ext import insights6 as ix


def test_reviewed_insight_and_setup_action_survive_table_reload(tmp_path):
    combat, table, mid = fight(tmp_path, [ix.ECONOMY], prepare=[
        {'type': 'temp_hp', 'applies_to': 'self', 'flat': 1}],
        prepare_target='SELF', prepare_costs=[(ix.QI, 2)])
    engine = reload(combat, mid)
    assert ix.owns(engine, engine.state.actors[LEFT], ix.ECONOMY)
    menu = table.state(mid)['menu']
    groups = [(g['source_definition_id'], g['label']) for g in menu['actions']
              if 'worker1' in g['source_definition_id']]
    setup = [a.source_definition_id for a in engine.action_catalog.values()
             if a.owner_id == LEFT and a.display_name == 'Prepare']
    from combat.action_legality import query
    assert any(g['label'] == 'Prepare' for g in menu['actions']), (
        groups, [query(engine, LEFT, a) for a in setup])
    resolve(lambda answers: act(table, mid, 'Prepare', answers))
    assert reload(combat, mid).state.actors[LEFT].resources[ix.QI] == 99


@pytest.mark.parametrize('name', ['a2_group_insights_1.json', 'a2_weapons_second_pass.json'])
def test_merged_review_documents_declare_the_census_schema(name):
    path = Path(__file__).parents[1] / 'authority/typed_mechanics/reviewed_final.d' / name
    assert json.loads(path.read_text())['schema'] == 'TianxiaFoundry.ReviewedFinalMechanics.v1'


def test_generated_authority_retains_every_insights6_review():
    root = Path(__file__).parents[1] / 'authority'
    authored = json.loads((root / 'typed_mechanics/reviewed_final.d/insights6.json').read_text())['mechanics']
    generated = json.loads((root / 'Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
    for key, row in authored.items():
        assert generated[key]['typing_status'] == 'reviewed_final', key
        assert generated[key]['insight_reviewed_text_sha256'] == row['text_sha256'], key
        assert generated[key]['riders'] == row['riders'], key
