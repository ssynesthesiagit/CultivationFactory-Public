"""Real desktop DOM/controller -> scoped table preview -> commit and cold reload."""
import json
import subprocess

from combat.ext import blossom
from tests import test_a2_flowers as flowers
from tests.hunt12_support import ME, STAMINA, reload


def test_desktop_draft_enabled_secondary_activation(tmp_path, monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    real_sheet = flowers.sheet

    def scarce_cp_sheet(*args, **kwargs):
        doc = real_sheet(*args, **kwargs)
        doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 2
        return doc

    monkeypatch.setattr(flowers, 'sheet', scarce_cp_sheet)
    combat, table, mid = flowers.scene(tmp_path, ['TAL_FLOWERS_CULTIVATE_BLOSSOM', blossom.SEED])
    state = table.state(mid)
    menu = state['menu']
    seed = next(cid for cid, spec in menu['composition'].items() if spec['source'].endswith('blossom.pick.seed'))
    assert table.act(mid, seed, menu['decision_id'], menu['state_version'], state['last_sequence'], [])['status'] == 'COMMITTED'
    state = table.state(mid)
    menu = state['menu']
    family = next(row for row in state['shapes'][ME] if row['base'].endswith('blossom.cultivate'))
    secondary = next(row for row in family['choices'] if row['button_id'].endswith('blossom.cultivate_bloom'))
    assert secondary['activation'] and not secondary['candidate_id']
    assert any(row['source_definition_id'] == family['base'] for row in menu['actions'])
    medicinal, spec = next((cid, spec) for cid, spec in menu['composition'].items()
                           if spec['source'].endswith('blossom.pick.medicinal'))
    source = secondary['button_id'].removeprefix('act:')
    payload = dict(actor_id=ME, decision_id=menu['decision_id'], state_version=menu['state_version'],
                   sources=[spec['source']], source_definition_id=source, request_id='desktop-draft')
    journal = combat._load_session(mid).store.journal_path
    before = journal.read_bytes()
    preview = table.preview_composition(mid, payload)
    assert preview['menu']['actions'] and journal.read_bytes() == before
    fixture = dict(state=state, preview=preview, family=family['base'], secondary=source,
                   medicinal=medicinal, medicinalSource=spec['source'])
    result = subprocess.run(['node', '--test', '--test-isolation=none', '--test-reporter=tap',
                             'tests/desktop_option_reachability.test.mjs'],
                            input=json.dumps(fixture), text=True, capture_output=True, timeout=120)
    failure = next((line.strip() for line in result.stdout.splitlines() if 'error:' in line), result.stderr)
    assert result.returncode == 0, failure + '\n' + result.stdout + result.stderr
    submitted = json.loads(next(line.split('DESKTOP_COMMIT ', 1)[1] for line in result.stdout.splitlines()
                                if 'DESKTOP_COMMIT ' in line))
    assert submitted['composition'] == payload
    reply = table.commit_composition(mid, submitted['composition'], submitted['candidate_id'], submitted['after'])
    assert reply['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ME].resources[STAMINA] == 1
    config = next(c.data for c in engine.state.actors[ME].conditions.values() if c.condition_id == blossom.SETUP)
    assert config['bloom'] == 'medicinal'
