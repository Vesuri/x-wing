"""Files a milestone finds in C:\\XWING beside the installation (owner decision 2026-11-19).

reference/seeds.csv rows (milestone, file) name a file under ref/films/ that the owner
supplied, pinned in manifest/films.sha256 (a save of the original: never committed). A
milestone's seeds are its own and those of the milestones its `after` names, recursively.
The DOS reference (tools/pc_run.py --seed), host lockstep (tests/host_run.py) and the Amiga
replay (tests/amiga_replay.py, amiga/debug.sh XWING_SEED_DIR) all place them with the
modification time STAMP, so the game sees one date in all three.
"""

from __future__ import annotations

import csv
import hashlib
import os
import shutil
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TABLE = REPO / 'reference/seeds.csv'
MILESTONES = REPO / 'reference/milestones.csv'
PINS = REPO / 'manifest/films.sha256'
FILMS = REPO / 'ref/films'
# The reference's DOS date (tools/pc_run.py clock-inputs.json), midnight local time
STAMP = time.mktime((1993, 2, 1, 0, 0, 0, 0, 0, -1))


def files(milestone: str) -> list[Path]:
    """The verified seed files of a milestone, in table order."""
    with MILESTONES.open() as f:
        after = {r['name']: r['after'] for r in csv.DictReader(f)}
    chain, name = set(), milestone
    while name:
        chain.add(name)
        name = after[name]
    with TABLE.open() as f:
        names = [r['file'] for r in csv.DictReader(f) if r['milestone'] in chain]
    pins = {}
    for line in PINS.read_text().splitlines():
        digest, path = line.split(maxsplit=1)
        pins[Path(path).name] = digest
    out = []
    for name in names:
        path = FILMS / name
        if not path.is_file():
            raise SystemExit(f'seed file missing: {path.relative_to(REPO)} (supplied by the owner)')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if pins.get(name) != digest:
            raise SystemExit(f'seed file {name}: sha256 {digest} is not its pin in {PINS.relative_to(REPO)}')
        out.append(path)
    return out


def place(paths: list[Path], directory: Path) -> None:
    """Copy seed files into a game directory with the modification time STAMP."""
    for path in paths:
        target = directory / path.name
        shutil.copyfile(path, target)
        os.utime(target, (STAMP, STAMP))
