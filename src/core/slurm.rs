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
//! ([`super::nodes::remember_nodes`]) are thread-safe. At most [`MAX_PARALLEL`] queries
//! run at once, so one user never floods slurmctld.
//!
//! # Tests
//!
//! Under `cfg(test)` every command goes to the [`fake::FakeSlurm`] of the current
//! [`crate::hooks::testing::Ctx`] (panics without one); release builds spawn directly.

use crate::error::{AbError, Result};
use crate::pyfmt;
use std::io;
#[cfg(not(test))]
use std::process::{Command, Stdio};

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

/// Most commands [`parallel`] runs at the same time.
pub const MAX_PARALLEL: usize = 8;

/// Spawn `argv`, wait, and capture its output (or inherit stdout/stderr). `Err` only when
/// it could not be started.
fn spawn<S: AsRef<str>>(argv: &[S], capture: bool) -> io::Result<Output> {
    #[cfg(test)]
    {
        let _ = capture;
        let argv: Vec<String> = argv.iter().map(|a| a.as_ref().to_owned()).collect();
        crate::hooks::testing::ctx()
            .slurm
            .as_ref()
            .unwrap_or_else(|| panic!("no FakeSlurm installed for {argv:?}"))
            .call(&argv)
    }
    #[cfg(not(test))]
    {
        let Some((program, args)) = argv.split_first() else {
            return Err(io::ErrorKind::NotFound.into());
        };
        let mut command = Command::new(program.as_ref());
        command
            .args(args.iter().map(AsRef::as_ref))
            .stdin(Stdio::inherit());
        if capture {
            let output = command.output()?;
            Ok(Output {
                status: exit_status(output.status),
                stdout: pyfmt::decode_text(output.stdout),
                stderr: pyfmt::decode_text(output.stderr),
            })
        } else {
            let status = command.status()?;
            Ok(Output {
                status: exit_status(status),
                ..Output::default()
            })
        }
    }
}

/// Python's `returncode`: the exit code, or `-signum` when killed by a signal.
fn exit_status(status: std::process::ExitStatus) -> i32 {
    use std::os::unix::process::ExitStatusExt;
    status
        .code()
        .unwrap_or_else(|| -status.signal().unwrap_or(0))
}

/// Python only raised `FileNotFoundError` for a missing command; other spawn errors
/// (EACCES, ...) end up on the same path here instead of a traceback.
fn not_found<S: AsRef<str>>(argv: &[S]) -> RunError {
    RunError::NotFound {
        argv0: argv
            .first()
            .map(|a| a.as_ref().to_owned())
            .unwrap_or_default(),
    }
}

fn check_output<S: AsRef<str>>(
    argv: &[S],
    output: Output,
) -> std::result::Result<Output, RunError> {
    if output.success() {
        return Ok(output);
    }
    let stderr = pyfmt::strip(&output.stderr);
    let stdout = pyfmt::strip(&output.stdout);
    let detail = if !stderr.is_empty() {
        stderr.to_owned()
    } else if !stdout.is_empty() {
        stdout.to_owned()
    } else {
        format!("command failed with exit code {}", output.status)
    };
    Err(RunError::Failed {
        joined_argv: pyfmt::shlex_join(argv),
        detail,
        output,
    })
}

fn interrupted() -> bool {
    #[cfg(test)]
    return false;
    #[cfg(not(test))]
    crate::signals::interrupted()
}

/// `Err(AbError::Interrupted)` once Ctrl-C arrived (after joining [`parallel`] work that
/// used [`try_run`]).
pub fn check_interrupted() -> Result<()> {
    if interrupted() {
        return Err(AbError::Interrupted);
    }
    Ok(())
}

/// `core.run(argv, check=check)`. See module docs.
pub fn run<S: AsRef<str>>(argv: &[S], check: bool) -> Result<Output> {
    let result = try_run(argv, check);
    if interrupted() {
        return Err(AbError::Interrupted);
    }
    result.map_err(|err| err.die())
}

/// [`run`] without printing: `Err` only for checked failures (`check=false` always gives
/// `Ok`, with the 127 output for a missing command). Ctrl-C is not reported here; callers
/// check [`crate::signals::check`] after joining.
pub fn try_run<S: AsRef<str>>(argv: &[S], check: bool) -> std::result::Result<Output, RunError> {
    match spawn(argv, true) {
        Ok(output) if check => check_output(argv, output),
        Ok(output) => Ok(output),
        Err(_) if check => Err(not_found(argv)),
        Err(_) => {
            let argv0 = argv.first().map(AsRef::as_ref).unwrap_or_default();
            Ok(Output {
                status: 127,
                stdout: String::new(),
                stderr: format!("command not found: {argv0}"),
            })
        }
    }
}

