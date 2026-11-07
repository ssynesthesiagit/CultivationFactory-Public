"""AUTO107 Brute: Get Over Here (a shove made through a tether) at the table.

Covers the printed lines that used to be read to the GM:
  "When you control one end of a tether attached to a creature, make shove attempts against it as though it were within
   reach"  -> the buttons are offered only against a creature a tether the owner controls is attached to, and only while
               it is inside that tether's own length;
  "On a success, move the target toward you instead of away" -> the target's distance to the shover shrinks, where the
               ordinary Brutal Shove's push grows it, and the Court/Sovereign extra movement does the same;
  "Apply Manhandle talents normally, but talents requiring natural reach function only if the target ends within natural
   reach" -> the owner's Manhandle talents are on the tether buttons, and Takedown grapples only when the pull ends the
               target in reach;
  "When using Shove Aside, movement must still bring the target at least diagonally closer" -> Shove Aside is a Brute
               Maneuvers option, so the button exists only for a creature that owns it;
and the plug-in is inert for a Brute that does not own the talent.
"""
import pytest
from tests.cw2_service_support import seal
from tests.worker2_support import FOE, OWNER, candidate, fixture, reload, settle, turn
from tests.test_r9i_karma_persistence import end_turn

GET_OVER_HERE = "TAL_BRUTE_GET_OVER_HERE"
TAKEDOWN = "TAL_BRUTE_TAKEDOWN"
SHOVE = "BRUTE_BASE_BRUTAL_SHOVE"
MANEUVERS = "BRUTE_BASE_BRUTE_MANEUVERS"
SET_TETHER = "TAL_CHAINS_SET_TETHER_BASE"
FOCUS = "resource:core.martial_focus"
BRUTE_SPHERE = "tianxia.sphere.brute"
COURT = "TAL_BRUTE_COURT_OF_THE_MOVING_MOUNTAIN"
SOV = "TAL_BRUTE_SOVEREIGN_WEIGHT_INCARNATION"
TETHER = "Get Over Here: Shove"
TETHER_TAKEDOWN = "Get Over Here: Shove + Takedown"
ASIDE = "Get Over Here: Shove Aside"
FAR = {'x': 9, 'y': 9}          # 30 feet from the owner (3,6): Set the Tether's whole printed length
INSIDE = {'x': 6, 'y': 6}        # 15 feet: inside a 15-foot tether
BEYOND = {'x': 7, 'y': 6}        # 20 feet: past that same 15-foot tether
NEAR = {'x': 3, 'y': 7}         # adjacent to the owner (3,6): inside the ordinary 5-foot reach


def _decisive(bundles):
    """The owner always wins the printed Strength (Athletics) contest; the target always loses it."""
    bundles[0]['skills'] = {'Athletics': 100}
    bundles[2]['skills'] = {'Athletics': -100, 'Acrobatics': -100}
    bundles[2]['actor_template']['saving_throws'] = {'STR': -20, 'DEX': -20, 'CON': -20, 'WIS': -20}
    for bundle in (bundles[0], bundles[2]):
        bundle.pop('bundle_sha256', None)
        if bundle is bundles[2]:
            bundle['actor_template']['saving_throws'] = {'STR': -20, 'DEX': -20, 'CON': -20, 'WIS': -20}
    seal(bundles[0])
    seal(bundles[2])


def _narrow(bundles, *, reach_weapon_ft=None):
    """A contest the owner wins by 4 points, so Brutal Shove's own "margin" movement is 0 feet.

    Brutal Shove moves the target "an additional 5 feet for every 5 points by which your Athletics check exceeds its
    opposing check". With a huge margin that bonus dwarfs the 5 and 10 feet the Court/Sovereign riders add, so a test
    that only asserts "the distance shrank" passes even when a rider pushes the wrong way -- which is exactly what the
    old version of this file did. The fighter's rolls are deterministic in a compiled test fight, so giving the FOE a 6
    point Athletics lead pins the margin at 4: the owner still wins the printed contest, and the shove's own extra
    movement is always 0 feet. Every distance asserted below is therefore the 5 foot pull plus the rider's own feet.
    ``_margin`` re-reads the recorded contest in each test, so a future change to the contest that moves the margin also
    fails these tests loudly instead of quietly changing what they measure.
    """
    bundles[0]['skills'] = {'Athletics': 0}
    bundles[2]['skills'] = {'Athletics': 6, 'Acrobatics': 6}
    bundles[2]['actor_template']['saving_throws'] = {'STR': -20, 'DEX': -20, 'CON': -20, 'WIS': -20}
    # Court and Sovereign each spend Martial Focus to turn on, so the combined case needs two points of it.
    for resource in bundles[0]['actor_template'].get('resources') or ():
        if resource.get('resource_id') == FOCUS:
            resource['initial'] = resource['maximum'] = 3
    if reach_weapon_ft is not None:
        for row in bundles[0].get('typed_reactions') or ():
            if row.get('block') == 'opportunity':
                row['reach_ft'] = int(reach_weapon_ft)  # a printed reach weapon; natural reach must ignore it
    for bundle in (bundles[0], bundles[2]):
        bundle.pop('bundle_sha256', None)
    seal(bundles[0])
    seal(bundles[2])


