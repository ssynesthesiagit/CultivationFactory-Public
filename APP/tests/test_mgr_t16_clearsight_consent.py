"""Allied creator consent belongs to the creator, tied to one live Clearsight."""
import pytest
from combat import zones, senses
from combat.ext.tabik_dark import CLEARSIGHT_PERMISSION
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn

CLEAR = 'TAL_DARK_CLEARSIGHT'
PURE = 'TAL_DARK_PURE_DARKNESS'


@pytest.mark.parametrize('allow', [False, True])
@pytest.mark.parametrize('creator_ai', [False, True])
def test_allied_darkness_creator_owns_consent_on_any_casters_turn(tmp_path, allow, creator_ai):
    def separate_area(bundles):
        # Keep an independently created area after Clearsight Concentration ends.
        for bundle in bundles:
            for action in bundle['action_catalog']:
                if action['display_name'] == 'Darkness':
                    action['concentration'] = False
                    action['parameters']['typed']['duration']['concentration'] = False
    combat, table, mid = fixture(tmp_path, [CLEAR, PURE], ally_talents=[PURE],
                                bundle_transform=separate_area, named=True)
    if creator_ai:
        combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='LOCAL_AUTO')
    prompts = settle(table, mid, candidate(combat, mid, 'Meld: Clearsight', target=OWNER).candidate_id,
                     picks={'choice:needle.clearsight_creator_consent': 'allow' if allow else None})
    engine = reload(tmp_path, mid)
    holder = engine.state.actors[OWNER]
    permissions = [c for c in holder.conditions.values() if c.condition_id == CLEARSIGHT_PERMISSION]
    assert bool(permissions) == (allow or creator_ai)
    if not creator_ai:
        assert any('Tobin' in str(p) and 'Clearsight' in str(p) for p in prompts)
    else:
        assert not prompts
    if permissions:
        assert permissions[0].source_actor_id == ALLY
        assert permissions[0].data['meld_instance'] in holder.conditions
    turn(table, mid, ALLY)
    # Explicitly choose this actor's own Darkness, then create it around the recipient.
    combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='MANUAL')
    settle(table, mid, candidate(combat, mid, 'Shape Darkness: Pure Darkness').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Darkness', at=(3, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    area = next(z for z in zones.typed_zones(engine) if z.owner_id == ALLY)
    assert zones.clear_sighted(engine, area, engine.state.actors[OWNER]) == (allow or creator_ai)
    assert not zones.clear_sighted(engine, area, engine.state.actors[FOE])
    turn(table, mid, OWNER)
    # Replacing Clearsight requires new creator consent. Earlier answers do not
    # apply to the replacement, even though the source action is the same.
    settle(table, mid, candidate(combat, mid, 'Meld: Clearsight', target=OWNER).candidate_id,
           picks={'choice:needle.clearsight_creator_consent': None})
    engine = reload(tmp_path, mid)
    area = next(z for z in zones.typed_zones(engine) if z.owner_id == ALLY)
    assert not zones.clear_sighted(engine, area, engine.state.actors[OWNER])
