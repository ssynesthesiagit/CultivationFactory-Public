"""Digest reviewed proof dependencies, ignoring Python documentation only."""
from __future__ import annotations

import ast
import hashlib
import io
from pathlib import PurePath
import tokenize

SKIP = {tokenize.COMMENT, tokenize.NL, tokenize.ENCODING}


def source_digest(source: bytes) -> str:
    text = source.decode("utf-8")
    docs = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docs.add((first.lineno, first.col_offset))
    out, after_doc = [], False
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type in SKIP:
            continue
        if tok.type == tokenize.STRING and tok.start in docs:
            after_doc = True
            continue
        if after_doc and tok.type == tokenize.NEWLINE:
            after_doc = False
            continue
        after_doc = False
        out.append(f"{tokenize.tok_name[tok.type]}:{tok.string}")
    return hashlib.sha256("\n".join(out).encode()).hexdigest()


def dependency_digest(path: str, content: bytes) -> str | None:
    """Hash Python tokens without docstrings, or raw bytes for other files.

    Unparseable Python cannot match a reviewed digest and therefore fails closed.
    """
    if PurePath(path).suffix == ".py":
        try:
            return source_digest(content)
        except (SyntaxError, UnicodeError, ValueError, tokenize.TokenError, IndentationError):
            return None
    return hashlib.sha256(content).hexdigest()
