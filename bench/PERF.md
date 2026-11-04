# Performance pass (branch `rust-perf`)

Goal: make `bab` faster where it pays off in lines changed vs. time saved, without
giving up byte-identical output or the Slurm call multiset (compat 846/846, replay
parity 532/532 after every change).

## How it was measured

* **Data**: the anonymised Allegro recordings (`data/allegro/snapshot`, 225 jobs,
  `scontrol --json show job` = 2.4 MB, `show nodes` = 236 KB; `as-user-a` for a user
  with pending jobs), served by the replay fake (`replay/fake`).
* **Wall time**: `replay/bench.py` (hyperfine; `--rounds` interleaved, rotated rounds of
  `--runs`; median), release builds with `--features test-hooks` (frozen clock/groups:
  the hooks cost ~2k instructions, 0.3 % of `bab --version`), `--cpus 4-7` (taskset).
  fox runs the `powersave` governor (0.8–3.5 GHz), so unpinned medians of the same
  binary moved by up to 2x between rounds; pinned, A/A runs agree within ~5 %
  (no-delay) / ~5 ms (realtime). Smaller differences below are noise.
* **Two Slurm models**: *no delay* (each fake call ≈ 1 ms of `sh` + `cat`: shows
  bab's own CPU time) and `--realtime` (each call sleeps as long as it took on Allegro
  when recorded, plus ~3 ms of `sleep`/`sh` overhead — the end-to-end view).
* **Instructions**: `valgrind --tool=callgrind` (deterministic; `perf` is not
  installed, `strace` is blocked by ptrace restrictions) and a symbolised build
  (`CARGO_PROFILE_RELEASE_STRIP=false CARGO_PROFILE_RELEASE_DEBUG=line-tables-only`)
  for profiles.

Recorded Allegro latencies (median of the recording, slurmctld round trip included):

| call | ms |
|---|---:|
| `scontrol --json show job` (all) | 138 |
| `scontrol --json show nodes` | 50 |
| `scontrol --oneliner --details show job` (all) | 38 |
| `squeue` (all / one user) | 21 / 17 |
| `sacctmgr show user`, `sacct`, `scontrol show config` | 13–17 |
| `scontrol --json show job ID`, `… --details show job ID` | 18 / 13 |
| `scontrol --oneliner show partition` / `reservation` | 11 / 11 |

So outside `-h`, Slurm dominates: bab's own CPU time was 1–30 ms of 25–260 ms.

## Changes

| commit | what | LOC (+/−, w/o tests) | effect |
|---|---|---:|---|
| `bench: replay benchmark runner…`, `bench: replay the recorded Slurm latencies` | `replay/bench.py`, `REPLAY_DELAY_MS`/`REPLAY_REALTIME` in the fake, durations in `build.py` | +162 / −2 (bench only) | — |
| `perf: ASCII twins of the \w/\d highlight regexes` | `render::highlight::LazyRegex`: on ASCII text use an ASCII spelling of `\w`/`\W`/`\d` (identical matches there; tests compare every pattern); the Unicode original only for non-ASCII text | +113 / −41 (+51 tests) | `bab -h`: 31.3M → 4.3M instructions, 7.8 → 2.2 ms; every `CMD -h` and usage-error panel likewise |
| `perf: parse only the job-record keys bab reads` | `core::jobs::job_records_json`: a serde visitor (`serde_core`, already a dependency of serde_json) keeps the 28 `JOB_KEYS` of each job and skips ~100 others; odd shapes fall back to the full parse; a test scans fit.rs/why.rs for keys read | +105 / −15 (+59 tests) | `why` 135.7M → 76.1M instr., 26.5 → 14.2 ms (realtime 257 → 243 ms); `q --all` 180M → 113M, 30.7 → 15.4 ms (realtime 226 → 202 ms); `queue` with pending jobs (as-user-a) 30.1 → 13.1 ms (realtime 228 → 210 ms) |
| `perf: free runs the reservation and partition queries side by side` | the reservation query is unchecked and nothing between it and the partition query can fail, so Python always makes both once the node query succeeded: same call multiset in every world | +6 / −2 | `free` realtime 110 → 95 ms, `free --nodes` 106 → 92 ms |

