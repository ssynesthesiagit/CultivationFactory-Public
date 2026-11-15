"""Carnage ownership belongs to saved fight bundles, never process actor IDs."""

import json
import subprocess
import sys
import textwrap
import zipfile

import pytest

from combat.ext.bodya_berserker import ADVANCING_CARNAGE, FLAG
from combat.gate2_runtime_content import AN, LEE
from combat.gate5_service import CombatService
from tests.test_auto_bodya import ME, ROOT, _bundle, _engine, _use
from tests.test_zones import SHEET


@pytest.mark.parametrize("owner", [False, True])
def test_owner_then_nonowner_with_same_id_keeps_ownership_fight_scoped(owner):
    owned = _bundle([ADVANCING_CARNAGE])
    unowned = _bundle([])  # same actor ID, compiled after the owner
    engine = _engine(owned if owner else unowned, positions={
        ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}, LEE: {"x": 3, "y": 5},
    })
    engine.state.actors[AN].current_hp = 1
    _use(engine, "Batter", (AN,))
    assert engine.state.actors[AN].current_hp <= 0
    assert bool(engine.state.actors[ME].turn_flags.get(FLAG)) is owner
    assert bool([c for c in engine.legal_candidates() if c.display_name.startswith("Advancing Carnage:")]) is owner


def test_saved_owner_triggers_carnage_after_fresh_process_service_reload(tmp_path):
    for project, talents in (("bodya_test", [ADVANCING_CARNAGE]), ("foe", []), ("other", [])):
        sheet = {**SHEET, "equipment": [], "spheres_and_talents": {
            "sphere_record_ids": ["tianxia.sphere.berserker"], "learned_talent_record_ids": talents,
        }}
        folder = tmp_path / "portable_characters" / project
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    match_id = CombatService(ROOT, tmp_path).create_factory_match(
        project_ids=["bodya_test"], opponent_actor_ids=["actor:factory.foe", "actor:factory.other"],
        match_seed="Q1-CARNAGE-RELOAD",
    )["match_id"]
    # The child loads only the saved bundles: no owner compilation in its process.
    script = textwrap.dedent('''
        import sys
        from pathlib import Path
        from combat.gate5_service import CombatService
        from combat.gate2_runtime_models import Position
        from combat.ext.bodya_berserker import FLAG
        from tests.test_auto_bodya import ME, ROOT, _use
        engine = CombatService(ROOT, Path(sys.argv[1]))._load_session(sys.argv[2]).engine
        foe, other = "actor:factory.foe", "actor:factory.other"
        for actor_id, xy in ((ME, (3, 6)), (foe, (4, 6)), (other, (3, 5))):
            engine.state.actors[actor_id].position = Position(x=xy[0], y=xy[1])
        engine.state.current_slot_index = engine.state.initiative_order.index(ME)
        engine.state.current_actor_id = ME
        engine._system_start_turn()
        assert not engine.state.actors[ME].turn_flags.get(FLAG)
        engine.state.actors[foe].current_hp = 1
        _use(engine, "Batter", (foe,))
        assert engine.state.actors[foe].current_hp <= 0
        assert engine.state.actors[ME].turn_flags.get(FLAG)
        assert any(c.display_name.startswith("Advancing Carnage:") for c in engine.legal_candidates())
    ''')
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), match_id],
                            cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
