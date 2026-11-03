"""Seeded autogeneration: a seed alone builds a whole character, no AI (owner 2026-09-24).

Every walk choice comes from sha256(seed | step), so the same seed and the same
rules rebuild the same character and a different seed gives a different one.
The seed first writes the identity (name, title and a concept drawn from the
inspiration lists).  Menus are ranked by fit to that concept, so later picks
lean toward the top of each menu while still varying from seed to seed.

The picks go through the same response validation and walk events as a model
answer; only the chooser differs.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from typing import Any, Mapping, Sequence

from .linear_menus import (
    MILESTONE_BRANCH_INSIGHT,
    OPTION_BUNDLE,
    OPTION_NONE,
    OPTION_PICK,
    STEP_KIND_ASI_OR_INSIGHT,
    StepMenu,
    StepOption,
)
from .linear_prompt import (
    _INSPIRATION,
    _owner_locked_concept,
    owner_locked_identity_name,
    owner_locked_identity_title,
)

SEED_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
SEED_LOCK_FIELD = "character_creation.autogen_seed"

_SURNAMES = (
    "Bai", "Chen", "Du", "Fang", "Gu", "Han", "He", "Hua", "Jiang", "Lan", "Lei", "Li", "Lin", "Liu", "Lu",
    "Mo", "Ning", "Qin", "Shen", "Song", "Su", "Tang", "Wei", "Wen", "Xu", "Yan", "Ye", "Yun", "Zhao", "Zhou",
)
_GIVEN = (
    "An", "Bo", "Chen", "Dao", "Fei", "Feng", "Hai", "Hong", "Hui", "Jian", "Jin", "Jing", "Kai", "Lan", "Ling",
    "Mei", "Ming", "Mu", "Qi", "Qing", "Rong", "Ruo", "Shan", "Shu", "Tian", "Wu", "Xi", "Xian", "Xue", "Yao",
    "Yi", "Ying", "Yu", "Yuan", "Zhen", "Zhi",
)
_TITLE_FROM_MOTIF = {
    "thunder": "Thunder", "rot and renewal": "Withering", "iron and forge smoke": "Iron", "moonlight": "Moonlit",
    "blood lineage": "Blood-Bound", "poison and cure": "Venom", "music": "Zither", "ancestors and graves": "Grave",
    "wildfire": "Wildfire", "frost": "Frost", "beasts of the wild": "Beast", "mirrors and illusion": "Mirror",
    "tides": "Tide", "ink and scripture": "Ink",
}
_TITLE_NOUNS = (
    "Blade", "Hermit", "Wanderer", "Sage", "Fist", "Shadow", "Lotus", "Crane", "Tiger", "Phantom", "Guardian", "Exile",
)
_FIGHTING_STYLES = (
    "with a saber", "with bare fists and palms", "with a spear", "with a bow", "with a staff", "with twin blades",
    "with a straight sword", "with talismans and formations", "with poisons and needles", "with a heavy blade",
    "with qi projected at range", "with a whip-chain",
)


def new_seed() -> str:
    """A short readable seed, e.g. ``QB-7F3A91``."""
    return "QB-" + secrets.token_hex(3).upper()


def valid_seed(value: Any) -> str | None:
    return value if isinstance(value, str) and SEED_PATTERN.fullmatch(value) else None


def _roll(seed: str, *parts: str) -> int:
    digest = hashlib.sha256("|".join(("tianxia.autogen.v1", seed, *parts)).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _pick(seed: str, values: Sequence[str], *parts: str) -> str:
    return values[_roll(seed, *parts) % len(values)]


def inspiration(seed: str) -> dict[str, str]:
    picks = {key: _pick(seed, values, "inspiration", key) for key, values in _INSPIRATION.items()}
    picks["style"] = _pick(seed, _FIGHTING_STYLES, "style")
    return picks


def identity(seed: str, request: Any = None, envelope: Any = None) -> dict[str, str]:
    idea = inspiration(seed)
    # An ancient-style name of the seed's Dao (owner 2026-09-27; factory_authoring/names.py), no longer 30 surnames x 36
    # syllables; the same seed still gives the same name.
    from factory_authoring import names

    name = names.generate(seed, dao=names.data()["motif_trigrams"].get(idea["motif"]),
                          themes=names.themes_for([idea["motif"]]), style=None)["name"]
    title = f"the {_TITLE_FROM_MOTIF.get(idea['motif'], 'Wandering')} {_pick(seed, _TITLE_NOUNS, 'title')}"
    concept = (f"A {idea['temperament']} {idea['role']} from {idea['origin']} who fights {idea['style']}, "
               f"whose cultivation is shaped by {idea['motif']}.")
    return {
        "name": owner_locked_identity_name(request, envelope) or name,
        "title": owner_locked_identity_title(request, envelope) or title,
        "concept": _owner_locked_concept(request, envelope) or concept[:240],
    }


def choose_option(seed: str, menu: StepMenu, *, prefer_insights: bool = False) -> str:
    """Pick one option, leaning toward the top of the concept-ranked menu.

    ``prefer_insights`` is the retained API flag for production build advice:
    use the first rules-backed mechanical recommendation, including a useful
    Insight when one fits. The default low-level weighted chooser preserves
    its earlier random-branch behavior for explicit callers. Players keep all
    legal options and owner locks are applied before this picker is called.
    """
    picks = [option for option in menu.options if option.kind in {OPTION_PICK, OPTION_BUNDLE} and not option.is_continuation]
    # Production mechanical choices follow the menu's rules-backed ranking.
    # Randomness still supplies identity/concept/acquisitions, not wasted
    # ability points. Explicit low-level callers retain their legacy policy.
    if prefer_insights:
        from character_creation.insight_build_policy import recommended_build_option
        preferred = recommended_build_option(menu)
        if preferred is not None:
            return preferred.option_id
    pool = _lean_to_insight_branch(menu, picks) or picks or [option for option in menu.options if option.kind == OPTION_NONE] or list(menu.options)
    weights = [len(pool) - index for index in range(len(pool))]
    ticket = _roll(seed, "step", menu.step_id) % sum(weights)
    for option, weight in zip(pool, weights):
        if ticket < weight:
            return option.option_id
        ticket -= weight
    return pool[-1].option_id


def _lean_to_insight_branch(menu: StepMenu, picks: list[StepOption]) -> list[StepOption]:
    """Reorder the level-milestone options so the Insight branch is offered first."""
    if menu.step_kind != STEP_KIND_ASI_OR_INSIGHT:
        return picks
    preferred = [option for option in picks if MILESTONE_BRANCH_INSIGHT in option.choice_ids]
    return [*preferred, *(option for option in picks if option not in preferred)]


def step_receipt(seed: str, menu: StepMenu, request: Any = None, envelope: Any = None) -> dict[str, Any]:
    """Stand-in for a provider receipt: the seeded answer for this menu."""
    value = identity(seed, request, envelope) if menu.step_kind == "identity" else {"option_id": choose_option(seed, menu, prefer_insights=True)}
    return {
        "value": value,
        "provider_id": "seeded_autogen",
        "model": "seeded_autogen.v1",
        "response_sha256": hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest(),
    }


def request_seed(request: Mapping[str, Any] | None) -> str | None:
    return valid_seed((request or {}).get("autogen_seed")) if isinstance(request, Mapping) else None
