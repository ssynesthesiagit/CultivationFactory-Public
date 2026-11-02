"""AUTO128 Sand: printed CL prerequisites are enforced by the engine, not left to the GM.

A printed "Prerequisite: CL N+" is character construction rather than a fight rule, so it is
typed as min_cl and checked at admission (combat/ext/activation_requirements.py). These cases
run at the table: the owner's real compiled Cultivation Level decides whether the talent is
offered at all, and no resource is paid either way.
"""
import json

import pytest
from tests.cw2_service_support import add_action, seal
from tests.test_r9i_karma_persistence import act
from tests.worker2_support import OWNER, FOE, candidate, fixture, reload, settle, turn

# (talent, printed gate, the action's name at the table)
CASES = [
    ('TAL_SAND_SAND_NEEDLE_VOLLEY', 5, 'Sand Needle Volley'),
    ('TAL_SAND_THOUSAND_MILE_SANDSTORM_BODY', 15, 'Thousand-Mile Sandstorm Body'),
    ('TAL_SAND_SAND_MIRROR_MIRAGE', 5, 'Sand Mirror Mirage'),
]


def offered(combat, mid, name):
    """The action's display name among the owner's legal candidates on their turn, or None."""
    engine = combat._load_session(mid).engine
    return any(getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None) == name
               for c in engine.legal_candidates()
               if engine.state.actors[c.actor_id].entity_id == OWNER)


@pytest.mark.parametrize('talent,gate,name', CASES)
@pytest.mark.parametrize('cl', [1, 4, 5, 11, 15])
def test_printed_cl_gate_decides_whether_the_talent_is_offered(tmp_path, talent, gate, name, cl):
    combat, _table, mid = fixture(tmp_path, [talent], cl=cl)
    # Below the printed gate the talent is not part of this character's options at all;
    # at or above it, the same character build offers it.
    assert offered(combat, mid, name) is (cl >= gate)


def test_a_character_below_the_gate_pays_nothing(tmp_path):
    """The gate is checked before any cost, so a CL 3 owner never sees a CP price for a CL 5+ talent."""
    combat, _table, mid = fixture(tmp_path, ['TAL_SAND_SAND_NEEDLE_VOLLEY'], cl=3)
    engine = combat._load_session(mid).engine
    owner = engine.state.actors[OWNER]
    assert owner.resources.get('resource:core.qi', 0) == 100  # untouched
    assert not offered(combat, mid, 'Sand Needle Volley')


def test_a_talent_without_a_printed_gate_is_unaffected(tmp_path):
    """No min_cl metadata means no gate: Gather Sand carries no printed prerequisite."""
    combat, _table, mid = fixture(tmp_path, ['SAND_BASE_GATHER_SAND'], cl=1)
    assert offered(combat, mid, 'Gather Sand')


GRAINS = 'condition:typed.sand_glass_grains'
EDGE = 'TAL_SAND_GLASS_EDGE_SCRIPTURE'
SCOUR = 'SAND_BASE_SCOURING_HAND'


def bury_the_foe(bundles):
    """Give the owner a sealed burial action and make the foe easy to hit."""
    add_action(bundles[0], 'Prepare Burial', [{'type': 'sand_bury', 'applies_to': 'target',
                                                'duration': 'one_minute'}])
    template = bundles[2]['actor_template']
    if 'armor_class' in template:
        template['armor_class'] = 1
    seal(bundles[2])


@pytest.mark.parametrize('accept,cling', [(True, True), (False, False)])
def test_glass_edge_grains_are_the_owner_s_choice_on_buried_damage(tmp_path, accept, cling):
    """Glass Edge Scripture: "you may cause glassy grains to cling to it" is asked, not assumed."""
    combat, table, mid = fixture(tmp_path, [EDGE, SCOUR], owner_dc=100, bundle_transform=bury_the_foe)
    settle(table, mid, candidate(combat, mid, 'Prepare Burial', target=FOE).candidate_id)
    picks = {'choice:needle.glass_edge_cling': 'cling'} if accept else {'choice:needle.glass_edge_cling': 'leave'}
    prompts = settle(table, mid, candidate(combat, mid, 'Scouring Hand: Reduce Speed', target=FOE).candidate_id, picks)
    cling_prompts = [p for p in prompts if 'cling' in p['context']['reaction_source_id']]
    # The printed "you may" is always put to the owner; taking it up is what clings the grains.
    assert len(cling_prompts) == 1
    e = reload(tmp_path, mid)
    names = {c.condition_id for c in e.state.actors[FOE].conditions.values()}
    assert (GRAINS in names) is cling
    if cling:
        # The prompt tells a newcomer what it does, who it affects and what it costs.
        text = json.dumps(cling_prompts[0])
        assert 'Glass Edge Scripture' in text and 'Piercing' in text and 'costs nothing extra' in text
        # ... it also says what happened and which talent did it. The printed trigger is damage dealt to a
        # creature that is already Buried; the damage does not bury it, and the prompt used to say it did.
        assert 'already Buried' in text
        assert 'Scouring Hand: Reduce Speed' in text


