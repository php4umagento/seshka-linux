from __future__ import annotations

import argparse
import json
import sys

from . import __version__, killer, scanner
from .format import format_bytes, human_age
from .store import Store


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seshka",
        description="Kill what Claude Code left behind (Linux).",
    )
    parser.add_argument("--version", action="version", version=f"seshka-linux {__version__}")
    sub = parser.add_subparsers(dest="command")

    list_p = sub.add_parser("list", help="List leftover and open-session processes")
    list_p.add_argument("--all", action="store_true", help="Include processes from open sessions")
    list_p.add_argument("--json", action="store_true", help="Machine-readable output")
    list_p.set_defaults(func=cmd_list)

    kill_p = sub.add_parser("kill", help="Terminate leftover processes")
    kill_p.add_argument("--pid", type=int, nargs="+", help="Kill specific PID(s)")
    kill_p.add_argument("--session", help="Kill leftovers matching session id prefix")
    kill_p.add_argument("--all", action="store_true", help="Kill every leftover")
    kill_p.add_argument(
        "--force-alive",
        action="store_true",
        help="With --session, also kill processes from open sessions",
    )
    kill_p.add_argument("-n", "--dry-run", action="store_true", help="Show targets only")
    kill_p.set_defaults(func=cmd_kill)

    end_p = sub.add_parser("end-session", help="End an open Claude Code session by its claude PID")
    end_p.add_argument("pid", type=int, help="PID of the claude process")
    end_p.add_argument("-n", "--dry-run", action="store_true")
    end_p.set_defaults(func=cmd_end_session)

    gui_p = sub.add_parser("gui", help="Open the system-tray GUI")
    gui_p.set_defaults(func=cmd_gui)

    # Compatibility with original macOS binary flags
    parser.add_argument("--list", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--kill", metavar="PID", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--kill-session", metavar="PID", type=int, help=argparse.SUPPRESS)

    return parser


def cmd_list(args: argparse.Namespace) -> int:
    store = Store()
    store.refresh_sync()
    orphans = store.orphans
    live = store.live if args.all else []
    leftover_procs = [p for g in orphans for p in g.procs]
    alive_procs = scanner.scan()
    alive_count = sum(1 for p in alive_procs if p.session_alive)

    if args.json:
        def dump_groups(groups):
            return [
                {
                    "session_id": g.session_id,
                    "project": g.project,
                    "title": g.title,
                    "memory": g.memory,
                    "procs": [
                        {
                            "pid": p.pid,
                            "command": p.command,
                            "age_s": p.age_s,
                            "memory": p.memory,
                            "ports": p.ports,
                            "helpers": len(p.helpers),
                            "session_alive": p.session_alive,
                        }
                        for p in g.procs
                    ],
                }
                for g in groups
            ]

        print(
            json.dumps(
                {
                    "leftovers": len(leftover_procs),
                    "alive_tagged": alive_count,
                    "orphans": dump_groups(orphans),
                    "live": dump_groups(store.live),
                    "sessions": [
                        {
                            "pid": s.pid,
                            "session_id": s.session_id,
                            "project": s.project,
                            "title": s.title,
                            "status": s.status,
                            "idle_s": s.idle_seconds(),
                            "memory": s.memory,
                            "bg": len(s.procs),
                        }
                        for s in store.sessions
                    ],
                },
                indent=2,
            )
        )
        return 0

    print(
        f"Found {len(leftover_procs)} leftover process(es), "
        f"{alive_count} still tied to open sessions."
    )
    _print_groups(orphans, empty="No leftover processes.")
    if args.all:
        print("Live (open-session background, unmatched):")
        _print_groups(live, empty="  (none)")
        print()
        print("All open-session tagged processes:")
        _print_groups(scanner.group([p for p in alive_procs if p.session_alive]), empty="  (none)")

    if store.sessions:
        print("Open Claude Code sessions:")
        for s in store.sessions:
            sid = (s.session_id or "?")[:8]
            idle = s.idle_seconds()
            state = s.status
            if s.status == "idle" and idle is not None:
                state = f"idle {human_age(idle)}"
            title = s.title or s.project
            print(
                f"  pid {s.pid}  {sid}  {state:12}  "
                f"{human_age(s.process.age_s):>4}  {format_bytes(s.memory):>7}  "
                f"{title}  (+{len(s.procs)} bg)"
            )
    else:
        print("No open Claude Code sessions.")
    return 0


