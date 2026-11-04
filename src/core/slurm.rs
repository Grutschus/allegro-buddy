//! Running Slurm (and other) commands. Mirrors `core.run`, `core.exec_replace`,
//! `core.run_parsable_rows`. Owned by P2-C.
//!
//! # Contract
//!
//! * [`run`]`(argv, check)` == Python `run(argv, check=check)` with `capture_output=True,
//!   text=True`: stdout/stderr captured and decoded as UTF-8 (lossy; Python would raise on
//!   invalid UTF-8 which never happens with Slurm). `stdin` inherited (Python default).
//!   - command missing (`FileNotFoundError` on exec: ENOENT, incl. not on PATH):
//!     `check` -> `die("required command not found: {argv[0]}")`;
//!     unchecked -> `Output { status: 127, stdout: "", stderr: "command not found: {argv[0]}" }`.
//!     (Other spawn errors, e.g. EACCES, raised a Python traceback; map them to the same
//!     die/127 path; document if a scenario hits it.)
//!   - `check` and non-zero exit: `die("{shlex.join(argv)} failed: {detail}")` with
//!     `detail = stderr.strip() or stdout.strip() or "command failed with exit code {rc}"`.
//!   - a child killed by a signal has Python returncode `-signum`.
//! * [`try_run`]: the same but NEVER prints: returns [`RunError`], so callers inside
//!   [`parallel`] can report errors later in deterministic (Python call) order with
//!   [`RunError::die`].
//! * [`run_inherit`]: `run(argv, capture_output=False)` (scancel): stdout/stderr inherited,
//!   check semantics the same (detail from empty strings -> "command failed with exit code").
//! * [`exec_replace`]: `os.execvp`; on ENOENT `die("command not found: {argv[0]}")`.
//!   Flushes both consoles and restores default signal dispositions first
//!   ([`crate::signals::restore_default`]).
//! * Ctrl-C: if SIGINT arrived while waiting, return `Err(AbError::Interrupted)` after the
//!   child exits (Python raises KeyboardInterrupt).
//!
//! # Concurrency
//!
//! [`parallel`] runs independent closures on scoped threads (`std::thread::scope`) and
//! returns results in input order. Rules (plan amendment 6): only read-only queries that
//! Python would make anyway in the same invocation, never mutations (sbatch, scancel,
//! scontrol update, ssh/srun) and never calls that Python only makes conditionally on an
//! earlier result (e.g. the `scontrol --oneliner show node` fallback). Closures must not
//! print: use [`try_run`] inside and report errors afterwards in Python's order. Node facts
//! ([`super::nodes::remember_nodes`]) are thread-safe.

use crate::error::{AbError, Result};

/// `subprocess.CompletedProcess` subset.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Output {
    /// Python `returncode` (negative signal number if killed by a signal).
    pub status: i32,
    pub stdout: String,
    pub stderr: String,
}

impl Output {
    pub fn success(&self) -> bool {
        self.status == 0
    }
}

/// A checked run that failed, not yet reported.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RunError {
    /// Executable not found: message `required command not found: {argv0}`.
    NotFound { argv0: String },
    /// Non-zero exit: message `{shlex.join(argv)} failed: {detail}`.
    Failed {
        joined_argv: String,
        detail: String,
        output: Output,
    },
}

impl RunError {
    /// The message `die()` prints (without `error: `).
    pub fn message(&self) -> String {
        match self {
            RunError::NotFound { argv0 } => format!("required command not found: {argv0}"),
            RunError::Failed {
                joined_argv,
                detail,
                ..
            } => format!("{joined_argv} failed: {detail}"),
        }
    }

    /// Print it like Python's `die` and return the error to propagate.
    #[must_use]
    pub fn die(&self) -> AbError {
        crate::error::die(self.message())
    }
}

/// `core.run(argv, check=check)`. See module docs.
pub fn run<S: AsRef<str>>(argv: &[S], check: bool) -> Result<Output> {
    todo!()
}

/// [`run`] without printing: `Err` only for checked failures (`check=false` always gives
/// `Ok`, with the 127 output for a missing command). Ctrl-C is not reported here; callers
/// check [`crate::signals::check`] after joining.
pub fn try_run<S: AsRef<str>>(argv: &[S], check: bool) -> std::result::Result<Output, RunError> {
    todo!()
}

/// `run(argv, capture_output=False)` (only `scancel` in Python), checked.
pub fn run_inherit<S: AsRef<str>>(argv: &[S]) -> Result<Output> {
    todo!()
}

/// `core.exec_replace(argv)`: replaces the process; only returns on failure.
pub fn exec_replace<S: AsRef<str>>(argv: &[S]) -> AbError {
    todo!()
}

/// `run_parsable_rows(argv, headers, check=check)` = `parse_pipe_rows(run(...).stdout, headers)`.
pub fn run_parsable_rows<S: AsRef<str>>(
    argv: &[S],
    headers: &[&str],
    check: bool,
) -> Result<Vec<super::Record>> {
    todo!()
}

/// A boxed task for [`parallel`].
pub type Task<'a, T> = Box<dyn FnOnce() -> T + Send + 'a>;

/// Run `tasks` concurrently on scoped threads; results in input order. With one task,
/// runs inline. See module docs for what may run here.
pub fn parallel<'a, T: Send>(tasks: Vec<Task<'a, T>>) -> Vec<T> {
    todo!()
}

/// Two different-typed tasks concurrently (convenience over [`parallel`]).
pub fn join2<A: Send, B: Send>(
    a: impl FnOnce() -> A + Send,
    b: impl FnOnce() -> B + Send,
) -> (A, B) {
    std::thread::scope(|scope| {
        let hb = scope.spawn(b);
        let ra = a();
        (ra, hb.join().expect("parallel task panicked"))
    })
}

/// Three different-typed tasks concurrently.
pub fn join3<A: Send, B: Send, C: Send>(
    a: impl FnOnce() -> A + Send,
    b: impl FnOnce() -> B + Send,
    c: impl FnOnce() -> C + Send,
) -> (A, B, C) {
    std::thread::scope(|scope| {
        let hb = scope.spawn(b);
        let hc = scope.spawn(c);
        let ra = a();
        (
            ra,
            hb.join().expect("parallel task panicked"),
            hc.join().expect("parallel task panicked"),
        )
    })
}
