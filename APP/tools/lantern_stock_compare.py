"""External evidence comparison of complete stock captures.

Capture fights through HeavyQ's stock gate, not this tool. Pass two existing
capture JSON files and a caller-owned output path; no checkout or host state is
read. The six native stock replays remain tests/test_a2_glass_stock.py.
"""
import argparse
import hashlib
import json
from pathlib import Path


def compare(before, after):
    raw = [json.dumps(c, sort_keys=True, separators=(',', ':')).encode()
           for c in (before, after)]
    result = {'identical': raw[0] == raw[1],
              'base_sha256': hashlib.sha256(raw[0]).hexdigest(),
              'head_sha256': hashlib.sha256(raw[1]).hexdigest(),
              'steps': after['steps']}
    assert before['state']['terminal_result'] and after['state']['terminal_result']
    assert result['identical'], result
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base', type=Path)
    parser.add_argument('head', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args(argv)
    result = compare(json.loads(args.base.read_text()), json.loads(args.head.read_text()))
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
