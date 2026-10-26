"""Sky-Fire Nerve Net: the real Meridian trigger, the printed per-turn clock, and both save branches.

Printed (authority/typed_mechanics/rules_text.json, TAL_LIGHTNING_SKY_FIRE_NERVE_NET):
"When a creature fails a saving throw against Meridian-Stopping Spark, you may choose one additional Charged creature
within 20 feet of it. The additional creature makes a Constitution saving throw. Failed Save: It cannot take Reactions
until the start of its next turn and has Disadvantage on the next Constitution saving throw it makes to maintain
Concentration before the end of its next turn. Successful Save: It loses its Charge. This talent can affect only one
additional creature each turn."

The save and both branches belong to a second creature the owner picks, never to the creature that already failed.
These are table-level tests: every one drives the real TabletopService, answers the printed prompts (accumulating
answers, as _check_pending_request requires), and reloads the committed fight.
"""
import copy
import json
import zipfile

from combat import ext
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.typed_executor import mark_condition_id
from tests.h1_support import ROOT, sheet
from tests.hunt15_support import action_sender, reload
from tests.test_carry import KIT
from combat.ext import lightning_riders as L

MERIDIAN = 'TAL_LIGHTNING_MERIDIAN_STOPPING_SPARK'
NET = 'TAL_LIGHTNING_SKY_FIRE_NERVE_NET'
QI = 'resource:core.qi'
LEFT, RIGHT, ALLY = "actor:factory.h15-left", "actor:factory.h15-right", "actor:factory.h15-ally"

#: A Constitution save whose failure carries the "cannot regain CP" condition but is NOT Meridian-Stopping Spark's.
#: Infection of the Cultivation Breath (combat/ext/disease.py:472) and Meridian Ruin Shock
#: (combat/ext/unmaking_forms.py:80) both resolve exactly this, with the save attributed to no named rider.
FOREIGN_SAVE = [{"type": "save", "ability": "con", "dc": "technique_save_dc", "applies_to": "target",
                 "on_fail": [{"type": "condition", "condition": "no_cp_regain", "applies_to": "target",
                              "duration": "until_end_of_next_turn"}],
                 "on_success": []}]


def _rows(engine, actor_id):
    return [(row.get('block'), row.get('kind')) for row in engine.typed_passive_rows.get(actor_id, [])]


