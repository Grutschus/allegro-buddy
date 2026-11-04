//! Jobs: details, JSON records, history, pending jobs, dev jobs, job output files.
//! Owned by P2-C. Each function names its Python original.

use super::parse::{
    base_job_id, expand_nodelist, is_nullish, job_state_is_finished, normalize_sacct_state,
    parse_int, parse_pipe_rows, parse_prop_line, user_from_userid,
};
use super::slurm::{self, Task};
use super::timefmt::{iso_to_dt, local_timestamp, total_seconds};
use super::{
    ACTIVE_STATES, DEV_JOB_NAME, RUNNING_STATES, Record, RecordExt, SACCT_HISTORY_HEADERS,
};
use crate::error::{Result, die, die_with_code};
use crate::pyfmt;
use chrono::NaiveDateTime;
use std::path::{Path, PathBuf};

/// One `scontrol --json show job` record (`jobs[i]`), used by `fit` and `why`.
pub type JobRecord = serde_json::Value;

/// The keys of a [`JobRecord`] that bab reads (`fit`, `handlers::why`); the ~100 others
/// are skipped while parsing ([`job_records_json`]). Reading another key: add it here (the
/// `job_keys_cover_reads` test checks fit.rs and why.rs).
#[rustfmt::skip]
pub const JOB_KEYS: [&str; 28] = [
    "array_job_id", "array_task_id", "array_task_string", "cpus", "cpus_per_tres",
    "excluded_nodes", "features", "het_job_id", "job_id", "job_state", "memory_per_cpu",
    "memory_per_node", "memory_per_tres", "minimum_cpus_per_node", "node_count", "partition",
    "required_nodes", "resv_name", "scheduled_nodes", "shared", "start_time", "state_reason",
    "tasks", "tres_per_job", "tres_per_node", "tres_per_task", "tres_req_str", "user_name",
];

/// `json.loads(stdout)["jobs"]` of `scontrol --json show job` (missing or not a list: `[]`),
/// each record reduced to [`JOB_KEYS`]; `None` when stdout is not a JSON object. Skipping
/// the other keys while parsing makes the 2.5 MB of a busy cluster parse twice as fast.
/// Unexpected shapes (a job that is not an object, ...) take the plain full parse, which also
/// decides about errors.
pub fn job_records_json(stdout: &str) -> Option<Vec<JobRecord>> {
    use serde_core::Deserializer;
    use serde_json::Value;
    let mut de = serde_json::Deserializer::from_str(stdout);
    let reduced = de.deserialize_map(reduced::Records::Top);
    if let Ok(jobs) = reduced.and_then(|jobs| de.end().map(|()| jobs)) {
        return Some(jobs);
    }
    match serde_json::from_str(stdout).ok()? {
        Value::Object(mut top) => match top.remove("jobs") {
            Some(Value::Array(jobs)) => Some(jobs),
            _ => Some(Vec::new()),
        },
        _ => None,
    }
}

/// The serde visitor of [`job_records_json`]: fails on anything but
/// `{"jobs": [{...}, ...], ...}` (and on escaped keys, which Slurm never writes).
mod reduced {
    use super::{JOB_KEYS, JobRecord};
    use serde_core::de::{
        DeserializeSeed, Deserializer, IgnoredAny, MapAccess, SeqAccess, Visitor,
    };
    use serde_json::{Map, Value};

    /// What is read: the top-level object, the `jobs` list (both: the jobs), or one job (a
    /// list of just it).
    #[derive(Clone, Copy)]
    pub enum Records {
        Top,
        Jobs,
        Job,
    }

    impl<'de> DeserializeSeed<'de> for Records {
        type Value = Vec<JobRecord>;
        fn deserialize<D: Deserializer<'de>>(self, de: D) -> Result<Vec<JobRecord>, D::Error> {
            match self {
                Records::Jobs => de.deserialize_seq(self),
                _ => de.deserialize_map(self),
            }
        }
    }

    impl<'de> Visitor<'de> for Records {
        type Value = Vec<JobRecord>;
        fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
            f.write_str("scontrol --json show job")
        }
        fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Vec<JobRecord>, A::Error> {
            let mut jobs = Vec::new();
            while let Some(mut job) = seq.next_element_seed(Records::Job)? {
                jobs.append(&mut job);
            }
            Ok(jobs)
        }
        fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Vec<JobRecord>, A::Error> {
            let (mut jobs, mut job) = (Vec::new(), Map::new());
            while let Some(key) = map.next_key::<&str>()? {
                match self {
                    Records::Top if key == "jobs" => jobs = map.next_value_seed(Records::Jobs)?,
                    Records::Job if JOB_KEYS.binary_search(&key).is_ok() => {
                        job.insert(key.to_owned(), map.next_value()?);
                    }
                    _ => drop(map.next_value::<IgnoredAny>()?),
                }
            }
            Ok(match self {
                Records::Job => vec![Value::Object(job)],
                _ => jobs,
            })
        }
    }
}

/// `USER_JOB_DETAIL_LIMIT`: past this many jobs one full listing beats per-job calls.
pub const USER_JOB_DETAIL_LIMIT: usize = 20;
/// `SQUEUE_PENDING_HEADERS`.
pub const SQUEUE_PENDING_HEADERS: [&str; 5] = ["JobID", "Name", "Partition", "TimeLimit", "Reason"];

/// `user or current_user()`.
fn user_or_current(user: Option<&str>) -> String {
    match user {
        Some(user) if !user.is_empty() => user.to_owned(),
        _ => super::users::current_user().to_owned(),
    }
}

fn data_lines(stdout: &str) -> impl Iterator<Item = &str> {
    pyfmt::splitlines(stdout)
        .into_iter()
        .filter(|line| !pyfmt::strip(line).is_empty())
}

/// `display_job_id(job)`: `ArrayJobId_ArrayTaskId` for array tasks, else `JobId`.
pub fn display_job_id(job: &Record) -> String {
    let array_job = job.get_str("ArrayJobId");
    let array_task = job.get_str("ArrayTaskId");
    if !array_job.is_empty() && !array_task.is_empty() && !matches!(array_task, "N/A" | "(null)") {
        return format!("{array_job}_{array_task}");
    }
    job.get_str("JobId").to_owned()
}

/// `parse_job_detail_line(line)`: props + `NodeBlocks` (everything after the first
/// ` Nodes=`) for per-node lookups.
pub fn parse_job_detail_line(line: &str) -> Record {
    let mut job = parse_prop_line(line);
    if let Some((_, blocks)) = line.split_once(" Nodes=") {
        job.insert("NodeBlocks".to_owned(), blocks.to_owned());
    }
    job
}

