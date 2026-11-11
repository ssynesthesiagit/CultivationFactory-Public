"""Heaven's Luck runs three times per fight (owner ruling 2026-10-22, LUCK3FIGHT1).

The owner, playtesting on 2026-10-22, ruled that the Heaven's Luck Insight reroll is usable three times per fight
instead of once: combat/ext/insights_five.py registers it with uses=3 on the one per-fight Rule limit, and
combat/ext/d20_rewrite.py counts those uses. Everything below drives the real table/service path -- prompts,
commits, cold reloads and the saved turn flags -- never the plug-in internals on their own.
"""
from combat.ext import d20_rewrite, insights_five
from tests.test_a2_insights_five import PREFIX, act, fight, turn
from tests.worker2_support import OWNER, FOE, reload

SOURCE = 'reaction:typed.' + PREFIX + 'heavens-luck'
FLAG = '_round_h1_fight:' + PREFIX + 'heavens-luck'


def use_heavens_luck(tmp_path, combat, table, mid):
    """Answer one failing save with Heaven's Luck; return the prompt the table showed (or None)."""
    prompts = act(combat, table, mid, 'Save', OWNER, {SOURCE: 'first'})
    return next((p for p in prompts if p['context']['reaction_source_id'] == SOURCE), None)


def rewrites(tmp_path, mid):
    return len([v for v in reload(tmp_path, mid).events if v.event_type == 'D20_REWRITTEN'])


def test_one_registered_rule_allows_more_than_one_use():
    # No other ability's limit changed: the count comes from the registration, and only Heaven's Luck asks for more.
    more = {rule.name: rule.uses for rule in d20_rewrite.RULES.values() if int(rule.uses or 1) != 1}
    assert more == {"Heaven's Luck": 3}
    rule = d20_rewrite.RULES[insights_five.LUCK]
    assert (rule.limit, rule.uses, rule.op) == ('fight', 3, 'reroll')
    # The AI path still spends a use only on a roll that already failed.
    class Roll:
        def __init__(self, failed):
            self.failed = failed

        def succeeded(self):
            return not self.failed
    assert rule.ai(None, None, Roll(True)) is True
    assert rule.ai(None, None, Roll(False)) is False


def test_three_uses_each_show_their_count_and_a_fourth_is_refused(tmp_path):
    c, t, m = fight(tmp_path, 'heavens-luck', save=-100)
    turn(t, m, FOE)
    names = []
    for _ in range(3):
        prompt = use_heavens_luck(tmp_path, c, t, m)
        assert prompt is not None, 'the table stopped offering a use it still had'
        names.append(prompt['reaction'])
        assert prompt['summary'] or prompt['rules'], prompt
    # Newcomer-readable availability, in the same counted form as the table's other limited abilities.
    assert names == ["Heaven's Luck (3 of 3 uses left this fight)",
                     "Heaven's Luck (2 of 3 uses left this fight)",
                     "Heaven's Luck (1 of 3 uses left this fight)"], names
    assert rewrites(tmp_path, m) == 3
    engine = reload(tmp_path, m)
    assert engine.state.actors[OWNER].turn_flags[FLAG] == 3
    # A fourth attempt changes nothing: no prompt, no reroll, and the printed "use the new result" stands for each use.
    assert use_heavens_luck(tmp_path, c, t, m) is None
    assert rewrites(tmp_path, m) == 3


def test_count_survives_a_commit_and_a_cold_reload_mid_fight(tmp_path):
    c, t, m = fight(tmp_path, 'heavens-luck', save=-100)
    turn(t, m, FOE)
    for _ in range(2):
        assert use_heavens_luck(tmp_path, c, t, m) is not None
    engine = reload(tmp_path, m)   # cold: the saved fight alone must carry the count
    assert engine.state.actors[OWNER].turn_flags[FLAG] == 2
    prompt = use_heavens_luck(tmp_path, c, t, m)
    assert prompt is not None and prompt['reaction'] == "Heaven's Luck (1 of 3 uses left this fight)"
    assert rewrites(tmp_path, m) == 3
    assert use_heavens_luck(tmp_path, c, t, m) is None
    assert rewrites(tmp_path, m) == 3


def test_a_new_fight_restores_all_three_uses(tmp_path):
    c, t, m = fight(tmp_path / 'first', 'heavens-luck', save=-100)
    turn(t, m, FOE)
    for _ in range(3):
        assert use_heavens_luck(tmp_path / 'first', c, t, m) is not None
    assert use_heavens_luck(tmp_path / 'first', c, t, m) is None
    # A second fight starts from its own turn flags, so all three uses are back.
    c2, t2, m2 = fight(tmp_path / 'second', 'heavens-luck', save=-100)
    turn(t2, m2, FOE)
    names = [(use_heavens_luck(tmp_path / 'second', c2, t2, m2) or {}).get('reaction') for _ in range(3)]
    assert names == ["Heaven's Luck (3 of 3 uses left this fight)",
                     "Heaven's Luck (2 of 3 uses left this fight)",
                     "Heaven's Luck (1 of 3 uses left this fight)"], names
    assert rewrites(tmp_path / 'second', m2) == 3
    assert use_heavens_luck(tmp_path / 'second', c2, t2, m2) is None


def test_will_manifestation_and_unbroken_frame_stay_once_per_fight(tmp_path):
    for slug in ('will-manifestation', 'unbroken-frame'):
        c, t, m = fight(tmp_path / slug, slug, save=-100)
        turn(t, m, FOE)
        source = 'reaction:typed.' + PREFIX + slug
        assert any(p['context']['reaction_source_id'] == source
                   for p in act(c, t, m, 'Save', OWNER, {source: 'first'})), slug
        assert rewrites(tmp_path / slug, m) == 1, slug
        # The second attempt is not offered and no second rewrite is recorded; only Heaven's Luck gained uses.
        assert not any(p['context']['reaction_source_id'] == source
                       for p in act(c, t, m, 'Save', OWNER, {source: 'first'})), slug
        assert rewrites(tmp_path / slug, m) == 1, slug
