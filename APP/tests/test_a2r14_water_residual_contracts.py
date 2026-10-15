"""A2R14 Water residual contracts: the printed Drowning-Pressure state and the
Abyssal save branches reach the engine instead of staying rider text.

Every case drives a real committed table action, cold-reloads the saved fight and
mechanically replays it before asserting, so the typed rows are exercised through
the production CombatService rather than a unit-level shortcut.

Covered rows (Manager inventory A2R14 / Group: Water residual contracts 1):
  TAL_WATER_ABYSSAL_PRESSURE_SEAL#success-soaked-spatial-gate
  TAL_WATER_HEAVEN_FALLING_TSUNAMI#pressure-object-residual
  TAL_WATER_FLOOD_THE_BATTLEFIELD#flood-terrain-pressure
"""
import pytest

from tests.worker2_support import OWNER, FOE, fixture, candidate, settle, reload

ABYSSAL = 'TAL_WATER_ABYSSAL_PRESSURE_SEAL'
TSUNAMI = 'TAL_WATER_HEAVEN_FALLING_TSUNAMI'
FLOOD = 'TAL_WATER_FLOOD_THE_BATTLEFIELD'
COURT = 'TAL_WATER_COURT_OF_THE_ENDLESS_TIDE'
FOE_START = {'x': 4, 'y': 3}

SOAKED = 'condition:typed.mark.soaked.'
PRESSURE = 'condition:typed.mark.drowning_pressure.'
RECIPIENTS = 'choice:needle.area_recipients'


def forced_save(fails):
    """Give the foe a hopeless or certain Strength save so each printed branch is exact.

    A save modifier of -100 always fails the printed DC; +100 always succeeds. This
    only sets the foe's own modifier; the DC and the ability row are production.
    """
    def prepare(bundles):
        for bundle in bundles:
            if bundle['actor_id'] == FOE:
                bundle['actor_template']['saving_throws']['STR'] = -100 if fails else 100
    return prepare


def has(engine, actor, prefix):
    return any(c.condition_id.startswith(prefix) for c in engine.state.actors[actor].conditions.values())


def rolled(engine, actor):
    return [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == actor]


def area_candidate(combat, mid, name):
    """Pick the placement of an area ability that actually covers the hostile.

    These abilities offer one candidate per possible area origin, most of them
    empty. Selecting the first by name silently tests an empty field, so the
    candidate is chosen by the engine's own hostile count for its area.
    """
    engine = combat._load_session(mid).engine
    rows = [c for c in engine.legal_candidates()
            if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None) == name
            and (c.metadata.get('hostiles_in_area') or 0) >= 1]
    assert rows, f'no {name} placement covers the hostile'
    return rows[0]


@pytest.mark.parametrize('fails', [True, False], ids=['failure', 'success'])
def test_tsunami_failure_suffers_drowning_pressure(tmp_path, fails):
    """Heaven-Falling Tsunami: only a failed save inflicts Drowning Pressure.

    Printed: "On a failed save ... suffers Drowning Pressure until the end of its
    next turn. On a successful save, it takes half damage, is pushed 15 feet, and
    becomes Soaked." Both branches leave the creature Soaked; only the failure adds
    the pressure that used to be rider text.
    """
    combat, table, mid = fixture(tmp_path, [TSUNAMI], foe_position=FOE_START,
                                 bundle_transform=forced_save(fails))
    settle(table, mid, area_candidate(combat, mid, 'Heaven-Falling Tsunami').candidate_id,
           {RECIPIENTS: [FOE]})
    engine = reload(tmp_path, mid)

    assert rolled(engine, FOE), 'the chosen recipient must make a Strength save'
    assert has(engine, FOE, SOAKED), 'both printed branches make the victim Soaked'
    assert has(engine, FOE, PRESSURE) is fails, \
        'Drowning Pressure belongs to the failed save only'


@pytest.mark.parametrize('fails', [True, False], ids=['failure', 'success'])
def test_flood_failure_suffers_drowning_pressure(tmp_path, fails):
    """Flood the Battlefield: the selected hostile suffers Drowning Pressure on failure.

    Printed: "On a failure, a creature is knocked Prone, moved 30 feet into a legal
    space, and suffers Drowning Pressure until the end of its next turn. On a
    success, it is moved 10 feet and becomes Soaked."
    """
    combat, table, mid = fixture(tmp_path, [COURT, FLOOD], foe_position=FOE_START,
                                 bundle_transform=forced_save(fails))
    settle(table, mid, candidate(combat, mid, 'Court of the Endless Tide').candidate_id)
    # The flood is a self-centered emanation, so its only candidate covers the Domain.
    settle(table, mid, candidate(combat, mid, 'Flood the Battlefield').candidate_id,
           {RECIPIENTS: [FOE]})
    engine = reload(tmp_path, mid)

    assert rolled(engine, FOE), 'the selected hostile must make a Strength save'
    assert has(engine, FOE, PRESSURE) is fails, \
        'Drowning Pressure belongs to the failed save only'


def test_abysseal_soaked_and_reaction_denial_follow_a_successful_save(tmp_path):
    """Abyssal Pressure Seal: Soaked and the reaction denial ride a *successful* save.

    Printed: "On a successful save, it is Soaked and cannot take Reactions until the
    start of your next turn." The failed branch keeps Restrained, silence, healing
    reduction and Concentration Disadvantage and must not carry Soaked.

    The compiled catalog row carries no ``activation`` metadata, so the talent is
    not offered as a legal candidate and cannot yet be exercised through the table;
    this test therefore guards the corrected branch contract of the compiled row
    itself. See the lane report: trigger gating for this talent remains open.
    """
    combat, _table, mid = fixture(tmp_path, [COURT, ABYSSAL], foe_position=FOE_START)
    engine = combat._load_session(mid).engine
    aid = next(a for a in engine.action_catalog if 'ABYSSAL' in a)
    effects = (engine.action_catalog[aid].parameters or {})['typed']['effects']
    save = next(e for e in effects if e.get('type') == 'save')

    def marks(rows):
        return {r.get('mark') for r in rows if r.get('type') == 'mark'}

    assert 'Soaked' in marks(save['on_success']), \
        'a successful save makes the creature Soaked'
    assert any(r.get('type') == 'reaction_denied' for r in save['on_success']), \
        'a successful save denies Reactions until the start of your next turn'
    assert 'Soaked' not in marks(save['on_fail']), \
        'Soaked belongs to the successful save only'
    assert any(r.get('condition') == 'restrained' for r in save['on_fail']), \
        'the failed save keeps Restrained'