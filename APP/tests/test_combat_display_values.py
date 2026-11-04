from pathlib import Path
from types import SimpleNamespace

from combat.display_values import compiled_armor_class


def test_compiled_armor_class_reuses_same_character_revision(tmp_path: Path):
    project_id = "cache-fixture"
    package = tmp_path / "installed" / project_id / "current.zip"
    package.parent.mkdir(parents=True)
    package.write_bytes(b"installed package revision one")

    class Tabletop:
        def __init__(self):
            self.combat = SimpleNamespace(
                combatant_library=SimpleNamespace(install_root=tmp_path / "installed"),
                userdata_root=tmp_path / "data",
            )
            self.buttons = SimpleNamespace(get=lambda _project: {})
            self.compiles = 0

        def _bundle_and_summary(self, _project):
            self.compiles += 1
            return ({"ability_scores_and_statistics": {"armor_class": {"value": 12}}},
                    {"actor_template": {"armor_class": 15}}, {})

    tabletop = Tabletop()
    assert compiled_armor_class(project_id, tabletop)["value"] == 15
    assert compiled_armor_class(project_id, tabletop)["value"] == 15
    assert tabletop.compiles == 1
    package.write_bytes(b"installed package revision two")
    assert compiled_armor_class(project_id, tabletop)["value"] == 15
    assert tabletop.compiles == 2