/// `job_on_node(job, node)`: that node's `Nodes=... CPU_IDs=... Mem=... GRES=...` block
/// (empty when there is none).
pub fn job_on_node(job: &Record, node: &str) -> Record {
    for block in job.get_str("NodeBlocks").split(" Nodes=") {
        let props = parse_prop_line(&format!("Nodes={block}"));
        if expand_nodelist(props.get_str("Nodes"))
            .iter()
            .any(|n| n == node)
        {
            return props;
        }
    }
    Record::new()
}

/// `job_gres_on_node(job, node)`: the block's `GRES`, or the job's `GRES` without blocks.
pub fn job_gres_on_node(job: &Record, node: &str) -> String {
    let block = job_on_node(job, node);
    if block.is_empty() {
        job.get_str("GRES").to_owned()
    } else {
        block.get_str("GRES").to_owned()
    }
}

fn job_details_argv(job_id: Option<&str>) -> Vec<String> {
    let mut argv: Vec<String> = ["scontrol", "--oneliner", "--details", "show", "job"]
        .map(str::to_owned)
        .to_vec();
    argv.extend(job_id.filter(|id| !id.is_empty()).map(str::to_owned));
    argv
}

fn parse_job_details(output: &slurm::Output) -> Vec<Record> {
    if !output.success() {
        return Vec::new();
    }
    data_lines(&output.stdout)
        .map(parse_job_detail_line)
        .collect()
}

/// `load_job_details(job_id)`: `scontrol --oneliner --details show job [id]`, checked only
/// without an id; failure with an id -> `[]`.
pub fn load_job_details(job_id: Option<&str>) -> Result<Vec<Record>> {
    let has_id = job_id.is_some_and(|id| !id.is_empty());
    let output = slurm::run(&job_details_argv(job_id), !has_id)?;
    Ok(parse_job_details(&output))
}

/// `get_job_detail(job_id)`: first record or None.
pub fn get_job_detail(job_id: &str) -> Result<Option<Record>> {
    Ok(load_job_details(Some(job_id))?.into_iter().next())
}

/// `get_user_jobs(user, name=name)`: `squeue -h --user=U --format=%F [--name=N]` (checked),
/// unique base ids in order; more than [`USER_JOB_DETAIL_LIMIT`] -> one full
/// `load_job_details(None)` filtered by user/name, else `load_job_details(id)` per id.
///
/// Parallel: Python makes the per-id `scontrol` calls one after another; they are
/// read-only, unchecked and all made unconditionally, so they run via
/// [`slurm::parallel`] with results kept in id order.
pub fn get_user_jobs(user: Option<&str>, name: Option<&str>) -> Result<Vec<Record>> {
    let user = user_or_current(user);
    let name = name.filter(|n| !n.is_empty());
    let mut argv = vec![
        "squeue".to_owned(),
        "-h".to_owned(),
        format!("--user={user}"),
        "--format=%F".to_owned(),
    ];
    if let Some(name) = name {
        argv.push(format!("--name={name}"));
    }
    let output = slurm::run(&argv, true)?;
    let mut job_ids: Vec<&str> = Vec::new();
    for id in pyfmt::split_whitespace(&output.stdout) {
        if !job_ids.contains(&id) {
            job_ids.push(id);
        }
    }
    if job_ids.len() > USER_JOB_DETAIL_LIMIT {
        return Ok(load_job_details(None)?
            .into_iter()
            .filter(|job| {
                user_from_userid(job.get_str("UserId")) == user
                    && name.is_none_or(|n| job.get_opt("JobName") == Some(n))
            })
            .collect());
    }
    let tasks: Vec<Task<'_, Vec<Record>>> = job_ids
        .iter()
        .map(|id| -> Task<'_, Vec<Record>> {
            Box::new(move || {
                slurm::try_run(&job_details_argv(Some(id)), false)
                    .map(|output| parse_job_details(&output))
                    .unwrap_or_default()
            })
        })
        .collect();
    let jobs = slurm::parallel(tasks).into_iter().flatten().collect();
    slurm::check_interrupted()?;
    Ok(jobs)
}

/// `load_running_jobs()`: all job details in [`super::RUNNING_STATES`].
pub fn load_running_jobs() -> Result<Vec<Record>> {
    Ok(load_job_details(None)?
        .into_iter()
        .filter(|job| RUNNING_STATES.contains(&job.get_str("JobState")))
        .collect())
}

/// `load_job_records(job_id, strict=strict)`: `scontrol --json show job [id]`; checked
/// only when strict and no id; non-zero -> `[]`; bad JSON -> strict:
/// `die("this needs a Slurm whose `scontrol --json show job` works", exit_code=2)`, else `[]`.
pub fn load_job_records(job_id: Option<&str>, strict: bool) -> Result<Vec<JobRecord>> {
    let job_id = job_id.filter(|id| !id.is_empty());
    let mut argv = vec!["scontrol", "--json", "show", "job"];
    argv.extend(job_id);
    let output = slurm::run(&argv, strict && job_id.is_none())?;
    if !output.success() {
        return Ok(Vec::new());
    }
    match job_records_json(&output.stdout) {
        Some(jobs) => Ok(jobs),
        None if strict => Err(die_with_code(
            "this needs a Slurm whose `scontrol --json show job` works",
            2,
        )),
        None => Ok(Vec::new()),
    }
}

/// `load_user_pending_jobs(user)`: `squeue -h --state=PD --user=U --format=%i|%j|%P|%l|%R`
/// (unchecked; failure -> `[]`) with [`SQUEUE_PENDING_HEADERS`].
pub fn load_user_pending_jobs(user: Option<&str>) -> Result<Vec<Record>> {
    let user = user_or_current(user);
    let argv = [
        "squeue".to_owned(),
        "-h".to_owned(),
        "--state=PD".to_owned(),
        format!("--user={user}"),
        "--format=%i|%j|%P|%l|%R".to_owned(),
    ];
    let output = slurm::run(&argv, false)?;
    if !output.success() {
        return Ok(Vec::new());
    }
    Ok(parse_pipe_rows(&output.stdout, &SQUEUE_PENDING_HEADERS))
}

/// Time deltas in seconds (`timedelta.total_seconds()`; None when unknown).
pub type Etas = Vec<Option<f64>>;

