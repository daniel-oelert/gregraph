"""Seed the gregraph-requirements repository from design appendix A (spec §19, M6).

Documents are created with the installed ``gregraph`` CLI (``new``); only the
Markdown prose (the §19 "paste the EARS text" step) is written here. Links go
through ``gregraph link`` or ``new --link``. Every commit runs through the
installed pre-commit hook. ``bootstrap-map.md`` maps provisional ``BOOT-nnn``
keys to generated identifiers and is deleted once seeding is complete.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from seed_data import FEATURES, FRS, GOALS, LINKS, NFRS, TESTCASES

GREGRAPH = "/home/daniel/sandbox/gregraph/.venv/bin/gregraph"
REPO = Path("/home/daniel/sandbox/gregraph/gregraph-requirements")
MAP = REPO / "bootstrap-map.md"

mapping: dict[str, tuple[str, str, str]] = {}


def run(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [GREGRAPH, *args]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc


def git(*args: str) -> None:
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"git failed ({proc.returncode}): git {' '.join(args)}")
    if proc.stdout.strip():
        print(proc.stdout.rstrip())


def commit(message: str) -> None:
    git("add", "-A")
    git("commit", "-m", message)


def write_map() -> None:
    lines = [
        "# Bootstrap map (temporary)",
        "",
        "Provisional design-appendix-A keys to generated GREGraph identifiers",
        "(design §19). Deleted once seeding is complete.",
        "",
        "| Key | Identifier | Type | Title |",
        "|---|---|---|---|",
    ]
    for boot in mapping:
        id_, type_, title = mapping[boot]
        lines.append(f"| {boot} | {id_} | {type_} | {title} |")
    MAP.write_text("\n".join(lines) + "\n")


def fill_body(path: Path, sections: dict[str, str]) -> None:
    lines = path.read_text().splitlines()
    out: list[str] = []
    current: str | None = None
    done: set[str] = set()
    for line in lines:
        if line.startswith("## "):
            current = line[3:].strip()
            out.append(line)
            continue
        stripped = line.strip()
        if (
            current in sections
            and current not in done
            and stripped.startswith("*")
            and stripped.endswith("*")
        ):
            out.append(sections[current])
            done.add(current)
        else:
            out.append(line)
    missing = set(sections) - done
    if missing:
        raise SystemExit(f"{path}: placeholder not found for {sorted(missing)}")
    path.write_text("\n".join(out) + "\n")


def create(
    boot: str,
    type_: str,
    title: str,
    sections: dict[str, str],
    extra: list[str],
) -> str:
    proc = run("new", type_, "--title", title, "--no-input", *extra)
    match = re.search(r"created (\S+)\s+(\S+)", proc.stdout)
    if not match:
        raise SystemExit(f"cannot parse new output: {proc.stdout!r}")
    id_, rel = match.group(1), match.group(2)
    fill_body(REPO / rel, sections)
    mapping[boot] = (id_, type_, title)
    write_map()
    print(f"  {boot} -> {id_}  ({type_})  {title}")
    return id_


def main() -> None:
    if REPO.exists():
        raise SystemExit(f"{REPO} already exists; refusing to overwrite")
    proc = subprocess.run(
        [GREGRAPH, "init", str(REPO), "--prefix", "RE"],
        capture_output=True,
        text=True,
    )
    print(proc.stdout.rstrip())
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit("init failed")

    write_map()

    print("goals:")
    for boot, type_, title, sections in GOALS:
        create(boot, type_, title, sections, [])
    commit("seed: goals from design appendix A")

    print("features:")
    for boot, type_, title, sections in FEATURES:
        create(boot, type_, title, sections, [])
    commit("seed: features from design appendix A")

    print("functional requirements:")
    for boot, type_, title, sections in FRS:
        create(boot, type_, title, sections, [])
    commit("seed: functional requirements from design appendix A")

    print("non-functional requirements and constraint:")
    for boot, type_, title, sections in NFRS:
        create(boot, type_, title, sections, [])
    commit("seed: non-functional requirements and constraint from design appendix A")

    print("links (refines/constrains):")
    for link_type, src, tgt in LINKS:
        run("link", mapping[src][0], link_type, mapping[tgt][0])
    print(f"  {len(LINKS)} links created")
    commit("seed: refines/constrains links per design appendix A")

    print("verification documents:")
    for fr_boot, title, sections in TESTCASES:
        fr_id = mapping[fr_boot][0]
        boot = "TC-" + fr_boot.split("-")[1]
        create(boot, "test-case", title, sections, ["--link", f"verifies:{fr_id}"])
    commit("seed: verification documents derived from the functional requirements")

    print("totals:")
    print(f"  documents: {len(mapping)}")
    print(f"  links: {len(LINKS) + len(TESTCASES)}")


if __name__ == "__main__":
    main()
