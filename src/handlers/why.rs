//! `bab why [JOBID] [--nodes] [--fix [auto|mem|cpus|gpus]] [-y]`, plus `queue_hints` used
//! by `bab q`. Port of `handlers/why.py`. Owned by P3-E.
//!
//! Notes:
//! * `--fix` confirmation: `hooks::interactive()` replaces `sys.stdin.isatty()`;
//!   `click.confirm('Apply?', default=False)` is `cli::prompt::confirm`.
//! * `_apply_fix` ends with a bare `raise SystemExit(1)` when the re-read does not match:
//!   return `Err(AbError::Exit(1))` (nothing printed by that line itself).
//! * `_start_text` uses `datetime.fromtimestamp(planned_start)` (local time):
//!   `core::timefmt::local_iso_from_epoch`.
//! * [`load_inputs`] runs its three read-only queries (`scontrol --json show job`,
//!   `scontrol --json show nodes`, `scontrol --oneliner show partition`) concurrently and
//!   then evaluates them in Python's order (first error wins, conditional node fallback
//!   stays sequential).

use crate::core::jobs::JobRecord;
use crate::core::nodes::{node_from_props, nodes_from_json, remember_nodes};
use crate::core::parse::parse_prop_line;
use crate::core::slurm::{self, Output, RunError};
use crate::error::{AbError, Result, die_with_code};
use crate::fit::{JobRequest, MemLimits, NodeCapacity, diagnose, mem_per_cpu_limits, queue_hint};
use crate::pyfmt;
use std::collections::{BTreeSet, HashMap};

/// `--fix` choice.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FixChoice {
    Auto,
    Mem,
    Cpus,
    Gpus,
}

/// `Inputs`: job records, node capacities, partition memory limits.
pub type Inputs = (Vec<JobRecord>, Vec<NodeCapacity>, MemLimits);

type Ran = std::result::Result<Output, RunError>;

/// The tail of `core.load_job_records` once `scontrol --json show job` ran.
fn job_records_from(ran: Ran, strict: bool) -> Result<Vec<JobRecord>> {
    let output = ran.map_err(|err| err.die())?;
    if !output.success() {
        return Ok(Vec::new());
    }
    match serde_json::from_str::<serde_json::Value>(&output.stdout) {
        Ok(serde_json::Value::Object(mut top)) => match top.remove("jobs") {
            Some(serde_json::Value::Array(jobs)) => Ok(jobs),
            _ => Ok(Vec::new()),
        },
        _ if strict => Err(die_with_code(
            "this needs a Slurm whose `scontrol --json show job` works",
            2,
        )),
        _ => Ok(Vec::new()),
    }
}

/// The tail of `core.load_nodes` once `scontrol --json show nodes` (unchecked) ran.
fn nodes_from(ran: Ran, strict: bool) -> Result<Vec<NodeCapacity>> {
    let parsed = match ran {
        Ok(output) if output.success() => nodes_from_json(&output.stdout).ok(),
        _ => None,
    };
    let nodes = match parsed {
        Some(nodes) => nodes,
        None => {
            let fallback = slurm::run(&["scontrol", "--oneliner", "show", "node"], strict)?;
            if fallback.success() {
                pyfmt::splitlines(&fallback.stdout)
                    .into_iter()
                    .filter(|line| !pyfmt::strip(line).is_empty())
                    .map(|line| node_from_props(&parse_prop_line(line)))
                    .collect()
            } else {
                Vec::new()
            }
        }
    };
    remember_nodes(&nodes);
    Ok(nodes.iter().map(NodeCapacity::from_node).collect())
}

/// The tail of `core.load_partitions` -> `mem_per_cpu_limits`.
fn limits_from(ran: Ran) -> Result<MemLimits> {
    let output = ran.map_err(|err| err.die())?;
    if !output.success() {
        return Ok(MemLimits::new());
    }
    let partitions: Vec<_> = pyfmt::splitlines(&output.stdout)
        .into_iter()
        .filter(|line| !pyfmt::strip(line).is_empty())
        .map(parse_prop_line)
        .collect();
    Ok(mem_per_cpu_limits(&partitions))
}

/// `load_inputs(strict=, job_id=)`: `load_job_records`, `load_nodes`, `load_partitions`
/// (independent read-only queries; may run concurrently).
pub fn load_inputs(strict: bool, job_id: Option<&str>) -> Result<Inputs> {
    let job_id = job_id.filter(|id| !id.is_empty());
    let mut job_argv = vec!["scontrol", "--json", "show", "job"];
    job_argv.extend(job_id);
    let (jobs, nodes, partitions) = slurm::join3(
        || slurm::try_run(&job_argv, strict && job_id.is_none()),
        || slurm::try_run(&["scontrol", "--json", "show", "nodes"], false),
        || slurm::try_run(&["scontrol", "--oneliner", "show", "partition"], strict),
    );
    slurm::check_interrupted()?;
    let records = job_records_from(jobs, strict)?;
    let nodes = nodes_from(nodes, strict)?;
    let limits = limits_from(partitions)?;
    Ok((records, nodes, limits))
}

/// `queue_hints(job_ids)` -> (raw job id -> hint, error text). Never fails: the hints
/// decorate `bab q` and must never break it. Python turns unexpected exceptions into
/// `"<ExceptionType>: <message>"`; the Rust port of the record parsing is total, so the
/// only error left is Ctrl-C (Python's KeyboardInterrupt), which yields no hints here:
/// callers notice it with `core::slurm::check_interrupted()`.
pub fn queue_hints(job_ids: &BTreeSet<String>) -> (HashMap<String, String>, Option<String>) {
    let Ok((records, nodes, limits)) = load_inputs(false, None) else {
        return (HashMap::new(), None);
    };
    if records.is_empty() || nodes.is_empty() {
        return (
            HashMap::new(),
            Some("scontrol returned no job or node data".to_owned()),
        );
    }
    let mut hints = HashMap::new();
    for record in &records {
        let job_id = record
            .get("job_id")
            .map_or_else(String::new, pyfmt::json_str);
        if job_ids.contains(&job_id) {
            let request = JobRequest::from_record(record);
            hints.insert(job_id, queue_hint(&diagnose(&request, &nodes, &limits)));
        }
    }
    (hints, None)
}
/// `cmd_why(jobid=, show_nodes=, fix=, assume_yes=)`.
pub fn cmd_why(
    jobid: Option<&str>,
    show_nodes: bool,
    fix: Option<FixChoice>,
    assume_yes: bool,
) -> Result<()> {
    todo!()
}
