# bench: real-cluster recordings, replay and parity

Tools to record what a real Slurm cluster answers, replay it deterministically to both
implementations, and compare the Python reference (`allegro-buddy` 2.7) with `bab` live.

| path | what |
|---|---|
| `live/rec_shim.py` | recording shim (symlinked as `squeue scontrol sinfo sacct sacctmgr`): runs `/usr/bin/<name>`, logs argv/stdout/stderr/exit as JSONL; refuses anything but read-only verbs |
| `live/record.py` | runs the reference once per command of `live/commands.txt` (or `commands-user.txt` with `--as-user`) through the shims: `calls.jsonl`, `runs.jsonl`, `meta.json` |
| `live/live_parity.py` | reference vs `bab` back to back on the live cluster (COLUMNS=160, real clock/groups); a differing pair is rerun once |
| `live/nss_check.sh` | `bab`'s groups (`examples/nss_groups`) vs Python's `current_groups()` vs `id -Gn` |
| `live/anonymise.py` | consistent pseudonyms for users, groups, accounts, job names, paths, uids, emails; proves no real name is left |
| `replay/fake` | the replay fake Slurm: POSIX sh, looks the exact argv up in a generated `case` table and `cat`s the recorded output; unknown argv: exit 1 and `MISS` in `$REPLAY_LOG`; `REPLAY_REALTIME=1` sleeps the recorded duration of the call, `REPLAY_DELAY_MS=N` N ms |
| `replay/build.py` | dataset -> replay tree (`bin/`, `runs/<id>/`, `common/` fallback, `runs.json`) |
| `replay/bench.py` | wall-time benchmark (hyperfine) of read-only commands on the replay, any number of `bab` builds and `--ref`; `--realtime` replays the recorded Slurm latencies; results of the performance pass in `PERF.md` |
| `replay/make_ab_venv.sh`, `replay/ab_bench_hooks.py` | the benchmark reference: a uv venv with allegro-buddy 2.7 timed through its own console script `venv/bin/ab`; a `.pth` line installs the `BAB_TEST_*` hooks only when `BAB_TEST_NOW` is set |
| `run_local.sh` | the final local comparison (no delay, realtime, cold cache, a user with pending jobs, hook overhead) -> `results/local/` |
| `live/bench_live.sh` | the live comparison, run on the cluster in one ssh session (read-only allowlist, 10 runs + 1 warmup per command and tool) -> `results/live/<run>/` |
| `plot.py` | `uv run bench/plot.py`: `plots/*.{svg,png}` and the tables of `RESULTS.md` |
| `RESULTS.md` | **the final numbers** (live on Allegro and local), methodology, plots |
| `replay/parity.py` | every recorded command x COLUMNS 80/160/200 x (plain, `FORCE_COLOR=1`) + one cold-cache run: stdout, stderr, exit and the multiset of Slurm calls |
| `data/allegro/` | anonymised recordings of Allegro (Slurm 24.11.5, 2026-11-04): `snapshot` (52 commands), `as-user-a`/`as-user-b` (12 user-centric commands as a user with pending/array jobs); `runs.jsonl` holds the reference output on the anonymised replay |

## Replay parity (deterministic, local)

```sh
cargo build --release --features test-hooks          # replay needs the BAB_TEST_* hooks
uv sync --project compat                             # the reference (allegro-buddy 2.7)
for d in bench/data/allegro/*/; do
  python3 bench/replay/parity.py --data "$d" --bin target/release/bab
done
```

Per case: `PATH=<replay>/bin:/usr/bin:/bin`, fresh HOME/XDG dirs, `USER`/`LOGNAME`, `TZ`,
`BAB_TEST_NOW` (the second the command was recorded), `BAB_TEST_GROUPS` (the recorded
`id -Gn`) and `BAB_TEST_HOSTNAME` from `meta.json`. `--groups`, `--tz` and `--now-shift`
replay the same world under other groups, time zones and clocks. Diffs land in
`bench/replay/.work/diffs/`.

For a benchmark use `replay/bench.py` (see `PERF.md`), or point `PATH` at `<replay>/bin`
and set `REPLAY_RUN=<replay>/runs/<id>`, `REPLAY_COMMON=<replay>/common` (see
`parity.py:run_case`).

## Recording / live parity (on the cluster, read-only)

Only read-only commands (see the allowlist in `live/commands.txt`); never `dev
start/stop/login`, `l`, `--watch`, `completion --install`, `why --fix`. The reference
lives in a private venv, never `/usr/bin/ab` (Apache Bench).

```sh
B=~/.local/share/bab-bench
python3 -m venv $B/venv && $B/venv/bin/pip install allegro-buddy==2.7 click==8.3.2 \
    rich==15.0.0 rich-click==1.9.9 markdown-it-py==4.0.0 pygments==2.20.0
rsync -a bench/live/ cluster:$B/live/; rsync -a compat/reference.py cluster:$B/ref/
cargo build --release --bin bab                      # NO test-hooks for the cluster
cargo build --release --example nss_groups
rsync -a target/release/bab target/release/examples/nss_groups cluster:$B/bin/
# on the cluster, in $B:
python3 live/record.py --ref venv/bin/allegro-buddy --out rec/allegro-$(date +%Y%m%dT%H%M%S)
python3 live/record.py --ref venv/bin/allegro-buddy --as-user SOMEONE \
    --commands live/commands-user.txt --out rec/allegro-$(date +%Y%m%dT%H%M%S)-as-SOMEONE
python3 live/live_parity.py --ref-python venv/bin/python --reference ref/reference.py \
    --bab bin/bab --out live-out/live.jsonl
sh live/nss_check.sh venv/bin/python bin/nss_groups
```

Raw recordings contain other users' names, jobs and paths: keep them out of git
(a private directory outside the repo), commit only `anonymise.py` output:

```sh
python3 bench/live/anonymise.py bench/data/allegro snapshot=RAW1 as-user-a=RAW2 as-user-b=RAW3
```
