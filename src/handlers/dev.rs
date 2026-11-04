//! `bab dev start|status|login|stop` and `bab l`. Port of `handlers/dev.py`. Owned by P3-F.
//!
//! Notes:
//! * Mutations (scancel, sbatch) run strictly sequentially, in Python's order, after every
//!   check that can fail (see the comments in dev.py: a bad `--replace` must never cancel).
//! * `wait_for_job_running` shows `console.status(...)` (spinner only on a terminal),
//!   polls with `signals::sleep(poll_interval)` and real elapsed time (`Instant`).
//!   On Ctrl-C during `dev start`'s wait, print
//!   `muted("Detached; {id} stays queued (bab dev stop cancels it).")` and return
//!   `Err(AbError::Interrupted)`.
//! * `cmd_dev_login` ends in `core::slurm::exec_replace` (ssh / srun); a not-running job
//!   without `--wait` ends with a bare `SystemExit(1)` -> `Err(AbError::Exit(1))`.

use crate::error::Result;

/// Arguments of `dev start` after defaults/default_map/callbacks (`gpu_type` canonical).
#[derive(Debug, Clone, PartialEq)]
pub struct DevStartArgs {
    pub partition: String,
    pub time_limit: String,
    pub gpu: Option<i64>,
    pub gpu_type: Option<String>,
    pub cpus: i64,
    pub mem: String,
    pub account: Option<String>,
    pub constraint: Option<String>,
    pub exclude: Option<String>,
    pub node: Option<String>,
    pub replace: bool,
    pub no_wait: bool,
    pub login: bool,
    pub timeout: Option<i64>,
    pub poll_interval: f64,
}

/// Arguments of `dev login` / `l`.
#[derive(Debug, Clone, PartialEq)]
pub struct DevLoginArgs {
    pub jobid: Option<String>,
    pub wait: bool,
    pub timeout: Option<i64>,
    pub poll_interval: f64,
    pub srun: bool,
    pub command: Option<String>,
}

/// `cmd_dev_start(...)`.
pub fn cmd_dev_start(args: &DevStartArgs) -> Result<()> {
    todo!()
}

/// `cmd_dev_status(jobid=)`.
pub fn cmd_dev_status(jobid: Option<&str>) -> Result<()> {
    todo!()
}

/// `cmd_dev_login(...)`: only returns on error (exec replaces the process).
pub fn cmd_dev_login(args: &DevLoginArgs) -> Result<()> {
    todo!()
}

/// `cmd_dev_stop(jobid=)`. Note the final `Canceled ...` line is a plain `str` print
/// (markup + ReprHighlighter: job ids are highlighted as numbers).
pub fn cmd_dev_stop(jobid: Option<&str>) -> Result<()> {
    todo!()
}
