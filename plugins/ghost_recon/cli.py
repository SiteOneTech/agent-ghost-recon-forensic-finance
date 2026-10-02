"""``hermes ghostrecon <verb>`` — case administration without the agent. Also runnable standalone:
``python -m plugins.ghost_recon.cli <verb>`` (uses GHOSTRECON_DB or ~/.ghostrecon/ghostrecon.db outside Hermes).

Verbs: init | doctor | cases | case <id|folder> | audits <id|folder> | timeline <id|folder> | verify <audit_id>
       | export <id|folder> --out file.json | import <case.json> | open <folder> [--name] | start <case_id> [--kind]
       | seal <audit_id> [--force] | pack <audit_id> [--formats md,pdf,xlsx]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import runtime
from .core import ids, service
from .core.reports import pack as pack_mod


def register_cli(sub: argparse.ArgumentParser) -> None:
    subs = sub.add_subparsers(dest="gr_command")
    subs.add_parser("init", help="Create/upgrade the case database and run the doctor")
    subs.add_parser("doctor", help="Environment diagnostics")
    p = subs.add_parser("cases", help="List cases"); p.add_argument("--json", action="store_true")
    p = subs.add_parser("case", help="Case status"); p.add_argument("case"); p.add_argument("--json", action="store_true")
    p = subs.add_parser("audits", help="Audits of a case"); p.add_argument("case")
    p = subs.add_parser("timeline", help="Case timeline"); p.add_argument("case"); p.add_argument("--json", action="store_true")
    p = subs.add_parser("verify", help="Verify an audit seal"); p.add_argument("audit_id")
    p = subs.add_parser("export", help="Export a case to JSON"); p.add_argument("case"); p.add_argument("--out", required=True)
    p = subs.add_parser("import", help="Import a case.json mirror"); p.add_argument("file")
    p = subs.add_parser("open", help="Open/load a case from an evidence folder"); p.add_argument("folder"); p.add_argument("--name"); p.add_argument("--context"); p.add_argument("--out")
    p = subs.add_parser("start", help="Start the next audit (intake / evidence pass)"); p.add_argument("case_id"); p.add_argument("--kind", default="initial", choices=["initial", "rerun"]); p.add_argument("--context")
    p = subs.add_parser("seal", help="Seal an audit"); p.add_argument("audit_id"); p.add_argument("--force", action="store_true")
    p = subs.add_parser("pack", help="Build the deliverable pack"); p.add_argument("audit_id"); p.add_argument("--formats", default="md,pdf,xlsx")


def _print(obj, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    else:
        print(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def main(args: argparse.Namespace) -> int:
    from .commands import cmd_case, cmd_cases, cmd_doctor
    cmd = getattr(args, "gr_command", None)
    st = runtime.store()
    try:
        if cmd in (None, "init"):
            print(f"Ghost Recon DB: {runtime.db_path()} (schema ok)")
            print(cmd_doctor())
        elif cmd == "doctor":
            print(cmd_doctor())
        elif cmd == "cases":
            _print([{"id": c["id"], "name": c["name"], "root_path": c["root_path"], "status": c["status"]} for c in st.list_cases()] if args.json else cmd_cases(), args.json)
        elif cmd == "case":
            status = service.case_status(st, args.case)  # raises CaseError → exit 1
            _print(status if args.json else cmd_case(args.case), args.json)
        elif cmd == "audits":
            case = st.get_case(args.case) or st.get_case(str(Path(args.case).expanduser().resolve()))
            if not case:
                print(f"case not found: {args.case}"); return 1
            for a in st.list_audits(case["id"]):
                print(f"{ids.short_audit(a['id'])}\t{a['kind']}\t{a['status']}\t{a['started_at']}\t{a['folder']}")
        elif cmd == "timeline":
            t = service.timeline(st, args.case)
            if args.json:
                _print(t, True)
            else:
                for e in t["events"]:
                    print(f"{e['ts']}\t{e['event_type']}\t{ids.short_audit(e['audit_id']) if e.get('audit_id') else '-'}\t{e['description']}")
        elif cmd == "verify":
            _print(service.verify_audit(st, args.audit_id), True)
        elif cmd == "export":
            case = st.get_case(args.case) or st.get_case(str(Path(args.case).expanduser().resolve()))
            if not case:
                print(f"case not found: {args.case}"); return 1
            Path(args.out).write_text(json.dumps(st.export_case(case["id"]), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print(f"exported to {args.out}")
        elif cmd == "import":
            data = json.loads(Path(args.file).read_text(encoding="utf-8"))
            c = st.import_case(data); print(f"imported {c['id']}")
        elif cmd == "open":
            _print(service.open_case(st, args.folder, name=args.name, context_md=args.context, out_dir=args.out,
                                     audits_dir=runtime.setting("audits_dirname")), True)
        elif cmd == "start":
            _print(service.start_audit(st, args.case_id, args.kind, context_md=args.context), True)
        elif cmd == "seal":
            _print(service.seal_audit(st, args.audit_id, force=args.force), True)
        elif cmd == "pack":
            _print(pack_mod.build_pack(st, args.audit_id, formats=tuple(f.strip() for f in args.formats.split(","))), True)
        else:
            print(f"unknown verb {cmd}"); return 2
    except (service.CaseError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr); return 1
    return 0


def _standalone() -> int:
    parser = argparse.ArgumentParser(prog="ghostrecon", description="Ghost Recon case administration")
    register_cli(parser)
    return main(parser.parse_args())


if __name__ == "__main__":
    sys.exit(_standalone())
