"""Six portable stock comparisons using the project's validated replay baseline.

The baseline is resolved by tests.replay_base, not a disposable lane checkout.
Historical six exact-base comparison artifacts remain in the lane evidence.
"""
from tests.test_a2_glass_stock import test_six_stock_captures_equal_main as test_exact_base_stock
