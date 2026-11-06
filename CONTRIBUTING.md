# Contributing

allegro-buddy is a Rust port of the Python allegro-buddy 2.7 (commit `91689b9`) that
must behave exactly like it. Notes for coding agents (conventions, cluster rules):
[`AGENTS.md`](AGENTS.md).

## Development

Stable Rust ≥ 1.88 (edition 2024).

```bash
cargo fmt --all --check
cargo clippy --all-targets --locked -- -D warnings
cargo test --locked
cargo build --release --locked
```

The program is `ab`; `allegro-buddy`, `bab` and `better-allegro-buddy` are the same
binary under other names (`Cargo.toml`), and it calls itself by the name it was started
as, like click does. `cargo test` builds it with the `test-hooks` feature (frozen clock,
groups and host name via `BAB_TEST_*` variables) for the snapshot test; a normal build
never reads them, ship that one. `tests/snapshots/` holds output of the Python reference;
`UPDATE_SNAPSHOTS=1 cargo test --test snapshots` rewrites it.

## Compatibility with 2.7

Everything observable is meant to be identical to allegro-buddy 2.7: stdout and stderr
(bytes, ANSI included), exit codes, files written and the Slurm calls that change
something (in order). Read-only Slurm queries may be cheaper ones carrying the same
information (`src/core/fast.rs`). How that was checked: a differential harness against
the pinned Python reference (846 scenarios, all identical but the 4 `--version` ones) and
a replay of recorded Allegro answers (532 cases), both run while the port was written;
the snapshot tests in `tests/snapshots/` keep checking it. Benchmarks:
[`bench/RESULTS.md`](bench/RESULTS.md).

Deliberate differences, all where 2.7 falls over or for speed:

- `--version` prints the package version (`ab, version 0.2.0`).
- Inputs that crash 2.7 with a Python traceback are rejected cleanly (`q -w nan` is a
  usage error).
- `UNICODE_VERSION` is ignored (Rich would switch to an older character-width table).
- Next to the cluster-name cache it keeps one more file, `slurm-version.<host>` (which
  Slurm the cheaper queries were checked for).

## Releasing

[`release.yml`](.github/workflows/release.yml) builds the binaries (manylinux2014
x86_64/aarch64, i.e. glibc ≥ 2.17; macOS x86_64/arm64) as wheels with
[maturin](https://www.maturin.rs) (`pyproject.toml`) and as
`allegro-buddy-$(uname -m)-$(uname -s).tar.gz` (`ab` plus its aliases as symlinks), plus
the sdist. It smoke-tests all of them on every push to `main` that touches the code. A
`v*` tag also creates the GitHub release (the README one-liner downloads from the latest
one) and, once enabled, uploads to PyPI.

1. Bump `version` in `Cargo.toml` (`ab --version` prints it), run `cargo check` to
   update `Cargo.lock`, merge into `main`.
2. `git tag vX.Y.Z && git push origin vX.Y.Z`. The tag must equal the `Cargo.toml`
   version. The workflow builds and checks everything, creates the release with all
   files and `SHA256SUMS`, and installs the release binaries with the README one-liner
   on Linux and macOS runners.

PyPI, one-time setup (until then tags only create GitHub releases):

1. On PyPI, project `allegro-buddy`: *Manage → Publishing → Add a new publisher*
   (GitHub): owner `Grutschus`, repository `allegro-buddy`, workflow `release.yml`,
   environment `pypi`.
2. On GitHub: *Settings → Environments* `pypi` (optionally with required reviewers),
   and *Settings → Secrets and variables → Actions → Variables*: `PYPI_PUBLISH` =
   `true`.
3. To publish a tag that was released before: *Actions → Release →* its run *→ Re-run
   all jobs* (the GitHub release stays as it is), or just publish with the next tag.

Locally: `uvx maturin build --release` (wheel for this machine), `uvx maturin sdist`.
