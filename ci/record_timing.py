from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from common import StageRecorder, read_json, utc_now, write_json


def begin(args: argparse.Namespace) -> int:
    write_json(
        args.state.resolve(),
        {
            "stage": args.stage,
            "command_identity": args.command,
            "started_at_utc": utc_now(),
            "started_epoch_ns": time.time_ns(),
        },
    )
    return 0


def finish(args: argparse.Namespace) -> int:
    state = read_json(args.state.resolve())
    ended_ns = time.time_ns()
    recorder = StageRecorder(args.output.resolve())
    recorder.record(
        stage=state["stage"],
        command=state["command_identity"],
        started_at_utc=state["started_at_utc"],
        ended_at_utc=utc_now(),
        elapsed_seconds=(ended_ns - int(state["started_epoch_ns"])) / 1_000_000_000,
        status=args.status,
        exit_code=args.exit_code,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    start = subparsers.add_parser("begin")
    start.add_argument("--stage", required=True)
    start.add_argument("--command", required=True)
    start.add_argument("--state", type=Path, required=True)
    start.set_defaults(handler=begin)
    end = subparsers.add_parser("finish")
    end.add_argument("--state", type=Path, required=True)
    end.add_argument("--output", type=Path, required=True)
    end.add_argument("--status", choices=("PASS", "FAIL"), required=True)
    end.add_argument("--exit-code", type=int)
    end.set_defaults(handler=finish)
    args = parser.parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
