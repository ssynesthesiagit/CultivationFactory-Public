"""AUTO120 Life: eligibility gates that the printed text requires, at the table.

Every case drives the real ability through ``TabletopService`` and then cold-reloads the saved
session, so each assertion reads committed fight state rather than an in-memory shortcut.  The
cases differ in what they commit: the offer-time gates below commit the setup action and then read
which casts the table offers, while the cast cases (``test_life_seal_reaches_a_sealed_ally_at_range``,
the Life-Seal Reach permission cases and the restraint cases) commit the ability itself and assert
its effect.
"""
import pytest

from tests.cw2_service_support import add_action
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload

P = 'tianxia.talent.life.'
ESCAPE_CHOICE = 'choice:needle.life_escape_skill'


def _injury(bundles):
    for bundle in bundles:
        add_action(bundle, 'Prepare injury', [{'type': 'damage', 'flat': 10, 'damage_types': ['force'], 'applies_to': 'target'}])


def _named(engine, name, target):
    return [c for c in engine.legal_candidates()
            if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '') == name
            and c.target_ids == (target,)]


def test_borrowed_breath_needs_an_injured_target(tmp_path):
    """"Borrowed Breath can only be used on an injured target."

    The gate used to raise NameError on every Borrowed Breath candidate, which the
    dispatcher logged and ignored, so the printed limit was never applied.
    """
    from tests.worker2_support import settle

    combat, table, mid = fixture(tmp_path, ['LIFE_BASE_BORROWED_BREATH'], bundle_transform=_injury, seed='AUTO120-BB')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].current_hp == engine.state.actors[ALLY].maximum_hp
    assert not _named(engine, 'Borrowed Breath', ALLY), 'Borrowed Breath offered on an uninjured target'

    settle(table, mid, candidate(combat, mid, 'Prepare injury', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].current_hp == 50
    assert _named(engine, 'Borrowed Breath', ALLY), 'Borrowed Breath not offered on an injured target'


def test_latent_healing_may_ride_an_uninjured_carrier(tmp_path):
    """Latent Healing's printed exception: the carrier need not be injured yet."""
    combat, table, mid = fixture(tmp_path, [P + 'latent_healing'], bundle_transform=_injury, seed='AUTO120-LATENT')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].current_hp == engine.state.actors[ALLY].maximum_hp
    offered = [getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '')
               for c in engine.legal_candidates() if c.target_ids == (ALLY,)
               and 'Borrowed Breath' in getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '')]
    # Lasting Breath is now an executable printed augment. Both delayed
    # variants remain legal on an uninjured carrier; ordinary Breath does not.
    assert sorted(offered) == [
        'Borrowed Breath + Latent Healing',
        'Borrowed Breath + Latent Healing + Lasting Breath (1 extra cultivation point; until your Long Rest)',
    ], offered


@pytest.mark.parametrize('owned,expected', [(False, False), (True, True)])
def test_esoteric_vitality_lifts_mend_undead_construct_limit(tmp_path, owned, expected):
    """"Mend the Pulse has no effect on undead or constructs unless a talent says otherwise."

    Esoteric Vitality: "Mend the Pulse ... can affect undead, constructs, animated objects,
    and artificial bodies that possess an animating pattern."
    """
    def as_construct(bundles):
        bundles[1]['actor_template']['creature_types'] = ['Construct']

    talents = [P + 'esoteric_vitality'] if owned else []
    combat, table, mid = fixture(tmp_path, talents, bundle_transform=as_construct, seed=f'AUTO120-EV{int(owned)}')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].creature_types == ('Construct',)
    assert bool(_named(engine, 'Mend the Pulse', ALLY)) is expected


def test_no_life_hook_failure_is_logged(tmp_path):
    """The candidate_allowed gate must not raise: a swallowed hook failure is a silent rule loss.

    The dispatcher records a failing hook into ``_ext_failures_logged`` while it builds the
    candidate list, so the list has to be generated *on this engine* before the set is read --
    otherwise the assertion passes without ever calling the hook.
    """
    combat, table, mid = fixture(tmp_path, ['LIFE_BASE_BORROWED_BREATH', P + 'latent_healing'],
                                 bundle_transform=_injury, seed='AUTO120-CLEAN')
    engine = reload(tmp_path, mid)
    engine.legal_candidates()  # the hook under test runs here, not at reload time
    assert engine.legal_candidates(), 'the fixture produced no candidates at all'
    assert not getattr(engine, '_ext_failures_logged', set()), getattr(engine, '_ext_failures_logged', set())