def _margin(engine):
    """The last recorded Brutal Shove contest's margin, and that the owner actually won it."""
    check = [e for e in engine.events if e.event_type == 'CHECK_ROLLED'][-1]
    payload = check.payload
    assert payload['success'], payload
    margin = int(payload['actor']['total']) - int(payload['target']['total'])
    assert 0 < margin < 5, f"this fixture pins the contest margin below 5 so the shove's own bonus is 0 feet, got {margin}"
    return margin


def _body_form():
    """The talents a Brute needs for a REAL printed body increase: Calamity Briar Incarnation, "Unarmed reach +10 feet,
    for the duration" (reviewed_final.d/paths.json).

    The Iron Fist base ability is what gives the sheet an unarmed/natural strike while
    combat/ext/reach_bonus.py's compile_actions hook is still running, so the printed reach row becomes a compiled reach
    variant -- the same row the attack menus and reach_bonus.natural_reach_ft read. The form's printed cost is 7 Stamina,
    so this fighter's primary pool is Stamina (worker2_support.fixture's ``primary``).
    """
    return ["TAL_IRON_FIST_IRON_FIST_TRAINING",
            "tianxia.subpath.body.black_thorn_demon_body.feature.calamity_briar_incarnation"]


BRIAR = "Calamity Briar Incarnation"
BRIAR_STATE = "condition:typed.state.calamity_briar_incarnation"


def _has_briar(engine):
    """Whether the owner's Calamity Briar Incarnation state is on. Each instance is keyed by its own record, so the
    printed condition id is the prefix of the instance id the engine stores."""
    return any(c.condition_id.startswith(BRIAR_STATE) for c in engine.state.actors[OWNER].conditions.values())


def _fastens_tether(bundles, tether_ft=30):
    """_decisive, plus one test-only free action the owner can take to fasten a tether to a creature.

    It carries the printed Chains Tether's own row data (``condition_data {"tether_ft": n}`` on a Bound condition) and
    nothing else. It exists so the test can put a real tether on the creature and still have the Action the shove needs:
    the printed "Set the Tether" is an Action whose tether lasts "until the start of your next turn", so pressing it
    would spend the very action Get Over Here needs. What is under test here is Get Over Here reading a tether state.
    The row is a declared free activation (``free_primary``): economy NONE alone is not a turn intent, and a Reaction
    is only offered through its own trigger window, so neither would let this setup step be taken on the owner's turn.
    """
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind

    _decisive(bundles)
    owner = bundles[0]
    typed = {"effects": [{"type": "condition", "condition": "bound", "applies_to": "target",
                          "duration": "until_start_of_next_turn",
                          "condition_data": {"tether_ft": tether_ft},
                          "evidence": "The target becomes Bound until the start of your next turn."}],
             "numbers": {}, "duration": {"kind": "instant"}, "range_ft": 60, "source": SET_TETHER, "riders": []}
    action = ActionDefinition(
        source_definition_id="action:typed.test.auto107_fasten_tether", display_name="Fasten the Tether",
        owner_id=owner["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED",
        target_kind="HOSTILE_ENTITY", range_ft=60,
        parameters={"typed": typed, "expected_damage": 0, "free_primary": True})
    owner['action_catalog'].append(action.model_dump(mode='json'))
    owner['actor_template']['action_ids'] = list(owner['actor_template'].get('action_ids') or ()) + [action.source_definition_id]
    owner.pop('bundle_sha256', None)
    seal(owner)


def _offered(engine, name, target=FOE):
    return [c for c in engine.legal_candidates()
            if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None) == name
            and c.target_ids == (target,)]


