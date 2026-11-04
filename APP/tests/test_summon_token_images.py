"""Every summoned creature has a picture of its own for its token (owner 2026-10-03: "Lesser Corpse Servant doesnt
have an image for its token").

A summon used to be drawn with bare initials unless a folder of pictures happened to exist for its kind under the
owner's data directory. Fifteen of the thirty kinds in ``combat/rules/summons.json`` had no such folder, and on a fresh
install the whole directory was missing, so *no* summon had a face. ``TabletopService._summon_token_pool`` now looks in
the owner's art, then in the art shipped with the program, then in one shared generic pool, so a summon always resolves
to a picture. A picture drawn *for that creature* is always preferred to the shared one.

These tests are the guard for that promise, and the promise is deliberately narrow: **every creature kind in
summons.json must have a folder of pictures of its own, and those files must really be pictures.** A kind that would
only be served the shared ``generic`` silhouette has no face of its own and is reported here, at build time, rather
than quietly on the owner's table. The two ``test_the_guard_catches_...`` tests below are the negative controls that
prove the guard still bites when a kind's folder is deleted or a new kind is added without art -- without them a
guard that accepts any picture, generic or not, would look identical to a working one.
"""

import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from combat import summons
from combat.factory_compiler import compile_character
from combat.tabletop_service import TabletopService

OWNER = "actor:factory.summoner"
GENERIC = TabletopService.GENERIC_SUMMON_KIND

# Talents whose compiled character actually brings creatures to the table (combat/rules/summons.json sources).
SUMMONING_TALENTS = [
    "TAL_DEATH_CORPSE_SERVANT",
    "tianxia.subpath.body.bone_monarch.feature.bone_guard_manifestation",
    "tianxia.talent.talismans.talisman_spirit",
    "tianxia.talent.beastmastery.mounted_offense",
]


def _sheet(talents: list[str], pb: int = 4, cl: int = 10) -> dict:
    return {
        "identity": {"proficiency_bonus": pb, "cultivation_level": cl, "path": "Qi Cultivation", "key_ability": "WIS"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Qi", "maximum": 30}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
            "speed": {"walking_ft": 30}, "technique_save_dc": 15, "technique_attack_bonus": 8,
        },
        "spheres_and_talents": {"learned_talent_record_ids": talents},
    }


def _table(tmp_path: Path) -> TabletopService:
    """A table whose owner's art directory is empty, i.e. a fresh install with nothing of the owner's own."""
    return TabletopService(SimpleNamespace(_load_session=lambda _: None), tmp_path)


def _engine_for(groups: list[str]):
    """A stand-in fight state holding one summoned actor per ``group`` (e.g. "corpse_servant", "beast0.wolf")."""
    actors = {}
    for index, group in enumerate(groups):
        entity_id = f"actor:factory.summoner.summon.{group}.{index + 1}"
        actors[entity_id] = SimpleNamespace(entity_id=entity_id, summon={"group": group})
    return SimpleNamespace(state=SimpleNamespace(actors=actors))


def _rule_kinds() -> list[str]:
    """Every creature kind a compiled character can bring: the creatures and the companions in summons.json."""
    table = summons.rules()
    return sorted(set(table["creatures"]) | set(table["beasts"]))


