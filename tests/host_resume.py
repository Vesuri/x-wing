"""Host lockstep resume (tests/host_run.py --save / --resume; docs/translator-design.md
Resume): what a save holds besides the runtime's fields (src/runtime/snapshot.c),
and whether another image may resume from it.

A save is made where a boot run reaches its milestone's resume point (POINTS) in
main code with no service, interrupt, REP slice or capture in progress; it counts
only once that run has passed its milestone. It holds the guest's RAM, state block
and EMS store, the runtime's fields, the generated code's registers, the open
guest calls (each 68k return address as its return site: the compare, the guest
label after it and the mismatch stop), the harness's cursors and checks, and the
fingerprints of what ran before it:
- generated code: per guest label that ran (its region from its label to the
  next), the region's assembly text (build/gen, symbols by name); the program's
  header text; per dispatch-table CS:IP its rows;
- the runtime: per input section that ran (one per C function, one per assembly
  object's text, link map), its bytes with the relocated fields zeroed, its
  relocations by target name and the read-only sections it refers to;
- the harness: the source of what decides guest-visible behavior (HARNESS).
An image resumes only if each of these is equal; anything else runs from boot.
Blocks are recorded by a C block hook (tests/host_cov.c), each once.
"""
from __future__ import annotations

import bisect
import ctypes as C
import hashlib
import inspect
import re
import struct
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SAVES = REPO / "tmp/resume"
FORMAT = 1
# Where a milestone's boot run saves: a guest label, its run-wide hit count. The
# flight's first FLIGHT.OVL instruction (its DOS time read), before the flight's
# sound loader and the effect capture (MEASURED, m12: services 39,962,763 and
# 39,962,872 of 40,066,706).
POINTS = {m: "FLIGHT.OVL+2856c#1" for m in
          ("m12-training-flight", "m13-mission-flight", "m14-tour-battle",
           "m15-film-replay", "m17-combat-film")}
SCRATCH, SCRATCH_BYTES = 0x01000000, 0x00100000   # harness memory past the image's map
STUBS = SCRATCH + 0xE0000         # the resumed calls' return stubs, 32 bytes each
SENTINEL = SCRATCH + SCRATCH_BYTES - 16   # return address of runtime calls from the harness
GUEST_LABEL = re.compile(r"^(R|FE|FLT|AD)_[0-9A-F]{5}(_bp)?$")
MISMATCH = ("rt_ret_mismatch", "rt_ret_far_mismatch")


# -- coverage ------------------------------------------------------------------
def coverage():
    """The block hook library (tests/host_cov.c), built into tmp on first use."""
    src = REPO / "tests/host_cov.c"
    out = REPO / "tmp/host-cov" / (hashlib.sha256(src.read_bytes()).hexdigest()[:16] + ".so")
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(f".{id(out)}.so")
        subprocess.run(["cc", "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror",
                        str(src), "-o", str(tmp)], check=True)
        tmp.rename(out)
    return C.CDLL(str(out))


def blocks(lib) -> list[tuple[int, int]]:
    n = C.c_uint32.in_dll(lib, "cov_n").value
    if C.c_uint32.in_dll(lib, "cov_lost").value:
        raise ValueError("coverage: more blocks than the hook records")
    addrs = (C.c_uint32 * n).from_address(C.addressof(C.c_uint32.in_dll(lib, "cov_addr")))
    sizes = (C.c_uint32 * n).from_address(C.addressof(C.c_uint32.in_dll(lib, "cov_size")))
    return [(a, max(s, 2)) for a, s in zip(addrs, sizes)]


