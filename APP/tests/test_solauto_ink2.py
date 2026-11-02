"""Living Illustration riders wired to shared climbing and Search seams (HKAUTO-INK2)."""
from combat import roof_movement
from combat.canonical import canonical_sha256
from tests.r1i_service_support import fixture, candidate, OWNER, FOE
from tests.test_r1i_round3 import reload
from tests.test_auto138_ink import owner_turn

INK = "tianxia.talent.ink."


def hidden_foe(suffix):
    """A foe-side no-cost action that takes the Hidden condition, so the beast has something to Search for."""
    def transform(bundles):
        foe = bundles[1]
        template = {**foe["action_catalog"][0], "source_definition_id": f"test:ink2.{suffix}",
                    "display_name": "Setup hidden", "economy": "NONE", "resolution_kind": "TYPED",
                    "target_kind": "SELF", "costs": [],
                    "parameters": {"free_primary": True, "typed": {"effects": [
                        {"type": "condition", "condition": "hidden", "applies_to": "self",
                         "expires_on": "UNTIL_REMOVED"}], "numbers": {}}}}
        foe["action_catalog"].append(template)
        foe["actor_template"]["action_ids"].append(template["source_definition_id"])
        foe.pop("bundle_sha256", None)
        foe["bundle_sha256"] = canonical_sha256(foe)
    return transform


def hide_foe(table, mid, commit):
    """Reach the foe's turn, hide it, and end that turn."""
    owner_turn(table, mid, commit, FOE)
    commit(candidate(table, mid, "Setup hidden"))
    commit(table.state(mid)["menu"]["end_turn"])


def beast_search(table, mid, commit, aid):
    """The summoner commands the beast, then the beast Searches on its own turn.

    An uncommanded summoned creature Dodges and its turn passes by itself, so the
    beast only reaches a menu after its owner spends the Bonus Action to command it.
    """
    owner_turn(table, mid, commit, OWNER)
    commit(candidate(table, mid, "Command Painted Beast"))
    commit(table.state(mid)["menu"]["end_turn"])
    assert table.state(mid)["menu"]["actor_id"] == aid
    commit(candidate(table, mid, "Search"))


def ai_seat_takes_search(combat, mid, aid):
    """Give the beast's turn to an AI seat, which takes its own Search.

    A companion's seat is its owner's control mode, so the whole table is told the
    owner's fighters run on Local AI. ``combat.controller`` is the service's
    controller seam (as tests/r1i_service_support.force_ai_candidate uses it), and
    the chooser reads the AI's own decision context: a Search the AI menu filters
    out is simply not there to pick, so this fails without the printed command
    reaching AI seats.
    """
    from combat.gate4_adapters import ManualControllerAdapter
    real = combat.controller

    class SearchChooser:
        def choose_primary_action(self, context):
            found = next(c for c in context.legal_candidates
                         if c.actor_id == aid and c.source_definition_id.endswith(".search"))
            return ManualControllerAdapter(lambda _context: (found.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = SearchChooser()
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")


def summon(table, combat, mid, send, tmp_path, form):
    from tests.test_r1i_round3 import resolve
    resolve(combat, mid, send, candidate(table, mid, "Painted Beast"),
            {"choice:needle.ink_forms": form})
    engine = reload(tmp_path, mid)
    return next(a.entity_id for a in engine.state.actors.values()
                if (a.summon or {}).get("group") == "painted_beast")


def test_spider_form_grants_climb_speed_40_only_to_spider(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path,
        [INK + "painted_beast", INK + "living_illustration"], seed="INK2-SPIDER")
    aid = summon(table, combat, mid, send, tmp_path, "spider")
    engine = reload(tmp_path, mid)
    assert roof_movement.profile(engine, engine.state.actors[aid]).speed_ft == 40


def test_non_spider_form_keeps_no_climb_speed(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path,
        [INK + "painted_beast", INK + "living_illustration"], seed="INK2-TIGER")
    aid = summon(table, combat, mid, send, tmp_path, "tiger")
    engine = reload(tmp_path, mid)
    assert roof_movement.profile(engine, engine.state.actors[aid]).speed_ft == 0


def test_the_painted_beast_offers_its_printed_search_command(tmp_path):
    # Search is offered when there is something to find, so a hidden foe makes the
    # printed Command visible in the beast's own menu.
    combat, table, mid, send, commit = fixture(tmp_path,
        [INK + "painted_beast", INK + "living_illustration"], bundle_transform=hidden_foe("command"), seed="INK2-COMMAND")
    aid = summon(table, combat, mid, send, tmp_path, "hound")
    commit(table.state(mid)["menu"]["end_turn"])  # the uncommanded beast Dodges and its turn passes
    hide_foe(table, mid, commit)
    owner_turn(table, mid, commit, OWNER)
    commit(candidate(table, mid, "Command Painted Beast"))
    commit(table.state(mid)["menu"]["end_turn"])
    assert table.state(mid)["menu"]["actor_id"] == aid
    assert candidate(table, mid, "Search")


def test_hound_search_for_hidden_foe_has_advantage_after_reload(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path,
        [INK + "painted_beast", INK + "living_illustration"], bundle_transform=hidden_foe("hide"), seed="INK2-HOUND")
    aid = summon(table, combat, mid, send, tmp_path, "hound")
    commit(table.state(mid)["menu"]["end_turn"])
    hide_foe(table, mid, commit)
    beast_search(table, mid, commit, aid)
    engine = reload(tmp_path, mid)
    checks = [e for e in engine.events if e.event_type == "CHECK_ROLLED" and e.actor_id == aid]
    assert checks[-1].payload["actor"]["mode"] == "ADVANTAGE"


def test_an_ai_controlled_beast_can_take_its_printed_search(tmp_path):
    # Rule 15 (never cut combat options): the printed Command belongs to the beast's
    # own seat. Marked player_only it vanished from the AI's menu, so an AI-controlled
    # Painted Beast could never Search and the Hound form's Advantage was inert for
    # every AI seat. The beast Searches a hidden foe here on its own AI turn.
    combat, table, mid, send, commit = fixture(tmp_path,
        [INK + "painted_beast", INK + "living_illustration"], bundle_transform=hidden_foe("ai"), seed="INK2-AI")
    aid = summon(table, combat, mid, send, tmp_path, "hound")
    commit(table.state(mid)["menu"]["end_turn"])
    hide_foe(table, mid, commit)
    owner_turn(table, mid, commit, OWNER)
    commit(candidate(table, mid, "Command Painted Beast"))
    commit(table.state(mid)["menu"]["end_turn"])
    assert table.state(mid)["menu"]["actor_id"] == aid
    ai_seat_takes_search(combat, mid, aid)
    result = table.auto_step(mid, 0)
    assert result["status"] == "COMMITTED", result
    engine = reload(tmp_path, mid)
    checks = [e for e in engine.events if e.event_type == "CHECK_ROLLED" and e.actor_id == aid]
    assert checks[-1].payload["actor"]["mode"] == "ADVANTAGE"


def test_tiger_search_has_no_hound_advantage(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path,
        [INK + "painted_beast", INK + "living_illustration"], bundle_transform=hidden_foe("hide2"), seed="INK2-TIGER-SEARCH")
    aid = summon(table, combat, mid, send, tmp_path, "tiger")
    commit(table.state(mid)["menu"]["end_turn"])
    hide_foe(table, mid, commit)
    beast_search(table, mid, commit, aid)
    engine = reload(tmp_path, mid)
    checks = [e for e in engine.events if e.event_type == "CHECK_ROLLED" and e.actor_id == aid]
    assert checks[-1].payload["actor"]["mode"] == "NORMAL"
