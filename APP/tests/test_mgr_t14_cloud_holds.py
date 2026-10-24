"""Cloud Immortal's printed physical-hold clause at the table (Ling reserve, Cloud Walker).

Printed: "You cannot be Grappled or Restrained by a physical effect whose Source CL
is no higher than yours." The form records the owning source's CL and the shared
`physical_holds` classifier decides whether an incoming Grappled/Restrained row is an
ordinary physical hold. A physical hold from a higher Source CL still lands, a magical
hold is never refused, and beginning the form ends a hold that already qualifies.

Every scene is a real table commit: compiled characters in a saved fight, then a cold
reload. The Cloud Walker's compiled saving throws are lowered, so the printed failure
branch is reached deterministically and the failing SAVE_ROLLED events are asserted;
a hold missing from the target is then the rule's answer, never a lucky make.
"""
from combat.canonical import canonical_sha256
from combat.ext.qi_subpaths_five import CLOUD
from tests.h1_support import sheet
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn

IMMORTAL = CLOUD + 'cloud_immortal'
FORM = 'condition:typed.cloud_walker_form'
GRAPPLE = 'condition:typed.grappled'
RESTRAINED = 'condition:typed.restrained'
BLACK_STAR_GRIP = 'tianxia.talent.gravity.black_star_grip'  # "Grappled by gravitational pressure"
OWNER_CL = 18  # Cloud Immortal is the CL18 Cloud Walker leaf
PLACES = {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 2, 'y': 6}, FOE: {'x': 4, 'y': 6}}


def _rehash(bundle):
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