def _pick(engine, name, target=FOE):
    rows = _offered(engine, name, target)
    assert len(rows) == 1, f"{name} is not offered exactly once against {target}"
    return rows[0]


def _distance(engine):
    """Distance between the two creatures' bodies: nearest occupied squares, as the engine measures reach.

    Anchor-to-anchor is not enough once the owner is Large: printed growth re-anchors the token while it still
    occupies the square it stood on, so the body is closer than the anchor square suggests.
    """
    return engine._distance_actor_to_actor(engine.state.actors[FOE], engine.state.actors[OWNER])


def _tethered(tmp_path, talents, *, position, transform=None, tether_ft=30, primary="Qi", cl=15):
    """A Brute owning Get Over Here, with a tether of the owner's fastened to the foe (see _fastens_tether)."""
    combat, table, mid = fixture(tmp_path, [SHOVE, GET_OVER_HERE, *talents], primary=primary, cl=cl,
                                 bundle_transform=transform or (lambda b: _fastens_tether(b, tether_ft)),
                                 foe_position=position)
    settle(table, mid, candidate(combat, mid, 'Fasten the Tether', target=FOE).candidate_id, {})
    return combat, table, mid, reload(tmp_path, mid)


def _sub(tmp_path, name):
    """A second fight in the same test needs its own character-sheet folders."""
    path = tmp_path / name
    path.mkdir(exist_ok=True)
    return path


def _activate(table, mid, combat, name, *, next_turn=False):
    """Spend the owner's turn taking their own Court/Sovereign state.

    Court and Sovereign are both Bonus Actions, so turning on two of them needs two turns. On a new turn the tether
    has lapsed (a tether lasts until the start of your next turn, whatever duration its condition asks for, because the
    owner has moved on from it), so the test refastens it before taking the second state.
    """
    if next_turn:
        end_turn(table, mid)
        turn(table, mid, OWNER)
        settle(table, mid, candidate(combat, mid, 'Fasten the Tether', target=FOE).candidate_id, {})
    settle(table, mid, candidate(combat, mid, name, target=OWNER).candidate_id, {})
    return table, mid


COURT_NAME = "Court of the Moving Mountain"
SOV_NAME = "Sovereign Weight Incarnation"


def _base_action():
    """The ordinary Brutal Shove button a Brute compiles, as compile_actions receives it."""
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind

    typed = {"effects": [{"type": "brutal_shove", "applies_to": "target", "max_size_larger": 1, "no_damage": False,
                          "evidence": "Brutal Shove: push the target 5 feet away or knock it Prone."}],
             "numbers": {}, "duration": {"kind": "instant"}, "range_ft": 5, "source": SHOVE, "riders": []}
    return ActionDefinition(source_definition_id="action:typed.auto107.granted.shove", display_name="Brutal Shove",
                            owner_id=OWNER, economy=EconomyKind.ACTION, resolution_kind="TYPED",
                            target_kind="HOSTILE_ENTITY", range_ft=5,
                            parameters={"typed": typed, "expected_damage": 0})


def test_tether_shove_is_offered_only_to_the_talent_owner(tmp_path):
    """The plug-in is inert for a Brute that does not own Get Over Here, tether or no tether."""
    _, _, _, owned = _tethered(tmp_path, [], position=NEAR)
    assert _offered(owned, TETHER) != [], "the owner of the talent may shove through its tether"
    _, _, mid = fixture(_sub(tmp_path, 'no_talent'), [SHOVE], bundle_transform=_decisive, foe_position=NEAR)
    e = reload(_sub(tmp_path, 'no_talent'), mid)
    assert _offered(e, TETHER) == [], "a Brute without the talent never gets the button"
    assert _offered(e, ASIDE) == []


def test_tether_shove_needs_a_tether_attached_to_that_creature(tmp_path):
    """"When you control one end of a tether attached to a creature": until a tether of the owner's is attached, there is
    nothing to shove with, so the button is not offered at all."""
    combat, table, mid = fixture(tmp_path, [SHOVE, GET_OVER_HERE], bundle_transform=_decisive, foe_position=NEAR)
    e = reload(tmp_path, mid)
    assert _offered(e, TETHER) == [], "no tether attached: the printed admission is not met"
    assert _offered(e, 'Brutal Shove') != [], "the ordinary shove is still offered in natural reach"