def _fight(tmp_path, *, left=(), extra=None, dc=100, cause_effects=(), charged=True, monkeypatch=None):
    """Three creatures: LEFT (the talent's owner) and two hostiles, RIGHT and ALLY, both in melee reach.

    Armor Class 1 and 1000 hit points make every strike land; save DC 100 makes every Constitution save fail unless
    the test forces the outcome otherwise. ALLY is hostile so "until the end of its next turn" resolves to ALLY's
    own next turn, which is what the printed rule says. LEFT also owns a free second melee strike ("Cause", the same
    compiled Unarmed Strike with no Action cost) so one turn can carry two qualifying hits.
    """
    actors = ((LEFT, left, "Keeper", "team:factory"), (RIGHT, (), "Visitor", "team:opponents"),
              (ALLY, (), "Second Blade", "team:opponents"))
    bundles = []
    for aid, owned, name, _team in actors:
        document = sheet(list(owned), cl=15, dc=dc, kit={"starting_kit": KIT})
        stats = document["ability_scores_and_statistics"]
        stats["primary_resource"]["maximum"] = 100
        stats["hit_points"]["maximum"] = 1000
        document["identity"]["display_name"] = name
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
        bundle = compile_character(document, actor_id=aid, reaction_plan={"ask": aid == LEFT})
        # The starting kit's armor decides Armor Class, not the sheet, so pin it here: every strike lands and
        # these tests vary the save DC, not the attack roll.
        bundle["actor_template"]["armor_class"] = 1
        if aid == LEFT:
            unarmed = copy.deepcopy(next(a for a in bundle["action_catalog"] if a["display_name"] == "Unarmed Strike"))
            cause = copy.deepcopy(unarmed)
            cause["source_definition_id"] = "action:test.auto121.cause"
            cause["display_name"] = "Cause"
            cause["economy"] = "NONE"
            cause["costs"] = []
            # A NONE-economy action is a primary turn intent only when it declares itself a printed free
            # activation (combat/primary_intents.py; the compiler seals this for plug-in builders).
            cause["parameters"]["free_primary"] = True
            typed = cause["parameters"]["typed"]
            typed["effects"] = [*(typed.get("effects") or []), *cause_effects]
            bundle["action_catalog"].append(cause)
            bundle["actor_template"]["action_ids"].append("action:test.auto121.cause")
        if extra is not None:
            extra(bundle)
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
        bundles.append(bundle)
    if charged and monkeypatch is not None:
        _charge_both_hostiles(monkeypatch)
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [LEFT, RIGHT, ALLY], {aid: team for aid, _o, _n, team in actors},
        {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}, ALLY: {"x": 4, "y": 5}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [LEFT], [RIGHT, ALLY],
        control_modes={aid: "MANUAL" for aid, _o, _n, _t in actors},
        match_seed="auto121", display_name="AUTO121 Sky-Fire", maximum_rounds=10)["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def _charge_both_hostiles(monkeypatch):
    """Both hostiles carry the printed "Charged" mark placed by LEFT, as Gather Charge would."""
    def charge(engine):
        for aid in (RIGHT, ALLY):
            actor = engine.state.actors.get(aid)
            if actor is not None:
                engine._apply_condition(actor, mark_condition_id("Charged", LEFT), "test:auto121", LEFT,
                                        expires_on="UNTIL_REMOVED")
    monkeypatch.setitem(ext._HOOKS, "match_start", [*ext._HOOKS.get("match_start", []), charge])


def _force_save(ability_holder, outcome, monkeypatch):
    """Make one creature's own typed save resolve to ``outcome`` (the engine's own R6 override seam)."""
    def force(ctx, subject, ability, named, failed):
        if subject.entity_id == ability_holder:
            ctx.engine._typed_roll_outcome = {subject.entity_id: outcome}
    monkeypatch.setitem(ext._HOOKS, "after_save", [*ext._HOOKS.get("after_save", []), force])


def _strike(combat, table, mid, source, target_id, picks):
    """Run one action, answering each printed prompt in turn.

    Answers accumulate: _check_pending_request rejects a re-sent choice whose earlier answers changed, so a real
    Electric Fist -> Meridian -> Sky-Fire chain must carry every answer it already gave.
    """
    send = action_sender(combat, table, mid, source, target_id=target_id)
    answers = []
    result = send(answers)
    seen = []
    for want in picks:
        assert result['status'] == 'REACTION_REQUIRED', (source, result['status'])
        prompt = result['reaction']
        options = [row['id'] for row in (prompt.get('choice') or {}).get('options') or []]
        if want is not None:
            assert want in options, (source, want, options)
        seen.append((options, prompt.get('trigger') or prompt.get('moment') or ''))
        answers.append({**prompt['context'], 'selection': 'USE' if want else 'DECLINE',
                        'option_ids': [want] if want else []})
        result = send(answers)
    return result, seen


def _saves_on(engine, actor_id):
    """The Constitution saves this creature was made to roll (SAVE_ROLLED names the roller as actor_id)."""
    return [event for event in engine.events
            if event.event_type == 'SAVE_ROLLED' and event.actor_id == actor_id]


def _forced_actor(combat, mid, actor_id, candidate_id):
    """Put ``actor_id`` on Local AI and make it take one exact table candidate, the printed way.

    A tactical preference is policy data; the candidate still comes from the production controller, which is
    what local_step then runs. Only the decision source is swapped (the same swap tests.hunt15_support.action_sender
    makes), so this stays fixture setup rather than a change to any engine method.
    """
    from combat.gate4_adapters import ManualControllerAdapter

    real = combat.controller

    class SelectedController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.set_controller_mode(mid, actor_id=actor_id, controller_mode="LOCAL_AUTO")
    combat.controller = SelectedController()
    return real


def _answer(prompt, want):
    """One answer to a printed prompt: ``want`` is an option id, or None for a plain Use/Decline."""
    options = [row['id'] for row in (prompt.get('choice') or {}).get('options') or []]
    assert want is None or want in options, (want, options)
    answer = {**prompt['context'], 'selection': 'USE'}
    if want is not None:
        answer['option_ids'] = [want]
    return answer


def _conditions(actor):
    return {c.condition_id: c for c in actor.conditions.values()}


# --------------------------------------------------------------------------------------- ownership
def test_sky_fire_owns_its_row_only_for_its_owner(tmp_path):
    """The ask's data is compiled for a character that has the talent, and for nobody else."""
    _combat, _table, mid = _fight(tmp_path, left=[MERIDIAN, NET], charged=False)
    engine = reload(_combat, mid)
    assert ('lightning_combat', 'sky_fire') in _rows(engine, LEFT)
    without = tmp_path / "without"
    without.mkdir()
    combat, _t2, mid2 = _fight(without, left=[MERIDIAN], charged=False)
    assert ('lightning_combat', 'sky_fire') not in _rows(reload(combat, mid2), LEFT)


# --------------------------------------------------------------------------------------- the printed ask
def test_the_fist_ask_names_meridian_both_deadlines_and_the_success_outcome(tmp_path, monkeypatch):
    """Checklist 13: the combined menu says which ability, when each penalty ends, and what a save does."""
    combat, table, mid = _fight(tmp_path, left=[L.FIST, MERIDIAN], monkeypatch=monkeypatch)
    result = action_sender(combat, table, mid, 'Unarmed Strike', target_id=RIGHT)([])
    assert result['status'] == 'REACTION_REQUIRED'
    choice = result['reaction'].get('choice') or {}
    labels = {row['id']: (row.get('description') or row.get('label') or '') for row in choice.get('options') or []}
    assert set(labels) == {'SHOCK', 'INTENSIFY'}, labels
    assert 'Meridian-Stopping Spark' in labels['INTENSIFY'], labels['INTENSIFY']
    assert 'cultivation points' in labels['INTENSIFY'].lower(), labels['INTENSIFY']
    assert 'saves' in labels['INTENSIFY'] or 'saving throw' in labels['INTENSIFY'], labels['INTENSIFY']
    trigger = result['reaction'].get('trigger') or choice.get('trigger') or ''
    if not trigger:
        trigger = json.dumps(result['reaction'], ensure_ascii=False)
    assert "start of your next turn" in trigger, trigger
    assert "end of Visitor's next turn" in trigger, trigger
    # The plain Fist penalty is the user's clock, Meridian's is the target's: the menu must not give both one deadline.
    assert "start of Visitor's next turn" not in trigger, trigger


def test_meridian_offers_intensify_on_the_electric_fist_hit_and_charges_one_cp(tmp_path, monkeypatch):
    """Printed: "you may spend 1 CP to intensify the meridian shock. The target makes a Constitution saving throw."

    Its typed modifier named Electric Fist Method, Charged Needle and Conductive Strike, but those are plug-in
    driven rather than compiled actions, so the modifier resolved to 'no matching ability' and the whole rider
    was dropped. The owner must still be offered the intensification on the Fist hit, and only pay for it when
    the intensification is the option taken.
    """
    combat, table, mid = _fight(tmp_path, left=[L.FIST, MERIDIAN], monkeypatch=monkeypatch)
    result, _seen = _strike(combat, table, mid, 'Unarmed Strike', RIGHT, ['INTENSIFY'])
    assert result['status'] == 'COMMITTED', result['status']
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources[QI] == 99
    assert len(_saves_on(engine, RIGHT)) == 2, "Electric Fist's save and Meridian's intensified save"
    assert any('no_cp_regain' in cid for cid in _conditions(engine.state.actors[RIGHT]))


def test_meridian_costs_nothing_when_the_owner_takes_the_plain_shock(tmp_path, monkeypatch):
    """Declining the intensification spends no CP and adds no second save."""
    combat, table, mid = _fight(tmp_path, left=[L.FIST, MERIDIAN], monkeypatch=monkeypatch)
    result, _seen = _strike(combat, table, mid, 'Unarmed Strike', RIGHT, ['SHOCK'])
    assert result['status'] == 'COMMITTED', result['status']
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources[QI] == 100
    assert len(_saves_on(engine, RIGHT)) == 1


def test_a_fist_without_meridian_never_offers_intensify(tmp_path, monkeypatch):
    """The intensification is inert for a character that does not own Meridian-Stopping Spark."""
    combat, table, mid = _fight(tmp_path, left=[L.FIST], monkeypatch=monkeypatch)
    result = action_sender(combat, table, mid, 'Unarmed Strike', target_id=RIGHT)([])
    assert result['status'] == 'REACTION_REQUIRED'
    options = [row['id'] for row in (result['reaction'].get('choice') or {}).get('options') or []]
    assert options == ['SHOCK'], options
    prompt = result['reaction']
    result = action_sender(combat, table, mid, 'Unarmed Strike', target_id=RIGHT)(
        [{**prompt['context'], 'selection': 'USE', 'option_ids': ['SHOCK']}])
    assert result['status'] == 'COMMITTED'
    assert reload(combat, mid).state.actors[LEFT].resources[QI] == 100


# --------------------------------------------------------------------------------------- the additional creature
def test_sky_fire_saves_the_creature_the_owner_picks_and_both_branches_reach_it(tmp_path, monkeypatch):
    """The whole printed chain: Fist hit -> Meridian's failure -> the ask -> the second creature's own save.

    The additional creature's failed save must land on the creature that was picked, must not land on the creature
    that already failed Meridian, and must survive a table commit and reload.
    """
    combat, table, mid = _fight(tmp_path, left=[L.FIST, MERIDIAN, NET], monkeypatch=monkeypatch)
    result, seen = _strike(combat, table, mid, 'Unarmed Strike', RIGHT, ['INTENSIFY', ALLY])
    assert result['status'] == 'COMMITTED', result['status']
    # The second prompt is the printed ask, naming Meridian's save and both outcomes.
    options, prompt = seen[1]
    assert options == [ALLY], options
    assert 'Sky-Fire Nerve Net' in prompt, prompt
    assert 'Meridian-Stopping Spark' in prompt, prompt
    assert 'only one additional creature each turn' in prompt, prompt

    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources[QI] == 99, "1 CP for the intensification"
    assert len(_saves_on(engine, RIGHT)) == 2, "Fist save and Meridian's save, on the struck creature"
    assert len(_saves_on(engine, ALLY)) == 1, "exactly one additional creature's save, and it is ALLY's"

    # The branch reached the picked creature, not the one that already failed.
    picked = _conditions(engine.state.actors[ALLY])
    assert any('reaction_denied' in cid for cid in picked), sorted(picked)
    assert any('concentration_mode' in cid for cid in picked), sorted(picked)
    failed_first = _conditions(engine.state.actors[RIGHT])
    # Meridian's own failure is what put no_cp_regain on RIGHT; Sky-Fire's branches are not Meridian's, so the
    # creature the owner picked is the only one carrying Sky-Fire's pair and the only one that never failed Meridian.
    assert 'condition:typed.no_cp_regain' in failed_first, sorted(failed_first)
    assert 'condition:typed.no_cp_regain' not in picked, sorted(picked)
    # The printed successful-save branch removes the Charge; a failure must not.
    assert mark_condition_id("Charged", LEFT) in picked, sorted(picked)


def test_the_additional_creatures_successful_save_takes_its_charge(tmp_path, monkeypatch):
    """Printed: "Successful Save: It loses its Charge." Only the additional creature loses it."""
    _force_save(ALLY, "success", monkeypatch)
    combat, table, mid = _fight(tmp_path, left=[L.FIST, MERIDIAN, NET], monkeypatch=monkeypatch)
    result, _seen = _strike(combat, table, mid, 'Unarmed Strike', RIGHT, ['INTENSIFY', ALLY])
    assert result['status'] == 'COMMITTED', result['status']
    engine = reload(combat, mid)
    picked = _conditions(engine.state.actors[ALLY])
    assert mark_condition_id("Charged", LEFT) not in picked, sorted(picked)
    assert not any('reaction_denied' in cid for cid in picked), sorted(picked)
    # The printed pair is the Failed Save's whole outcome, so a successful save leaves no Concentration
    # penalty either: nothing may be applied by the branch that does not print it.
    assert not any('concentration_mode' in cid for cid in picked), sorted(picked)
    assert len(_saves_on(engine, ALLY)) == 1
    assert mark_condition_id("Charged", LEFT) in _conditions(engine.state.actors[RIGHT]), "the first target keeps its Charge"


def test_a_constitutional_failure_meridian_did_not_cause_never_opens_sky_fire(tmp_path, monkeypatch):
    """Only Meridian-Stopping Spark's own save is the printed trigger.

    Infection of the Cultivation Breath and Meridian Ruin Shock fail a Constitution save with the very same
    "cannot regain CP" condition. Keying the trigger on that shared condition gave a character who owns Sky-Fire
    an extra save (or a Charge loss / Reaction denial) on abilities it never touched.
    """
    combat, table, mid = _fight(tmp_path, left=[L.FIST, MERIDIAN, NET], cause_effects=FOREIGN_SAVE,
                                 monkeypatch=monkeypatch)
    result = action_sender(combat, table, mid, 'Cause', target_id=RIGHT)([])
    if result['status'] == 'REACTION_REQUIRED':  # the Fist's own ask still comes; it is not the Sky-Fire ask
        prompt = result['reaction']
        options = [row['id'] for row in (prompt.get('choice') or {}).get('options') or []]
        assert set(options) == {'SHOCK', 'INTENSIFY'}, options
        result = action_sender(combat, table, mid, 'Cause', target_id=RIGHT)(
            [{**prompt['context'], 'selection': 'USE', 'option_ids': ['SHOCK']}])
    assert result['status'] == 'COMMITTED', result['status']
    engine = reload(combat, mid)
    # The foreign failure is real (that is the shared signature the old gate matched on)...
    assert any('no_cp_regain' in cid for cid in _conditions(engine.state.actors[RIGHT])), \
        sorted(_conditions(engine.state.actors[RIGHT]))
    # ...and it opened nothing: no ask, no second creature, no save of its own.
    assert len(_saves_on(engine, ALLY)) == 0, "Sky-Fire added a save nobody printed"
    assert not any('sky_fire' in str(cid) or 'reaction_denied' in cid
                   for cid in _conditions(engine.state.actors[ALLY])), sorted(_conditions(engine.state.actors[ALLY]))


# --------------------------------------------------------------------------------------- the once-per-turn clock
def test_declining_the_additional_creature_leaves_the_turns_use_available(tmp_path, monkeypatch):
    """Declining affects no creature, so it must not spend the printed "one additional creature each turn"."""
    combat, table, mid = _fight(tmp_path, left=[L.FIST, MERIDIAN, NET], monkeypatch=monkeypatch)
    result, seen = _strike(combat, table, mid, 'Unarmed Strike', RIGHT, ['INTENSIFY', None])
    assert result['status'] == 'COMMITTED', result['status']
    options, _prompt = seen[1]
    assert options == [ALLY], options
    engine = reload(combat, mid)
    assert len(_saves_on(engine, ALLY)) == 0, "declining saved nobody"
    assert not engine.state.actors[LEFT].turn_flags.get(L.NET_USES), "declining spent the turn's use"

    # A second qualifying hit in the same turn must still offer the talent.
    send = action_sender(combat, table, mid, 'Cause', target_id=ALLY)
    result = send([])
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    options = [row['id'] for row in (prompt.get('choice') or {}).get('options') or []]
    assert set(options) == {'SHOCK', 'INTENSIFY'}, options
    result = send([{**prompt['context'], 'selection': 'USE', 'option_ids': ['INTENSIFY']}])
    assert result['status'] == 'REACTION_REQUIRED', 'the turn\'s use was spent by declining'
    second = result['reaction']
    options = [row['id'] for row in (second.get('choice') or {}).get('options') or []]
    assert options == [RIGHT], options
    assert len(_saves_on(reload(combat, mid), ALLY)) == 0


def test_accepting_the_additional_creature_spends_the_turns_use(tmp_path, monkeypatch):
    """The accepted use closes the printed once-per-turn limit for the rest of that turn."""
    combat, table, mid = _fight(tmp_path, left=[L.FIST, MERIDIAN, NET], monkeypatch=monkeypatch)
    result, _seen = _strike(combat, table, mid, 'Unarmed Strike', RIGHT, ['INTENSIFY', ALLY])
    assert result['status'] == 'COMMITTED', result['status']
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].turn_flags.get(L.NET_USES), sorted(engine.state.actors[LEFT].turn_flags)
    saves_after_first = len(_saves_on(engine, ALLY))

    send = action_sender(combat, table, mid, 'Cause', target_id=ALLY)
    result = send([])
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    options = [row['id'] for row in (prompt.get('choice') or {}).get('options') or []]
    assert set(options) == {'SHOCK', 'INTENSIFY'}, options
    result = send([{**prompt['context'], 'selection': 'USE', 'option_ids': ['INTENSIFY']}])
    # No further prompt: the turn's single use was already spent on ALLY, so Meridian's new failure asked nothing.
    assert result['status'] == 'COMMITTED', result['status']
    engine = reload(combat, mid)
    assert len(_saves_on(engine, RIGHT)) == 2, "the spent turn saved RIGHT as well"
    # ALLY's own two strikes are the only extra saves it made (the second hit's Fist and Meridian saves).
    assert len(_saves_on(engine, ALLY)) == saves_after_first + 2


