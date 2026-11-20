# Showing commands run for real (`terminal` beat: `chay:<ref>` in the one command)

A follow-along video must let the viewer do the same, so it shows the commands and what they print. The chain runs the commands for real in a throwaway folder, keeps the log, and draws the real log as phone-sized terminal stills, which the builder plays as an ordinary capture picture (the GPU builder is unchanged). Nothing is typed or edited by hand: the text on screen is the captured output (owner, 20/11/2026: "quay màn hình nếu cần ... user xem video là có thể làm theo được luôn"; free things only; "chú ý bảo mật, không tải virus, hay khiến máy anh hoặc user gặp nguy hiểm").

```
script (terminal beat)  ->  chay:<ref>  ->  giong  ->  lap-rap  ->  anh  ->  kiem-anh  ->  dung  ->  nhac  ->  goi
                            (before the voice: a wrong command or a typosquatted package costs seconds, not four minutes)
```
| piece | file |
| --- | --- |
| the run block, the safety gates, the run, the pictures | `halcyon_chay.py` (standard library; Pillow for drawing, from the GPU interpreter) |
| script contract, the `run` source, the step, the pack | `halcyon_mot_lenh.py`, [KICH-BAN.md](KICH-BAN.md) 1b and 7, [MOT-LENH.md](MOT-LENH.md) |
| the beat becomes a capture picture | `halcyon_kich_ban.py` (`terminal_cap`, `terminal_key`) |
| the font | `fonts/JetBrainsMono-Medium.ttf`, a 30 KB subset of JetBrains Mono Medium (printable ASCII, Latin-1, typographic dashes and quotes, bullet, ellipsis, right arrow; hinting kept so the advance stays 29 px at 48 px; no layout features). SIL OFL (`fonts/OFL-JetBrainsMono.txt`; the licence declares no Reserved Font Name, so the family name is kept). Made with `pyftsubset` from the upstream file; sha256 of the subset `430DD4B0C13E66DE78F28167B82216E87DC1457B7A9467A1261E54F2992999A1`. A character outside the subset is refused (`glyph`), never drawn as a box |

## The script
```
"sources": { "thu": { "run": {
    "files": [ {"name": "server.py", "dir": "agent", "from": "https://raw.githubusercontent.com/<owner>/<repo>/<ref>/README.md", "fence": "# server.py"} ],
    "packages": { "fastapi": "fastapi/fastapi" },              (package -> the GitHub repository it must come from; the source project is the default)
    "steps": [ {"cmd": "pip install ag-ui-protocol fastapi uvicorn", "cwd": "agent"},
               {"cmd": "uvicorn server:app --port 8000", "cwd": "agent", "serve": true, "ready": "Uvicorn running", "port": 8000},
               {"cmd": "npx tsx client.ts", "cwd": "client", "expect": ["Hello from AG-UI!"], "deadline": 120} ],
    "max_rows": 8 } } }
a beat:  {"kind": "terminal", "level": "FOOT", "headline": [2 lines], "kicker": ..., "terminal": {"ref": "thu", "step": 2, "bands": [{"text": "Hello from AG-UI!", "anchor": "spoken words"}]}}
```
- A `terminal` beat shows **one step** (`step` counts from 0): the command and the end of its own output, as one picture. A video shows as many steps, in as many beats, as it needs: there is no cap on beats or steps.
- `files`: each file is written from **the fenced block of the named README whose first line is `fence`** (exactly one block, verbatim). `dir` and the step `cwd` are one plain folder name inside the throwaway folder (made when needed). A file cannot be typed into the script.
- `serve: true` starts a long-running command, waits for its `ready` text (60 s) and, with `port`, for the port to listen; later steps run against it; it is stopped at the end with its whole process tree. `expect` lists texts the real output must hold. `deadline` is 10 to 300 s (default 120).
- `bands` name phrases on one row of the picture; the builder highlights them at the spoken `anchor` (as for captures). The picture of a step is the key `<ref>-s<step>` in the capture manifest.
- Writing the command the way the viewer types it: one command per step (Windows PowerShell 5.1 takes no `&&`: write `npm init -y` and `npm pkg set type=module` as two steps).

