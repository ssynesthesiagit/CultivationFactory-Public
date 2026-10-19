"""Size public CI to the exact request; full snapshots retain all 19 shards."""
import argparse
import json
import os
from pathlib import Path

from public_test_shard import requested_files, select


def build_plan(files, *, full=False, node_files=None):
    """Missing Node dependency metadata conservatively enables Node for Python."""
    count = 19 if full else min(19, max(1, (len(files) + 24) // 25))
    python = [p for p in files if p.endswith('.py')]
    matrix = {'include': [
        {'shard': i, 'needs_node': bool(select(python, i, count)) and
         (node_files is None or bool(set(select(python, i, count)) & set(node_files)))}
        for i in range(count)
    ]}
    return {'version': 1, 'pytest_shards': list(range(count)), 'matrix': matrix,
            'count': count, 'node': full or any(p.endswith(('.mjs', '.js')) for p in files)}


def planned_artifacts(plan):
    """Validate the uploaded plan before trusting its expected artifact set."""
    if not isinstance(plan, dict) or plan.get('version') != 1:
        raise ValueError('Missing or invalid public test plan')
    count = plan.get('count')
    if type(count) is not int or not 1 <= count <= 19 or type(plan.get('node')) is not bool:
        raise ValueError('Invalid public test plan count/node')
    if plan.get('pytest_shards') != list(range(count)):
        raise ValueError('Invalid public test plan shard set')
    matrix = plan.get('matrix')
    entries = matrix.get('include') if isinstance(matrix, dict) else None
    if (not isinstance(entries, list) or len(entries) != count or
            any(not isinstance(e, dict) for e in entries) or
            [e.get('shard') for e in entries] != list(range(count)) or
            any(type(e.get('needs_node')) is not bool for e in entries)):
        raise ValueError('Invalid public test plan matrix')
    return {('pytest', i) for i in range(count)} | ({('node', 0)} if plan['node'] else set())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, default=Path('plan.json'))
    args = parser.parse_args()
    metadata = args.root / 'PUBLIC_TEST_NODE_FILES.json'
    plan = build_plan(requested_files(args.root), full=not (args.root / 'PUBLIC_TEST_REQUEST.txt').exists(),
                      node_files=json.loads(metadata.read_text()) if metadata.exists() else None)
    args.output.write_text(json.dumps(plan, indent=2) + '\n')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            for name in ('matrix', 'count', 'node'):
                stream.write(name + '=' + json.dumps(plan[name], separators=(',', ':')) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