## Tried or considered, and rejected

| idea | result | why not |
|---|---|---|
| More concurrent Slurm calls (`info`, `why`, `node`, …) | the remaining sequential pairs are gated: a checked call that dies (`down` worlds), the `scontrol --oneliner show node` fallback after bad node JSON, `unknown node` before the job query, bad job JSON (exit 2) before the node query | Starting the later call early adds it to the call log in failure worlds (the fake logs on invocation; a killed call is still a call): breaks compat. `free` was the only unconditional pair left (done above); `config show`, `q` hints, `info`'s sacctmgr+squeue, per-job `scontrol` were already concurrent |
| mimalloc as global allocator | `q --all` −30 %, `why` −20 % wall | +0.6–1 ms startup on *every* command (`--version` 0.6 → 1.2 ms), +4 MB RSS, a C dependency; the JSON change took most of the allocation churn anyway |
| `Record::with_capacity` in `parse_prop_line` (no rehash) | `node` 72.3M → 67.8M instr. (−6 %), `info`/`free` +0.7 % | ≈ 0.5 ms of a 139 ms command |
| Reduced parse of `scontrol --json show nodes` (same visitor) | estimate −5M instr. (~1.5 ms) in info/free/why/node/config | < 2 % of their 80–140 ms; would need the visitor generalised |
| ASCII twins for the `regex`-crate patterns (`GPU_RESOURCE_CHUNK`, `GRES_GPU`, `MEM_TOKEN`) | ~1.1–1.4M instr. (0.3 ms) each, compiled once per run | needs `LazyRegex` generic over two regex types and 7 call sites for < 3 % |
| Faster replay fake (compiled, no `sh`) | the fake costs ~1 ms/call, identical for ab and bab | callgrind isolates bab exactly; not worth a binary in bench/ |
| Process spawning | `std::process::Command` with only stdio set takes std's `posix_spawn` path (vfork-like); 64 KiB pipe reads; startup is 0.6 ms / 0.58M instr. | nothing left to gain |
| `-C target-cpu=native` | — | not portable (the binary is copied to the cluster) |

## Per command, before → after this pass

Allegro snapshot, `bench.py --cpus 4-7`, medians; `ab` = Python allegro-buddy 2.7 on
the same replay (realtime run).

| command | instr. (M) | no delay (ms) | realtime (ms) | ab realtime (ms) |
|---|---:|---:|---:|---:|
| `--version` | 0.6 → 0.6 | 0.61 → 0.66 | 0.54 → 0.55 | 110 |
| `-h` | 31.3 → 4.3 | 7.84 → 2.24 | 6.21 → 2.33 | 121 |
| `info` | 22.3 → 22.5 | 7.52 → 7.58 | 139 → 137 | 315 |
| `free` | 22.9 → 23.2 | 6.18 → 5.42 | 110 → 95 | 247 |
| `free --nodes` | 29.2 → 29.6 | 7.43 → 6.64 | 106 → 92 | 277 |
| `queue` | 1.1 → 1.1 | 1.10 → 1.11 | 27 → 27 | 144 |
| `q --all` | 180.2 → 112.8 | 30.74 → 15.40 | 226 → 202 | 568 |
| `why` | 135.7 → 76.1 | 26.48 → 14.16 | 257 → 243 | 399 |
| `why <pending>` | 21.2 → 21.2 | 6.91 → 6.66 | 108 → 109 | 246 |
| `node gpu062` | 72.3 → 72.5 | 11.11 → 10.84 | 134 → 140 | 276 |
| `job history` | 1.1 → 1.1 | 1.16 → 1.15 | 23 → 23 | 138 |
| `config show` | 19.1 → 19.4 | 4.22 → 4.25 | 79 → 80 | 234 |

as-user-a (a user with pending jobs, realtime): `queue` 228 → 210 ms (ab 471), `why`
265 → 245 ms (ab 409), `free` 107 → 92 ms (ab 252).

Reproduce:

```sh
cargo build --release --features test-hooks
python3 bench/replay/bench.py --cpus 4-7 --bin bab=target/release/bab [--bin old=...] \
    [--realtime] [--ref] [--data bench/data/allegro/as-user-a]
```
