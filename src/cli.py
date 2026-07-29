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
from datetime import datetime, timezone

from . import wd_config as config, wd_dbc as dbc
from .run_scan import run_scan, run_single_firm, summarize


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
        help='Single-firm override, skips the scanner entirely.',
    )
    return parser


def _mark_interrupted() -> None:
    """A run cut off by Ctrl+C (KeyboardInterrupt) never reaches
    signal_pipeline.run()'s own crash handler -- that inner try/except only
    catches Exception, not BaseException, so a KeyboardInterrupt propagates
    straight past it without ever marking wd_runs.status='crashed'. Its own
    `finally: dbc.release_run_lock()` DOES still run (finally runs for any
    BaseException), so the lock is never actually stuck -- but the row
    itself sits at 'running' forever unless a bot happens to start later and
    reconcile it. Finds the run via latest_running_run() (the same lookup
    reconcile_orphaned_runs() uses at bot startup) since an interrupted
    run_scan()/run_single_firm()/run_resume() call never returns a `result`
    with a run_id to read directly. release_run_lock() is safe to call again
    even though the interrupted call's own finally likely already did."""
    run = dbc.latest_running_run()
    if run:
        dbc.update_wd_run(run["id"], status="crashed",
                          finished_at=datetime.now(timezone.utc), notes="interrupted")
    dbc.release_run_lock()


def main(argv: list | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command != "scan":
        parser.print_help()
        return 1

    try:
        if args.firm:
            result = run_single_firm(mode="manual", firm_name=args.firm,
                                     dry=args.dry, progress=print)
        else:
            result = run_scan(
                mode="manual",
                days=args.days,
                dry=args.dry,
                gate_cap=args.cap,
                progress=print,
            )
    except dbc.RunAlreadyInProgress as e:
        # Not this process's fault and not a crash: the Postgres advisory
        # lock is held elsewhere (the bot, or another CLI invocation).
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # a crashed run must say so, not print a traceback only
        print(f"Workflow D run CRASHED: {type(e).__name__}: {e}", file=sys.stderr)
        raise
    except BaseException as e:
        # Not an Exception (KeyboardInterrupt/SystemExit) -- the branch
        # above never ran. Mark the row crashed, release the lock, re-raise
        # so Ctrl+C still exits the process the normal way.
        _mark_interrupted()
        print(f"\nInterrupted: {type(e).__name__}. Run marked crashed, lock released.",
              file=sys.stderr)
        raise

    print("")
    print(summarize(result, dry_hint="--dry"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