/// `run(argv, capture_output=False)` (only `scancel` in Python), checked.
pub fn run_inherit<S: AsRef<str>>(argv: &[S]) -> Result<Output> {
    let result = match spawn(argv, false) {
        Ok(output) => check_output(argv, output),
        Err(_) => Err(not_found(argv)),
    };
    if interrupted() {
        return Err(AbError::Interrupted);
    }
    result.map_err(|err| err.die())
}

/// `core.exec_replace(argv)`: replaces the process; only returns on failure, after
/// printing `error: command not found: {argv0}` (Python's message for ENOENT; other exec
/// errors, a Python traceback, take the same path). The consoles write through on every
/// print, so there is nothing to flush. Under `cfg(test)` the argv goes to the fake and a
/// successful "exec" returns `AbError::Exit(0)`.
pub fn exec_replace<S: AsRef<str>>(argv: &[S]) -> AbError {
    let argv0 = argv.first().map(AsRef::as_ref).unwrap_or_default();
    #[cfg(test)]
    {
        let argv: Vec<String> = argv.iter().map(|a| a.as_ref().to_owned()).collect();
        let ctx = crate::hooks::testing::ctx();
        let slurm = ctx.slurm.as_ref().expect("no FakeSlurm installed");
        if slurm.call(&argv).is_ok() {
            return AbError::Exit(0);
        }
    }
    #[cfg(not(test))]
    {
        use std::os::unix::process::CommandExt;
        crate::signals::restore_default();
        let _ = Command::new(argv0)
            .args(argv.iter().skip(1).map(AsRef::as_ref))
            .exec();
    }
    crate::error::die(format!("command not found: {argv0}"))
}

/// `run_parsable_rows(argv, headers, check=check)` = `parse_pipe_rows(run(...).stdout, headers)`.
pub fn run_parsable_rows<S: AsRef<str>>(
    argv: &[S],
    headers: &[&str],
    check: bool,
) -> Result<Vec<super::Record>> {
    let output = run(argv, check)?;
    Ok(super::parse::parse_pipe_rows(&output.stdout, headers))
}

/// A boxed task for [`parallel`].
pub type Task<'a, T> = Box<dyn FnOnce() -> T + Send + 'a>;

/// Run `tasks` concurrently on scoped threads (at most [`MAX_PARALLEL`] at a time);
/// results in input order. With one task, runs inline. See module docs for what may run
/// here.
pub fn parallel<'a, T: Send>(tasks: Vec<Task<'a, T>>) -> Vec<T> {
    if tasks.len() <= 1 {
        return tasks.into_iter().map(|task| task()).collect();
    }
    let count = tasks.len();
    let queue: std::sync::Mutex<std::vec::IntoIter<(usize, Task<'a, T>)>> = std::sync::Mutex::new(
        tasks
            .into_iter()
            .enumerate()
            .collect::<Vec<_>>()
            .into_iter(),
    );
    let results: std::sync::Mutex<Vec<Option<T>>> =
        std::sync::Mutex::new((0..count).map(|_| None).collect());
    #[cfg(test)]
    let ctx = crate::hooks::testing::ctx();
    std::thread::scope(|scope| {
        for _ in 0..count.min(MAX_PARALLEL) {
            #[cfg(test)]
            let ctx = ctx.clone();
            let worker = || loop {
                let next = queue.lock().expect("task queue").next();
                let Some((index, task)) = next else { break };
                let value = task();
                results.lock().expect("results")[index] = Some(value);
            };
            #[cfg(test)]
            scope.spawn(move || crate::hooks::testing::with_ctx(ctx, worker));
            #[cfg(not(test))]
            scope.spawn(worker);
        }
    });
    results
        .into_inner()
        .expect("results")
        .into_iter()
        .map(|value| value.expect("parallel task panicked"))
        .collect()
}