/// `get_user_job_etas(user, now=now)`: (pending start deltas, running end deltas).
/// Consumers truncate with `int()`.
pub fn get_user_job_etas(user: Option<&str>, now: NaiveDateTime) -> Result<(Etas, Etas)> {
    let user = user_or_current(user);
    let jobs = get_user_jobs(Some(&user), None)?;
    let delta = |value: &str| iso_to_dt(value).map(|target| total_seconds(target, now));
    let (mut pending, mut running) = (Etas::new(), Etas::new());
    for job in &jobs {
        match job.get_str("JobState") {
            "PENDING" => pending.push(delta(job.get_str("StartTime"))),
            "RUNNING" => running.push(delta(job.get_str("EndTime"))),
            _ => {}
        }
    }
    Ok((pending, running))
}

/// `_history_sort_key(job)` compared like Python tuples.
fn history_order(a: &Record, b: &Record) -> std::cmp::Ordering {
    let key = |job: &Record| {
        let end = iso_to_dt(job.get_str("End")).map_or(f64::NEG_INFINITY, local_timestamp);
        let id = job.get_str("JobId").to_owned();
        (end, parse_int(Some(base_job_id(&id)), -1), id)
    };
    let (ka, kb) = (key(a), key(b));
    ka.0.total_cmp(&kb.0)
        .then(ka.1.cmp(&kb.1))
        .then_with(|| ka.2.cmp(&kb.2))
}

/// `load_job_history(user, strict=strict, since=since)`: sacct over a bounded window,
/// normalized (`JobId`, `StateToken`, `HistorySource`), newest first, unique by JobId.
/// Error message adds the `SLURM_CONF` tip for `host:localhost:6819`.
pub fn load_job_history(user: Option<&str>, strict: bool, since: &str) -> Result<Vec<Record>> {
    let user = user_or_current(user);
    let argv = vec![
        "sacct".to_owned(),
        "--parsable2".to_owned(),
        "--noheader".to_owned(),
        "-X".to_owned(),
        format!("--user={user}"),
        format!("--starttime={since}"),
        format!("--format={}", SACCT_HISTORY_HEADERS.join(",")),
    ];
    let output = slurm::run(&argv, false)?;
    if !output.success() {
        if !strict {
            return Ok(Vec::new());
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
        let slurm_conf_set = std::env::var_os("SLURM_CONF").is_some_and(|v| !v.is_empty());
        let hint = if detail.contains("host:localhost:6819") && !slurm_conf_set {
            " (tip: set SLURM_CONF to a user config that points AccountingStorageHost to your slurmdbd host)"
        } else {
            ""
        };
        return Err(die(format!(
            "{} failed: {detail}{hint}",
            pyfmt::shlex_join(&argv)
        )));
    }
    let mut history: Vec<Record> = Vec::new();
    for row in parse_pipe_rows(&output.stdout, &SACCT_HISTORY_HEADERS) {
        let raw = row.get_str("JobIDRaw");
        let id = pyfmt::strip(if raw.is_empty() {
            row.get_str("JobID")
        } else {
            raw
        })
        .to_owned();
        if id.is_empty() {
            continue;
        }
        let mut normalized = row.clone();
        normalized.insert("JobId".to_owned(), id);
        normalized.insert(
            "StateToken".to_owned(),
            normalize_sacct_state(row.get_str("State")),
        );
        normalized.insert("HistorySource".to_owned(), "sacct".to_owned());
        history.push(normalized);
    }
    history.sort_by(|a, b| history_order(b, a));
    let mut seen = std::collections::HashSet::new();
    history.retain(|row| seen.insert(row.get_str("JobId").to_owned()));
    Ok(history)
}

/// `get_user_job_history(user, finished_only=..., strict=..., since=...)`: without dev jobs.
pub fn get_user_job_history(
    user: Option<&str>,
    finished_only: bool,
    strict: bool,
    since: &str,
) -> Result<Vec<Record>> {
    Ok(load_job_history(user, strict, since)?
        .into_iter()
        .filter(|job| job.get_opt("JobName") != Some(DEV_JOB_NAME))
        .filter(|job| !finished_only || job_state_is_finished(job.get_str("State")))
        .collect())
}

/// `job_history_completion_ids(incomplete, user)` (2-day window, never fails).
pub fn job_history_completion_ids(incomplete: &str, user: Option<&str>) -> Vec<String> {
    let history = get_user_job_history(user, false, false, "now-2days").unwrap_or_default();
    let mut matches: Vec<String> = Vec::new();
    for job in &history {
        let job_id = job.get_str("JobId");
        if job_id.is_empty() {
            continue;
        }
        let root = base_job_id(job_id);
        let candidates = if root != job_id {
            vec![job_id, root]
        } else {
            vec![job_id]
        };
        for candidate in candidates {
            if candidate.is_empty() || matches.iter().any(|m| m == candidate) {
                continue;
            }
            if !incomplete.is_empty() && !candidate.starts_with(incomplete) {
                continue;
            }
            matches.push(candidate.to_owned());
        }
    }
    matches
}

/// `os.path.expandvars`: `$name` / `${name}` from the environment, unknown ones kept.
fn expandvars(path: &str) -> String {
    if !path.contains('$') {
        return path.to_owned();
    }
    let is_word = |b: u8| b.is_ascii_alphanumeric() || b == b'_';
    let mut path = path.to_owned();
    let mut i = 0;
    while let Some(offset) = path[i..].find('$') {
        let start = i + offset;
        let bytes = path.as_bytes();
        let after = start + 1;
        let (end, name) = if bytes.get(after) == Some(&b'{') {
            match path[after..].find('}') {
                Some(close) => (after + close + 1, path[after + 1..after + close].to_owned()),
                None => {
                    i = after;
                    continue;
                }
            }
        } else {
            let len = bytes[after..].iter().take_while(|&&b| is_word(b)).count();
            if len == 0 {
                i = after;
                continue;
            }
            (after + len, path[after..after + len].to_owned())
        };
        match std::env::var_os(&name) {
            Some(value) if !name.is_empty() => {
                let tail = path[end..].to_owned();
                path.truncate(start);
                path.push_str(&value.to_string_lossy());
                i = path.len();
                path.push_str(&tail);
            }
            _ => i = end,
        }
    }
    path
}

/// `str(PurePosixPath(path))` as root + parts: `//` kept, `.` and empty parts dropped.
fn posix_parts(path: &str) -> (&'static str, Vec<&str>) {
    let root = if path.starts_with("//") && !path.starts_with("///") {
        "//"
    } else if path.starts_with('/') {
        "/"
    } else {
        ""
    };
    let parts = path
        .split('/')
        .filter(|p| !p.is_empty() && *p != ".")
        .collect();
    (root, parts)
}

fn join_posix(root: &str, parts: &[&str]) -> String {
    let joined = format!("{root}{}", parts.join("/"));
    if joined.is_empty() {
        ".".to_owned()
    } else {
        joined
    }
}

/// `os.path.expanduser` of a single `~` / `~user` component.
fn expand_tilde(part: &str) -> Option<String> {
    let user = &part[1..];
    let home = if user.is_empty() {
        match std::env::var_os("HOME") {
            Some(home) => home.to_string_lossy().into_owned(),
            None => crate::hooks::home_of(None)?,
        }
    } else {
        crate::hooks::home_of(Some(user))?
    };
    let trimmed = home.trim_end_matches('/');
    Some(if trimmed.is_empty() {
        "/".to_owned()
    } else {
        trimmed.to_owned()
    })
}

/// `Path(path).expanduser()` as a string.
pub fn pathlib_expanduser(path: &str) -> String {
    let (root, parts) = posix_parts(path);
    if root.is_empty() {
        if let Some(first) = parts.first().filter(|p| p.starts_with('~')) {
            if let Some(home) = expand_tilde(first) {
                let (home_root, mut home_parts) = posix_parts(&home);
                home_parts.extend(&parts[1..]);
                return join_posix(home_root, &home_parts);
            }
        }
    }
    join_posix(root, &parts)
}

/// `resolve_slurm_output_path(template, job_id, raw_id=, name=, user=)`: `%J %j %A %a %x
/// %u %%` with zero-pad widths; unknown patterns kept; then `os.path.expandvars` and
/// `expanduser`. None for nullish templates.
pub fn resolve_slurm_output_path(
    template: &str,
    job_id: &str,
    raw_id: &str,
    name: &str,
    user: &str,
) -> Option<PathBuf> {
    if is_nullish(Some(template)) {
        return None;
    }
    let base_id = base_job_id(job_id);
    let task = job_id.split_once('_').map_or("0", |(_, task)| task);
    let value_of = |key: char| -> Option<&str> {
        Some(match key {
            'J' => {
                if raw_id.is_empty() {
                    job_id
                } else {
                    raw_id
                }
            }
            'j' => {
                if raw_id.is_empty() {
                    base_id
                } else {
                    raw_id
                }
            }
            'A' => base_id,
            'a' => task,
            'x' => name,
            'u' => user,
            _ => return None,
        })
    };
    // re.sub(r"%(\d*)(.)", fill, template.strip())
    let chars: Vec<char> = pyfmt::strip(template).chars().collect();
    let mut resolved = String::new();
    let mut i = 0;
    while i < chars.len() {
        if chars[i] != '%' {
            resolved.push(chars[i]);
            i += 1;
            continue;
        }
        let digits_end = (i + 1..chars.len())
            .find(|&k| !chars[k].is_ascii_digit())
            .unwrap_or(chars.len());
        let key_at = if digits_end < chars.len() && chars[digits_end] != '\n' {
            Some(digits_end)
        } else if digits_end > i + 1 {
            Some(digits_end - 1)
        } else {
            None
        };
        let Some(key_at) = key_at else {
            resolved.push('%');
            i += 1;
            continue;
        };
        let width: String = chars[i + 1..key_at].iter().collect();
        let key = chars[key_at];
        if key == '%' {
            resolved.push('%');
        } else {
            match value_of(key) {
                None => resolved.extend(&chars[i..=key_at]),
                Some(value) if width.is_empty() => resolved.push_str(value),
                Some(value) => {
                    resolved.push_str(&pyfmt::zfill(value, width.parse().unwrap_or(usize::MAX)))
                }
            }
        }
        i = key_at + 1;
    }
    Some(PathBuf::from(pathlib_expanduser(&expandvars(&resolved))))
}

/// Which output stream (`OutputStream`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OutputStream {
    Stdout,
    Stderr,
}