# -- object files ----------------------------------------------------------------
class Object:
    """An ELF32 big-endian relocatable: sections, symbols, relocations."""

    def __init__(self, path: Path):
        d = self.d = path.read_bytes()
        shoff, = struct.unpack_from(">I", d, 0x20)
        shentsize, shnum, shstrndx = struct.unpack_from(">HHH", d, 0x2E)
        self.secs = [struct.unpack_from(">10I", d, shoff + k * shentsize) for k in range(shnum)]
        names = self.secs[shstrndx]
        self.names = [self.cstr(names[4] + s[0]) for s in self.secs]
        self.by_name = {}
        for k, n in enumerate(self.names):
            self.by_name.setdefault(n, k)
        self.syms = []
        for s in self.secs:
            if s[1] == 2:
                strtab = self.secs[s[6]][4]
                for k in range(s[5] // 16):
                    name, value, size, info, _, shndx = struct.unpack_from(">IIIBBH", d, s[4] + 16 * k)
                    self.syms.append((self.cstr(strtab + name), value, info, shndx))
        self.relas = {}
        for s in self.secs:
            if s[1] == 4:
                self.relas[s[7]] = [struct.unpack_from(">IIi", d, s[4] + 12 * k) for k in range(s[5] // 12)]

    def cstr(self, a: int) -> str:
        return self.d[a:self.d.index(b"\0", a)].decode()

    def target(self, sym: int) -> str:
        name, _, info, shndx = self.syms[sym]
        if info & 15 == 3 or not name:      # STT_SECTION
            return self.names[shndx] if shndx < len(self.names) else f"#{shndx}"
        return name

    def content(self, k: int) -> tuple:
        """Section k: bytes, relocated fields zeroed, and its relocations by name."""
        s = self.secs[k]
        data = bytearray(self.d[s[4]:s[4] + s[5]]) if s[1] != 8 else bytearray(s[5])
        relocs = []
        for off, info, addend in self.relas.get(k, ()):
            kind = info & 0xFF
            width = {1: 4, 2: 2, 3: 1, 4: 4, 5: 2, 6: 1}.get(kind, 4)
            data[off:off + width] = bytes(width)
            relocs.append((off, kind, self.target(info >> 8), addend))
        return bytes(data), tuple(relocs)

    def fingerprint(self, section: str) -> str:
        k = self.by_name.get(section)
        if k is None:
            return "missing"
        data, relocs = self.content(k)
        h = hashlib.sha256(data + repr(relocs).encode())
        for name in sorted({t for _, _, t, _ in relocs if t.startswith(".rodata")}):
            if name in self.by_name:        # read-only data it refers to, one level
                h.update(name.encode() + repr(self.content(self.by_name[name])).encode())
        return h.hexdigest()


def link_map(path: Path) -> list[tuple[int, int, str, str]]:
    """GNU ld map: the input sections as (address, size, object, section)."""
    out, pending = [], None
    for line in path.read_text().splitlines():
        m = re.match(r"^ (\S+)\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+(\S+\.o)$", line)
        if m:
            out.append((int(m[2], 16), int(m[3], 16), m[4], m[1]))
            pending = None
            continue
        m = re.match(r"^ (\.\S+)$", line)
        if m:
            pending = m[1]
            continue
        m = re.match(r"^\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+(\S+\.o)$", line)
        if m and pending:
            out.append((int(m[1], 16), int(m[2], 16), m[3], pending))
        pending = None
    return out


# -- generated code text -------------------------------------------------------------
def gen_dir(elf: Path) -> Path:
    return elf.parent / "gen" if (elf.parent / "gen").is_dir() else REPO / "build/gen"


def label_regions(gen: Path, labels: set[str]) -> dict[str, str]:
    """Per symbol label of the module and support files, its text up to the next."""
    out = {}
    for f in sorted(gen.glob("*.s")):
        if f.name == "program.s":
            continue
        name, lines = None, []
        for line in f.read_text().splitlines():
            m = re.match(r"^([A-Za-z_]\w*):", line)
            if m and m[1] in labels:
                if name:
                    out[name] = "\n".join(lines)
                name, lines = m[1], []
            if name:
                lines.append(line)
        if name:
            out[name] = "\n".join(lines)
    return out


def program_text(gen: Path) -> tuple[str, dict]:
    """program.s: its text but comments, the dispatch rows and their count (the
    header), and the rows per CS:IP in order."""
    header, rows, key = [], {}, None
    lines = (gen / "program.s").read_text().splitlines()
    in_table = False
    for k, line in enumerate(lines):
        if line.startswith(";"):
            continue
        if line.startswith("dispatch_count:"):
            header.append(line)
            lines[k + 1] = ";"          # the count
            continue
        if line.startswith("dispatch_table:"):
            in_table = True
            header.append(line)
            continue
        if in_table:
            m = re.match(r"^\tdc\.w\t([^,]+),([^,]+),([^,]+),([^,]+)$", line)
            if m:
                key = (m[1], m[2])
                rows.setdefault(key, []).append([m[3], m[4]])
                continue
            m = re.match(r"^\tdc\.l\t(\S+)$", line)
            if m and key:
                rows[key][-1].append(m[1])
                key = None
                continue
            in_table = False
        header.append(line)
    return hashlib.sha256("\n".join(header).encode()).hexdigest(), rows


# -- an image ------------------------------------------------------------------------
class Image:
    """A host image's units for the fingerprints: the runtime's input sections and
    the generated code's label regions, by address."""

    def __init__(self, elf: Path, syms: dict):
        self.elf, self.syms = elf, syms
        self.map = link_map(elf.with_suffix(".map"))
        self.gen = gen_dir(elf)
        self.objects: dict[str, Object | None] = {}
        self.paths: dict[str, Path] = {}
        units = []
        generated = []
        for addr, size, obj, sec in self.map:
            path = Path(obj) if Path(obj).is_absolute() else REPO / obj
            if path.name == "program.o":
                if sec.startswith(".text.") and size:
                    generated.append((addr, addr + size))
                continue
            self.paths[path.name] = path
            if sec.startswith(".text") and size:
                units.append((addr, addr + size, ("rt", path.name, sec)))
        names = sorted((a, n) for n, a in syms.items()
                       if any(lo <= a < hi for lo, hi in generated) and not n.startswith("."))
        self.labels = {n for _, n in names}
        for k, (a, n) in enumerate(names):
            end = names[k + 1][0] if k + 1 < len(names) else max(hi for _, hi in generated)
            units.append((a, max(end, a + 1), ("gen", n)))
        units.sort()
        self.units = units
        self.starts = [u[0] for u in units]
        self.ends = []
        top = 0
        for u in units:               # running maximum end: overlaps found by bisect
            top = max(top, u[1])
            self.ends.append(top)
        self._regions = None
        self._program = None

    def obj(self, name: str) -> Object:
        if self.objects.get(name) is None:
            self.objects[name] = Object(self.paths[name])
        return self.objects[name]

    def executed(self, blocks) -> set:
        keys = set()
        for a, size in blocks:
            k = bisect.bisect_right(self.starts, a + size - 1) - 1
            while k >= 0 and self.ends[k] > a:
                lo, hi, key = self.units[k]
                if lo < a + size and a < hi:
                    keys.add(key)
                k -= 1
        return keys

    def regions(self) -> dict:
        if self._regions is None:
            self._regions = label_regions(self.gen, self.labels)
        return self._regions

    def program(self) -> tuple[str, dict]:
        if self._program is None:
            self._program = program_text(self.gen)
        return self._program

    def fingerprint(self, key) -> str:
        if key[0] == "rt":
            if key[1] not in self.paths:
                return "missing"
            return self.obj(key[1]).fingerprint(key[2])
        text = self.regions().get(key[1])
        return hashlib.sha256(text.encode()).hexdigest() if text is not None else "missing"


def fingerprints(image: Image, ran, harness: str) -> dict:
    header, rows = image.program()
    return {"units": {key: image.fingerprint(key) for key in sorted(ran)},
            "header": header, "rows": rows, "harness": harness}


def refusals(saved: dict, image: Image, harness: str) -> list[str]:
    """Why this image may not resume from a save with these fingerprints (none: it may)."""
    out = []
    if saved["harness"] != harness:
        out.append("the harness's behavior changed (tests/host_resume.py HARNESS)")
    header, rows = image.program()
    if saved["header"] != header:
        out.append("the generated program's header changed (program.s)")
    moved = [k for k, r in saved["rows"].items() if rows.get(k) != r]
    if moved:
        out.append(f"{len(moved)} dispatch CS:IP rows changed, first {moved[0]}")
    changed = [k for k, f in saved["units"].items() if image.fingerprint(k) != f]
    if changed:
        names = ", ".join(":".join(k[1:]) for k in changed[:5])
        out.append(f"{len(changed)} units that ran before the save changed: {names}"
                   f"{' ...' if len(changed) > 5 else ''}")
    return out


# The harness's guest-visible behavior: platform services, inputs, the replay of the
# reference's interrupts, keys, VGA status reads and REP slices (sources hashed).
HARNESS = ("Host.platform", "Host.vga_status", "Host.post", "Host.press", "Host.guest_vector",
           "Host.run", "MemFile", "KeyRelease", "key_events", "key_code", "dos_file_stamp",
           "reference_clocks", "reference_inputs", "retrace_runs", "milestone_script", "trigger",
           "KEYS")


def field_span(record: bytes, name: str) -> tuple[int, int]:
    """The offset and size of a named field's bytes in a src/runtime/snapshot.c record."""
    at = 6                                      # "XWRS", the version
    while n := record[at]:
        key = record[at + 1:at + 1 + n].decode()
        size = struct.unpack(">I", record[at + 1 + n:at + 5 + n])[0]
        at += 5 + n
        if key == name:
            return at, size
        at += size
    raise KeyError(f"snapshot record: no field {name}")


def harness_hash(module, rep_module) -> str:
    h = hashlib.sha256()
    for name in HARNESS:
        obj = module
        for part in name.split("."):
            obj = getattr(obj, part)
        h.update(name.encode() + (repr(obj) if isinstance(obj, dict) else inspect.getsource(obj)).encode())
    h.update(inspect.getsource(rep_module.Replay).encode())
    return h.hexdigest()


def plants(saved: dict, image_of, harness: str) -> list[str]:
    """Controls (host_run.py --resume-plants): the image as saved may resume; each
    change to what ran before the save is refused; a change to what did not is not.
    Returns the plants whose outcome was not the expected one."""
    missed = []
    base = refusals(saved, image_of(), harness)
    print(f"resume plant {'unchanged':24}: {'; '.join(base) or 'may resume'}")
    if base:
        return ["unchanged image refused: rebuild the save"]
    ran = set(saved["units"])

    def flip(image, key):
        o = image.obj(key[1])
        s = o.secs[o.by_name[key[2]]]
        d = bytearray(o.d)
        d[s[4] + s[5] // 2] ^= 0x01
        o.d = bytes(d)

    def text(image, name):
        image.regions()[name] += "\n\tnop"

    image = image_of()
    gen_ran = next(k for k in sorted(ran) if k[0] == "gen")
    gen_idle = next(("gen", n) for n in sorted(image.labels, reverse=True)
                    if ("gen", n) not in ran and GUEST_LABEL.match(n) and n in image.regions())
    rt_ran = next(k for k in sorted(ran) if k[0] == "rt" and k[2].startswith(".text."))
    rt_idle = next(u[2] for u in image.units if u[2][0] == "rt" and u[2] not in ran
                   and u[2][2].startswith(".text."))
    row = next(iter(sorted(saved["rows"])))
    cases = [
        (f"generated ran {gen_ran[1]}", True, lambda i: text(i, gen_ran[1]), harness),
        (f"generated idle {gen_idle[1]}", False, lambda i: text(i, gen_idle[1]), harness),
        (f"runtime ran {rt_ran[2]}", True, lambda i: flip(i, rt_ran), harness),
        (f"runtime idle {rt_idle[2]}", False, lambda i: flip(i, rt_idle), harness),
        (f"dispatch row {row[0]}:{row[1]}", True,
         lambda i: i.program()[1].__setitem__(row, [["0", "0", "R_00000"]]), harness),
        ("harness behavior", True, lambda i: None, harness + "x"),
    ]
    for name, refused, change, h in cases:
        image = image_of()
        change(image)
        why = refusals(saved, image, h)
        print(f"resume plant {name[:24]:24}: {'; '.join(why) or 'may resume'}")
        if bool(why) != refused:
            missed.append(name)
    return missed


# -- the open guest calls ------------------------------------------------------------
def return_site(h, addr: int, names_at: dict) -> tuple:
    """The return site at 68k return address addr: (width 2 or 4, the compared
    return IP or CS:IP, the guest label after it, its mismatch stop)."""
    def u16(a): return struct.unpack(">H", h.mem(a, 2))[0]
    def s16(a): return struct.unpack(">h", h.mem(a, 2))[0]
    a = addr
    op = u16(a)
    if op == 0x6000:                                # bra.w to the compare (indirect calls)
        a = a + 2 + s16(a + 2)
    elif op >> 8 == 0x60 and op & 0xFF not in (0, 0xFF):
        a = a + 2 + (op & 0xFF if op & 0x80 == 0 else (op & 0xFF) - 256)
    op = u16(a)
    if op in (0x0C47, 0xBE7C):                      # cmp.w #ip,d7 (cmpi or cmp form)
        width, value, a = 2, u16(a + 2), a + 4
    elif op in (0x0C87, 0xBEBC):                    # cmp.l #cs:ip,d7
        width, value, a = 4, struct.unpack(">I", h.mem(a + 2, 4))[0], a + 6
    else:
        raise ValueError(f"no return compare at {addr:x} ({op:04x})")
    op = u16(a)
    if op == 0x6600:
        target, after = a + 2 + s16(a + 2), a + 4
    elif op >> 8 == 0x66 and op & 0xFF not in (0, 0xFF):
        target, after = a + 2 + (op & 0xFF if op & 0x80 == 0 else (op & 0xFF) - 256), a + 2
    else:
        raise ValueError(f"no mismatch branch after the compare at {addr:x}")
    label = next((n for n in names_at.get(after, ()) if GUEST_LABEL.match(n)), None)
    if label is None:
        raise ValueError(f"no guest label after the return site at {addr:x}")
    if u16(target) != 0x4EF9:
        raise ValueError(f"mismatch branch at {addr:x} to {target:x}: no jmp")
    stop = next((n for n in names_at.get(struct.unpack(">I", h.mem(target + 2, 4))[0], ())
                 if n in MISMATCH), None)
    if stop is None:
        raise ValueError(f"mismatch branch at {addr:x}: not a mismatch stop")
    return width, value, label, stop


def open_calls(h, a7: int, entry: int) -> list[tuple]:
    """The open guest calls between the label's a7 and the guest entry's, innermost
    first: each long a return address into generated code."""
    names_at: dict[int, list] = {}
    for n, a in h.syms.items():
        names_at.setdefault(a, []).append(n)
    if (entry - a7) % 4 or a7 > entry:
        raise ValueError(f"native stack {a7:x} not below the guest entry's {entry:x} in longs")
    out = []
    for at in range(a7, entry, 4):
        ret = struct.unpack(">I", h.mem(at, 4))[0]
        if not h.code[0] <= ret < h.code[1]:
            raise ValueError(f"native stack +{at - a7:x}: {ret:x} is no generated return address")
        out.append(return_site(h, ret, names_at))
    return out


def stub(width: int, value: int, label: int, stop: int) -> bytes:
    """The return site resumed: the same compare, its label on a match (the compare's
    flags, as at the site), the mismatch stop otherwise."""
    cmp = struct.pack(">HH", 0x0C47, value) if width == 2 else struct.pack(">HI", 0x0C87, value)
    return cmp + struct.pack(">HHHIHI", 0x6600, 8, 0x4EF9, label, 0x4EF9, stop)


# -- runtime calls from the harness ------------------------------------------------------
REG_NAMES = [f"d{k}" for k in range(8)] + [f"a{k}" for k in range(8)] + ["sr"]


def call(h, U, name: str, *args: int) -> int:
    """Run runtime function `name` (68020 C ABI) to its return, every register kept."""
    saved = {r: h.r(r) for r in REG_NAMES + ["pc"]}
    sp = (saved["a7"] - 0x1000) & ~3
    for v in reversed(args):
        sp -= 4
        h.e.write(sp, struct.pack(">I", v & 0xFFFFFFFF))
    sp -= 4
    h.e.write(sp, struct.pack(">I", SENTINEL))
    h.e.reg_write(U.M68K["a7"], sp)
    err = h.e.start(h.syms[name], SENTINEL)
    d0, pc = h.r("d0"), h.r("pc")
    for r in REG_NAMES + ["pc"]:
        h.e.reg_write(U.M68K[r], saved[r])
    if err or pc != SENTINEL:
        raise RuntimeError(f"{name}: unicorn error {err} at {pc:x}")
    return d0
