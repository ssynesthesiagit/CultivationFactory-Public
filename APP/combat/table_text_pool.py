"""Lossless table transport: send repeated long rules text once per response.

Only opt-in compact table states use this encoding. The browser API boundary
expands references before any sheet, button, tooltip or rules consumer sees it.
No text or legal options are omitted, abbreviated or loaded from another fight.
"""
from collections import Counter
import json


def pack(state):
    menu = state.get('menu')
    if menu and isinstance(menu.get('movement_grid'), (list, tuple)):
        from .movement_menu import pack_grid
        state = {**state, 'menu': {**menu, 'movement_grid': pack_grid(menu['movement_grid'])}}
    counts = Counter()
    def count(value):
        if isinstance(value, str) and len(value) >= 24:
            counts[value] += 1
        elif isinstance(value, dict):
            for item in value.values():
                count(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                count(item)
    count(state)
    # Include repeated identifiers as well as prose only when the complete
    # dictionary entry plus references is smaller than the original strings.
    texts = []
    for text, n in counts.items():
        size = len(json.dumps(text))
        reference_size = len(json.dumps({'$table_text': len(texts)}, separators=(',', ':')))
        if n * (size - reference_size) > size + 1:
            texts.append(text)
    if not texts:
        return state
    indices = {text: index for index, text in enumerate(texts)}
    def encode(value):
        if isinstance(value, str) and value in indices:
            return {'$table_text': indices[value]}
        if isinstance(value, dict):
            return {key: encode(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [encode(item) for item in value]
        return value
    return {**encode(state), 'table_texts': texts}