# ============================================================================================ Thousand-Grain Grip (AUTO128r1)
GRIP = 'TAL_SAND_THOUSAND_GRAIN_GRIP'


def bury_out_of_reach(bundles):
    """A sealed preparation that Buries the foe at a DC its escape check cannot beat, so the
    printed "If it fails, it takes Slashing damage" branch is the one reached."""
    add_action(bundles[0], 'Prepare Burial', [{'type': 'sand_bury', 'applies_to': 'target',
                                                'duration': 'one_minute'}],
               typed={'numbers': {'pb': 4, 'key_mod': 2, 'save_dc': 60, 'cl': 15}})


def dig_free_attempt(tmp_path, cl):
    """The owner buries the foe, then the foe's own turn spends its Action on "Dig free of the sand",
    accepting the burier's Thousand-Grain Grip offer if the burier is asked. Returns the prompts."""
    combat, table, mid = fixture(tmp_path, [GRIP], cl=cl, bundle_transform=bury_out_of_reach)
    settle(table, mid, candidate(combat, mid, 'Prepare Burial', target=FOE).candidate_id)
    turn(table, mid, FOE)
    cid = candidate(combat, mid, 'Dig free of the sand').candidate_id
    answers, prompts = [], []
    for _ in range(20):
        result = act(table, mid, cid, answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return tmp_path, mid, prompts
        prompt = result['reaction']
        prompts.append(prompt)
        answer = {**prompt['context'], 'selection': 'USE' if grip_prompts([prompt]) else 'DECLINE'}
        if prompt.get('choice'):  # a multiple-burial menu would arrive as a choice, not a use/decline
            answer['option_ids'] = [prompt['choice']['options'][0]['id']]
        answers.append(answer)
    raise AssertionError('The escape check never resolved')


def grip_prompts(prompts):
    return [p for p in prompts if GRIP in json.dumps(p)]


def grip_damage(engine):
    return [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id == GRIP]


def escape_checks(engine):
    return [e.payload for e in engine.events if e.event_type == 'CHECK_ROLLED']


def test_thousand_grain_grip_waits_for_its_printed_cl_on_the_escape_check(tmp_path):
    """Thousand-Grain Grip prints "Prerequisite: CL 5+" and answers the escape check itself, which is
    not the admission path the gate was first wired into. Below the gate the burier is never asked, the
    check is not made at Disadvantage, no Grip damage lands, and its Reaction is left unspent."""
    tmp_path, mid, prompts = dig_free_attempt(tmp_path, cl=4)
    assert grip_prompts(prompts) == []
    engine = reload(tmp_path, mid)  # a cold reload that must also replay mechanically
    assert escape_checks(engine) and all(r['actor']['mode'] != 'DISADVANTAGE' for r in escape_checks(engine))
    assert grip_damage(engine) == []
    assert engine.state.actors[OWNER].reaction_available  # the printed 0 CP means the Reaction is the cost


def test_thousand_grain_grip_worsens_the_escape_check_at_its_printed_cl(tmp_path):
    """The same fight at the printed gate: the burier is asked on its own turn, and taking it up costs
    the Reaction and adds Disadvantage and the printed failure damage."""
    tmp_path, mid, prompts = dig_free_attempt(tmp_path, cl=5)
    assert len(grip_prompts(prompts)) == 1
    engine = reload(tmp_path, mid)
    assert escape_checks(engine)[-1]['actor']['mode'] == 'DISADVANTAGE'
    assert grip_damage(engine)
    assert not engine.state.actors[OWNER].reaction_available
