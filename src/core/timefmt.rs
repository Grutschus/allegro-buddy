//! Time parsing/formatting from `core.py`. Owned by P2-C. "now" always comes from
//! [`crate::hooks::now`]; functions take it as a parameter where Python has `now=`.
//!
//! Python datetimes here are naive local times; `datetime.fromisoformat` accepts
//! `YYYY-MM-DDTHH:MM:SS` (Slurm's format) and more (Python 3.11+ accepts most ISO 8601,
//! incl. offsets: an aware datetime then breaks `end - now` with a TypeError; Slurm never
//! sends one). `strftime("%a"/"%b")` uses the C locale (English names) since Python
//! doesn't call setlocale.

use chrono::NaiveDateTime;

/// `parse_slurm_time("1-02:03:04")` -> seconds; `UNLIMITED`/`INFINITE`/`INFINITY`/`N/A`
/// -> None; unparseable -> None. `MM:SS` without a day part, `D-HH:MM` with one; a single
/// number is minutes (`D-HH` with a day part). Python `int()` accepts surrounding
/// whitespace, `+`/`-` signs and `_` digit separators.
pub fn parse_slurm_time(value: &str) -> Option<i64> {
    todo!()
}

/// `format_seconds(value)`: None -> `unlimited`; `45s`, `40m`, `6h35m`, `2d2h`
/// (negatives clamp to 0 -> `0s`).
pub fn format_seconds(value: Option<i64>) -> String {
    todo!()
}

/// `iso_to_dt(value)`: None for empty, `Unknown`, `N/A`, `None` or unparseable.
pub fn iso_to_dt(value: &str) -> Option<NaiveDateTime> {
    todo!()
}

/// `int((a - b).total_seconds())` (truncation toward zero, microseconds included).
pub fn delta_seconds(a: NaiveDateTime, b: NaiveDateTime) -> i64 {
    todo!()
}

/// `format_eta(end_time, now=now)`: `unknown` or `format_seconds(end - now)`.
pub fn format_eta(end_time: &str, now: NaiveDateTime) -> String {
    todo!()
}

/// `format_eta(end_time)` with `now = hooks::now()`.
pub fn format_eta_now(end_time: &str) -> String {
    format_eta(end_time, crate::hooks::now())
}

/// `format_pending_start(start_time, now=now)`: `in 2h10m (Tue 16:40)`,
/// `due (Tue 16:40)`, or None; dates `< 7` calendar days ahead show the weekday, later
/// ones `%b %d %H:%M`.
pub fn format_pending_start(start_time: &str, now: NaiveDateTime) -> Option<String> {
    todo!()
}

/// `format_history_end(end_time, now=now)`: `today 08:41`, `Mon 23:17` (1..6 days ago),
/// `%b %d %H:%M` same year, else `%Y-%m-%d`; unparseable: `-` if nullish else verbatim.
pub fn format_history_end(end_time: &str, now: NaiveDateTime) -> String {
    todo!()
}

/// `datetime.fromtimestamp(epoch).isoformat()` in local time (TZ honoured), used by
/// `why._start_text`.
pub fn local_iso_from_epoch(epoch: i64) -> String {
    todo!()
}

/// `dt.timestamp()` of a naive local datetime (sorting keys in history/dev jobs).
pub fn local_timestamp(dt: NaiveDateTime) -> f64 {
    todo!()
}