def _png_bytes() -> bytes:
    """A real, decodable picture, so a test's own stand-in art is a picture too and not just a PNG header."""
    buffer = io.BytesIO()
    Image.new("RGBA", (4, 4), (128, 96, 64, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def _is_a_picture(path: Path) -> bool:
    """Whether ``path`` is a picture that really decodes, not merely a file that starts with the PNG header."""
    try:
        with Image.open(path) as image:
            image.load()  # reads the pixels; Image.open() alone only reads the header
            return bool(image.width > 0 and image.height > 0)
    except Exception:  # noqa: BLE001 - a file that will not load is simply not a picture
        return False


def _own_picture(table: TabletopService, kind: str) -> Path | None:
    """A serving path to one of ``kind``'s own pictures, or ``None`` if it has none.

    Used by the guard, so it deliberately refuses the shared catch-all: a kind that only reaches the generic pool
    has no face of its own and is not accepted.
    """
    found = table._summon_token_pool(kind)
    if not found or found[0] != kind or not found[1]:
        return None
    folder, pool = found
    try:
        served = table.summon_token_path(folder, pool[0])
    except Exception:  # noqa: BLE001 - unservable art is as good as missing art for this guard
        return None
    return served if _is_a_picture(served) else None


def _kinds_without_their_own_picture(table: TabletopService, kinds: list[str]) -> list[str]:
    """The kinds in ``kinds`` that have no picture of their own. Empty list means the guard is satisfied."""
    return [kind for kind in kinds if _own_picture(table, kind) is None]


def test_every_summon_kind_in_the_rules_has_a_picture_of_its_own(tmp_path):
    """The owner's report, as a test: no kind in summons.json may be left without a face of its own.

    On a fresh install, with nothing of the owner's own on disk, so what is measured is the art that ships with
    the program. A shared fallback picture does **not** satisfy this: see the module docstring.
    """
    table = _table(tmp_path)
    assert not table.summon_token_root().exists(), "a fresh install: the owner has no art of their own yet"
    without = _kinds_without_their_own_picture(table, _rule_kinds())
    assert not without, (
        f"summon kinds with no picture of their own; add one under "
        f"APP/static/tabletop/summon_tokens/<kind>/: {without}"
    )


def test_the_guard_catches_a_kind_whose_picture_folder_is_deleted(tmp_path, monkeypatch):
    """Negative control: a kind whose folder of pictures is gone must be reported, not served the generic face.

    Without this, the guard above cannot tell "every kind has art" from "every kind has *some* picture", which is
    the hole MMX91's review found in finding 2.
    """
    only_one = tmp_path / "bundled_art"
    (only_one / "corpse_servant").mkdir(parents=True)
    (only_one / "corpse_servant" / "1.png").write_bytes(_png_bytes())
    table = _table(tmp_path / "owner_art")
    monkeypatch.setattr(TabletopService, "bundled_summon_token_root", lambda self: only_one)

    kinds = _rule_kinds()
    assert len(kinds) > 1, "the rules kinds list collapsed; the negative control would prove nothing"
    reported = _kinds_without_their_own_picture(table, kinds)
    assert "corpse_servant" not in reported, "the one kind that kept its art must pass the guard"
    assert set(reported) == set(kinds) - {"corpse_servant"}, (
        f"every kind missing its own folder must be reported; got {sorted(reported)}"
    )


def test_the_guard_catches_a_new_creature_kind_added_without_a_picture(tmp_path, monkeypatch):
    """Negative control: adding a creature to summons.json without drawing it must fail the guard."""
    real = summons.rules()
    monkeypatch.setattr(
        summons, "rules", lambda: {**real, "creatures": {**real["creatures"], "brand_new_creature": {"name": "New One"}}}
    )
    table = _table(tmp_path)
    assert "brand_new_creature" in _kinds_without_their_own_picture(table, _rule_kinds())


def test_every_creature_picture_is_a_real_image_the_table_can_serve(tmp_path):
    """Each kind resolves to a folder of its own whose files exist, really decode, and are reachable by the route."""
    table = _table(tmp_path)
    kinds = _rule_kinds()
    served_total = 0
    for kind in kinds:
        found = table._summon_token_pool(kind)
        assert found and found[0] == kind, f"{kind} resolved to {(found or (None,))[0]!r}, not a folder of its own"
        folder, pool = found
        for name in pool:
            path = table.summon_token_path(folder, name)
            assert path.is_file(), f"{kind}: {path} is missing"
            assert _is_a_picture(path), f"{kind}: {path} does not decode as a picture"
            served_total += 1
    assert served_total >= len(kinds), f"only {served_total} pictures for {len(kinds)} kinds"


def test_every_summon_a_compiled_character_creates_has_a_picture(tmp_path):
    """The end-to-end guard: compile real characters and check the creatures they bring, at the service level."""
    table = _table(tmp_path)
    checked, missing = set(), []
    for talent in SUMMONING_TALENTS:
        bundle = compile_character(_sheet([talent]), actor_id=OWNER)
        for row in (bundle.get("summon_options") or {}).get("groups") or []:
            checked.add(str(row.get("group") or ""))
        for creature in bundle.get("summons") or []:
            checked.add(str((creature.get("summon") or {}).get("group") or ""))
        for key in ((bundle.get("summon_options") or {}).get("beasts") or []):
            checked.add(f"beast0.{key.get('key')}")
        for key in ((bundle.get("summon_options") or {}).get("mounts") or []):
            checked.add(f"mount.{key.get('key')}")
    assert checked, "no summoning talent compiled a creature; the guard would be vacuous"
    engine = _engine_for(sorted(checked))
    tokens = table._summon_tokens("fight", engine)
    for group in sorted(checked):
        kind = group.rsplit(".", 1)[-1]
        if _own_picture(table, kind) is None:
            missing.append(f"{group} (kind {kind})")
    assert not missing, f"compiled summons with no picture of their own: {missing}"
    # Every creature that is actually on the map carries a URL the board can load, pointing at its own folder.
    for entity_id in engine.state.actors:
        assert entity_id in tokens, f"{entity_id} was drawn with no token picture"
    for url in tokens.values():
        folder, _, _ = url.removeprefix("/api/tabletop/summon-tokens/").partition("/")
        assert folder != GENERIC, f"{url} fell back to the shared catch-all for a creature that has its own art"


def test_the_owners_own_art_is_used_before_the_programs(tmp_path):
    """The owner's folder still wins, so art they add by hand keeps working."""
    table = _table(tmp_path)
    mine = table.summon_token_root() / "corpse_servant"
    mine.mkdir(parents=True)
    (mine / "owner_face.png").write_bytes(_png_bytes())
    folder, pool = table._summon_token_pool("corpse_servant")
    assert (folder, pool) == ("corpse_servant", ["owner_face.png"])
    assert table.summon_token_path(folder, pool[0]) == mine / "owner_face.png"
    tokens = table._summon_tokens("fight", _engine_for(["corpse_servant"]))
    assert list(tokens.values()) == ["/api/tabletop/summon-tokens/corpse_servant/owner_face.png"]


def test_a_shared_folder_does_not_replace_a_creatures_own_face(tmp_path):
    """Review finding 1: one catch-all picture must not flatten creatures that have real art.

    The owner adds a single shared picture, expecting it only to cover creatures nobody drew. It must not become the
    face of a wolf or a corpse servant that already has its own, which is what the old owner-first search order did.
    """
    table = _table(tmp_path)
    shared = table.summon_token_root() / GENERIC
    shared.mkdir(parents=True)
    (shared / "owners_shared_face.png").write_bytes(_png_bytes())

    for kind in ("corpse_servant", "wolf", "brown_bear"):
        folder, pool = table._summon_token_pool(kind)
        assert folder == kind, f"{kind} was given the shared {folder!r} picture instead of its own"
        assert "owners_shared_face.png" not in pool, f"{kind} was given the owner's shared catch-all"
    # And the creatures on the map are pointed at their own folders.
    tokens = table._summon_tokens("fight", _engine_for(["corpse_servant", "beast0.wolf", "mount.warhorse"]))
    assert {url.removeprefix("/api/tabletop/summon-tokens/").split("/")[0] for url in tokens.values()} == {
        "corpse_servant", "wolf", "warhorse",
    }


def test_the_owners_own_shared_folder_still_wins_when_a_creature_has_no_picture_anywhere(tmp_path):
    """Inside the shared category the owner's art still wins, so their catch-all is honoured where it applies."""
    table = _table(tmp_path)
    shared = table.summon_token_root() / GENERIC
    shared.mkdir(parents=True)
    (shared / "owners_shared_face.png").write_bytes(_png_bytes())
    folder, pool = table._summon_token_pool("a_creature_nobody_drew")
    assert (folder, pool) == (GENERIC, ["owners_shared_face.png"])
    tokens = table._summon_tokens("fight", _engine_for(["a_creature_nobody_drew"]))
    assert list(tokens.values()) == ["/api/tabletop/summon-tokens/generic/owners_shared_face.png"]


def test_a_kind_with_no_art_of_its_own_falls_back_to_the_shared_pool(tmp_path):
    """The clear generic fallback: an unknown kind still gets a picture, not bare initials."""
    table = _table(tmp_path)
    folder, pool = table._summon_token_pool("a_creature_nobody_drew")
    assert folder == GENERIC and pool
    assert table.summon_token_path(folder, pool[0]).is_file()
    tokens = table._summon_tokens("fight", _engine_for(["a_creature_nobody_drew"]))
    assert list(tokens.values()) == [f"/api/tabletop/summon-tokens/{folder}/{pool[0]}"]


def test_a_fresh_install_with_no_data_folder_still_has_faces(tmp_path):
    """The old ``if not root.is_dir(): return {}`` handed back no tokens at all when the folder was missing."""
    table = _table(tmp_path)
    assert not table.summon_token_root().exists()
    tokens = table._summon_tokens("fight", _engine_for(["lesser_corpse_servant", "corpse_servant", "wolf"]))
    assert len(tokens) == 3
    for url in tokens.values():
        folder, _, name = url.removeprefix("/api/tabletop/summon-tokens/").partition("/")
        served = table.summon_token_path(folder, name)
        assert served.is_file()
        assert _is_a_picture(served), f"{served} does not decode as a picture"


def test_a_missing_generic_pool_still_leaves_initials_rather_than_an_error(tmp_path, monkeypatch):
    """If the program's own art is somehow missing, the table shows initials as before instead of failing."""
    table = _table(tmp_path)
    monkeypatch.setattr(TabletopService, "bundled_summon_token_root", lambda self: tmp_path / "no_art_here")
    assert table._summon_token_pool("corpse_servant") is None
    assert table._summon_tokens("fight", _engine_for(["corpse_servant"])) == {}
    with pytest.raises(Exception):
        table.summon_token_path("corpse_servant", "1.png")


def test_the_generic_pool_is_not_also_a_creature_kind():
    """``generic`` is the fallback folder, so no creature in summons.json may be given that name."""
    assert GENERIC not in _rule_kinds()
