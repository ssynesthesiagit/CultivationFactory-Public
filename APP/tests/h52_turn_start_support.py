"""Real portable-character fixture helpers for Hunt 52 turn-start regressions."""
import json
import shutil
import zipfile
from pathlib import Path

from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "h52_turn_start"
PEOPLE = {
    "ning": "b95b3754-eeae-49d6-9dbd-6bbd4bb9d4f9",
    "lingyue": "bc0d6d5d-0ad7-48d4-ab3b-34fce51bb4a2",
    "jia": "e62229bf-88de-4f8b-8201-b766d06d16bb",
    "yun": "d21a30e2-4990-4265-b031-63350512c2f1",
}


def fight(tmp_path, owner_key, opponents=None, *, qi=None):
    """The owner's fight. By default the owner and Jia/Yun/Lingyue/Ning fill two teams of two; ``opponents`` (keys)
    instead makes a smaller fight of the owner alone against them.

    ``qi`` gives the owner a smaller Qi pool (maximum and current), so a regression about the zero-Qi recovery
    only needs a few real Qi actions to reach zero. The full 86-point pool made a loaded CI run spend its whole
    per-test limit walking slow table menus instead of testing the recovery."""
    owner_pid = PEOPLE[owner_key]
    other_keys = list(opponents) if opponents else [key for key in ("jia", "yun", "lingyue", "ning") if key != owner_key][:3]
    ids = [owner_pid, *(PEOPLE[key] for key in other_keys)]
    allies = 1 if opponents else 2
    for pid in ids:
        source = FIXTURES / pid / "current.zip"
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        shutil.copy2(source, folder / "current.zip")
        if qi is not None and pid == owner_pid:
            sheet = folder / "current.zip"
            with zipfile.ZipFile(sheet) as archive:
                name = archive.namelist()[0]
                document = json.loads(archive.read(name))
            resource = (document.get("ability_scores_and_statistics") or {}).get("primary_resource") or {}
            resource["maximum"] = int(qi)
            for definition in resource.get("definitions") or ():
                if definition.get("resource_id") == "tianxia.resource.qi":
                    definition["current"] = int(qi)
                    definition["max"] = int(qi)
            with zipfile.ZipFile(sheet, "w") as archive:
                archive.writestr(name, json.dumps(document))
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions(owner_pid, {"mode": "ask"}, set())
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    combat.tabletop_maps.save({"map_id": "h52-turn-start", "display_name": "Turn Start Yard",
        "width_squares": 8, "height_squares": 8,
        # A smaller fight starts the sides 20 feet apart, so ranged attacks are not made at Disadvantage.
        "starts": {"team1": [[3, 3], [3, 4]], "team2": [[7, 3], [7, 4]] if opponents else [[4, 3], [4, 4]]}})
    modes = {"actor:factory." + pid: "MANUAL" for pid in ids}
    match = combat.create_factory_match(project_ids=ids[:allies], opponent_actor_ids=["actor:factory." + p for p in ids[allies:]],
        control_modes=modes, arena_id="battlefield:map.h52-turn-start", match_seed="H52-L42-" + owner_key,
        maximum_rounds=60)
    return combat, table, match["match_id"], "actor:factory." + owner_pid


def commit(table, match_id, menu, candidate_id=None, *, after=None):
    from tests.iron_fist_support import answering_iron_fist
    answers = []
    action = menu["end_turn"] if candidate_id is None else candidate_id
    # Reuse the caller's last_sequence when it has one: a queued prompt does not
    # commit, so the table's sequence is unchanged while the answers are collected.
    sequence = table.state(match_id)["last_sequence"] if after is None else after
    send = answering_iron_fist(lambda submitted: table.act(
        match_id, action, menu["decision_id"], menu["state_version"], sequence, submitted))
    for _ in range(20):
        response = send(answers)
        sequence = (response.get("state") or {}).get("last_sequence", sequence)
        if response["status"] != "REACTION_REQUIRED":
            assert response["status"] == "COMMITTED", response
            return response
        prompt = response["reaction"]
        choice = prompt.get("choice") or {}
        options = [option["id"] for option in choice.get("options") or []]
        if options and not choice.get("allow_decline", True):
            # A required question (a square to place an area, a printed "choose one")
            # is not a decline; answer it with the table's own preferred option.
            picks = [key for key in (choice.get("preferred") or []) if key in options] or options
            count = max(1, int(choice.get("minimum") or 1))
            answers.append({**prompt["context"], "selection": "USE", "option_ids": picks[:count]})
        else:
            answers.append({**prompt["context"], "selection": "DECLINE"})
    raise AssertionError("reaction prompts did not resolve")


def next_action(table, match_id, owner_id, owner_action=None, *, attack_owner=False, combat=None):
    state = table.state(match_id)
    menu = state["menu"]
    assert "error" not in menu, f"the table menu is unavailable: {menu['error']}"
    if menu["actor_id"] == owner_id:
        candidate = owner_action(menu) if owner_action else None
    elif attack_owner:
        engine = engine_at(combat, match_id)
        candidate = None
        for group in menu.get("actions", []):
            action = engine.action_catalog.get(group.get("source_definition_id"))
            effects = ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("effects") or [] if action else []
            if not any(effect.get("type") == "attack" for effect in effects if isinstance(effect, dict)):
                continue
            option = next((row for row in group.get("options", []) if owner_id in row.get("target_ids", [])), None)
            if option:
                candidate = option["candidate_id"]
                break
    else:
        candidate = None
    return commit(table, match_id, menu, candidate, after=state["last_sequence"])


def engine_at(combat, match_id):
    return combat._load_session(match_id).engine