## What is on the picture
1170 px wide (390 css px at scale 3), JetBrains Mono 48 px on a 29 px character grid, 36 columns, 8 rows by default (`max_rows` 3 to 12). With the builder's 763 px capture width the text is 31 px on the frame (gate: not under 28). The prompt and the command, then the **end** of the real output: lines wrap at spaces, whole earlier lines are dropped behind a marked row `[... N earlier lines]`, a last line too long for the rows is cut and ends in `...`. Blank lines are dropped, escape codes removed, a carriage return overwrites its line. A phrase named in `bands` is drawn in amber in the picture itself (it is also passed to the builder as a band, but the builder's highlighter is made for light pages and hardly shows on this dark one; the emphasis therefore is on from the start, not timed to the voice). Flat dark margins (no window chrome) so the builder's shown-rows and contrast checks measure real ink. A character the font lacks is refused (`glyph`), never drawn as a box.

## The safety gates (a follow-along installs third-party packages)
Every refusal is `chay: <kind>: <why>` and `to fix: ...`. The ones that need no network run in `kiem-kich-ban` (`--chi-kiem`) by the same code that runs the steps; each has a test in `tests/test_halcyon_chay.py` (or `test_halcyon_mot_lenh.py`).

| gate | refused kind | when |
| --- | --- | --- |
| allow list | `command` | anything but `pip install <pkgs>`, `npm init -y`, `npm pkg set type=module`, `npm install <pkgs>`, `npx <package installed by an earlier step> <file>`, `uvicorn <file>:<app> [--port N]`, `python <file>`, `node <file>` (a file of the run block; no `-c`, `-e`, `-m`; no other npm or pip subcommand) |
| chained or piped | `chain`, `redirect`, `shell` | `& \| ;` (so `curl ... \| sh`, `iwr ... \| iex`, `&&`), `< >`, `` ` $ ( ) { } ^ % ! `` quotes, backslash, line break |
| dangerous words | `danger` | download tools (`curl`, `wget`, `iwr`, `Invoke-WebRequest`, `iex`, `Invoke-Expression`), `sudo`, `runas` and other privilege raisers, `Set-ExecutionPolicy`, `Set-MpPreference`/`Add-MpPreference` (antivirus), `netsh` (firewall), registry and service tools, shells, installers (`winget`, `choco`, `apt`...), deleters |
| global or outside install | `global`, `path`, `address` | `-g`, `--global`, `--user`, `--prefix`, `--target`, `--break-system-packages`...; a path with `..`, an absolute path or `~`; any address in a command (no install from a link, archive or path); a `cwd` that is not one plain folder name |
| other package sources | `registry` | `--index-url`, `--extra-index-url`, `--registry`, `--find-links`, `--trusted-host`, `--proxy`...; and the environment itself fixes the sources: `PIP_INDEX_URL=https://pypi.org/simple/`, `npm_config_registry=https://registry.npmjs.org/`, no user config files (the home folder is inside the throwaway folder) |
| `npx` | `npx` | running a package no earlier step installed (npx would fetch it) |
| files | `file`, `fence` | a source host other than `raw.githubusercontent.com`; no block, or more than one, starts with the `fence` line |
| package named by the source | `package-source` | a package not named in any fenced block of the source's README |
| package check, before any install | `typosquat`, `network`, `package-yanked`, `package-deprecated`, `package-version` | the package must exist on its official registry (pypi.org, registry.npmjs.org), the version must exist and not be yanked or deprecated, and the registry's own metadata must point at the GitHub repository the script says it comes from (the source project by default, `packages` for the others): a look-alike name fails here. Recorded in `chay.json`: registry, name, version, registry page address, repository, publish date |
| versions pinned | `version` | after the installs the version installed (read from `pip freeze` and `package-lock.json`) must equal the version checked; the whole freeze and lock are recorded (`pins`). A version that does not fit can be pinned in the command: `name==1.2.3`, `name@1.2.3` |
| download origin | `registry` | an install printed a download address outside `pypi.org`, `files.pythonhosted.org`, `registry.npmjs.org`, or `package-lock.json` resolved a package from elsewhere |
| install scripts | (environment) | `npm_config_ignore_scripts=true`: no package's install script runs; `PIP_ONLY_BINARY=:all:`: only wheels, so no `setup.py` runs. A package that cannot work that way stops the run with the install's own error. No script is allowed to run in this version (a package that needs one: tell the coordinator) |
| scrubbed environment | `environment` | a short allow list of machine variables; none whose name holds KEY, TOKEN, SECRET, PASSWORD, CREDENTIAL, AUTH, COOKIE; home, temp and cache folders inside the throwaway folder; `PATH` without any repository folder; the venv first on `PATH`; `PIP_REQUIRE_VIRTUALENV=1` |
| nothing from the checkout | `location` | `--out` inside the repository checkout; a tool resolved to a path inside it |
| exit and text | `exit`, `expect`, `band` | a step exits non-zero (its last output lines are in the message); a text in `expect` is not in the real output; a phrase to highlight is not on one row of the picture |
| ports | `port`, `serve` | a named port already listening; a server that never prints its `ready` text or does not listen |
| time | `deadline` | a step over its deadline is killed with its whole process tree |
| size | `too-tall`, `text-size`, `glyph` | a command that needs more than half the rows; text under 28 frame px; a character the font cannot draw |
| leftovers | `leftover` | after the run (refused or not): every process started is killed with its tree, then the processes whose command line names the throwaway folder are listed (`leftover_processes_after`, must be 0), then the folder is deleted; the log stays in `log/` |

