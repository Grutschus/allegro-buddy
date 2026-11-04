---
name: verify-equivalence
description: Check that bab still behaves exactly like the Python reference allegro-buddy 2.7, using the differential harness and real-cluster replay at the git tag equivalence-harness. Use after changing output, argument parsing, settings, Slurm calls or performance-sensitive code, before benchmarking, or when adding new Slurm query forms or scenarios.
---

# Verifying equivalence with the Python reference

`cargo test` covers a few whole-command snapshots. The full proof lives at the git tag
`equivalence-harness` (removed from the branch to keep it small). Its message says what
it contains and how to run it: `git tag -n99 equivalence-harness`. Details:
`compat/README.md` and `bench/README.md` at the tag.

## Run it against the current code

The harness stays at the tag; the binary under test comes from your branch.

```sh
# in your branch worktree: the binary with the BAB_TEST_* hooks the harness needs
cargo build --release --locked --features test-hooks
BIN=$(realpath "${CARGO_TARGET_DIR:-target}/release/bab")

# once: the harness in its own worktree, next to (not inside) yours
git worktree add --detach ../bab-eq equivalence-harness
cd ../bab-eq
uv run --project compat compat/run.py check --bin "$BIN"         # vs committed goldens
uv run --project compat compat/run.py diff --bin "$BIN" -k why   # vs the live reference
for d in bench/data/allegro/*/; do                                # real-cluster replay
  uv run --project compat python3 bench/replay/parity.py --data "$d" --bin "$BIN"
done
```

- Expected: every scenario and case passes (totals in the tag message). A failure
  prints a unified diff (ANSI as `\x1b`) and the differing Slurm calls.
- `-k REGEX` selects scenarios; `compat/run.py list` shows them.
- `diff` and the replay run the Python reference from `compat/.venv`. If
  `UV_PROJECT_ENVIRONMENT` is set in your shell, prefix the `uv run` commands with
  `env -u UV_PROJECT_ENVIRONMENT`: otherwise uv syncs the harness into that other venv
  and the reference is not found (`exec: uv: not found`).
- A binary without `--features test-hooks` fails most scenarios: build it as above.

## When behaviour or Slurm calls change

- The reference decides. Read the Python code (`AGENTS.md`, "The invariant") and match
  it; never "fix" a golden or snapshot by regenerating it from `bab`.
- Both fake Slurms fail closed: an unexpected call is logged and exits 1. Mutating
  calls must be the same sequence as Python's. Read-only differences are expected only
  where bab asks cheaper forms (`src/core/fast.rs`: `scontrol --version`,
  `scontrol --oneliner --details show node`, `squeue --json --state=PD [--user=U]`,
  `squeue -h --user=U --format=%i|%T|%S|%e`) or
  prefetches; the harness's fake must answer those forms from the same world.
- New query form or code path that Python also has: add a scenario to
  `compat/scenarios.py` (and a world in `compat/worlds.py` if needed) in the tag
  worktree, `compat/run.py golden -k <name>` writes its golden from the reference, then
  `check`. For the branch's own tests, add a fixture line to `tests/fake-slurm/index`
  and a case to `tests/snapshots.rs`, with the expected output taken from the reference.
- The tag is a fixed record: commit harness extensions on a new branch from it, and ask
  the maintainer before moving the tag.
