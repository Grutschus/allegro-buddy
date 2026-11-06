---
name: verify-equivalence
description: Check that ab still behaves exactly like the Python reference allegro-buddy 2.7, using the differential harness and real-cluster replay at the git tag equivalence-harness-3. Use after changing output, argument parsing, settings, Slurm calls or performance-sensitive code, before benchmarking, or when adding new Slurm query forms or scenarios.
---

# Verifying equivalence with the Python reference

`cargo test` covers a few whole-command snapshots. The full proof lives at the git tag
`equivalence-harness-3` (removed from the branch to keep it small; it is the original
`equivalence-harness` plus a fake Slurm and call comparison that know the port's cheaper
queries, -2 and -3 each adding forms). The tags live in the fork the port was written
in: `git fetch https://github.com/plainerman/better-allegro-buddy 'refs/tags/equivalence-harness*:refs/tags/equivalence-harness*'`. Its message says what it contains and how to run
it: `git tag -n99 equivalence-harness-3`. Details: `compat/README.md` and `bench/README.md`
at the tag.

## Run it against the current code

The harness stays at the tag; the binary under test comes from your branch. The tag's
scenarios call the program `bab` and its reference renames Python's `CLI_NAME` to `bab`;
since the program says `ab` again (in hints; usage lines follow argv[0]), drop that
renaming once and regenerate the goldens from the reference, then test the `bab` alias.

```sh
# in your branch worktree: the binary with the BAB_TEST_* hooks the harness needs
cargo build --release --locked --features test-hooks
BIN=$(realpath "${CARGO_TARGET_DIR:-target}/release/bab")   # the alias, as the scenarios call it

# once: the harness in its own worktree, next to (not inside) yours
git worktree add --detach ../bab-eq equivalence-harness-3
cd ../bab-eq
# once: no renaming (SUBSTITUTIONS = [], drop the audit() call in build()), new goldens
$EDITOR compat/reference.py
uv run --project compat compat/run.py golden
uv run --project compat compat/run.py check --bin "$BIN"         # vs those goldens
uv run --project compat compat/run.py check --bin compat/ref-bab --exact-calls  # self-check
uv run --project compat compat/run.py diff --bin "$BIN" -k why   # vs the live reference
for d in bench/data/allegro/*/; do                                # real-cluster replay
  uv run --project compat python3 bench/replay/parity.py --data "$d" --bin "$BIN"
done
```

- Expected: every scenario passes except the 4 `--version` ones (`bab, version 0.2.0`
  vs 2.7); the replay differs only in its `--version` cases and in read-only calls the
  recording can't answer (`scontrol --version`, after which it asks like Python). A failure
  prints a unified diff (ANSI as `\x1b`) and the differing Slurm calls.
- `-k REGEX` selects scenarios; `compat/run.py list` shows them.
- `diff` and the replay run the Python reference from `compat/.venv`. If
  `UV_PROJECT_ENVIRONMENT` is set in your shell, prefix the `uv run` commands with
  `env -u UV_PROJECT_ENVIRONMENT`: otherwise uv syncs the harness into that other venv
  and the reference is not found (`exec: uv: not found`).
- A binary without `--features test-hooks` fails most scenarios: build it as above.
- With the tag's goldens (recorded on Linux), on macOS (bash 3.2) 13 bash-completion
  scenarios fail for the reference too; goldens regenerated on macOS record that.

## When behaviour or Slurm calls change

- The reference decides. Read the Python code (`AGENTS.md`, "The invariant") and match
  it; never "fix" a golden or snapshot by regenerating it from `bab`.
- Both fake Slurms fail closed: an unexpected call is logged and exits 1. Mutating
  calls must be the same sequence as Python's. Read-only differences are expected only
  where bab asks cheaper forms (`src/core/fast.rs`: `scontrol --version`,
  `scontrol --oneliner --details show node`, `squeue --json --state=PD [--user=U|--jobs=IDS]`,
  `squeue -h -r --user=U --format=%A|%i|%T|%S|%e`,
  `squeue -h --nodelist=NODE --states=R,CG,CF --format=%i` + `scontrol --oneliner
  --details show job ID` per job) or
  prefetches; the harness's fake must answer those forms from the same world. `run.py`
  accepts exactly that (`_readonly_problems`): a query of ab's may be missing only if
  the form standing in for it succeeded, an extra one only if the reference makes it
  for the same subcommand elsewhere; `--exact-calls` turns this off. A new cheaper form
  needs both: an answer in `compat/fake_slurm/fake_slurm.py` and an entry in run.py.
- New query form or code path that Python also has: add a scenario to
  `compat/scenarios.py` (and a world in `compat/worlds.py` if needed) in the tag
  worktree, `compat/run.py golden -k <name>` writes its golden from the reference, then
  `check`. For the branch's own tests, add a fixture line to `tests/fake-slurm/index`
  and a case to `tests/snapshots.rs`, with the expected output taken from the reference.
- The tags are fixed records: commit harness extensions on a detached HEAD or a new
  branch from the newest tag, tag the result anew (`equivalence-harness-4`, ...,
  annotated: what changed, how to run, results), and never move or delete a tag.
