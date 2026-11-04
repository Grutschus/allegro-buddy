# better-allegro-buddy

**[allegro-buddy](https://github.com/Grutschus/allegro-buddy), rewritten in Rust™.** Yes, really.

<p align="center">
  <picture align="center">
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/plainerman/better-allegro-buddy/main/bench/plots/hero-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/plainerman/better-allegro-buddy/main/bench/plots/hero-light.svg">
    <img alt="Bar chart: running all 12 read-only commands once takes 0.88 s with bab and 2.96 s with ab." src="https://raw.githubusercontent.com/plainerman/better-allegro-buddy/main/bench/plots/hero-light.svg">
  </picture>
</p>
<p align="center">
  <i>Running all 12 read-only commands once, live on the Allegro cluster. Same output, byte for byte.</i>
</p>

`bab` is a byte-for-byte compatible Rust rewrite of `ab`, the Python CLI
allegro-buddy 2.7 by [Grutschus](https://github.com/Grutschus): a small Slurm
companion for everyday cluster work. It tells you what is free, why your job is waiting,
and gets you a dev node in one command. It reads what it needs from Slurm, so it works
beyond the Allegro cluster it was born on.

The original is a great tool. Its only flaw: it is Python, so every call spends ~150 ms
importing itself before it asks Slurm anything. Rewriting things in Rust is a meme, so
we did it as a joke and gave it the most modest name we could think of. Then the joke
got a differential test harness, a benchmark suite and a CI pipeline. Now it is
**3.4× faster** (median, live on Allegro). Same commands, flags, config and output, down
to the last ANSI escape code. Only the name changed, and it got one more `b`.

## Install

One command, no Python needed. It fetches the `bab` binary for Linux (x86_64/aarch64,
glibc ≥ 2.17: RHEL/CentOS 7 and newer) or macOS (Intel/Apple silicon):

```bash
mkdir -p ~/.local/bin && curl -fsSL https://github.com/plainerman/better-allegro-buddy/releases/latest/download/bab-$(uname -m)-$(uname -s).tar.gz | tar -xz -C ~/.local/bin
bab completion --install               # optional: tab completion
```

Run it again to upgrade. If your shell can't find `bab`, put `~/.local/bin` on your `PATH`
(`export PATH="$HOME/.local/bin:$PATH"`; most Linux setups already have it, macOS does
not). The macOS binary isn't signed, but files fetched with `curl` aren't quarantined, so
it just runs. On Linux `bab` links glibc dynamically on purpose: group lookups through
sssd/LDAP work as they do for `ab`. All files: [releases](https://github.com/plainerman/better-allegro-buddy/releases).

From PyPI, where the package is called `better-allegro-buddy` (the name `bab` was taken),
with the same binary inside:

```bash
uv tool install better-allegro-buddy   # or: pipx install better-allegro-buddy
uv tool upgrade better-allegro-buddy   # later
uvx --from better-allegro-buddy bab q  # or just try it without installing
```

`ab` and `bab` happily live side by side.

From source, with Rust ≥ 1.88 (e.g. via [rustup](https://rustup.rs)):

```bash
cargo install --locked --git https://github.com/plainerman/better-allegro-buddy
```

This puts `bab` into `~/.cargo/bin` (run it again to upgrade). Such a build needs the
glibc of the machine it was built on (or newer), so build it on the cluster itself, or
use the binaries above, which are built for glibc 2.17.

## Commands

| Command | What it does |
| --- | --- |
| `bab info` | Partitions you can use, with free CPUs, memory and GPUs |
| `bab free [--nodes] [-G a5000]` | Free GPUs by type, per partition or per node |
| `bab q [--all] [-w]` | Your queue, with start estimates and what pending jobs lack |
| `bab why [JOBID] [--fix]` | Why a job waits, and the one change that starts it now |
| `bab node [NODE]` | Which jobs use a node's GPUs, CPUs and memory, and for how long |
| `bab dev start / login / status / stop` | A detached dev allocation; `bab l` logs in |
| `bab job history / output` | Your finished jobs and their output |
| `bab config show` | Every setting and where it came from |

Every command has `-h`. It comes back in ~3 ms now, so you can afford to ask.

The screenshots below were taken with the original `ab`. We didn't redo them: apart
from the program name, `bab` prints exactly the same bytes. That's the whole point.

<img src=".github/assets/queue.svg" alt="bab queue: your jobs, start estimates and why pending jobs wait">

### Why is my job waiting?

<img src=".github/assets/why.svg" alt="bab why: what a pending job waits for and the change that starts it now">

`bab why JOBID --fix` applies the suggested change after asking. It only touches
your own pending jobs and never lowers the GPU count unless you pass `--fix gpus`.

### What is free?

<img src=".github/assets/free.svg" alt="bab free --nodes: free GPUs, CPUs and memory per node">

### Dev nodes

```bash
bab dev start --gpu 1 --gpu-type a5000  # waits until running, then shows how to log in
bab l                                   # ssh into it (--srun where SSH is blocked)
bab dev stop
```

## Configuration

`bab` is a drop-in replacement. It reads the same config files and environment variables
as `ab`, shares its cluster-name cache, and names dev jobs `ab-dev` too. So
`bab dev status` finds the dev job you started with `ab dev start`, and vice versa.

Slurm tells it which partitions have GPUs, which GPU types exist and which partition is
the default. A config file only fills in the rest, such as your own `bab dev start`
defaults:

```ini
# ~/.config/allegro-buddy/config.ini
[dev]
gpu = 1
gpu-type = a5000
cpus = 8
mem = 32G
time = 04:00:00
```

Values come from, highest first: command-line flags, your user file, a site file
(`$AB_SITE_CONFIG` or `/etc/allegro-buddy/config.ini`), a shipped cluster preset
(`allegro`, `bhlrn4`), then Slurm. The preset follows Slurm's `ClusterName`;
`AB_CLUSTER=none` turns it off. `bab config show` lists every value and its source.

## Is it really identical?

"Byte-identical" is easy to say, so we tested it. A lot. Before `bab` replaced anything,
it had to pass:

- **A differential harness: 846 of 846 scenarios identical** (40 of them on a PTY).
  `bab` and the pinned Python reference (allegro-buddy 2.7 from PyPI with its exact
  click/rich/rich-click versions, renamed to `bab`) ran against the same fake Slurm.
  Compared: stdout and stderr (bytes, ANSI included), exit code, files written and Slurm
  calls (mutating ones in order). Covered: every `-h`, parsing errors, colours, widths,
  themes, `why --fix` prompts (yes, no, EOF), dev start/login/stop, `--watch` with
  Ctrl-C, completion, config layers, and job names full of Rich markup, emoji and wide
  characters.
- **Replay parity: 532 of 532 cases identical** on real Allegro Slurm answers (Slurm
  24.11.5), recorded read-only, anonymised and replayed: every recorded command ×
  `COLUMNS` 80/160/200 × plain/`FORCE_COLOR`.
- Component checks against the reference: 538 CLI parsing/help cases vs click and
  rich-click, 85 rendering cases vs Rich, and live spot checks on the cluster.

That harness (and the benchmark data) was heavier than the tool, so it now lives at the
git tag [`equivalence-harness`](https://github.com/plainerman/better-allegro-buddy/tree/equivalence-harness), with instructions to rerun it. The branch keeps
a small test suite in the spirit of the original: unit tests and the original's 23
whole-command snapshots (`tests/snapshots/`, byte-exact reference output) against a tiny
fake Slurm.

That includes the quirks. `bab --version` says `2.7`, not `2.7.0`. A job named
`[bold]x[/bold]` renders bold, because Rich would. Deliberate differences, all where the
original falls over: inputs that crash it with a Python traceback are rejected cleanly
(`q -w nan` is a usage error), and `bab` ignores `UNICODE_VERSION` (Rich would switch to
an older character-width table).

## Performance

Live on Allegro (login node, Slurm 24.11.5, 194 jobs, 93 nodes, 10 runs each, mean
wall time):

| command | `ab` | `bab` | speedup |
| --- | ---: | ---: | ---: |
| `--version` | 146 ms | 1.5 ms | **98×** |
| `-h` | 161 ms | 3.5 ms | **46×** |
| `q` | 148 ms | 16 ms | **9.3×** |
| `q --all` | 571 ms | 181 ms | **3.2×** |
| `free` | 230 ms | 67 ms | **3.4×** |
| `info` | 255 ms | 88 ms | **2.9×** |
| `why` | 361 ms | 209 ms | **1.7×** |

Median over 13 commands: **3.4×** (geometric mean 5.7×); every call saves 130–390 ms.
Against an instant fake Slurm (pure tool overhead) the median is **19×**: `ab` needs
85–222 ms per command, `bab` 0.6–15 ms.

<p align="center">
  <img src="https://raw.githubusercontent.com/plainerman/better-allegro-buddy/main/bench/plots/live.png" alt="bab vs ab, live on Allegro: wall time per command" width="600">
</p>

Where it comes from: no interpreter start-up and imports (~145 ms of rich, rich-click
and click on Allegro's login node), parsing only the 28 job fields it actually reads,
and running independent read-only Slurm queries side by side.

Where it stops, honestly:

- **Slurm is the floor.** Rust doesn't make slurmctld answer any faster. `why` has to
  wait ~140 ms for `scontrol --json show job` and then ~50 ms for the nodes. The second
  call depends on the first one's result, and running both at once would change which
  calls happen when things fail (the harness checked that too). So `why` "only" gets 1.7×.
- These numbers come from a quiet evening. Under daytime load Slurm takes longer; the
  absolute savings stay, but the ratios of Slurm-bound commands shrink.
- At ~0.2 s saved per call, the rewrite pays for itself after a few million `bab q`s.
  We're working on it.

Full tables, methodology, local replay numbers and the optimisation pass:
[`bench/RESULTS.md`](https://github.com/plainerman/better-allegro-buddy/blob/main/bench/RESULTS.md). Raw data and scripts: tag
[`equivalence-harness`](https://github.com/plainerman/better-allegro-buddy/tree/equivalence-harness/bench).

## Development

Stable Rust ≥ 1.88 (edition 2024).

```bash
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
```

`cargo test` builds `bab` with the `test-hooks` feature (frozen clock, groups and host
name via `BAB_TEST_*` variables) for the snapshot test; a normal build never reads them,
ship that one. `UPDATE_SNAPSHOTS=1 cargo test --test snapshots` rewrites
`tests/snapshots/`. The full differential harness: tag
[`equivalence-harness`](https://github.com/plainerman/better-allegro-buddy/tree/equivalence-harness).

### Releasing

[`release.yml`](https://github.com/plainerman/better-allegro-buddy/blob/main/.github/workflows/release.yml)
builds the `bab` binaries (manylinux2014 x86_64/aarch64, i.e. glibc ≥ 2.17; macOS
x86_64/arm64) as wheels with [maturin](https://www.maturin.rs) (`pyproject.toml`) and as
`bab-$(uname -m)-$(uname -s).tar.gz`, plus the sdist. It smoke-tests all of them on every
push to `main` that touches the code. A `v*` tag also creates the GitHub release (the
Install one-liner downloads from the latest one) and, once enabled, uploads to PyPI.

1. Bump `version` in `Cargo.toml` (and `VERSION_DISPLAY` in `src/lib.rs`, which is what
   `bab --version` prints), run `cargo check` to update `Cargo.lock`, merge into `main`.
2. `git tag vX.Y.Z && git push origin vX.Y.Z`. The tag must equal the `Cargo.toml`
   version. The workflow builds and checks everything, creates the release with all
   files and `SHA256SUMS`, and installs the release binaries with the one-liner on Linux
   and macOS runners.

PyPI, one-time setup (until then tags only create GitHub releases):

1. On PyPI: *Your account → Publishing → Add a new pending publisher* (GitHub):
   project `better-allegro-buddy`, owner `plainerman`, repository
   `better-allegro-buddy`, workflow `release.yml`, environment `pypi`.
2. On GitHub: *Settings → Environments → New environment* `pypi` (optionally with
   required reviewers), and *Settings → Secrets and variables → Actions → Variables*:
   `PYPI_PUBLISH` = `true`.
3. To publish a tag that was released before: *Actions → Release →* its run *→ Re-run all
   jobs* (the GitHub release stays as it is), or just publish with the next tag.

Locally: `uvx maturin build --release` (wheel for this machine), `uvx maturin sdist`.

## Credits and license

All the ideas, the UX and every word `bab` prints come from
[allegro-buddy](https://github.com/Grutschus/allegro-buddy) by
[Grutschus](https://github.com/Grutschus). This repository only made it rustier. If you
like `bab`, star the original. If you'd rather keep Python, use the original:
`uv tool install allegro-buddy`.

MIT, see [LICENSE](LICENSE). Copyright © 2026 Grutschus (allegro-buddy) and
© 2026 Michael Plainer (the Rust rewrite).
