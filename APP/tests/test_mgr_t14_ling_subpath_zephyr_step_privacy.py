"""Focused table-level privacy regression; permits normal option metadata."""
import json

from tests.test_mgr_t14_ling_subpath_zephyr_step import (
    FOE, cold, concealed_fight, move, saves,
)


def test_unlocated_recipient_name_is_masked_in_every_thunderhead_prompt(tmp_path):
    svc, table, mid = concealed_fight(tmp_path)
    hidden_name = cold(svc, mid).state.actors[FOE].display_name
    _, prompts = move(svc, table, mid, 4, 6)
    assert len(prompts) == 2
    option = prompts[0]['choice']['options'][0]
    # Presentation can add description and other metadata. Privacy applies to
    # the entire prompt below, not to a fixed set of dictionary keys.
    assert option['id'] == FOE
    assert option['label'] == 'Unseen hostile creature'
    for prompt in prompts:
        assert hidden_name not in json.dumps(prompt), prompt
    assert 'Unseen hostile creature' in prompts[1]['moment']
    eng = cold(svc, mid)
    assert len(saves(eng)) == 1 and eng.state.actors[FOE].current_hp < 500