def test_the_turn_clock_is_swept_at_any_creatures_turn_start(tmp_path, monkeypatch):
    """'each turn' is the shared all-creature clock, not the owner's own turn.

    An owner-turn flag is only cleared when that owner starts a turn, which blocked a qualifying hit on somebody
    else's turn; combat/turn_uses.py sweeps the once_per_turn: namespace from every actor at every turn start.
    """
    assert L.NET_USES.startswith('once_per_turn:'), L.NET_USES
    combat, table, mid = _fight(tmp_path, left=[L.FIST, MERIDIAN, NET], monkeypatch=monkeypatch)
    result, _seen = _strike(combat, table, mid, 'Unarmed Strike', RIGHT, ['INTENSIFY', ALLY])
    assert result['status'] == 'COMMITTED', result['status']
    assert reload(combat, mid).state.actors[LEFT].turn_flags.get(L.NET_USES)

    from tests.hunt15_support import act
    for _ in range(2):  # end LEFT's turn; the next creature's turn starts and sweeps the use
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    reset = [e for e in engine.events
             if e.event_type == 'PER_TURN_USES_RESET' and L.NET_USES in ((e.payload or {}).get('keys') or [])]
    assert reset, "the use was never swept by a turn start"
    assert any((e.payload or {}).get('turn_actor_id') != LEFT for e in reset), \
        [(e.event_type, e.payload) for e in reset]
    assert not engine.state.actors[LEFT].turn_flags.get(L.NET_USES), sorted(engine.state.actors[LEFT].turn_flags)


