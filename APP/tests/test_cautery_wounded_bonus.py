"""Red Lotus Cautery: below half Hit Points (yours or the source's) the reduction grows by one Proficiency Bonus.

Reuses the table fixture of test_mgr_t14_ling_cautery_sum: PB 2 and a Path key modifier of -1 reduce by 1 at full health.
"""
from combat.canonical import canonical_sha256
from tests.test_mgr_t14_ling_cautery_sum import (CONSENT, SEED, cautery_fight, committed, owner_bundle, resolved,
                                                  seal_qualifying_attack)
from tests.worker2_support import FOE, OWNER, candidate, fixture, reload, settle, turn


def _hits(tmp_path, maximum_hp, consents):
    """The foe hits the owner once per entry in ``consents`` (True = take the Cautery reaction)."""
    def delivery(bundles):
        seal_qualifying_attack(bundles)
        bundles[0]['actor_template']['maximum_hp'] = maximum_hp
        bundles[0].pop('bundle_sha256', None)
        bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])

    combat, table, mid = fixture(tmp_path, [], seed=SEED, owner_bundle=owner_bundle(ash=1), bundle_transform=delivery)
    for take in consents:
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, 'Cautery qualifying attack', target=OWNER).candidate_id,
               {CONSENT: 'first'} if take else {})
        turn(table, mid, OWNER)
    return reload(tmp_path, mid)


def test_cautery_at_full_health_reduces_by_the_base_sum_only(tmp_path):
    [row] = resolved(cautery_fight(tmp_path))
    assert row['reduction'] == 1


def _hit_damage(tmp_path):
    return committed(_hits(tmp_path / "probe", 200, [False]))["hp_damage"]


def test_cautery_below_half_health_adds_one_proficiency_bonus(tmp_path):
    # Max 2d-1: the first (declined) hit of d points leaves d-1 of 2d-1, which is below half.
    d = _hit_damage(tmp_path)
    [row] = resolved(_hits(tmp_path / "run", 2 * d - 1, [False, True]))
    assert row["reduction"] == 1 + 2


def test_cautery_exactly_half_health_is_not_below_half(tmp_path):
    # Max 2d: the first hit leaves exactly d of 2d, which is not below half.
    d = _hit_damage(tmp_path)
    [row] = resolved(_hits(tmp_path / "run", 2 * d, [False, True]))
    assert row["reduction"] == 1