impl OutputStream {
    /// `"stdout"` / `"stderr"` as used in messages.
    pub fn as_str(self) -> &'static str {
        match self {
            OutputStream::Stdout => "stdout",
            OutputStream::Stderr => "stderr",
        }
    }
}

/// `resolve_job_output_path(job_id, stream=, user=)`: scontrol detail, else the sacct
/// fallback; None when unknown or owned by someone else.
pub fn resolve_job_output_path(
    job_id: &str,
    stream: OutputStream,
    user: Option<&str>,
) -> Result<Option<PathBuf>> {
    let field = match stream {
        OutputStream::Stdout => "StdOut",
        OutputStream::Stderr => "StdErr",
    };
    let expected_user = user_or_current(user);
    let mut detail = get_job_detail(job_id)?;
    if detail.is_none() {
        let argv = [
            "sacct",
            "-X",
            "-n",
            "-P",
            "-j",
            job_id,
            "--format=User,StdOut,StdErr,JobIDRaw,JobName,JobID",
        ];
        let headers = ["UserId", "StdOut", "StdErr", "JobIDRaw", "JobName", "JobID"];
        detail = slurm::run_parsable_rows(&argv, &headers, false)?
            .into_iter()
            .next();
    }
    let Some(detail) = detail else {
        return Ok(None);
    };
    let owner = user_from_userid(detail.get_str("UserId"));
    if !owner.is_empty() && owner != expected_user {
        return Ok(None);
    }
    let display_id = detail.get_str("JobID");
    Ok(resolve_slurm_output_path(
        detail.get_str(field),
        if display_id.is_empty() {
            job_id
        } else {
            display_id
        },
        detail.get_str("JobIDRaw"),
        detail.get_str("JobName"),
        if owner.is_empty() {
            &expected_user
        } else {
            owner
        },
    ))
}

/// `read_log_tail(path, max_lines=)`: last N lines (UTF-8, errors replaced, universal
/// newlines; 0 = all); OSError -> `die("could not read {path}: {exc}")` with Python's
/// `str(OSError)` format (`[Errno 13] Permission denied: '/path'`). Python keeps the last
/// N lines in a deque; bab reads the file backwards from the end, so memory is bounded by
/// the size of those lines as well (and a huge log is not read in full).
pub fn read_log_tail(path: &Path, max_lines: usize) -> Result<String> {
    let fail = |err: std::io::Error| {
        die(format!(
            "could not read {}: {}",
            path.display(),
            pyfmt::os_error_str(&err, path)
        ))
    };
    let bytes = if max_lines == 0 {
        std::fs::read(path).map_err(fail)?
    } else {
        let mut file = std::fs::File::open(path).map_err(fail)?;
        tail_lines_bytes(&mut file, max_lines).map_err(fail)?
    };
    Ok(pyfmt::decode_text(bytes))
}

