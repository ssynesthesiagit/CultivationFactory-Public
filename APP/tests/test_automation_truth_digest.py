"""The proof digest ignores documentation, not executable changes."""
from tools.automation_truth_digest import dependency_digest


def test_dependency_digest_distinguishes_code_and_json_from_docstrings():
    path = "APP/combat/ext/example.py"
    original = b'''"""module docs"""
class C:
    """class docs"""
    def f(self):
        """function docs"""
        return 1
    async def g(self):
        """async docs"""
        return 2
'''
    docs = original.replace(b"docs", b"changed docs") + b"# comment\n"
    code = original.replace(b"return 1", b"return 3")
    digest = dependency_digest(path, original)
    assert digest == dependency_digest(path, docs)
    assert digest != dependency_digest(path, code)
    assert dependency_digest(path, b"def broken(") is None
    assert dependency_digest("rules.json", b'{"x":1}') != dependency_digest("rules.json", b'{"x": 1}')
