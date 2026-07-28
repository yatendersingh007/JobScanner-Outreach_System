"""Local/VS Code entrypoint. One code path, two front doors (Prompt 1):
this CLI and the Telegram bot (src/bot.py, prompt 2) both call
src.run_scan.run_scan(); neither contains its own business logic.

    python -m src.cli scan [--days N] [--dry] [--cap N] [--firm "Name"]

`scan` runs the FULL pipeline by default: scan -> gate -> draft, no separate
pursue step, no confirm prompt. `--dry` is the opt-out that stops after
gating, not the default — this is a deliberate inversion from the earlier
scan-then-pursue design (Prompt 1).
"""
from __future__ import annotations

import argparse
import sys

from . import wd_config as config
from .run_scan import run_scan, summarize


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser(
        "scan",
        help="Scan, gate, and draft (full pipeline, no confirm prompt). "
             "--dry stops after gating.",
    )
    scan_p.add_argument(
        "--days", type=int, default=None, metavar="N",
        help=f"Catch-up window in days (default {config.DEFAULT_SCAN_DAYS}, "
             f"max {config.MAX_SCAN_DAYS}). Only widen after a gap between "
             "runs; a posting a prior run already recorded and dropped is "
             "not recoverable by widening a later run's window.",
    )
    scan_p.add_argument(
        "--dry", action="store_true", default=False,
        help="Stop after gating. No Apollo calls, no Gmail drafts. The "
             "opt-out, not the default.",
    )
    scan_p.add_argument(
        "--cap", type=int, default=None, metavar="N",
        help=f"Override GATE_CAP_PER_RUN ({config.GATE_CAP_PER_RUN}) for this run only.",
    )
    scan_p.add_argument(
        "--firm", type=str, default=None, metavar="NAME",
        help='Single-firm override, skips the scanner entirely. Not built '
             'yet (prompt 2). The argument is accepted so the surface '
             'matches the eventual /scan "Firm" command, but using it today '
             "is an error, not a silent no-op.",
    )
    return parser


def main(argv: list | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command != "scan":
        parser.print_help()
        return 1

    if args.firm:
        print(
            f'--firm "{args.firm}": single-firm override is not built yet '
            "(prompt 2). Run a full scan for now.",
            file=sys.stderr,
        )
        return 2

    try:
        result = run_scan(
            mode="manual",
            days=args.days,
            dry=args.dry,
            gate_cap=args.cap,
            progress=print,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # a crashed run must say so, not print a traceback only
        print(f"Workflow D run CRASHED: {type(e).__name__}: {e}", file=sys.stderr)
        raise

    print("")
    print(summarize(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