def _fails_every_save(bundles):
    bundles[0]['actor_template']['saving_throws'] = {key: -50 for key in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')}
    _rehash(bundles[0])


def scene(root, *, foe_cl=OWNER_CL, foe_talents=(), probe=None, form=True):
    """OWNER at CL18 with Cloud Immortal beside a foe compiled at `foe_cl`, in one real fight."""
    def prepare(bundles):
        _fails_every_save(bundles)
        if probe is not None:
            probe(bundles)

    c, t, mid = fixture(root, [], cl=OWNER_CL, owner_features=[IMMORTAL], ask=True, seed='CLOUD-HOLDS',
                        foe_sheet=sheet(list(foe_talents), cl=foe_cl), bundle_transform=prepare, positions=PLACES)
    if form:
        begin_the_form(c, t, mid, root)
    return c, t, mid


def committed(c, root, mid):
    """The same fight, cold reloaded from disk, with its sheet commitment and journal replay verified."""
    session = c._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    return reload(root, mid)


def begin_the_form(c, t, mid, root):
    settle(t, mid, candidate(c, mid, 'Cloud Immortal').candidate_id)
    engine = committed(c, root, mid)
    recorded = [row for row in engine.state.actors[OWNER].conditions.values() if row.condition_id == FORM]
    assert recorded and recorded[0].data['source_cl'] == OWNER_CL, 'the form did not record its owning source CL'


def holds(engine, condition=GRAPPLE, actor=OWNER):
    return [row for row in engine.state.actors[actor].conditions.values() if row.condition_id == condition]


def failed_saves(engine):
    return [event for event in engine.events
            if event.event_type == 'SAVE_ROLLED' and event.payload.get('success') is False]


def foe_grapples(t, c, mid):
    turn(t, mid, FOE)
    settle(t, mid, candidate(c, mid, 'Grapple', target=OWNER).candidate_id)


def test_immortal_form_refuses_an_ordinary_physical_grapple_at_its_own_source_cl(tmp_path):
    """(a) An ordinary Grapple from a Source CL no higher than the form's does not land.

    The control is the same table without the form: that creature's failed Grapple save
    really does grapple it, so the refusal is the printed rule and not a made save.
    """
    root = tmp_path / 'through'
    c, t, mid = scene(root)
    foe_grapples(t, c, mid)
    engine = committed(c, root, mid)
    assert failed_saves(engine), 'the Grapple save did not fail, so the refusal would be untested'
    assert not holds(engine), 'an ordinary Grapple held a Cloud Immortal from an equal Source CL'

    root = tmp_path / 'without'
    c, t, mid = scene(root, form=False)
    foe_grapples(t, c, mid)
    engine = committed(c, root, mid)
    assert failed_saves(engine)
    held = holds(engine)
    assert held, 'the ordinary Grapple no longer holds anything, so the refusal proves nothing'
    assert held[0].data.get('grappling_part'), 'the control hold is not the physical Grapple'


def test_immortal_form_keeps_a_physical_grapple_from_a_higher_source_cl(tmp_path):
    """(b) "no higher than yours" is a bound: a physical hold from a higher Source CL still holds the cloud."""
    c, t, mid = scene(tmp_path, foe_cl=OWNER_CL + 2)
    foe_grapples(t, c, mid)
    engine = committed(c, tmp_path, mid)
    assert failed_saves(engine)
    held = holds(engine)
    assert held, 'a higher Source CL ordinary Grapple was refused by Cloud Immortal'
    assert held[0].source_actor_id == FOE


def test_immortal_form_refuses_a_physical_restraint_at_its_own_source_cl(tmp_path):
    """(c) The clause covers Restrained as well as Grappled.

    The applied row is the Trap plug-in's own net row (combat/ext/trap.py, "Failed Save:
    The creature has the Restrained condition until it escapes or the net is destroyed",
    hold_kind ordinary_physical), carried by a public table action so the shared reducer
    sees exactly the data a real net produces.
    """
    def net_row(bundles):
        bundle, sid = bundles[2], 'action:test.cloud_holds.net'
        bundle['action_catalog'].append({
            'source_definition_id': sid, 'display_name': 'A thrown net', 'owner_id': FOE,
            'economy': 'ACTION', 'resolution_kind': 'TYPED', 'target_kind': 'HOSTILE_ENTITY', 'range_ft': 30,
            'parameters': {'typed': {'numbers': {'cl': OWNER_CL}, 'effects': [
                {'type': 'condition', 'condition': 'restrained', 'applies_to': 'target', 'until_escape': True,
                 'hold_kind': 'ordinary_physical'}]}}})
        bundle['actor_template']['action_ids'].append(sid)
        _rehash(bundle)

    root = tmp_path / 'through'
    c, t, mid = scene(root, probe=net_row)
    turn(t, mid, FOE)
    settle(t, mid, candidate(c, mid, 'A thrown net', target=OWNER).candidate_id)
    engine = committed(c, root, mid)
    assert not holds(engine, RESTRAINED), 'an ordinary physical Restrained condition held a Cloud Immortal'

    root = tmp_path / 'without'
    c, t, mid = scene(root, probe=net_row, form=False)
    turn(t, mid, FOE)
    settle(t, mid, candidate(c, mid, 'A thrown net', target=OWNER).candidate_id)
    engine = committed(c, root, mid)
    assert holds(engine, RESTRAINED), 'the net no longer restrains anything, so the refusal proves nothing'


def test_immortal_form_does_not_stop_a_magical_grapple(tmp_path):
    """(d) A magical Grapple is not a physical effect, so the clause never refuses it."""
    from combat.ext.physical_holds import source

    c, t, mid = scene(tmp_path, foe_talents=[BLACK_STAR_GRIP])
    turn(t, mid, FOE)
    settle(t, mid, candidate(c, mid, 'Black-Star Grip', target=OWNER).candidate_id)
    engine = committed(c, tmp_path, mid)
    held = holds(engine)
    assert held, 'Cloud Immortal refused a magical Grapple'
    assert held[0].source_actor_id == FOE
    assert source(engine, held[0])[0] is False, 'the gravitational grip must not classify as an ordinary hold'


def test_beginning_the_form_releases_an_existing_qualifying_physical_hold(tmp_path):
    """(e) The form's own start ends a hold it could have refused, and the release survives reload and replay."""
    c, t, mid = scene(tmp_path, form=False)
    foe_grapples(t, c, mid)
    assert holds(committed(c, tmp_path, mid)), 'the Grapple did not land before the form, so the release is untested'
    begin_the_form(c, t, mid, tmp_path)
    engine = committed(c, tmp_path, mid)
    assert not holds(engine), 'beginning Cloud Immortal kept an ordinary physical Grapple it should end'
    released = [event for event in engine.events
                if event.event_type == 'CONDITION_REMOVED' and event.actor_id == OWNER
                and (event.payload or {}).get('condition_id') == GRAPPLE]
    assert released, 'the released hold left no native CONDITION_REMOVED record'


def test_beginning_the_form_keeps_a_hold_from_a_higher_source_cl(tmp_path):
    """(f) The release uses the refusal's own bound: a higher Source CL hold stays through the form."""
    c, t, mid = scene(tmp_path, foe_cl=OWNER_CL + 2, form=False)
    foe_grapples(t, c, mid)
    assert holds(committed(c, tmp_path, mid)), 'the higher Source CL Grapple did not land'
    begin_the_form(c, t, mid, tmp_path)
    assert holds(committed(c, tmp_path, mid)), 'beginning Cloud Immortal ended a hold from a higher Source CL'
