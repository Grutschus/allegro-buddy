//! Shared output helpers from `core.py`: `warn`, `hint`, `render_table`, `as_cell` and the
//! `*_text` styling helpers. Owned by P2-C (uses P2-A's render API).
//!
//! Styling never calls Slurm: `partition_text`/`node_text` only read settings and the
//! already-loaded node facts ([`super::nodes::loaded_node_facts`]).

use crate::render::table::{Cell, Justify};
use crate::render::text::Text;

/// One table row (`TableRow`): cells as Python passes them (`str` or `Text`; Python
/// `None`/`""` -> pass `Cell::Str(String::new())`, rendered as a dim `-` by [`as_cell`]).
pub type TableRow = Vec<Cell>;

/// `warn(message)`: `Text.assemble(("warning: ", "bold yellow"), message)` on stderr.
pub fn warn(message: impl Into<Text>) {
    todo!()
}

/// `hint(text)`: `Text(f"ⓘ {text}", style="dim")` on stdout.
pub fn hint(text: &str) {
    todo!()
}

/// `as_cell(value)`: Text as is; empty str -> `Text("-", style="dim")`; str as is.
pub fn as_cell(cell: Cell) -> Cell {
    todo!()
}

/// `render_table(columns, rows, title=, caption=, section_breaks=, width=)`:
/// no rows -> `muted("Nothing to show.")`; else [`crate::render::Table::simple`] with
/// `end_section` on the rows in `section_breaks`, printed with `width`, then the caption
/// as `muted(caption)` on its own line (not Rich's caption).
pub fn render_table(
    columns: &[(&str, Justify)],
    rows: Vec<TableRow>,
    title: Option<&str>,
    caption: Option<&str>,
    section_breaks: &[usize],
    width: Option<usize>,
) {
    todo!()
}

/// `state_text(state)`: [`super::STATE_STYLES`] or `white`.
pub fn state_text(state: &str) -> Text {
    todo!()
}

/// `partition_text(name)`: `bold green` for GPU partitions (no detection), `bold blue`
/// when nodes are loaded or `gpu_partitions` configured, else `bold`.
pub fn partition_text(name: &str) -> Text {
    todo!()
}

/// `node_text(name, partition)`: `(pending)`/empty -> yellow; green for GPU nodes (loaded
/// facts or a GPU partition of the job), else blue.
pub fn node_text(name: &str, partition: &str) -> Text {
    todo!()
}

/// `job_id_text(job_id)`: cyan.
pub fn job_id_text(job_id: &str) -> Text {
    Text::styled(job_id, "cyan")
}

/// `ratio_text(free, total, unit=, free_style=)`: `free/total[unit]` (free in
/// `free_style` or dim when 0, rest dim); total <= 0 -> dim `-`.
pub fn ratio_text(free: i64, total: i64, unit: &str, free_style: &str) -> Text {
    todo!()
}

/// `muted(value)`: `Text(value, style="dim")` (Python default `"-"`).
pub fn muted(value: &str) -> Text {
    Text::styled(value, "dim")
}

/// `gpu_free_text(free, usable, total)`: `usable[+n]/total`.
pub fn gpu_free_text(free: i64, usable: i64, total: i64) -> Text {
    todo!()
}

/// `exit_code_text(exit_code)`.
pub fn exit_code_text(exit_code: &str) -> Text {
    todo!()
}

/// `build_job_history_rows(jobs)` (uses `format_history_end` with `hooks::now()`).
pub fn build_job_history_rows(jobs: &[super::Record]) -> Vec<TableRow> {
    todo!()
}

/// `build_dev_job_rows(jobs)`.
pub fn build_dev_job_rows(jobs: &[super::Record]) -> Vec<TableRow> {
    todo!()
}