def test_tether_shove_reaches_exactly_the_tether_length(tmp_path):
    """"as though it were within reach" -- the reach is that tether's own length (Set the Tether: 30 feet), never the
    whole battlefield."""
    _, _, _, inside = _tethered(tmp_path, [], position=FAR)
    assert _distance(inside) == 30
    assert _offered(inside, TETHER) != [], "30 feet is the whole tether"
    assert _offered(inside, 'Brutal Shove') == [], "only the tether reaches that far"
    _, _, _, inside = _tethered(_sub(tmp_path, 'short_tether'), [], position=INSIDE, tether_ft=15)
    assert _distance(inside) == 15
    assert _offered(inside, TETHER) != [], "15 feet is inside a 15-foot tether"
    _, _, _, outside = _tethered(_sub(tmp_path, 'past_short_tether'), [], position=BEYOND, tether_ft=15)
    assert _distance(outside) == 20
    assert _offered(outside, TETHER) == [], "20 feet is past that tether's 15 feet"


def test_tether_shove_moves_the_target_toward_the_shover(tmp_path):
    """"On a success, move the target toward you instead of away" -- where the ordinary shove's push grows the distance."""
    _, table, mid, e = _tethered(tmp_path, [], position=FAR)
    start = _distance(e)
    settle(table, mid, _pick(e, TETHER).candidate_id, {'choice:needle.brutal_shove_result': 'push'})
    after = _distance(reload(tmp_path, mid))
    assert after < start, f"the tether shove should have dragged {FOE} toward {OWNER} ({start} -> {after})"


def test_ordinary_brutal_shove_still_pushes_away(tmp_path):
    combat, table, mid = fixture(tmp_path, [SHOVE, GET_OVER_HERE, SET_TETHER], bundle_transform=_decisive,
                                 foe_position=NEAR)
    e = reload(tmp_path, mid)
    start = _distance(e)
    settle(table, mid, _pick(e, 'Brutal Shove').candidate_id, {'choice:needle.brutal_shove_result': 'push'})
    after = _distance(reload(tmp_path, mid))
    assert after > start, f"the ordinary shove pushes away ({start} -> {after})"


def test_shove_aside_needs_its_own_printed_talent(tmp_path):
    """Shove Aside is a Brute Maneuvers option ("Use Brutal Shove to move the target into one different legal space
    within your reach"); Get Over Here only says what changes when the creature uses it, so it must not hand it out.
    The character sheet grants every Brute Maneuvers, so this asks the compiler seam directly."""
    from combat.ext import brute_tether

    base = _base_action()
    def compile_with(owned):
        info = {"spheres": [BRUTE_SPHERE], "owned_ids": {GET_OVER_HERE, *owned}, "actor_id": OWNER,
                "short": "auto107", "numbers": {}, "actions": [base]}
        return [a.display_name for a in (brute_tether.tether_buttons(info) or ())]
    assert "Get Over Here: Shove" in compile_with(set())
    assert "Get Over Here: Shove Aside" not in compile_with(set()), "no Brute Maneuvers, no Shove Aside"
    assert "Get Over Here: Shove Aside" in compile_with({MANEUVERS})


def test_tether_shove_carries_the_owners_manhandle_talents(tmp_path):
    """"Apply Manhandle talents normally": the owner's own Manhandle talent rides on the tether shove, as it does on the
    ordinary one, and the ordinary button keeps its own."""
    _, _, _, e = _tethered(tmp_path, [TAKEDOWN], position=NEAR)
    assert _offered(e, TETHER) != [], "the plain tether shove is still offered"
    assert _offered(e, TETHER_TAKEDOWN) != [], "the owner's Takedown is on the tether shove"
    assert _offered(e, 'Brutal Shove + Takedown') != [], "the ordinary shove keeps its own variant"