/// The bytes of the last `max_lines` (> 0) lines of `file`, line ends as in Python's
/// universal newlines mode (`\n`, `\r\n`, `\r`; a final line may lack one). The bytes
/// `\r`/`\n` never occur inside a UTF-8 sequence and end any invalid one, so decoding
/// these bytes gives exactly the tail of the decoded file.
fn tail_lines_bytes(
    file: &mut (impl std::io::Read + std::io::Seek),
    max_lines: usize,
) -> std::io::Result<Vec<u8>> {
    use std::io::SeekFrom;
    const BLOCK: u64 = 64 * 1024;
    let end = file.seek(SeekFrom::End(0))?;
    let mut pos = end;
    // blocks from the end of the file backwards
    let mut blocks: Vec<Vec<u8>> = Vec::new();
    let mut after: Option<u8> = None;
    let mut found = 0;
    'scan: while pos > 0 {
        let start = pos.saturating_sub(BLOCK);
        let mut block = vec![0u8; (pos - start) as usize];
        file.seek(SeekFrom::Start(start))?;
        file.read_exact(&mut block)?;
        for i in (0..block.len()).rev() {
            let byte = block[i];
            let line_end = byte == b'\n' || (byte == b'\r' && after != Some(b'\n'));
            after = Some(byte);
            // the line end of the last line does not start another line
            if line_end && start + i as u64 + 1 != end {
                found += 1;
                if found == max_lines {
                    block.drain(..=i);
                    blocks.push(block);
                    break 'scan;
                }
            }
        }
        blocks.push(block);
        pos = start;
    }
    blocks.reverse();
    Ok(blocks.concat())
}

/// `get_job_output(job_id, stream=, tail_lines=, user=)` -> (path, text), with the
/// Python die() messages for unresolvable/missing/non-file paths.
pub fn get_job_output(
    job_id: &str,
    stream: OutputStream,
    tail_lines: usize,
    user: Option<&str>,
) -> Result<(PathBuf, String)> {
    let stream_name = stream.as_str();
    let Some(path) = resolve_job_output_path(job_id, stream, user)? else {
        return Err(die(format!(
            "could not resolve {stream_name} path for job {job_id}"
        )));
    };
    if !path.exists() {
        return Err(die(format!(
            "{stream_name} file for job {job_id} does not exist yet: {}",
            path.display()
        )));
    }
    if !path.is_file() {
        return Err(die(format!(
            "{stream_name} path for job {job_id} is not a file: {}",
            path.display()
        )));
    }
    let text = read_log_tail(&path, tail_lines)?;
    Ok((path, text))
}

/// `find_dev_jobs(user, job_id=)`: active (not COMPLETING) `ab-dev` jobs, RUNNING first,
/// newest SubmitTime first.
pub fn find_dev_jobs(user: Option<&str>, job_id: Option<&str>) -> Result<Vec<Record>> {
    let jobs = get_user_jobs(user, Some(DEV_JOB_NAME))?;
    Ok(filter_dev_jobs(jobs, job_id))
}

fn filter_dev_jobs(jobs: Vec<Record>, job_id: Option<&str>) -> Vec<Record> {
    let mut jobs: Vec<Record> = jobs
        .into_iter()
        .filter(|job| {
            let state = job.get_str("JobState");
            job.get_opt("JobName") == Some(DEV_JOB_NAME)
                && ACTIVE_STATES.contains(&state)
                && state != "COMPLETING"
                && job_id.is_none_or(|id| {
                    job.get_opt("JobId") == Some(id)
                        || base_job_id(job.get_str("JobId")) == base_job_id(id)
                })
        })
        .collect();
    let key = |job: &Record| {
        let rank = i32::from(job.get_str("JobState") != "RUNNING");
        let time = iso_to_dt(job.get_str("SubmitTime")).map_or(0.0, |t| -local_timestamp(t));
        (rank, time)
    };
    jobs.sort_by(|a, b| {
        let (ka, kb) = (key(a), key(b));
        ka.0.cmp(&kb.0).then(ka.1.total_cmp(&kb.1))
    });
    jobs
}

#[cfg(test)]
mod tests {
    //! Port of the job parts of `tests/test_slurm.py`, `test_parsing.py` and `test_dev.py`.
    use super::*;
    use crate::core::slurm::Output;
    use crate::core::slurm::fake::{FakeSlurm, fail, ok};
    use crate::hooks::testing::Ctx;