/// Two different-typed tasks concurrently (convenience over [`parallel`]).
pub fn join2<A: Send, B: Send>(
    a: impl FnOnce() -> A + Send,
    b: impl FnOnce() -> B + Send,
) -> (A, B) {
    #[cfg(test)]
    let ctx = crate::hooks::testing::ctx();
    std::thread::scope(|scope| {
        #[cfg(test)]
        let hb = scope.spawn(move || crate::hooks::testing::with_ctx(ctx, b));
        #[cfg(not(test))]
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
    let (ra, (rb, rc)) = join2(a, || join2(b, c));
    (ra, rb, rc)
}

/// The Slurm stand-in for unit tests (Python's `patch('subprocess.run', ...)`).
#[cfg(test)]
pub mod fake {
    use super::Output;
    use std::io;
    use std::sync::{Arc, Mutex};

    type Handler = dyn Fn(&[String]) -> Option<Output> + Send + Sync;

    /// Answers every command with a closure (`None` = command not found) and records argv.
    pub struct FakeSlurm {
        handler: Box<Handler>,
        calls: Mutex<Vec<Vec<String>>>,
    }

    impl FakeSlurm {
        pub fn new(
            handler: impl Fn(&[String]) -> Option<Output> + Send + Sync + 'static,
        ) -> Arc<FakeSlurm> {
            Arc::new(FakeSlurm {
                handler: Box::new(handler),
                calls: Mutex::default(),
            })
        }

        /// Every command gets the same answer (`patch('subprocess.run', return_value=...)`).
        pub fn always(output: Output) -> Arc<FakeSlurm> {
            FakeSlurm::new(move |_| Some(output.clone()))
        }

        pub fn call(&self, argv: &[String]) -> io::Result<Output> {
            self.calls.lock().expect("calls").push(argv.to_vec());
            (self.handler)(argv).ok_or_else(|| io::ErrorKind::NotFound.into())
        }

        /// Every argv so far, in call order.
        pub fn calls(&self) -> Vec<Vec<String>> {
            self.calls.lock().expect("calls").clone()
        }
    }

    /// `_proc(stdout=...)`.
    pub fn ok(stdout: &str) -> Output {
        Output {
            status: 0,
            stdout: stdout.to_owned(),
            stderr: String::new(),
        }
    }

    /// `_proc(stderr=..., returncode=...)`.
    pub fn fail(status: i32, stderr: &str) -> Output {
        Output {
            status,
            stdout: String::new(),
            stderr: stderr.to_owned(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::fake::{FakeSlurm, fail, ok};
    use super::*;
    use crate::hooks::testing::Ctx;

    // Python TestRun
    #[test]
    fn returns_completed_process_on_success() {
        let _ctx = Ctx::default().slurm(FakeSlurm::always(ok("ok"))).install();
        assert_eq!(
            run(&["scontrol", "show", "partition"], true)
                .unwrap()
                .stdout,
            "ok"
        );
    }

    #[test]
    fn nonzero_returncode_fails_with_the_python_message() {
        let _ctx = Ctx::default()
            .slurm(FakeSlurm::always(fail(1, "bad\n")))
            .install();
        let err = try_run(&["scontrol", "show", "bad thing"], true).unwrap_err();
        assert_eq!(err.message(), "scontrol show 'bad thing' failed: bad");
        let quiet = FakeSlurm::always(Output {
            status: 3,
            ..ok(" out ")
        });
        let _ctx = Ctx::default().slurm(quiet).install();
        assert_eq!(
            try_run(&["x"], true).unwrap_err().message(),
            "x failed: out"
        );
        let _ctx = Ctx::default()
            .slurm(FakeSlurm::always(fail(-9, "")))
            .install();
        assert_eq!(
            try_run(&["x"], true).unwrap_err().message(),
            "x failed: command failed with exit code -9"
        );
    }

    #[test]
    fn check_false_allows_nonzero_returncode() {
        let _ctx = Ctx::default()
            .slurm(FakeSlurm::always(fail(1, "")))
            .install();
        assert_eq!(run(&["sacct"], false).unwrap().status, 1);
    }

    #[test]
    fn file_not_found() {
        let _ctx = Ctx::default().slurm(FakeSlurm::new(|_| None)).install();
        assert_eq!(
            try_run(&["nonexistent_command"], true)
                .unwrap_err()
                .message(),
            "required command not found: nonexistent_command"
        );
        assert_eq!(
            run(&["nonexistent_command"], false).unwrap(),
            Output {
                status: 127,
                stdout: String::new(),
                stderr: "command not found: nonexistent_command".to_owned()
            }
        );
    }

    #[test]
    fn parallel_keeps_order_and_context() {
        let fake = FakeSlurm::new(|argv| Some(ok(&argv[1])));
        let _ctx = Ctx::default().slurm(fake.clone()).install();
        let tasks: Vec<Task<'_, String>> = (0..20)
            .map(|i| -> Task<'_, String> {
                Box::new(move || {
                    run(&["echo".to_owned(), i.to_string()], true)
                        .unwrap()
                        .stdout
                })
            })
            .collect();
        let expected: Vec<String> = (0..20).map(|i| i.to_string()).collect();
        assert_eq!(parallel(tasks), expected);
        assert_eq!(fake.calls().len(), 20);
        let (a, b, c) = join3(|| 1, crate::hooks::user, || "c");
        assert_eq!((a, b, c), (1, "alice", "c"));
    }
}
