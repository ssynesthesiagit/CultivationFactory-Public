from tests.test_a2_foundations4 import setup, select_venom_dark_marrow, B, FOE, OWNER, REFUSAL
from tests.worker2_support import settle, candidate, turn


def test_probe_note(tmp_path):
    combat, table, mid = setup(tmp_path, B, held=1, ask=True, prepare=True, stage='Refined')
    select_venom_dark_marrow(combat, table, mid)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Constitution pressure', target=OWNER).candidate_id,
                     choices={REFUSAL: 'USE'})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == REFUSAL)
    assert False, 'PROBE NOTE=' + repr(prompt.get('table_note')) + ' SUMMARY=' + repr(prompt.get('summary'))
