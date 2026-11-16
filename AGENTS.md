# X-Wing

Amiga port of X-Wing. The base is the DOS floppy release 1.0, translated offline to 68020
assembly with Secret Weapons of the Luftwaffe's translator and runtime, copied and adapted
(`docs/port-plan.md`). The Macintosh demo's 68k code is an optional donor of native routines
in the speed phase. Current scope is reference setup only. The DOS release is installed by
its own installer and run under a scripted DOSBox-X. The Macintosh demo is installed on a
fresh System 7.5.5 volume and launched on an emulated 68040 Macintosh. The DOS reference
runs are traced with Secret Weapons of the Luftwaffe's tracer and reach pinned milestones.
The static and live map of the DOS program is in place. SWOTL's translator is copied;
its decoder, IR and interpreter cover X-Wing's x86 code and pass gate 3, and its 68020
backend translates every in-scope module and passes gate 4. SWOTL's runtime and Amiga
platform are copied; the generated code draws the LucasArts logo on the 68030 model,
where a diagnostic replay matches the reference at m1, and runs in host lockstep to m1
(gate 5); host lockstep and the Amiga replay match it over every pinned milestone (gate 6),
and host lockstep to a flight milestone resumes from a save at the flight's start. SWOTL's FM
re-hoster plays the music on Paula and the effects play prerendered (P7). Read `docs/open-work.md` first.

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
- Before implementing a service, copy it from Secret Weapons of the Luftwaffe where it
  exists there (`docs/port-plan.md`). Otherwise inspect Vette!, Alone in the Dark and
  Prince of Persia 2 and reuse their code through AmigaXDev's shared helpers.
- Shell scripts must work with macOS `/bin/bash` 3.2.
- `docs/open-work.md` is the only work queue; remove completed items in their commit.
  Docs describe the current state; history belongs in Git.
- Names live in `disasm/symbols.csv` once analysis begins. Addresses use (segment,
  offset) of the 68k CODE resources, or offsets relative to the DOS program's load segment
  and overlay, never Amiga or emulator load addresses. Label evidence
  MEASURED, DERIVED or INFERRED.
- Owner decisions live in `docs/design.md` and change only with owner authorization.

## Translator rules

Copied from Secret Weapons of the Luftwaffe's standing rules at the commit pinned in
`manifest/references.tsv`.

- Guest code reaches the Amiga only as translator output. Never hand-port a guest routine
  to C or assembly, never edit generated files and never fix output by hand: fix the
  translator or `annotations/` and regenerate.
- Hand-written code is the runtime and platform layer only, named by the surface item it
  implements (DOS service, port, interrupt, device), never by guest address. Replacing a
  guest routine natively, the copy-protection bypass included, needs an
  `annotations/hle.csv` entry with its reason and oracle.
- Phase gates in `docs/phases.md` are hard. A milestone counts only if its pixels come
  from generated code.
- Unknown control flow, code writes, ports and interrupts fail loudly.
- Tests settle correctness: x86 semantics against Unicorn, generated 68k on the host 68k
  core, the whole game in lockstep with DOSBox-X. Never compare the port with itself.
- Reusable scripts live in `tools/` and are named in the doc that uses them. The method
  behind every committed number is in a committed tool or its commit message. A script
  stays in `tmp/` only if nothing committed names or relies on it.

## Validation scope

Copied from Secret Weapons of the Luftwaffe, as above.

- Run only the gates relevant to the changed code and its affected callers, consumers and
  shared contracts. State the selected checks and why before running them.
- Translator or shared runtime changes: the affected differential, guard and sabotage
  tests and the relevant original-game host and replay fixtures. Broaden when shared
  memory, flags, control flow, interrupts or other cross-cutting contracts change.
- Audio-only changes: the FM waveform, quality, envelope and allocation checks, backend
  integration where affected, and their sabotage. Build and smoke the Amiga image for
  platform changes. Do not rerun translator, DOS, file, input or whole-game suites for
  isolated audio synthesis.
- Docs-only changes: consistency and diff checks. Build and release changes: the affected
  builds, image audits and launch and package checks.
- Keep every selected check, oracle and tolerance. Scope by dependencies, never by
  whether a test passes. Run the full gate suite only when the impact spans its suites or
  the owner asks. Green results for unchanged inputs stand.

## Project docs

| Document | Read when |
|---|---|
| `README.md` | setting up a checkout: inputs to supply and the commands |
| `docs/design.md` | choosing an approach or target; owner decisions |
| `docs/port-plan.md` | the steps, what is copied from Secret Weapons of the Luftwaffe and why; what Wing Commander 2 shares |
| `docs/phases.md` | before committing work of a new phase: the hard gates |
| `docs/translator-design.md` | translator, runtime or test contract; each SWOTL decision kept or changed |
| `docs/source-inventory.md` | anything about the supplied archive and its contents |
| `docs/dos-reference.md` | installing and running the DOS original under DOSBox-X |
| `docs/mac-reference.md` | booting the original under MAME |
| `docs/overlay-manager.md` | X-Wing's overlay manager, its model and check |
| `docs/external-surface.md` | interrupts, ports, VGA, EMS, the music driver and the translator fit |
| `docs/indirect-coverage.md` | indirect calls and jumps the traces never ran: their pointers, targets and status |
| `docs/x86-notes.md` | x86 real-mode facts the decoder, IR and lowering rely on; Unicorn quirks |
| `docs/open-work.md` | before starting any work |

## Shared guidance

Shared guidance starts at `~/.local/share/amiga/docs/index.md`: read the rows that match
the task. It routes to the playbooks, references and shared tools (`docs/environment.md`,
"Shared tools"); this project follows `docs/playbooks/new-port-playbook.md` there. The
environment comes from AmigaXDev's `make setup`, and `amiga/env.sh` sources
`~/.local/share/amiga/env.sh`. Generic lessons go into AmigaXDev's docs (edit them there and
run `make share`); this repository keeps what is specific to this game.
