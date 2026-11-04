//! Ctrl-C handling (Python `KeyboardInterrupt`). Owned by P2-B.
//!
//! Python turns SIGINT into `KeyboardInterrupt` wherever the interpreter happens to be.
//! bab installs a SIGINT handler at startup ([`install`], called by `cli::main`) that only
//! sets a flag; the places where Python can realistically be interrupted check it:
//!
//! * [`sleep`] (dev wait polling, `--watch` interval) returns `Err(AbError::Interrupted)`.
//! * Slurm subprocess waits ([`crate::core::slurm`]) return `Err(AbError::Interrupted)`
//!   once the child exits after the flag is set (the child got SIGINT from the tty too).
//! * Prompts ([`crate::cli::prompt`]) map Ctrl-C/EOF to `AbError::Abort`.
//!
//! [`restore_default`] resets SIGINT (and SIGPIPE) to default before `execvp`
//! (`core::slurm::exec_replace`), so ssh/srun behave as when started by Python.
//! `cli::main` also sets SIGPIPE to `SIG_DFL` so `bab q | head` ends quietly.

use crate::error::Result;
use std::time::Duration;

/// Install the flag-setting SIGINT handler (idempotent).
pub fn install() {
    todo!()
}

/// True once SIGINT arrived (since [`install`]).
pub fn interrupted() -> bool {
    todo!()
}

/// Return `Err(AbError::Interrupted)` if SIGINT arrived.
pub fn check() -> Result<()> {
    todo!()
}

/// Interruptible `time.sleep(duration)`: wakes early with `Err(Interrupted)` on Ctrl-C.
pub fn sleep(duration: Duration) -> Result<()> {
    todo!()
}

/// SIGINT and SIGPIPE back to `SIG_DFL` (before exec).
pub fn restore_default() {
    todo!()
}