    fn rec(pairs: &[(&str, &str)]) -> Record {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    const SACCT_HISTORY_OUTPUT: &str = "12345|12345|training|COMPLETED|0:0|2024-05-01T10:00:00|None\n\
12346|12346|inference|FAILED|1:0|2024-05-02T11:30:00|None\n\
12347|12347|data_prep|CANCELLED by 12000|0:9|2024-05-03T09:00:00|None\n\
12348|12348|ab-dev|COMPLETED|0:0|2024-05-04T08:00:00|None\n";

    fn history(output: Output) -> Vec<Record> {
        let _ctx = Ctx::default().slurm(FakeSlurm::always(output)).install();
        load_job_history(Some("alice"), true, "now-30days").unwrap()
    }

    #[test]
    fn display_ids() {
        assert_eq!(
            display_job_id(&rec(&[
                ("JobId", "12345"),
                ("ArrayJobId", "N/A"),
                ("ArrayTaskId", "N/A")
            ])),
            "12345"
        );
        assert_eq!(
            display_job_id(&rec(&[
                ("JobId", "12345_3"),
                ("ArrayJobId", "12345"),
                ("ArrayTaskId", "3")
            ])),
            "12345_3"
        );
        assert_eq!(
            display_job_id(&rec(&[
                ("JobId", "12345"),
                ("ArrayJobId", "12345"),
                ("ArrayTaskId", "(null)")
            ])),
            "12345"
        );
        assert_eq!(
            display_job_id(&rec(&[
                ("JobId", "12345"),
                ("ArrayJobId", "12345"),
                ("ArrayTaskId", "N/A")
            ])),
            "12345"
        );
    }

    #[test]
    fn job_history() {
        let rows = history(ok(SACCT_HISTORY_OUTPUT));
        assert_eq!(rows.len(), 4);
        let ids: Vec<&str> = rows.iter().map(|j| j.get_str("JobId")).collect();
        assert_eq!(ids, ["12348", "12347", "12346", "12345"]);
        let cancelled = rows.iter().find(|j| j["JobId"] == "12347").unwrap();
        assert_eq!(cancelled["StateToken"], "CANCELLED");
        assert!(rows.iter().all(|j| j["HistorySource"] == "sacct"));
        let duplicated = format!(
            "{SACCT_HISTORY_OUTPUT}12345|12345|training|COMPLETED|0:0|2024-05-01T10:00:00|None\n"
        );
        let rows = history(ok(&duplicated));
        assert_eq!(rows.iter().filter(|j| j["JobId"] == "12345").count(), 1);
        assert!(history(ok("")).is_empty());
        let _ctx = Ctx::default()
            .slurm(FakeSlurm::always(fail(1, "")))
            .install();
        assert!(
            load_job_history(Some("alice"), false, "now-30days")
                .unwrap()
                .is_empty()
        );
    }

    #[test]
    fn history_window_and_unknown_end_times() {
        let fake = FakeSlurm::always(ok(
            "7|7|a|RUNNING|0:0|Unknown|None\n8|8|b|COMPLETED|0:0|2024-05-01T10:00:00|None\n9_1|9_1|c|COMPLETED|0:0|2024-05-01T10:00:00|None\n|10|d|X|0:0||\n|  |e|X|0:0||\n",
        ));
        let _ctx = Ctx::default().slurm(fake.clone()).install();
        let rows = load_job_history(Some("alice"), true, "now-30days").unwrap();
        let ids: Vec<&str> = rows.iter().map(|j| j.get_str("JobId")).collect();
        assert_eq!(ids, ["9_1", "8", "10", "7"]);
        assert_eq!(
            fake.calls()[0],
            [
                "sacct",
                "--parsable2",
                "--noheader",
                "-X",
                "--user=alice",
                "--starttime=now-30days",
                "--format=JobIDRaw,JobID,JobName,State,ExitCode,End,Reason"
            ]
        );
    }

    #[test]
    fn completion_ids_from_two_days_of_history() {
        let fake = FakeSlurm::always(ok(
            "130|123_7|t|COMPLETED|0:0|2024-05-03T10:00:00|None\n123_6|123_6|t|COMPLETED|0:0|2024-05-02T10:00:00|None\n99|99|ab-dev|COMPLETED|0:0|2024-05-04T10:00:00|None\n",
        ));
        let _ctx = Ctx::default().slurm(fake.clone()).install();
        assert_eq!(
            job_history_completion_ids("", Some("alice")),
            ["130", "123_6", "123"]
        );
        assert_eq!(
            job_history_completion_ids("12", Some("alice")),
            ["123_6", "123"]
        );
        assert!(fake.calls()[0].contains(&"--starttime=now-2days".to_owned()));
        let _ctx = Ctx::default()
            .slurm(FakeSlurm::always(fail(1, "down")))
            .install();
        assert!(job_history_completion_ids("", Some("alice")).is_empty());
    }

    #[test]
    fn job_records_reduced_like_full_parse() {
        use serde_json::json;
        let doc = r#"{"meta": {"x": [1, {"jobs": 2}]}, "jobs": [
            {"job_id": 1, "job_state": ["PENDING"], "flags": ["A"], "cpus": {"set": true,
             "infinite": false, "number": 4}, "job_resources": {"nodes": {"list": "a"}},
             "user_name": "x", "user_name": "alice"},
            {"job_id": 2, "command": "a \"b\""}], "warnings": []}"#;
        assert_eq!(
            job_records_json(doc).unwrap(),
            [
                json!({"job_id": 1, "job_state": ["PENDING"], "user_name": "alice",
                       "cpus": {"set": true, "infinite": false, "number": 4}}),
                json!({"job_id": 2}),
            ]
        );
        // unexpected shapes: whatever the full parse says
        let escaped = r#"{"jobs": [{"job\u005fid": 1}]}"#;
        assert_eq!(job_records_json(escaped).unwrap(), [json!({"job_id": 1})]);
        assert_eq!(
            job_records_json(r#"{"jobs": [1, {"x": 2}]}"#).unwrap(),
            [json!(1), json!({"x": 2})]
        );
        for empty in [r#"{"jobs": null}"#, r#"{"jobs": {}}"#, "{}"] {
            assert_eq!(job_records_json(empty), Some(Vec::new()), "{empty}");
        }
        for bad in [
            "not json",
            "[]",
            r#"{"jobs": []} x"#,
            r#"{"jobs": [{"job_id": 1e999}]}"#,
        ] {
            assert_eq!(job_records_json(bad), None, "{bad}");
        }
    }

    /// Every key fit.rs and why.rs read from a job record is in JOB_KEYS (sorted: it is
    /// binary-searched).
    #[test]
    fn job_keys_cover_reads() {
        assert!(JOB_KEYS.is_sorted());
        let read = regex::Regex::new(
            r#"(?:number|text|string_list|field_is|\.get)\(\s*(?:&?[a-z_]+,\s*)?"([a-z_]+)""#,
        )
        .unwrap();
        // nested keys: Slurm's number wrapper, the parsed tres_req_str
        let nested = ["set", "infinite", "number", "cpu", "mem"];
        for source in [
            include_str!("../fit.rs"),
            include_str!("../handlers/why.rs"),
        ] {
            let code = source.split("#[cfg(test)]").next().unwrap();
            for caps in read.captures_iter(code) {
                let key = &caps[1];
                assert!(JOB_KEYS.contains(&key) || nested.contains(&key), "{key}");
            }
        }
    }

    #[test]
    fn job_records() {
        let fake = FakeSlurm::always(ok(
            r#"{"jobs": [{"job_id": 65177, "job_state": ["PENDING"]}]}"#,
        ));
        let _ctx = Ctx::default().slurm(fake.clone()).install();
        let records = load_job_records(None, true).unwrap();
        assert_eq!(
            records,
            [serde_json::json!({"job_id": 65177, "job_state": ["PENDING"]})]
        );
        assert_eq!(fake.calls()[0], ["scontrol", "--json", "show", "job"]);
        let fake = FakeSlurm::always(fail(1, ""));
        let _ctx = Ctx::default().slurm(fake.clone()).install();
        assert!(load_job_records(Some("999999"), true).unwrap().is_empty());
        assert_eq!(
            fake.calls()[0],
            ["scontrol", "--json", "show", "job", "999999"]
        );
        assert!(load_job_records(None, false).unwrap().is_empty());
        let _ctx = Ctx::default()
            .slurm(FakeSlurm::always(ok("not json")))
            .install();
        assert!(load_job_records(None, false).unwrap().is_empty());
    }

    const MULTI_NODE_LINE: &str = "JobId=7 JobName=big UserId=alice(1000) JobState=RUNNING NodeList=gpu[081-082] \
Nodes=gpu081 CPU_IDs=0-7 Mem=1000 GRES=gpu:a100:2(IDX:0-1) \
Nodes=gpu082 CPU_IDs=0-7 Mem=1000 GRES=gpu:a100:2(IDX:2-3) \
MinCPUsNode=1";