def _seal(bundles):
    for bundle in bundles:
        add_action(bundle, 'Seal ally', [{'type': 'mark', 'mark': 'Pulse Seal',
                                          'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'}])


def _mend_casts(engine):
    return sorted({getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '')
                   for c in engine.legal_candidates()
                   if (a := engine.action_catalog.get(c.source_definition_id)) is not None
                   and 'Mend the Pulse' in a.display_name})


@pytest.mark.parametrize('path,reach_expected', [('Qi Cultivation', True), ('Body Refining', False)])
def test_life_seal_reach_is_withheld_from_body_refiners(tmp_path, path, reach_expected):
    """Life-Seal Reach: "Body Refiners cannot use Life-Seal Reach unless they have a forged technique,
    subpath feature, variant scripture, or GM permission that explains how their bodily Life cultivation
    remains physically connected."

    The typed modifier compiled its remote variant for every character, so a Body Refiner was offered a
    reach their Path forbids.
    """
    from tests.worker2_support import settle

    combat, table, mid = fixture(tmp_path, [P + 'life_seal_reach', 'LIFE_BASE_MEND_THE_PULSE'],
                                 bundle_transform=_seal, owner_path=path, seed=f'AUTO120-LSR{path[:4]}')
    settle(table, mid, candidate(combat, mid, 'Seal ally', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    casts = _mend_casts(engine)
    assert 'Mend the Pulse' in casts, casts
    assert ('Mend the Pulse + Life-Seal Reach' in casts) is reach_expected, casts


def test_life_seal_reach_reaches_a_sealed_ally_at_range(tmp_path):
    """The reach itself works: a Pulse Seal bearer beyond touch is mended from across the room.

    The ally stands 35 feet away -- outside the 5-foot touch range -- and is injured, so the cast
    can only resolve through Life-Seal Reach's printed remote range.  This commits the cast and
    then cold-reloads, so it proves the healing happened, not merely that a button appeared.
    """
    from tests.worker2_support import settle

    combat, table, mid = fixture(tmp_path, [P + 'life_seal_reach', 'LIFE_BASE_MEND_THE_PULSE'],
                                 bundle_transform=lambda bundles: (_seal(bundles), _injury(bundles)),
                                 owner_path='Qi Cultivation', ally_position={'x': 10, 'y': 10},
                                 seed='AUTO120-LSRUSE')
    settle(table, mid, candidate(combat, mid, 'Seal ally', target=ALLY).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Prepare injury', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    assert engine._distance_actor_to_actor(engine.state.actors[OWNER], ally) > 5, 'the ally is in touch range'
    assert ally.current_hp < ally.maximum_hp, 'the ally is not injured'
    reach = [c for c in engine.legal_candidates()
             if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '') == 'Mend the Pulse + Life-Seal Reach'
             and c.target_ids == (ALLY,)]
    assert reach, 'Life-Seal Reach did not offer a cast on a Pulse Seal bearer'
    assert engine.action_catalog[reach[0].source_definition_id].range_ft == 120
    before_hp = ally.current_hp
    before_qi = engine.state.actors[OWNER].resources['resource:core.qi']
    settle(table, mid, reach[0].candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].current_hp > before_hp, 'the remote mend healed nobody'
    assert engine.state.actors[OWNER].resources['resource:core.qi'] < before_qi, 'the mend was free'

# ------------------------------------------------------------------ Life-Seal Reach: the printed permission
SUBPATH = 'tianxia.subpath.qi.abyssal_depths_cultivator.feature.deep_s_embrace'
REACH = P + 'life_seal_reach'
PERMISSION = {'talent_id': REACH, 'record_id': 'gm-note-2026-10-06',
              'note': 'Forged Meridian Breathing: the GM ruled this Body Refiner\'s Life Seal stays physically joined '
                      'to whoever wears the Pulse Seal.'}


def _remote_mend(tmp_path, talents, path, seed, **kw):
    """Commit the reach on a sealed, injured ally 35 feet away and return the reloaded engine."""
    from tests.worker2_support import settle

    combat, table, mid = fixture(tmp_path, talents, bundle_transform=lambda b: (_seal(b), _injury(b)),
                                 owner_path=path, ally_position={'x': 10, 'y': 10}, seed=seed, **kw)
    settle(table, mid, candidate(combat, mid, 'Seal ally', target=ALLY).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Prepare injury', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    before = engine.state.actors[ALLY].current_hp
    reach = [c for c in engine.legal_candidates()
             if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '') == 'Mend the Pulse + Life-Seal Reach'
             and c.target_ids == (ALLY,)]
    if not reach:
        return None, before
    settle(table, mid, reach[0].candidate_id)
    return reload(tmp_path, mid), before


def test_life_seal_reach_permission_lets_an_authorised_body_refiner_cast_it(tmp_path):
    """A Body Refiner whose GM recorded the permission keeps the reach their text grants.

    Life-Seal Reach: "Body Refiners cannot use Life-Seal Reach unless they have a forged technique,
    subpath feature, variant scripture, or GM permission that explains how their bodily Life cultivation remains
    physically connected."  Withholding the reach from a Body Refiner who *has* that permission would take away a
    legal cast, so the recorded permission has to reach the table -- and keep reaching it after the fight is saved
    and reloaded, which this commits and then cold-reads.
    """
    engine, before = _remote_mend(tmp_path, [REACH, 'LIFE_BASE_MEND_THE_PULSE'],
                                  'Body Refining', 'AUTO120-LSRPERM', owner_permission=PERMISSION)
    assert engine is not None, 'a Body Refiner with a recorded permission was not offered Life-Seal Reach'
    assert engine.state.actors[ALLY].current_hp > before, 'the permitted remote mend healed nobody'
    assert any(action.parameters.get('life_seal_reach_permission') == PERMISSION
               for action in engine.action_catalog.values()), 'reload lost the permission ruling and its source'


def test_life_seal_reach_stays_withheld_from_an_unauthorised_body_refiner(tmp_path):
    """The same cast, with nothing recorded: the printed Path restriction still holds."""
    engine, _before = _remote_mend(tmp_path, [REACH, 'LIFE_BASE_MEND_THE_PULSE'],
                                   'Body Refining', 'AUTO120-LSRBARE')
    assert engine is None, 'an unauthorised Body Refiner was offered Life-Seal Reach'


def test_life_seal_reach_stays_withheld_from_an_ordinary_body_feature(tmp_path):
    """A learned Body feature is not a permission: only the recorded one opens the reach.

    "Body Refiners cannot use Life-Seal Reach unless they have a forged technique, subpath feature,
    variant scripture, or GM permission that explains how their bodily Life cultivation remains physically
    connected."  Deep's Embrace is a real subpath feature of another character, and the table cannot tell whether
    it is the *qualifying* one, so it never treats an ordinary learned feature as permission.
    """
    engine, _before = _remote_mend(tmp_path, [REACH, 'LIFE_BASE_MEND_THE_PULSE', SUBPATH],
                                   'Body Refining', 'AUTO120-LSRFEAT')
    assert engine is None, 'an ordinary learned path feature granted Life-Seal Reach'


def test_life_seal_reach_stays_withheld_from_a_permission_for_another_talent(tmp_path):
    """The permission record names the talent it grants, so another talent's cannot open this one."""
    engine, _before = _remote_mend(tmp_path, [REACH, 'LIFE_BASE_MEND_THE_PULSE'], 'Body Refining',
                                   'AUTO120-LSROTHER', owner_permission={'talent_id': P + 'meridian_unbinding',
                                                                          'note': 'unrelated permission'})
    assert engine is None, 'a permission recorded for another talent granted Life-Seal Reach'



# ------------------------------------------------------------------ Meridian Unbinding: mundane restraints
NET_TALENT = 'tianxia.talent.trap.net'
NOOSE_TALENT = 'TAL_TRAP_NOOSE'


def _net_owner(bundles):
    """Prepare a separate hold through a table action for cleanup-isolation assertions."""
    add_action(bundles[0], 'Prepare unrelated grapple', [
        {'type': 'condition', 'condition': 'grappled', 'applies_to': 'target',
         'expires_on': 'UNTIL_REMOVED', 'hold_kind': 'ordinary_physical'},
    ])


def _net_fight(tmp_path, seed, owner_dc=30, extra=(), trap_talents=(NET_TALENT,), form='Net (Snare use)',
               ally_talents=(), ally_skills=None):
    """A real Trap net on ALLY, committed through the table and cold-reloaded.

    The trapper's Save DC is raised so the net reliably lands; the resulting ``netted`` marker and its
    Restrained row are the Trap plug-in's own printed record of a physical bond.
    """
    from tests.worker2_support import settle, turn

    combat, table, mid = fixture(tmp_path, [*trap_talents, P + 'meridian_unbinding', *extra],
                                 cl=20, owner_dc=owner_dc, bundle_transform=_net_owner, seed=seed,
                                 ally_talents=ally_talents, ally_skills=ally_skills)

    def set_trap():
        engine = combat._load_session(mid).engine
        return next(c for c in engine.legal_candidates()
                    if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '') == 'Set Trap'
                    and c.destination and (c.destination.x, c.destination.y) == (3, 5))

    settle(table, mid, candidate(combat, mid, f'Trap form: {form}').candidate_id)
    settle(table, mid, set_trap().candidate_id)
    turn(table, mid, ALLY)
    walk = [c for c in combat._load_session(mid).engine.legal_candidates()
            if c.display_name == 'Move to 3,5' and c.actor_id == ALLY]
    settle(table, mid, walk[0].candidate_id)
    engine = reload(tmp_path, mid)
    held = {c.condition_id for c in engine.state.actors[ALLY].conditions.values()}
    assert 'condition:typed.restrained' in held, f'the net did not land: {held}'
    assert 'condition:typed.netted' in held, f'the trap recorded no netted marker: {held}'
    return combat, table, mid


def _escape_checks(engine):
    return [e.payload for e in engine.events
            if e.event_type == 'CHECK_ROLLED' and e.payload.get('check') == 'Escape']


def _conditions(engine, actor=ALLY):
    return {c.condition_id for c in engine.state.actors[actor].conditions.values()}


def _forced_checks(monkeypatch, natural):
    """One creature's CHECK: d20 is the given face, every other roll stays the seeded one."""
    from combat.gate2_rolls import DeterministicRollAuthority

    real = DeterministicRollAuthority.d20

    def dice(roller, **kwargs):
        while True:
            roll = real(roller, **kwargs)
            if kwargs['actor_id'] != ALLY or not kwargs['reason'].startswith('CHECK:') or roll.natural_result == natural:
                return roll

    monkeypatch.setattr(DeterministicRollAuthority, 'd20', dice)


def test_meridian_unbinding_does_not_delete_a_mundane_net(tmp_path):
    """"This does not remove mundane restraints unless your treatment gives the target a chance to
    escape them." (Meridian Unbinding)

    A patient caught in a net was freed simply by picking "Remove Restrained", with no escape
    attempted. The treatment must now give the target its printed escape chance; when that check
    fails the bond stands.
    """
    from tests.worker2_support import settle, turn

    combat, table, mid = _net_fight(tmp_path, 'AUTO120-NET')
    turn(table, mid, OWNER)
    purify = [c for c in combat._load_session(mid).engine.legal_candidates()
              if 'Meridian Unbinding' in c.display_name and tuple(c.target_ids or ()) == (ALLY,)]
    settle(table, mid, purify[0].candidate_id, {'choice:needle.purify_extra': 'restrained'})
    engine = reload(tmp_path, mid)
    held = {c.condition_id for c in engine.state.actors[ALLY].conditions.values()}
    checks = _escape_checks(engine)
    assert checks, 'Meridian Unbinding removed the restraint without offering an escape'
    assert checks[-1]['dc'] == 30, checks
    if not checks[-1]['success']:
        assert 'condition:typed.restrained' in held, 'a failed escape still deleted the net'


def test_deep_root_does_not_delete_a_mundane_net(tmp_path):
    """Deep Root removes "any conditions ... Purify the Pulse or your Life talents could remove
    individually", so it inherits Meridian Unbinding's escape requirement for a mundane restraint."""
    from tests.worker2_support import settle, turn

    combat, table, mid = _net_fight(tmp_path, 'AUTO120-NETROOT', extra=(P + 'deep_root_restoration',))
    engine = reload(tmp_path, mid)
    turn(table, mid, OWNER)
    deep = [c for c in combat._load_session(mid).engine.legal_candidates()
            if 'Deep Root' in c.display_name and tuple(c.target_ids or ()) == (ALLY,)]
    assert deep, 'Deep Root was not compiled for this character'
    settle(table, mid, deep[0].candidate_id, {'choice:needle.deep_root': ['restrained']})
    engine = reload(tmp_path, mid)
    assert _escape_checks(engine), 'Deep Root removed a net without offering an escape'
    held = {c.condition_id for c in engine.state.actors[ALLY].conditions.values()}
    if not _escape_checks(engine)[-1]['success']:
        assert 'condition:typed.restrained' in held, 'a failed escape still deleted the net'


def test_meridian_unbinding_frees_a_mundane_bond_the_target_escapes(tmp_path):
    """The permission branch: when the treatment's escape chance succeeds, the bond really ends.

    The hold is an ordinary physical restraint (its own row declares ``hold_kind:
    ordinary_physical``) with a DC the target always beats, so this covers the success path that the
    net cases above deliberately fail.
    """
    from tests.worker2_support import settle

    def net(bundles):
        add_action(bundles[0], 'Snare the patient',
                   [{'type': 'condition', 'condition': 'restrained', 'applies_to': 'target',
                     'expires_on': 'UNTIL_REMOVED', 'hold_kind': 'ordinary_physical',
                     'condition_data': {'escape_dc': 1}}])

    combat, table, mid = fixture(tmp_path, [P + 'meridian_unbinding'], bundle_transform=net, seed='AUTO120-BOND')
    settle(table, mid, candidate(combat, mid, 'Snare the patient', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.restrained' for c in engine.state.actors[ALLY].conditions.values())
    purify = [c for c in engine.legal_candidates()
              if 'Meridian Unbinding' in c.display_name and tuple(c.target_ids or ()) == (ALLY,)]
    settle(table, mid, purify[0].candidate_id, {'choice:needle.purify_extra': 'restrained'})
    engine = reload(tmp_path, mid)
    checks = _escape_checks(engine)
    assert checks and checks[-1]['success'], checks
    assert not any(c.condition_id == 'condition:typed.restrained' for c in engine.state.actors[ALLY].conditions.values())


# ------------------------------------------------------------------ the escape the treatment grants
ATHLETICS = [{'skill': 'Athletics', 'bonus': 12}]
ACROBATICS = [{'skill': 'Acrobatics', 'bonus': 12}]
IRON_BONE = 'TAL_METAL_IRON_BONE_INTERNAL_METHOD'


def _treat(combat, table, mid, label, picks=None):
    """Commit the owner's Meridian Unbinding on ALLY, answering its Remove Restrained choice."""
    from tests.worker2_support import settle, turn

    turn(table, mid, OWNER)
    purify = [c for c in combat._load_session(mid).engine.legal_candidates()
              if label in c.display_name and tuple(c.target_ids or ()) == (ALLY,)]
    assert purify, f'{label} was not offered on the patient'
    return settle(table, mid, purify[0].candidate_id, {'choice:needle.purify_extra': 'restrained', **(picks or {})})


@pytest.mark.parametrize('trap_talents,form,extra_markers', [
    (NET_TALENT, 'Net (Snare use)', ()),
    (NOOSE_TALENT, 'Noose', ('condition:typed.silenced',)),
])
def test_a_freed_real_net_takes_its_own_marker_with_it(tmp_path, monkeypatch, trap_talents, form, extra_markers):
    """A successful escape ends the whole bond, not just the Restrained row.

    "A Restrained creature may take the Utilize Action to make a Strength (Athletics) or Dexterity
    (Acrobatics) check against your Cultivation Save DC, ending the condition on itself on a success."
    The Trap plug-in records a net or noose twice -- the Restrained row and its own "Caught in a net" marker
    beside it -- so freeing only the restraint left the pill and the Escape the net action behind, for a net and for
    a noose's silence as well. The check is given a fixed 20 and the patient a real Athletics bonus, so the success
    branch is the one under test; everything is read after a commit and a cold reload.
    """
    from tests.worker2_support import settle, turn

    _forced_checks(monkeypatch, 20)
    combat, table, mid = _net_fight(tmp_path, f'AUTO120-FREE{form[:4]}', trap_talents=(trap_talents,),
                                    form=form, ally_skills=ATHLETICS)
    trapped = reload(tmp_path, mid)
    markers = [c for c in trapped.state.actors[ALLY].conditions.values() if c.condition_id == 'condition:typed.netted']
    assert markers and all(not c.data.get('hold_id') for c in markers), 'this case must exercise untracked cleanup'
    assert set(extra_markers) <= _conditions(trapped)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Prepare unrelated grapple', target=ALLY).candidate_id)
    other_hold = {iid for iid, c in reload(tmp_path, mid).state.actors[ALLY].conditions.items()
                  if c.condition_id == 'condition:typed.grappled'}
    assert other_hold
    _treat(combat, table, mid, 'Meridian Unbinding')
    engine = reload(tmp_path, mid)
    checks = _escape_checks(engine)
    assert checks and checks[-1]['success'], checks
    held = _conditions(engine)
    assert 'condition:typed.restrained' not in held, held
    assert 'condition:typed.netted' not in held, f'the freed net kept its marker: {held}'
    for marker in extra_markers:
        assert marker not in held, f'the freed bond kept {marker}: {held}'
    assert other_hold <= set(engine.state.actors[ALLY].conditions), 'treatment removed an unrelated grapple'
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    escape_buttons = [c.display_name for c in engine.legal_candidates()
                      if c.actor_id == ALLY and 'scape the net' in (c.display_name or '')]
    assert not escape_buttons, escape_buttons


def test_the_granted_escape_uses_the_patients_own_skill_bonus(tmp_path, monkeypatch):
    """"your treatment gives the target a chance to escape them": the patient escapes in its own right.

    A proficient patient must not be worse off here than with the restraint's own Escape the net action: the
    printed check is Strength (Athletics) or Dexterity (Acrobatics), so skill proficiency counts. The patient lists
    Athletics +12 against a plain +2 Strength, and the check is given the worst possible d20 -- the recorded roll
    therefore proves which bonus answered it, and the net standing afterwards proves nothing was deleted instead.
    """
    combat, table, mid = _net_fight(tmp_path, 'AUTO120-BONUS', ally_skills=ATHLETICS)
    _forced_checks(monkeypatch, 1)
    _treat(combat, table, mid, 'Meridian Unbinding')
    engine = reload(tmp_path, mid)
    checks = _escape_checks(engine)
    assert checks, 'the treatment gave no escape chance at all'
    roll = checks[-1]['actor']
    assert checks[-1]['ability'] == 'STR', checks[-1]
    assert roll['modifier'] == 12, f'the check ignored the patient\'s Athletics proficiency: {roll}'
    assert not checks[-1]['success'], checks[-1]
    assert 'condition:typed.restrained' in _conditions(engine), 'a failed check still deleted the net'


@pytest.mark.parametrize('patient_auto', [False, True])
def test_the_patient_chooses_the_check_it_escapes_with(tmp_path, monkeypatch, patient_auto):
    """The check is the patient's: it picks its own ability and skill, whoever is acting.

    The patient lists Acrobatics +12 and no Athletics, and answers with Dexterity; the recorded roll has to
    name that ability and that skill's bonus, which the old mixed-skill path could not do.
    """
    from tests.worker2_support import turn

    combat, table, mid = _net_fight(tmp_path, 'AUTO120-SKILL', ally_skills=ACROBATICS)
    turn(table, mid, OWNER)
    if patient_auto:
        combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='LOCAL_AUTO')
    _forced_checks(monkeypatch, 1)
    prompts = _treat(combat, table, mid, 'Meridian Unbinding', {ESCAPE_CHOICE: 'DEX'})
    choices = [p for p in prompts if p['context']['reaction_source_id'] == ESCAPE_CHOICE]
    assert bool(choices) is not patient_auto, choices
    engine = reload(tmp_path, mid)
    checks = _escape_checks(engine)
    assert checks, 'the treatment gave no escape chance at all'
    assert checks[-1]['ability'] == 'DEX', f'the patient\'s own choice was not used: {checks[-1]}'
    assert checks[-1]['actor']['modifier'] == 12, checks[-1]['actor']


def test_the_escape_honours_the_patients_scoped_check_benefit(tmp_path, monkeypatch):
    """A scoped benefit against being Restrained reaches this check too.

    Iron-Bone's own printed "Advantage on Strength and Constitution checks against forced movement, Grappled,
    Restrained, and Prone" is recorded as a hazard-scoped check rule, so the treatment's escape check reads it
    only when the check names its hazard -- which the shared explicit-check route does and the old unscoped
    route did not.
    """
    from tests.worker2_support import settle, turn

    combat, table, mid = _net_fight(tmp_path, 'AUTO120-SCOPED', ally_talents=(IRON_BONE,), ally_skills=ATHLETICS)
    # The patient activates its own benefit first, then its turn ends.
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Iron-Bone Internal Method: Advantage on Checks').candidate_id)
    assert 'condition:typed.check_against' in _conditions(reload(tmp_path, mid))
    _forced_checks(monkeypatch, 1)
    _treat(combat, table, mid, 'Meridian Unbinding')
    engine = reload(tmp_path, mid)
    checks = _escape_checks(engine)
    assert checks, 'the treatment gave no escape chance at all'
    assert checks[-1]['actor']['mode'] == 'ADVANTAGE', f'the scoped benefit was ignored: {checks[-1]}'


def test_a_player_patient_answers_its_escape_during_an_ai_turn(tmp_path, monkeypatch):
    """A player-owned decision is asked whoever is acting: the healer here is the automatic controller.

    The healer plays Deep Root Restoration -- "any conditions ... Purify the Pulse or your Life talents could remove
    individually" -- whose own menu for this patient is exactly [Restrained], so the AI reaches the escape without a
    player choosing anything. The patient's skill choice is a player decision and must still stop the fight, on the
    AI's turn.
    """
    from tests.r1i_service_support import force_ai_candidate
    from tests.worker2_support import turn

    _forced_checks(monkeypatch, 20)
    combat, table, mid = _net_fight(tmp_path, 'AUTO120-AITURN', extra=(P + 'deep_root_restoration',),
                                    ally_skills=ATHLETICS)
    turn(table, mid, OWNER)
    deep = [c for c in combat._load_session(mid).engine.legal_candidates()
            if 'Deep Root' in c.display_name and tuple(c.target_ids or ()) == (ALLY,)]
    assert deep, 'Deep Root was not compiled for this character'
    force_ai_candidate(combat, mid, OWNER, deep[0].candidate_id)
    answers, prompts = [], []
    for _ in range(20):
        result = table.auto_step(mid, 0, list(answers))
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            break
        p = result['reaction']
        prompts.append(p)
        rid = p['context']['reaction_source_id']
        choice = {ESCAPE_CHOICE: 'STR'}.get(rid, 'first' if rid.startswith('choice:') else None)
        answer = {**p['context'], 'selection': 'USE' if choice is not None else 'DECLINE'}
        if choice is not None and p.get('choice'):
            answer['option_ids'] = [p['choice']['options'][0]['id']] if choice == 'first' else [choice]
        answers.append(answer)
    else:
        raise AssertionError('Too many prompts')
    asked = [p for p in prompts if p['context']['reaction_source_id'] == ESCAPE_CHOICE]
    assert asked, f'the patient was never asked for its check: {[p["context"]["reaction_source_id"] for p in prompts]}'
    assert all(p['context']['reactor_id'] == ALLY for p in asked), [p['context']['reactor_id'] for p in asked]
    engine = reload(tmp_path, mid)
    assert all('Deep Root' in p['moment'] and engine.state.actors[ALLY].display_name in p['moment']
               for p in asked)
    checks = _escape_checks(engine)
    assert checks and checks[-1]['success'], checks
    assert 'condition:typed.restrained' not in _conditions(engine)
    assert 'condition:typed.netted' not in _conditions(engine)