`npm audit --omit=dev --json` runs in each folder that has a `package-lock.json` and is recorded in `chay.json` (`audit`); a known vulnerability is printed as a warning and listed in the pack. `pip-audit` is not installed by the chain: when it is not already there, only versions are recorded (the pack says so). The packages' own dependencies are installed from the same two registries but are not checked one by one: their versions are recorded, not their code.

## Output (`<run>/cong-viec/chay/<ref>/`)
`chay.json` (tools and versions, files with SHA-256 and their fence, documents with SHA-256, packages checked and installed, pins, audit, environment variable names that passed, per step: command, cwd, exit code, seconds, the output, the rows drawn and the capture-manifest entry), `s<step>.png` (the picture of each step), `log/step-<n>.log` (the full real output of each step). The throwaway folder `work/` is deleted. The step is reused when the run block, the tool and the font are unchanged and `chay.json` is under 6 hours old; the pack's `tom-tat.md` lists "Nguồn đã chạy (máy)" (commands, exit codes, files, packages with their registry pages, audit), one line under "Máy đã kiểm" and two under "Máy chưa kiểm được" (that it runs on the viewer's machine; that dependencies are not checked one by one). Stills, `chay.json` and the logs go to "6 - Nguồn/chay-lenh" in `luu-tru.json`.

## What this cannot show
That the command works on the viewer's machine (another OS, Python or Node), that the project is worth following, or that a dependency's code is clean. The pictures are stills, not a live recording; the order of what the voice says against what is on screen is for the contact sheet and the person who writes the script.

## Tests and a live run
`python -m unittest tests.test_halcyon_chay tests.test_halcyon_mot_lenh tests.test_halcyon_kich_ban` (run with the GPU interpreter so the drawing test runs; the class `RunsForReal` runs real local Python in a venv, about a minute). A live run of the AG-UI case (installs from pypi.org and registry.npmjs.org, about 45 s): `python video/halcyon/halcyon_chay.py run --job job.json --out <folder outside the repo>`, or through `mot-lenh.py` with a `terminal` beat.
