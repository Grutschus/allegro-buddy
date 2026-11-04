//! Test hooks: the only sanctioned way to read the wall clock, the user, the user's groups,
//! the hostname and whether stdin is a terminal.
//!
//! Each hook reads a `BAB_TEST_*` environment variable; when it is unset (or empty) the
//! real value is used, exactly as Python gets it. The compat harness patches the Python
//! reference the same way, so goldens are reproducible.
//!
//! | hook            | env var                | real behaviour (Python)                          |
//! |-----------------|------------------------|--------------------------------------------------|
//! | [`now`]         | `BAB_TEST_NOW`         | `datetime.now()` / `time.strftime` (local, naive) |
//! | [`groups`]      | `BAB_TEST_GROUPS`      | `{grp.getgrgid(g).gr_name for g in os.getgroups()}` (unknown gids skipped) |
//! | [`interactive`] | `BAB_TEST_INTERACTIVE` | `sys.stdin.isatty()`                              |
//! | [`hostname`]    | `BAB_TEST_HOSTNAME`    | `socket.gethostname()`                            |
//! | [`user`]        | (none; set `LOGNAME`/`USER`) | `getpass.getuser()`                         |
//!
//! Formats: `BAB_TEST_NOW` is an ISO local naive datetime (`2026-05-04T12:00:00`, also
//! accepts a space separator and fractional seconds, like `datetime.fromisoformat`);
//! `BAB_TEST_GROUPS` is a comma list (`alice,gpu-users`; empty entries ignored);
//! `BAB_TEST_INTERACTIVE` is `1`/`0`; `BAB_TEST_HOSTNAME` is the name verbatim.
//!
//! Elapsed time and sleeping (dev wait polling, `--watch`) stay real: use
//! `std::time::Instant` and [`crate::signals::sleep`].
//!
//! Values that cannot change during a run (user, groups, hostname) are cached per process.

use chrono::NaiveDateTime;
use std::collections::BTreeSet;

/// Local wall-clock time as a naive datetime (Python `datetime.now()`), or the frozen
/// `BAB_TEST_NOW`. Not cached: `--watch` shows the time of each refresh.
pub fn now() -> NaiveDateTime {
    todo!("BAB_TEST_NOW or chrono::Local::now().naive_local()")
}

/// Python `getpass.getuser()`: first non-empty of `LOGNAME`, `USER`, `LNAME`, `USERNAME`,
/// else the passwd name of the real uid (`pwd.getpwuid(os.getuid())[0]`). Cached.
pub fn user() -> &'static str {
    todo!()
}

/// Names of the groups of this process (`core.current_groups()`), or `BAB_TEST_GROUPS`.
/// Uses `getgroups(2)` + `getgrgid_r(3)` (NSS, hence glibc and not musl). Cached.
pub fn groups() -> &'static BTreeSet<String> {
    todo!()
}

/// `sys.stdin.isatty()`, or `BAB_TEST_INTERACTIVE` (`1` true, anything else false).
pub fn interactive() -> bool {
    todo!()
}

/// `socket.gethostname()`, or `BAB_TEST_HOSTNAME`. Cached.
pub fn hostname() -> &'static str {
    todo!()
}