def test_takedown_through_the_tether_applies_when_the_pull_ends_the_target_in_reach(tmp_path):
    """"Apply Manhandle talents normally": the owner's Takedown is applied by the tether shove, and its own printed reach
    requirement is checked on the target's square after the pull -- a pull that ends the target adjacent grapples it.
    (The negative half of that printed line -- a pull that ends it out of reach -- is lane4_brute's own Takedown check,
    covered by that module's tests; this is the tether integration.)"""
    _, table, mid, e = _tethered(tmp_path, [TAKEDOWN], position={'x': 3, 'y': 9})
    start = len(e.events)
    settle(table, mid, _pick(e, TETHER_TAKEDOWN).candidate_id, {'choice:needle.brutal_shove_result': 'push'})
    e = reload(tmp_path, mid)
    assert _distance(e) == 5, f"the pull must drag the target to adjacent, not leave it at {_distance(e)} feet"
    assert any('grappled' in c.condition_id for c in e.state.actors[FOE].conditions.values()), \
        "the pull ended the target in reach, so Takedown's Grapple attempt grappled it"
    assert not [ev for ev in e.events[start:] if ev.event_type == 'GM_RIDER' and 'no Grapple attempt' in str(ev.payload)], \
        "the pull ended the target in reach, so Takedown did not skip its Grapple attempt"


@pytest.mark.parametrize("talents,names,extra", [((), (), 0), ((COURT,), (COURT_NAME,), 5),
                                                 ((SOV,), (SOV_NAME,), 10), ((COURT, SOV), (COURT_NAME, SOV_NAME), 15)])
def test_activated_court_and_sovereign_move_the_target_toward_the_shover(tmp_path, talents, names, extra):
    """Court of the Moving Mountain ("when Brutal Shove succeeds, move the target 5 additional feet") and Sovereign Weight
    Incarnation ("once per turn when you successfully shove, move the target 10 additional feet") must move the creature the
    same way the Get Over Here shove moved it: toward, not back out.

    This is a table-level regression with the states actually activated, after a commit and a cold reload. The old
    version only *owned* Court, never turned it on, so the bonus it measured was never applied and its assertion passed
    with the direction bug still in place. The contest margin is pinned below 5 (_narrow), so Brutal Shove's own
    "5 feet per 5 points of margin" movement is 0 feet and the exact distance asserted here is the 5 foot pull plus the
    rider's own feet.
    """
    combat, table, mid, e = _tethered(tmp_path, list(talents), position=FAR,
                                       transform=lambda b: (_fastens_tether(b), _narrow(b)))
    for index, name in enumerate(names):
        _activate(table, mid, combat, name, next_turn=bool(index))
    e = reload(tmp_path, mid)
    start = _distance(e)
    assert start == 30, start
    settle(table, mid, _pick(e, TETHER).candidate_id, {'choice:needle.brutal_shove_result': 'push'})
    e = reload(tmp_path, mid)
    _margin(e)
    after = _distance(e)
    assert after == start - 5 - extra, \
        f"a pull of 5 feet plus {extra} feet of rider movement should leave {start - 5 - extra} feet, not {after}"


def test_takedown_needs_natural_reach_not_the_s_weapon_reach(tmp_path):
    """"talents requiring natural reach function only if the target ends within natural reach".

    The owner here holds a printed reach weapon, so its melee profile reaches 10 feet, and the pull leaves the target
    exactly 10 feet away. Natural reach is the body, so the talent must NOT grapple. Reading the weapon's reach here
    (the bug this guards) let a reach weapon grant natural reach.
    """
    from combat.ext import reach_bonus

    _, table, mid, e = _tethered(tmp_path, [TAKEDOWN], position=INSIDE,
                                 transform=lambda b: (_fastens_tether(b, 15), _narrow(b, reach_weapon_ft=10)))
    assert _distance(e) == 15, _distance(e)
    assert reach_bonus.natural_reach_ft(e, e.state.actors[OWNER]) == 5, \
        "a 10-foot reach weapon is not the body: natural reach stays 5 feet"
    start = len(e.events)
    settle(table, mid, _pick(e, TETHER_TAKEDOWN).candidate_id, {'choice:needle.brutal_shove_result': 'push'})
    e = reload(tmp_path, mid)
    _margin(e)
    assert _distance(e) == 10, f"the pull of 5 feet must leave the target 10 feet away, not {_distance(e)}"
    assert not any('grappled' in c.condition_id for c in e.state.actors[FOE].conditions.values()), \
        "10 feet away is outside natural reach even when the owner wields a 10-foot reach weapon"
    assert any('no Grapple attempt' in str(ev.payload) for ev in e.events[start:] if ev.event_type == 'GM_RIDER'), \
        "the talent must say why it did not grapple"


