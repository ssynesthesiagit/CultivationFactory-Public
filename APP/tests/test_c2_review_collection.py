"""Keep the C2 regression module importable by pytest."""

from pathlib import Path


def test_c2_review_has_valid_python_syntax():
    source = Path(__file__).with_name("test_c2_review.py")
    compile(source.read_bytes(), str(source), "exec")