# --------------------------------------------------------------------------------------- off-turn, on an AI turn
def test_the_manual_owner_answers_the_whole_chain_off_turn_and_both_penalties_end_as_printed(tmp_path, monkeypatch):
    """Checklist items 7 and 9 on the path the rest of this file never drove: the owner is a real player, the
    current actor is Local AI, and the qualifying hit happens on somebody else's turn.

    AUTO121r2 finding 1: the clock test above only advanced turns and read the use flag. It never made an
    off-turn qualifying hit, never answered the manual owner's choice during an AI actor's turn, and never
    asserted that either Sky-Fire condition expires, so an off-turn consent regression or a premature or
    permanent penalty would have passed. Everything here is a real table decision:

      * the owner spends its printed use on its own turn, then Local AI walks it out of reach;
      * the owner's Opportunity Attack, the Fist hit's choice and Meridian's intensification are all asked of
        that manual owner while the AI's action is still in flight, and nothing commits until it answers;
      * "each turn" is the shared all-creature clock, so that earlier use does not block the off-turn one;
      * the two penalties carry the two different printed deadlines, both read off the saved table: the
        Reaction denial ends at the recipient's next turn start, and the Concentration penalty is still there
        at that same boundary and ends at the end of that turn.
    """
    from combat.gate3_reducer import canonical_state_sha256
    from tests.hunt15_support import act

    combat, table, mid = _fight(tmp_path, left=[L.FIST, MERIDIAN, NET], monkeypatch=monkeypatch)

    # The owner's own turn spends the printed use, and the additional creature's save lands there.
    result, _seen = _strike(combat, table, mid, 'Unarmed Strike', RIGHT, ['INTENSIFY', ALLY])
    assert result['status'] == 'COMMITTED', result['status']
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].turn_flags.get(L.NET_USES), "the prior use"
    assert engine.state.actors[LEFT].resources[QI] == 99
    saves_after_own_turn = len(_saves_on(engine, ALLY))

    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert engine.state.current_actor_id == RIGHT, engine.state.current_actor_id
    # The prior use was swept by somebody else's turn start, which is what makes the off-turn one legal.
    assert not engine.state.actors[LEFT].turn_flags.get(L.NET_USES), sorted(engine.state.actors[LEFT].turn_flags)
    assert [e for e in engine.events if e.event_type == 'PER_TURN_USES_RESET'
            and L.NET_USES in ((e.payload or {}).get('keys') or [])
            and (e.payload or {}).get('turn_actor_id') == RIGHT], "RIGHT's own turn start must sweep the use"

    # RIGHT is Local AI and walks one square out of LEFT's reach, which is a printed Opportunity Attack.
    engine = combat._load_session(mid).engine
    walk = next(c for c in engine.legal_candidates() if c.display_name == 'Move to 5,6')
    before = canonical_state_sha256(engine.state)
    restore = _forced_actor(combat, mid, RIGHT, walk.candidate_id)
    asked = []
    answers = []
    try:
        for _ in range(8):  # answers accumulate: each call re-sends every answer already given
            state = table.state(mid)
            step = table.auto_step(mid, state['last_sequence'], list(answers))
            if step['status'] != 'REACTION_REQUIRED':
                assert step['status'] == 'COMMITTED', step['status']
                break
            prompt = step['reaction']
            context = prompt['context']
            asked.append((context.get('reactor_id'), context.get('reaction_source_id'),
                          [row['id'] for row in (prompt.get('choice') or {}).get('options') or []]))
            # Nothing may move while a player's answer is outstanding, on an AI turn either.
            assert canonical_state_sha256(combat._load_session(mid).engine.state) == before, \
                "the AI's action committed before the owner's answer"
            source = context.get('reaction_source_id')
            want = 'INTENSIFY' if source == 'choice:needle.electric_fist' else \
                (ALLY if source == 'choice:needle.sky_fire' else None)
            answers.append(_answer(prompt, want))
        else:
            raise AssertionError('the owner was never asked the whole chain')
    finally:
        combat.controller = restore
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode='MANUAL')

    # Every prompt was the manual owner's own decision, taken on the AI creature's turn.
    assert [source for _reactor, source, _options in asked] == [
        'reaction:typed.opportunity_attack', 'choice:needle.electric_fist', 'choice:needle.sky_fire'], asked
    assert {reactor for reactor, _source, _options in asked} == {LEFT}, asked
    assert asked[2][2] == [ALLY], 'the ask offered the other Charged creature'

    engine = reload(combat, mid)
    assert engine.state.current_actor_id == RIGHT, "the off-turn hit resolved inside the AI creature's turn"
    assert engine.state.actors[LEFT].resources[QI] == 98, 'the off-turn intensification cost its own 1 CP'
    assert len(_saves_on(engine, ALLY)) == saves_after_own_turn + 1, \
        "the off-turn chain must ask again and roll one more additional-creature save"
    picked = _conditions(engine.state.actors[ALLY])
    assert any('reaction_denied' in cid for cid in picked), sorted(picked)
    penalty = next(c for c in engine.state.actors[ALLY].conditions.values() if 'concentration_mode' in c.condition_id)
    # "has Disadvantage on the next Constitution saving throw it makes to maintain Concentration": the stored
    # rule is what combat/concentration.py save_mode reads, and "next" is what makes that save consume it.
    assert (penalty.data or {}).get('rule', {}).get('concentration_mode') == 'DISADVANTAGE', penalty.data
    assert (penalty.data or {}).get('rule', {}).get('next') is True, penalty.data
    # Meridian's own penalties are on the creature that failed Meridian, not on the one Sky-Fire picked.
    assert 'condition:typed.no_cp_regain' not in picked, sorted(picked)

    # "It cannot take Reactions until the start of its next turn."
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert engine.state.current_actor_id == ALLY, engine.state.current_actor_id
    after_start = _conditions(engine.state.actors[ALLY])
    assert not any('reaction_denied' in cid for cid in after_start), sorted(after_start)
    # "...before the end of its next turn": the Concentration penalty is NOT gone at that same boundary.
    assert any('concentration_mode' in cid for cid in after_start), sorted(after_start)

    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    after_end = _conditions(engine.state.actors[ALLY])
    assert not any('concentration_mode' in cid for cid in after_end), sorted(after_end)
    assert mark_condition_id('Charged', LEFT) in after_end, sorted(after_end)