def test_a_real_body_form_extends_natural_reach_through_commit_reload_and_expiry(tmp_path):
    """The other half of that printed line, with a real printed body increase instead of a test-only one.

    Calamity Briar Incarnation: "Unarmed reach +10 feet" for the duration. Its reach row is compiled into this
    fighter's own packet (combat/ext/reach_bonus.py), so natural reach is 5 feet before the form, 15 while the state
    is on, and 5 again once the form's own one-minute duration runs out -- each read after a real table commit and a
    cold reload. The same pull that must not grapple at 10 feet in the test above therefore grapples here, because a
    body that really reaches 15 feet is inside natural reach.

    The Iron Fist base ability in _body_form is what gives the sheet an unarmed strike while the reach rows compile;
    the extended-reach button it produces is asserted too, because it is the same compiled row -- one implementation of
    one printed increase, read by the attack menu and by the talent alike.
    """
    from combat.ext import reach_bonus

    combat, table, mid, e = _tethered(tmp_path, [TAKEDOWN, *_body_form()], position=INSIDE, primary="Stamina", cl=18,
                                       transform=lambda b: (_fastens_tether(b, 15), _narrow(b)))
    owner = e.state.actors[OWNER]
    assert reach_bonus.natural_reach_ft(e, owner) == 5, "the body is 5 feet long until a printed form says otherwise"
    assert _distance(e) == 15, _distance(e)

    settle(table, mid, candidate(combat, mid, BRIAR, target=OWNER).candidate_id, {})
    e = reload(tmp_path, mid)
    owner = e.state.actors[OWNER]
    assert _has_briar(e), sorted(owner.conditions)
    assert reach_bonus.natural_reach_ft(e, owner) == 15, \
        f'"Unarmed reach +10 feet" is a real compiled body increase, not {_distance(e)}'
    offered = {getattr(e.action_catalog.get(c.source_definition_id), 'display_name', None)
               for c in e.legal_candidates() if c.target_ids == (FOE,)}
    assert 'Unarmed Strike (Iron Fist) (extended reach)' in offered, \
        'the same compiled row must offer its 15-foot unarmed strike, so reach is one implementation'

    settle(table, mid, _pick(e, TETHER_TAKEDOWN).candidate_id, {'choice:needle.brutal_shove_result': 'push'})
    e = reload(tmp_path, mid)
    _margin(e)
    assert _distance(e) == 10, f"the pull of 5 feet must leave the target 10 feet away, not {_distance(e)}"
    assert any('grappled' in c.condition_id for c in e.state.actors[FOE].conditions.values()), \
        "a body that genuinely reaches 15 feet is inside natural reach, so the Grapple attempt is made"

    for _ in range(4 * 12):  # the printed one-minute duration, in rounds; not a token of this test's own
        if not _has_briar(e):
            break
        end_turn(table, mid)
        e = reload(tmp_path, mid)
    else:
        raise AssertionError("the body form never expired")
    assert reach_bonus.natural_reach_ft(e, e.state.actors[OWNER]) == 5, \
        "the form's own duration ran out, so the body is 5 feet again"


def test_the_push_or_prone_prompt_says_which_way_the_creature_moves(tmp_path):
    """The question the player answers must describe the move that happens, and name the ability that asked it."""
    for index, (name, moved, ability) in enumerate(((TETHER, 'toward you', 'Get Over Here'),
                                                    ('Brutal Shove', 'away', 'Brutal Shove'))):
        _, table, mid, e = _tethered(_sub(tmp_path, f'prompt{index}'), [], position=NEAR)
        prompts = settle(table, mid, _pick(e, name).candidate_id, {})
        asked = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.brutal_shove_result']
        assert len(asked) == 1, [p['context']['reaction_source_id'] for p in prompts]
        shown = ' '.join(str(asked[0][field]) for field in ('moment', 'trigger', 'title', 'reaction'))
        assert moved in shown.lower(), f"{name} must describe the move it makes: {shown}"
        assert ability in shown, shown
        assert {o['id'] for o in asked[0]['choice']['options']} == {'push', 'prone'}
        labels = ' '.join(o['label'] for o in asked[0]['choice']['options'])
        assert moved in labels.lower(), labels
        assert not any(word in shown for word in ('TAL_', 'brutal_shove', 'choice:', 'NEEDLE')), shown
