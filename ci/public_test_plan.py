"""Size public CI to the exact request; full snapshots use all MAX_SHARDS shards (2026-10-20: 19 shards of ~115 files
ran past the 40-min job limit; 40 shards of ~55 files run in two waves of 19 runners)."""
MAX_SHARDS = 80   # 40 -> 80 (2026-10-20: 6 of the first 12 sweep shards of ~55 files hit the 90-min job timeout)
MAX_NODE_SHARDS = 4   # the one node job (110 files) ran past its 60-min timeout; files are hashed over these
NODE_FILES_PER_SHARD = 28
# A full run takes at most FULL_PARALLEL runners at a time (2026-10-20: a 40-shard sweep held all 20 of the account's
# concurrent jobs for over an hour and every lane's CI run queued behind it); lane runs keep the rest.
FULL_PARALLEL, LANE_PARALLEL = 12, 19   # 6 -> 12 (owner via Ino 2026-10-20: lanes used 3-7 slots; lanes keep >= 7)
# A sweep that starts on a quiet ci queue or at night may run wider (Ino 2026-10-21): its branch name ends in -w<N>
# (nightly_sweep decides), capped at FULL_WIDE_MAX so that with the one node runner lanes still keep 2 of the 20.
FULL_WIDE_MAX = 17
import argparse
import json
import os
import re
from pathlib import Path

from public_test_shard import requested_files, select


def full_width(ref_name):
    """Pytest runners for a full run: -w<N> at the end of the branch name, at most FULL_WIDE_MAX; else FULL_PARALLEL."""
    m = re.search(r'-w([0-9]{1,2})$', ref_name or '')
    return max(1, min(int(m.group(1)), FULL_WIDE_MAX)) if m else FULL_PARALLEL


def build_plan(files, *, full=False, node_files=None, width=None):
    """Missing Node dependency metadata conservatively enables Node for Python."""
    count = MAX_SHARDS if full else min(MAX_SHARDS, max(1, (len(files) + 24) // 25))
    python = [p for p in files if p.endswith('.py')]
    matrix = {'include': [
        {'shard': i, 'needs_node': bool(select(python, i, count)) and
         (node_files is None or bool(set(select(python, i, count)) & set(node_files)))}
        for i in range(count)
    ]}
    node_files = [p for p in files if p.endswith(('.mjs', '.js'))]
    node = full or bool(node_files)
    node_count = (MAX_NODE_SHARDS if full else
                  min(MAX_NODE_SHARDS, max(1, (len(node_files) + NODE_FILES_PER_SHARD - 1) // NODE_FILES_PER_SHARD)))
    return {'version': 1, 'pytest_shards': list(range(count)), 'matrix': matrix,
            'max_parallel': (width or FULL_PARALLEL) if full else LANE_PARALLEL,
            'count': count, 'node': node, 'node_count': node_count,
            'node_parallel': 1 if full else node_count,   # a sweep keeps 12 + 1 runners: lanes keep >= 7 of 20
            'node_matrix': {'include': [{'shard': i} for i in range(node_count)]}}


def planned_artifacts(plan):
    """Validate the uploaded plan before trusting its expected artifact set."""
    if not isinstance(plan, dict) or plan.get('version') != 1:
        raise ValueError('Missing or invalid public test plan')
    count = plan.get('count')
    if type(count) is not int or not 1 <= count <= MAX_SHARDS or type(plan.get('node')) is not bool:
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
    node_count = plan.get('node_count', 1)          # plans written before node shards: one node job
    if type(node_count) is not int or not 1 <= node_count <= MAX_NODE_SHARDS:
        raise ValueError('Invalid public test plan node count')
    return {('pytest', i) for i in range(count)} | ({('node', i) for i in range(node_count)} if plan['node'] else set())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, default=Path('plan.json'))
    args = parser.parse_args()
    metadata = args.root / 'PUBLIC_TEST_NODE_FILES.json'
    plan = build_plan(requested_files(args.root), full=not (args.root / 'PUBLIC_TEST_REQUEST.txt').exists(),
                      node_files=json.loads(metadata.read_text()) if metadata.exists() else None,
                      width=full_width(os.environ.get('GITHUB_REF_NAME', '')))
    args.output.write_text(json.dumps(plan, indent=2) + '\n')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            for name in ('matrix', 'count', 'node', 'max_parallel', 'node_count', 'node_matrix', 'node_parallel'):
                stream.write(name + '=' + json.dumps(plan[name], separators=(',', ':')) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
