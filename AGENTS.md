# X-Wing

Amiga port of X-Wing. The base is the DOS floppy release 1.0, translated offline to 68020
assembly with Secret Weapons of the Luftwaffe's translator and runtime, copied and adapted
(`docs/port-plan.md`). The Macintosh demo's 68k code is an optional donor of native routines
in the speed phase. Current scope is reference setup only. The DOS release is installed by
its own installer and run under a scripted DOSBox-X. The Macintosh demo is installed on a
fresh System 7.5.5 volume and launched on an emulated 68040 Macintosh. No analysis or port
work has started; read `docs/open-work.md` first.

## Rules

- Commit directly to `main`, one verified coherent change per commit. Author and
  committer: Vesa Halttunen <vesuri@jormas.com>. Unsigned (`commit.gpgsign` and
  `tag.gpgsign` false, repository-local), `core.hooksPath=/dev/null`, no Co-Authored-By
  or other trailers. Never change global Git settings.
- Never commit original or byte-derived material: the demo archive, extracted forks,
  ROMs, System disks, PRAM, generated code or tables, disassembly, captures, traces,
  saves or emulator state. They live in ignored `tmp/` and `ref/`. Check
  `git status --ignored` before adding new files. Commit names and hashes only.
- The original DOS execution is the ground truth; the original Macintosh execution is the
  ground truth for any donor 68k routine. Preserve original game
  decisions; implement the services it calls. Unknown calls, control flow, code writes,
  device accesses and interrupts are named loud stops, never guessed successes.
- Correctness needs tests against the original and positive completion signals. A
  timeout or an unreached probe is not a pass; negative observations need controls.
- No performance claims without matched-workload measurements.
- Never kill emulators or debuggers by process name (`pkill mame`, `pkill fs-uae`,
  `pkill gdb`); other projects run them. Kill only this project's recorded PIDs through
  the shared `FSUAE_COMMON` helper. Never edit a running shell launcher.
- No personal paths or paths into other projects in tracked files. Name other projects
  by name. `~/.local` and `~/.local/share/amiga` are the allowed conventions.
- Pin inputs by SHA-256 or commit in `manifest/` and verify them before use. Leave the
  originals untouched; a differing output moves to `.replaced/`, never deleted.
- Before implementing a service, inspect Vette!, Alone in the Dark and Prince of
  Persia 2 and reuse their code through AmigaXDev's shared helpers.
- Shell scripts must work with macOS `/bin/bash` 3.2.
- `docs/open-work.md` is the only work queue; remove completed items in their commit.
  Docs describe the current state; history belongs in Git.
- Names live in `disasm/symbols.csv` once analysis begins. Addresses use (segment,
  offset) of the 68k CODE resources, or offsets relative to the DOS program's load segment
  and overlay, never Amiga or emulator load addresses. Label evidence
  MEASURED, DERIVED or INFERRED.
- Owner decisions live in `docs/design.md` and change only with owner authorization.

## Project docs

| Document | Read when |
|---|---|
| `README.md` | setting up a checkout: inputs to supply and the commands |
| `docs/design.md` | choosing an approach or target; owner decisions |
| `docs/port-plan.md` | the steps, what is copied from Secret Weapons of the Luftwaffe and why |
| `docs/source-inventory.md` | anything about the supplied archive and its contents |
| `docs/dos-reference.md` | installing and running the DOS original under DOSBox-X |
| `docs/mac-reference.md` | booting the original under MAME |
| `docs/open-work.md` | before starting any work |

## Shared guidance

Shared guidance starts at `~/.local/share/amiga/docs/index.md`: read the rows that match
the task. It routes to the playbooks, references and shared tools (`docs/environment.md`,
"Shared tools"); this project follows `docs/playbooks/new-port-playbook.md` there. The
environment comes from AmigaXDev's `make setup`, and `amiga/env.sh` sources
`~/.local/share/amiga/env.sh`. Generic lessons go into AmigaXDev's docs (edit them there and
run `make share`); this repository keeps what is specific to this game.
