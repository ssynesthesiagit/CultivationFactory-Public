from __future__ import annotations

from itertools import product
from typing import Iterable

from .gate2_runtime_models import CandidateChoiceDomain, CandidateKind, LegalCandidate


# Explicit executable option-domain authority for the current R6.6.9 catalog.
# No domain is inferred from prose or display labels.
_SINGLE_WITH_DEFAULT: dict[str, tuple[str, str, tuple[str, ...], str]] = {
    "action:an_eui.ruin_tempered_armament_quick": (
        "weapon_mode", "Weapon mode", ("PRIMARY_WEAPON", "PAIRED_WEAPONS"), "PRIMARY_WEAPON"
    ),
    "action:an_eui.first_arm": (
        "break_guard", "Break the Guard result", ("AC_MINUS_1", "NEXT_ATTACK_ADVANTAGE", "NO_HALF_COVER"), "AC_MINUS_1"
    ),
    "talent:an_eui.stomping_step": (
        "movement_mode", "Movement mode", ("DASH", "DISENGAGE"), "DASH"
    ),
    "action:lee_jia.lightning_lash": (
        "lightning_mode", "Lightning Lash mode", ("CHARGE", "JOLT", "FLASH", "ARC"), "CHARGE"
    ),
    "action:bai_meizhen.moon_disc_descent": (
        "damage_type", "Damage type", ("RADIANT", "FORCE", "BLUDGEONING"), "RADIANT"
    ),
}

_EXACT_ONE_NO_DEFAULT: dict[str, tuple[str, str]] = {
    "talent:lee_jia.aura_reading_countercurrent": ("visible_pattern", "Visible active pattern"),
}

_ZERO_OR_ONE: dict[str, tuple[str, str]] = {
    "talent:lee_jia.spark_step": ("ignored_reactor", "Ignore one visible creature's opportunity reaction"),
}

_BOUND_EXACT_SOURCES = {
    "action:bai_meizhen.command_cui",
    "action:lee_jia.gather_charge",
}


def choice_domains_for(
    source_definition_id: str,
    option_ids: Iterable[str],
    *,
    kind: CandidateKind,
) -> tuple[CandidateChoiceDomain, ...]:
    options = tuple(option_ids)
    if not options:
        return ()

    if source_definition_id == "action:an_eui.scouring_destruction_blast":
        # Break Guard precedes DEEPEN in canonical controller order. This
        # preserves the accepted Gate 2 order-sensitive resolver for retained
        # scripted fights while allowing Gate 4/Gate 5 controllers to execute
        # both independent selections without a second resolution path.
        return (
            CandidateChoiceDomain(
                domain_id="break_guard",
                display_name="Break the Guard result",
                selection_rule="ZERO_OR_ONE",
                option_ids=("AC_MINUS_1", "NEXT_ATTACK_ADVANTAGE", "NO_HALF_COVER"),
                minimum_selections=0,
                maximum_selections=1,
                default_option_ids=("AC_MINUS_1",),
            ),
            CandidateChoiceDomain(
                domain_id="modifier:deepen",
                display_name="Deepen the blast",
                selection_rule="ZERO_OR_ONE",
                option_ids=("DEEPEN",),
                minimum_selections=0,
                maximum_selections=1,
                default_option_ids=(),
                option_costs={"DEEPEN": {"resource:an_eui.stamina": 1}},
            ),
        )

    if source_definition_id in _SINGLE_WITH_DEFAULT:
        domain_id, label, expected, default = _SINGLE_WITH_DEFAULT[source_definition_id]
        offered = tuple(option for option in expected if option in options)
        if not offered:
            return ()
        return (
            CandidateChoiceDomain(
                domain_id=domain_id,
                display_name=label,
                selection_rule="ZERO_OR_ONE",
                option_ids=offered,
                minimum_selections=0,
                maximum_selections=1,
                default_option_ids=((default,) if default in offered else ()),
            ),
        )

    if source_definition_id in _EXACT_ONE_NO_DEFAULT:
        domain_id, label = _EXACT_ONE_NO_DEFAULT[source_definition_id]
        return (
            CandidateChoiceDomain(
                domain_id=domain_id,
                display_name=label,
                selection_rule="EXACTLY_ONE",
                option_ids=options,
                minimum_selections=1,
                maximum_selections=1,
                default_option_ids=(),
            ),
        )

    if source_definition_id in _ZERO_OR_ONE:
        domain_id, label = _ZERO_OR_ONE[source_definition_id]
        return (
            CandidateChoiceDomain(
                domain_id=domain_id,
                display_name=label,
                selection_rule="ZERO_OR_ONE",
                option_ids=options,
                minimum_selections=0,
                maximum_selections=1,
                default_option_ids=(),
            ),
        )

    if source_definition_id in _BOUND_EXACT_SOURCES or len(options) == 1:
        return (
            CandidateChoiceDomain(
                domain_id="candidate_bound_options",
                display_name="Candidate-bound option",
                selection_rule="EXACT_SET",
                option_ids=options,
                minimum_selections=len(options),
                maximum_selections=len(options),
                default_option_ids=options,
            ),
        )

    # Unknown multi-option semantics are a material authority gap. The candidate
    # remains visible for existing automatic behavior, but owner composition is
    # blocked by choice_authority_status=GAP.
    return ()