def _print_groups(groups, empty: str) -> None:
    if not groups:
        print(empty)
        return
    print()
    for group in groups:
        title = f" — {group.title}" if group.title else ""
        print(f"session {group.short_id}  {group.project}{title}  ({format_bytes(group.memory)})")
        for proc in group.procs:
            ports = f" :{','.join(proc.ports)}" if proc.ports else ""
            helpers = f" (+{len(proc.helpers)} helpers)" if proc.helpers else ""
            print(
                f"  {proc.pid:>7}  {human_age(proc.age_s):>4}  "
                f"{format_bytes(proc.memory):>7}{ports:>10}  {proc.short_command}{helpers}"
            )
        print()


def cmd_kill(args: argparse.Namespace) -> int:
    store = Store()
    store.refresh_sync()
    all_procs = scanner.scan()
    leftovers = [p for p in all_procs if not p.session_alive]

    if args.pid:
        wanted = set(args.pid)
        targets = [p for p in all_procs if p.pid in wanted]
        missing = wanted - {p.pid for p in targets}
        if missing:
            print(
                f"PID(s) not Claude-tagged (or gone): {', '.join(map(str, sorted(missing)))}",
                file=sys.stderr,
            )
    elif args.session:
        pool = all_procs if args.force_alive else leftovers
        targets = [p for p in pool if p.session_id.startswith(args.session)]
        if not targets:
            print(f"No matching processes for session prefix {args.session!r}", file=sys.stderr)
            return 1
    elif args.all:
        targets = [p for p in leftovers if not store.is_protected(p)]
        if not targets:
            print("Nothing leftover to kill.")
            return 0
    else:
        print("Specify --pid, --session, or --all", file=sys.stderr)
        return 2

    targets = [p for p in targets if not store.is_protected(p)]
    total = sum(p.memory for p in targets)
    print(f"Killing {len(targets)} process(es) holding ~{format_bytes(total)}:")
    for proc in targets:
        print(f"  {proc.pid}  {proc.short_command}")
    if args.dry_run:
        print("Dry run — no signals sent.")
        return 0
    forced = killer.terminate(targets)
    gone = sum(1 for p in targets if not killer.is_running(p.pid))
    print(f"Done. Exited: {gone}. Force-killed: {len(forced)}. Freed ~{format_bytes(total)}.")
    return 0


def cmd_end_session(args: argparse.Namespace) -> int:
    store = Store()
    store.refresh_sync()
    session = next((s for s in store.sessions if s.pid == args.pid), None)
    if not session:
        print(f"not an open Claude Code session: {args.pid}", file=sys.stderr)
        return 1
    targets = [session.process] + [p for p in session.procs if not store.is_protected(p)]
    total = sum(p.memory for p in targets)
    print(f"Ending session {args.pid} ({session.project}) — {len(targets)} process(es), {format_bytes(total)}")
    for p in targets:
        print(f"  {p.pid}  {p.short_command}")
    if args.dry_run:
        print("Dry run — no signals sent.")
        return 0
    killer.terminate(targets)
    gone = not killer.is_running(args.pid)
    print(f"session {args.pid}: {'ended' if gone else 'STILL RUNNING'}, freed {format_bytes(total)}")
    return 0 if gone else 1


def cmd_gui(_args: argparse.Namespace) -> int:
    from .gui.app import main as gui_main

    return gui_main()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # macOS-compatible top-level flags
    if getattr(args, "list", False):
        return cmd_list(argparse.Namespace(all=True, json=False))
    if getattr(args, "kill", None) is not None:
        return cmd_kill(
            argparse.Namespace(pid=[args.kill], session=None, all=False, force_alive=False, dry_run=False)
        )
    if getattr(args, "kill_session", None) is not None:
        return cmd_end_session(argparse.Namespace(pid=args.kill_session, dry_run=False))

    if not args.command:
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
