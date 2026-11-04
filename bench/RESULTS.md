# ab vs bab: performance

Python `allegro-buddy` 2.7 (`ab`) vs its byte-identical Rust rewrite `bab`, every
read-only command. The live numbers, the README plots and this file's live table come from
`bench/live.sh` (run on the cluster), summarised into `bench/results/live.json` and
plotted by `bench/plot.py`; see [Updating the numbers](#updating-the-numbers). The local
replay (anonymised Allegro recordings, replay fake, raw hyperfine exports) is kept at the
git tag
[`equivalence-harness`](https://github.com/plainerman/better-allegro-buddy/tree/equivalence-harness/bench).

## Summary

- **Live on Allegro** (2026-11-04, 20:28 CET, Slurm 24.11.5, 194 jobs, 93 nodes,
  10 runs + 1 warmup each): `bab` is **3.4× faster** (median over 13 commands;
  geometric mean 5.7×). Every call saves **130–390 ms**. Slurm-bound commands: 1.7×
  (`why`) to 11.2× (`job history`). Pure start-up: `--version` 146 → 1.5 ms (98×).
  All 12 read-only commands once each: `ab` **2.96 s**, `bab` **0.88 s** (the README
  header chart). A second pass 11 minutes later agreed within 4 % on most ratios.
- **Local, instant fake Slurm** (pure tool overhead, 30 runs per command): median
  **19×**, from 8.7× (`why`) to 154× (`--version`); `ab` needs 85–222 ms per command,
  `bab` 0.6–15 ms. Peak RSS `ab` 23–32 MiB, `bab` 3.6–10 MiB.
- **Local, replayed Slurm latencies** (each fake call sleeps as long as it took on
  Allegro): median **2.7×** (1.5× `why` … 151× `--version`).

![bab vs ab, live on Allegro](plots/live.png)

## Live on Allegro

Login node (2× Xeon E5-2690 v4), quiet evening. `ab` = console script of a private venv
(Python 3.13.5, allegro-buddy 2.7, click 8.3.2, rich 15.0.0, rich-click 1.9.9); `bab` =
release build without test hooks. Real clock, groups and host, no user config,
`COLUMNS=160`, output to /dev/null, hyperfine `-N`. Speedup = mean(ab) / mean(bab).

| command | ab mean ± σ (ms) | bab mean ± σ (ms) | speedup |
|---|---:|---:|---:|
| `--version` | 145.6 ± 1.8 | 1.48 ± 0.20 | **98.3×** |
| `-h` | 160.6 ± 3.2 | 3.50 ± 0.32 | **45.9×** |
| `info` | 254.6 ± 4.4 | 88.06 ± 4.48 | **2.9×** |
| `info` (cold cache) | 275.3 ± 10.3 | 104.77 ± 4.04 | **2.6×** |
| `free` | 230.0 ± 8.9 | 66.77 ± 1.81 | **3.4×** |
| `free --nodes` | 267.2 ± 10.1 | 68.95 ± 2.15 | **3.9×** |
| `q` | 148.1 ± 3.0 | 15.91 ± 1.06 | **9.3×** |
| `q --all` | 571.0 ± 20.6 | 180.55 ± 4.40 | **3.2×** |
| `why` | 361.1 ± 8.3 | 208.74 ± 1.81 | **1.7×** |
| `why <pending job>` | 215.9 ± 4.5 | 78.95 ± 3.82 | **2.7×** |
| `node gpu062` | 255.6 ± 13.2 | 102.32 ± 4.91 | **2.5×** |
| `job history` | 145.6 ± 2.2 | 12.99 ± 0.78 | **11.2×** |
| `config show` | 208.5 ± 3.1 | 55.17 ± 2.23 | **3.8×** |

## Local replay

Workstation (Xeon W-1250P, `powersave` governor, both tools pinned to CPUs 4–7), the
anonymised Allegro snapshot (225 jobs, `scontrol --json show job` = 2.4 MB), served by a
`sh` + `cat` fake Slurm (~1 ms per call for both tools). 5 interleaved rounds × 6 runs.

| command | ab, no delay (ms) | bab, no delay (ms) | speedup | ab, realtime (ms) | bab, realtime (ms) | speedup |
|---|---:|---:|---:|---:|---:|---:|
| `--version` | 91.9 | 0.60 | 154× | 91.1 | 0.60 | 151× |
| `-h` | 102.6 | 1.60 | 64× | 102.2 | 1.61 | 64× |
| `info` | 100.4 | 7.40 | 13.6× | 287.3 | 134.5 | 2.1× |
| `free` | 97.2 | 5.07 | 19.2× | 217.8 | 90.7 | 2.4× |
| `q` | 84.6 | 1.12 | 75× | 112.7 | 26.0 | 4.3× |
| `q --all` | 221.9 | 15.4 | 14.4× | 524.0 | 195.9 | 2.7× |
| `why` | 113.2 | 13.0 | 8.7× | 378.2 | 249.6 | 1.5× |
| `node gpu062` | 113.8 | 11.6 | 9.8× | 242.7 | 131.4 | 1.8× |
| `job history` | 85.0 | 1.13 | 75× | 107.1 | 21.4 | 5.0× |
| `config show` | 96.6 | 4.35 | 22× | 207.1 | 77.9 | 2.7× |

## Where the speedup comes from, and where it stops

1. **No interpreter start-up and imports.** `ab --version` is 91 ms locally (`import
   allegro_buddy.cli` alone 79 ms: click, rich, rich-click), ~145 ms on Allegro's login
   node; `bab --version` 0.6 ms.
2. **Parsing and rendering.** `q --all` (2.4 MB of job JSON, a 225-row table): `ab`
   ~130 ms of own work, `bab` 15 ms. `bab` decodes only the 28 job keys it reads.
3. **Independent read-only Slurm queries side by side**, only where `ab` makes both
   calls anyway (`free`, `config show`, the `q` hints, `info`'s sacctmgr + squeue), so
   the set of Slurm calls is identical.
4. **The floor is Slurm.** `why` must wait for `scontrol --json show job` (~140 ms live)
   and then `show nodes` (~50 ms); the second call depends on the first one's result,
   so it "only" gets 1.7×. Under daytime load the absolute savings stay, the ratios of
   Slurm-bound commands shrink.

## Performance pass

Measured with callgrind (instructions) and pinned hyperfine on the replay; output and
Slurm calls verified unchanged after every change (compat 846/846, replay 532/532).

| change | effect |
|---|---|
| ASCII twins of the `\w`/`\d` highlight regexes (Unicode originals only for non-ASCII text) | `bab -h`: 31.3M → 4.3M instructions, 7.8 → 2.2 ms; every help and usage-error panel likewise |
| Parse only the 28 job-record keys bab reads (a serde visitor; odd shapes fall back to the full parse) | `why` 26.5 → 14.2 ms, `q --all` 30.7 → 15.4 ms of own work |
| `free` runs the reservation and partition queries side by side | `free` realtime 110 → 95 ms |

Tried and rejected: more concurrent Slurm calls (would change the calls made when an
earlier one fails), mimalloc (+0.6 ms start-up on every command), smaller wins under
2 % (pre-sized records, a reduced node-JSON parse), `-C target-cpu=native` (not
portable).

## Methodology notes

- Same output: the measured builds pass replay parity 532/532 (every recorded command ×
  `COLUMNS` 80/160/200 × plain/`FORCE_COLOR`; stdout, stderr, exit code, Slurm calls).
- hyperfine `-N` runs `venv/bin/ab` and `bab` directly (no shell, no `uv run`). The
  replay freezes clock, groups and host name for both tools (`BAB_TEST_*` hooks for
  `bab`, an equivalent patch for `ab`); measured cost within noise. Live runs use no hooks.
- Peak RSS live includes the Slurm clients (`scontrol --json` ~50 MiB for both tools);
  the local numbers are the tools' own.
- Python differs between hosts (3.12.11 locally, 3.13.5 on Allegro); comparisons are
  always within one host.

## Updating the numbers

Live, on the cluster (≈ 2 minutes, read-only commands only):

```sh
# once: the reference in a private venv (never /usr/bin/ab, that is Apache Bench)
B=.local/share/bab-bench
ssh allegro "python3 -m venv $B/venv && $B/venv/bin/pip install allegro-buddy==2.7 \
    click==8.3.2 rich==15.0.0 rich-click==1.9.9 markdown-it-py==4.0.0 pygments==2.20.0 \
    && mkdir -p $B/bin"
scp "$(command -v hyperfine)" allegro:$B/bin/

# each time: a release build WITHOUT test hooks (glibc no newer than the cluster's,
# e.g. built on the cluster or a release binary), then the run
cargo build --release
scp target/release/bab bench/live.sh allegro:$B/bin/
ssh allegro "cd $B && timeout 900 sh bin/live.sh out/live-\$(date +%Y%m%dT%H%M%S)"
mkdir -p bench/.work && scp -r allegro:$B/out/live-<stamp> bench/.work/
uv run bench/plot.py --run bench/.work/live-<stamp>
```

`plot.py --run` rewrites `bench/results/live.json` (per command and tool: n, mean, σ, min
in ms, plus the run's `env.txt`), redraws `bench/plots/live.png` and
`bench/plots/hero-{light,dark}.svg`, and prints the live table and the summary numbers
(median speedup, total of all read-only commands) for this file and the README.
`uv run bench/plot.py` alone redraws the plots from the committed summary. Commit
`live.json` and the plots, not the raw run (`bench/.work/` is ignored); update the numbers
quoted above and in the README (header chart alt text, intro, the `-h` time under
Commands, Performance). The local replay numbers do not come from this run (see the
`equivalence-harness` tag).