    #[test]
    fn gres_per_node_block() {
        let _ctx = Ctx::default()
            .slurm(FakeSlurm::always(ok(&format!("{MULTI_NODE_LINE}\n"))))
            .install();
        let jobs = load_job_details(None).unwrap();
        assert_eq!(jobs.len(), 1);
        assert_eq!(job_gres_on_node(&jobs[0], "gpu081"), "gpu:a100:2(IDX:0-1)");
        assert_eq!(job_gres_on_node(&jobs[0], "gpu082"), "gpu:a100:2(IDX:2-3)");
        assert_eq!(job_on_node(&jobs[0], "gpu082")["Mem"], "1000");
        assert_eq!(
            job_gres_on_node(&rec(&[("GRES", "gpu:1(IDX:0)")]), "gpu001"),
            "gpu:1(IDX:0)"
        );
    }

    fn sacct_fallback(sacct_stdout: &'static str) -> crate::hooks::testing::Guard {
        let fake = FakeSlurm::new(move |argv| {
            Some(if argv[0] == "scontrol" {
                fail(1, "")
            } else {
                ok(sacct_stdout)
            })
        });
        Ctx::default().slurm(fake).install()
    }

    fn output_path(job_id: &str) -> Option<String> {
        resolve_job_output_path(job_id, OutputStream::Stdout, Some("alice"))
            .unwrap()
            .map(|p| p.display().to_string())
    }

    #[test]
    fn job_output_falls_back_to_sacct() {
        let _ctx = sacct_fallback("alice|/home/alice/out-%j.txt|/home/alice/err-%j.txt\n");
        assert_eq!(output_path("42").as_deref(), Some("/home/alice/out-42.txt"));
        let _ctx = sacct_fallback("alice|/logs/out-%j.log||71512|train\n");
        assert_eq!(
            output_path("71485_0").as_deref(),
            Some("/logs/out-71512.log")
        );
        let _ctx = sacct_fallback("alice|/logs/%u/%x-%j.out||42|train\n");
        assert_eq!(
            output_path("42").as_deref(),
            Some("/logs/alice/train-42.out")
        );
        let _ctx = sacct_fallback("alice|/h/%x-%A_%a.out||130|train|123_7\n");
        assert_eq!(output_path("130").as_deref(), Some("/h/train-123_7.out"));
        let _ctx = sacct_fallback("bob|/home/bob/out.txt|\n");
        assert_eq!(output_path("42"), None);
        let _ctx = sacct_fallback("");
        assert_eq!(output_path("42"), None);
    }

    #[test]
    fn forgotten_task_never_borrows_a_sibling_tasks_log() {
        let fake = FakeSlurm::new(|argv| {
            Some(if argv[0] == "scontrol" {
                if argv.last().unwrap() == "123" {
                    ok("JobId=130 UserId=alice(1) StdOut=/h/out-123_7.log\n")
                } else {
                    fail(1, "")
                }
            } else {
                ok("alice|/h/out-%A_%a.log||128|train|123_5\n")
            })
        });
        let _ctx = Ctx::default().slurm(fake).install();
        assert_eq!(output_path("123_5").as_deref(), Some("/h/out-123_5.log"));
    }

    #[test]
    fn output_path_templates() {
        let r = |t: &str, id: &str| {
            resolve_slurm_output_path(t, id, "", "", "").map(|p| p.display().to_string())
        };
        assert_eq!(
            r("/home/user/output.txt", "12345").as_deref(),
            Some("/home/user/output.txt")
        );
        assert_eq!(
            r("/home/user/job-%J.out", "12345").as_deref(),
            Some("/home/user/job-12345.out")
        );
        assert_eq!(
            r("/home/user/job-%j.out", "12345_3").as_deref(),
            Some("/home/user/job-12345.out")
        );
        assert_eq!(
            r("/home/user/job-%A_%a.out", "12345_3").as_deref(),
            Some("/home/user/job-12345_3.out")
        );
        assert_eq!(r("(null)", "12345"), None);
        assert_eq!(r("", "12345"), None);
        assert_eq!(
            r("/out/100%%-%4a-%N.out", "7_3").as_deref(),
            Some("/out/100%-0003-%N.out")
        );
        assert_eq!(
            r("/out/%A_%a.out", "12345").as_deref(),
            Some("/out/12345_0.out")
        );
        assert_eq!(r("/out//./x/%5", "1").as_deref(), Some("/out/x/%5"));
        assert_eq!(r("rel/%", "1").as_deref(), Some("rel/%"));
        assert_eq!(
            r("/a/${BAB_SURELY_UNSET}/$BAB_SURELY_UNSET/x", "1").as_deref(),
            Some("/a/${BAB_SURELY_UNSET}/$BAB_SURELY_UNSET/x")
        );
        let home = std::env::var("HOME").unwrap_or_default();
        let tilde = r("~/slurm-output/job-%j.out", "12345").unwrap();
        assert!(tilde.starts_with(home.trim_end_matches('/')), "{tilde}");
        assert!(tilde.ends_with("/slurm-output/job-12345.out"));
        assert_eq!(
            r("~nosuchuser-bab/x", "1").as_deref(),
            Some("~nosuchuser-bab/x")
        );
    }

    #[test]
    fn user_jobs_ask_only_for_the_user() {
        let fake = FakeSlurm::new(|argv| {
            Some(if argv[0] == "squeue" {
                ok("71485\n71485\n42\n")
            } else {
                ok(&format!(
                    "JobId={} UserId=alice(1) JobState=RUNNING\n",
                    argv.last().unwrap()
                ))
            })
        });
        let _ctx = Ctx::default().slurm(fake.clone()).install();
        let jobs = get_user_jobs(Some("alice"), None).unwrap();
        let ids: Vec<&str> = jobs.iter().map(|j| j.get_str("JobId")).collect();
        assert_eq!(ids, ["71485", "42"]);
        let calls = fake.calls();
        assert!(
            !calls
                .iter()
                .any(|c| c == &["scontrol", "--oneliner", "--details", "show", "job"])
        );
        assert!(calls[0].contains(&"--user=alice".to_owned()));
        assert_eq!(calls.len(), 3);
    }

    #[test]
    fn job_that_ended_meanwhile_is_skipped() {
        let fake = FakeSlurm::new(|argv| {
            Some(if argv[0] == "squeue" {
                ok("42\n")
            } else {
                fail(1, "Invalid job id specified")
            })
        });
        let _ctx = Ctx::default().slurm(fake).install();
        assert!(get_user_jobs(Some("alice"), None).unwrap().is_empty());
    }

