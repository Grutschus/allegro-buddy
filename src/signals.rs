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
//! SIGPIPE: Python ignores it and rich-click exits 1 on `BrokenPipeError`; bab exits 1
//! from a SIGPIPE handler (quietly, like `bab q | head` in Python).

use crate::error::{AbError, Result};
use std::sync::Once;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

static INTERRUPTED: AtomicBool = AtomicBool::new(false);
static INSTALL: Once = Once::new();

extern "C" fn on_sigint(_: libc::c_int) {
    INTERRUPTED.store(true, Ordering::SeqCst);
}

/// Python ignores SIGPIPE and exits 1 on `BrokenPipeError` (rich-click's main); exiting
/// from the handler gives the same status without a message.
extern "C" fn on_sigpipe(_: libc::c_int) {
    unsafe { libc::_exit(1) }
}

fn set_handler(signal: libc::c_int, handler: libc::sighandler_t) {
    // No SA_RESTART: blocking reads (prompts) return EINTR on Ctrl-C.
    unsafe {
        let mut action: libc::sigaction = std::mem::zeroed();
        action.sa_sigaction = handler;
        libc::sigemptyset(&mut action.sa_mask);
        action.sa_flags = 0;
        libc::sigaction(signal, &action, std::ptr::null_mut());
    }
}

/// Install the flag-setting SIGINT handler and the SIGPIPE handler (idempotent).
pub fn install() {
    INSTALL.call_once(|| {
        set_handler(libc::SIGINT, on_sigint as extern "C" fn(libc::c_int) as libc::sighandler_t);
        set_handler(libc::SIGPIPE, on_sigpipe as extern "C" fn(libc::c_int) as libc::sighandler_t);
    });
}

/// True once SIGINT arrived (since [`install`]).
pub fn interrupted() -> bool {
    INTERRUPTED.load(Ordering::SeqCst)
}

/// Return `Err(AbError::Interrupted)` if SIGINT arrived.
pub fn check() -> Result<()> {
    if interrupted() {
        Err(AbError::Interrupted)
    } else {
        Ok(())
    }
}

/// Interruptible `time.sleep(duration)`: wakes early with `Err(Interrupted)` on Ctrl-C.
pub fn sleep(duration: Duration) -> Result<()> {
    let deadline = Instant::now().checked_add(duration);
    loop {
        check()?;
        let left = match deadline {
            Some(deadline) => deadline.saturating_duration_since(Instant::now()),
            None => Duration::from_secs(3600),
        };
        if left.is_zero() {
            return Ok(());
        }
        std::thread::sleep(left.min(Duration::from_millis(50)));
    }
}

/// SIGINT and SIGPIPE back to `SIG_DFL` (before exec).
pub fn restore_default() {
    set_handler(libc::SIGINT, libc::SIG_DFL);
    set_handler(libc::SIGPIPE, libc::SIG_DFL);
}