def choice_authority_status(option_ids: Iterable[str], domains: Iterable[CandidateChoiceDomain]) -> str:
    options = tuple(option_ids)
    if not options:
        return "NOT_APPLICABLE"
    covered = {option for domain in domains for option in domain.option_ids}
    return "COMPLETE" if covered == set(options) else "GAP"


def validate_option_selection(candidate: LegalCandidate, selected: Iterable[str]) -> tuple[str, ...]:
    selected_tuple = tuple(selected)
    findings: list[str] = []
    if len(set(selected_tuple)) != len(selected_tuple):
        findings.append("duplicate_option_id")
    if any(option not in candidate.option_ids for option in selected_tuple):
        findings.append("option_not_offered")
    if candidate.choice_authority_status == "GAP":
        findings.append("choice_authority_gap")
        return tuple(findings)
    domains = candidate.choice_domains
    covered = {option for domain in domains for option in domain.option_ids}
    if any(option not in covered for option in selected_tuple):
        findings.append("option_without_typed_domain")
    selected_set = set(selected_tuple)
    for domain in domains:
        count = sum(1 for option in domain.option_ids if option in selected_set)
        if count < domain.minimum_selections:
            findings.append(f"domain_minimum_not_met:{domain.domain_id}")
        if count > domain.maximum_selections:
            findings.append(f"domain_maximum_exceeded:{domain.domain_id}")
        if domain.selection_rule == "EXACT_SET" and count != len(domain.option_ids):
            findings.append(f"domain_exact_set_mismatch:{domain.domain_id}")
    return tuple(findings)



def canonicalize_option_selection(candidate: LegalCandidate, selected: Iterable[str]) -> tuple[str, ...]:
    """Return a deterministic domain-ordered selection for controller intents.

    Retained Gate 2 scripted intent bytes are not rewritten. Gate 4/Gate 5
    controllers use this order so independent typed domains resolve through the
    accepted order-sensitive runtime without changing historical replay truth.
    """
    selected_set = set(selected)
    if not candidate.choice_domains:
        return tuple(selected)
    return tuple(
        option
        for domain in candidate.choice_domains
        for option in domain.option_ids
        if option in selected_set
    )

def default_option_selection(candidate: LegalCandidate) -> tuple[str, ...]:
    if not candidate.choice_domains:
        return ()
    return tuple(
        option
        for domain in candidate.choice_domains
        for option in domain.default_option_ids
    )


def expand_option_selections(candidate: LegalCandidate, *, limit: int = 32) -> tuple[tuple[str, ...], ...]:
    if not candidate.option_ids:
        return ((),)
    if candidate.choice_authority_status != "COMPLETE":
        return tuple((option,) for option in candidate.option_ids)
    domain_rows: list[tuple[tuple[str, ...], ...]] = []
    for domain in candidate.choice_domains:
        if domain.selection_rule == "EXACT_SET":
            rows = (tuple(domain.option_ids),)
        elif domain.selection_rule == "EXACTLY_ONE":
            rows = tuple((option,) for option in domain.option_ids)
        elif domain.selection_rule == "ZERO_OR_ONE":
            rows = ((),) + tuple((option,) for option in domain.option_ids)
        else:
            rows = (tuple(domain.default_option_ids),)
        domain_rows.append(rows)
    expanded: list[tuple[str, ...]] = []
    for row in product(*domain_rows):
        selection = tuple(option for group in row for option in group)
        if not validate_option_selection(candidate, selection):
            expanded.append(selection)
        if len(expanded) > limit:
            raise ValueError(f"candidate option expansion exceeds {limit}: {candidate.candidate_id}")
    return tuple(expanded)