    #[test]
    fn many_jobs_use_one_full_listing() {
        let ids: String = (1..=21).map(|i| format!("{i}\n")).collect();
        let fake = FakeSlurm::new(move |argv| {
            Some(if argv[0] == "squeue" {
                ok(&ids)
            } else {
                ok(
                    "JobId=1 UserId=alice(1) JobName=ab-dev\nJobId=2 UserId=bob(2) JobName=ab-dev\nJobId=3 UserId=alice(1) JobName=x\n",
                )
            })
        });
        let _ctx = Ctx::default().slurm(fake.clone()).install();
        let jobs = get_user_jobs(Some("alice"), Some("ab-dev")).unwrap();
        assert_eq!(jobs.len(), 1);
        assert_eq!(jobs[0]["JobId"], "1");
        assert_eq!(
            fake.calls(),
            [
                vec![
                    "squeue",
                    "-h",
                    "--user=alice",
                    "--format=%F",
                    "--name=ab-dev"
                ],
                vec!["scontrol", "--oneliner", "--details", "show", "job"],
            ]
        );
    }

    #[test]
    fn etas() {
        let fake = FakeSlurm::new(|argv| {
            Some(if argv[0] == "squeue" {
                ok("1\n2\n3\n")
            } else {
                match argv.last().unwrap().as_str() {
                    "1" => ok("JobId=1 JobState=PENDING StartTime=2026-10-06T16:40:00\n"),
                    "2" => ok("JobId=2 JobState=RUNNING EndTime=2026-10-06T14:00:00\n"),
                    _ => ok("JobId=3 JobState=PENDING StartTime=Unknown\n"),
                }
            })
        });
        let _ctx = Ctx::default().slurm(fake).install();
        let now = iso_to_dt("2026-10-06T14:30:00").unwrap();
        let (pending, running) = get_user_job_etas(Some("alice"), now).unwrap();
        assert_eq!(pending, [Some(7800.0), None]);
        assert_eq!(running, [Some(-1800.0)]);
    }

    #[test]
    fn completing_dev_job_no_longer_counts() {
        let running = rec(&[
            ("JobId", "111"),
            ("JobName", "ab-dev"),
            ("JobState", "RUNNING"),
            ("SubmitTime", "2030-01-01T08:00:00"),
        ]);
        let mut completing = running.clone();
        completing.insert("JobState".into(), "COMPLETING".into());
        let mut other = running.clone();
        other.insert("JobId".into(), "222".into());
        let ids: Vec<String> = filter_dev_jobs(vec![completing, other], None)
            .iter()
            .map(|j| j["JobId"].clone())
            .collect();
        assert_eq!(ids, ["222"]);
    }

    #[test]
    fn dev_jobs_order_and_filter() {
        let job = |id: &str, state: &str, submit: &str| {
            rec(&[
                ("JobId", id),
                ("JobName", "ab-dev"),
                ("JobState", state),
                ("SubmitTime", submit),
            ])
        };
        let jobs = vec![
            job("1", "PENDING", "2030-01-01T09:00:00"),
            job("2", "RUNNING", "2030-01-01T08:00:00"),
            job("3", "RUNNING", "2030-01-01T10:00:00"),
            job("4_1", "PENDING", "Unknown"),
            job("5", "SUSPENDED", "2030-01-01T10:00:00"),
        ];
        let ids = |jobs: Vec<Record>| jobs.iter().map(|j| j["JobId"].clone()).collect::<Vec<_>>();
        assert_eq!(
            ids(filter_dev_jobs(jobs.clone(), None)),
            ["3", "2", "1", "4_1"]
        );
        assert_eq!(ids(filter_dev_jobs(jobs, Some("4_7"))), ["4_1"]);
    }

    #[test]
    fn log_tails() {
        let dir = std::env::current_exe()
            .unwrap()
            .parent()
            .unwrap()
            .parent()
            .unwrap()
            .join(format!("bab-test-scratch/logs-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("out.log");
        std::fs::write(&path, b"a\r\nb\rc\nd\xff\ne").unwrap();
        assert_eq!(read_log_tail(&path, 0).unwrap(), "a\nb\nc\nd\u{fffd}\ne");
        assert_eq!(read_log_tail(&path, 2).unwrap(), "d\u{fffd}\ne");
        assert_eq!(read_log_tail(&path, 99).unwrap(), "a\nb\nc\nd\u{fffd}\ne");
        std::fs::write(&path, "x\ny\n").unwrap();
        assert_eq!(read_log_tail(&path, 1).unwrap(), "y\n");
        assert_eq!(read_log_tail(&path, 2).unwrap(), "x\ny\n");
        std::fs::remove_dir_all(dir).unwrap();
    }

    /// Python's `"".join(deque(open(..., errors="replace"), maxlen=n))`, over the whole
    /// decoded text (what bab did before reading backwards).
    fn deque_tail(bytes: &[u8], n: usize) -> String {
        let text = pyfmt::decode_text(bytes.to_vec());
        let mut lines: Vec<&str> = text.split_inclusive('\n').collect();
        let keep = lines.len().saturating_sub(n);
        lines.drain(..keep);
        lines.concat()
    }

    #[test]
    fn log_tail_read_backwards_matches_the_whole_file_tail() {
        let mut cases: Vec<Vec<u8>> = [
            &b""[..],
            b"\n",
            b"\r",
            b"\r\n",
            b"\n\n\r\r\n\n",
            b"a",
            b"a\rb",
            b"a\r\n\r\nb\r",
            b"\xe2\x82\ra\xe2\n\xff\xfe\r\n\xf0\x9f\x98",
            "snow \u{2603}\r\nline\n".as_bytes(),
        ]
        .iter()
        .map(|b| b.to_vec())
        .collect();
        // line ends and a split \r\n around the 64 KiB block boundary
        for at in [65534usize, 65535, 65536, 65537] {
            let mut big = vec![b'x'; 70000];
            big[at] = b'\r';
            big[at + 1] = b'\n';
            big[3] = b'\n';
            cases.push(big.clone());
            big[at + 1] = b'\r';
            cases.push(big);
        }
        let mut seed = 7u64;
        for _ in 0..200 {
            let len = (seed % 300) as usize;
            let bytes = (0..len)
                .map(|_| {
                    seed = seed
                        .wrapping_mul(6364136223846793005)
                        .wrapping_add(1442695040888963407);
                    b"ab\r\n\xe2\x98\x83\xff"[(seed >> 33) as usize % 8]
                })
                .collect();
            cases.push(bytes);
        }
        for bytes in &cases {
            for n in [1, 2, 3, 5, 100, 100_000] {
                let tail = tail_lines_bytes(&mut std::io::Cursor::new(bytes), n).unwrap();
                assert_eq!(
                    pyfmt::decode_text(tail),
                    deque_tail(bytes, n),
                    "{bytes:?} n={n}"
                );
            }
        }
    }
}
