//! rich-click 1.9.9 help output and error rendering. Owned by P2-B.
//!
//! Configuration (Python `CLICK_CONTEXT_SETTINGS`): `RichHelpConfiguration(theme='modern',
//! commands_table_column_types=['name_with_aliases', 'help'], max_width=100)`; the
//! `RICH_CLICK_THEME` env var overrides the theme (rich-click reads it); rich-click also
//! reads `FORCE_COLOR`, `PY_COLORS`, `GITHUB_ACTIONS` (forces colour/terminal) at import:
//! replicate what rich-click 1.9.9 does with them. Help width: `min(console width, 100)`,
//! lines padded with trailing spaces to the full width (see the old snapshot
//! `git show main:tests/snapshots/allegro-help.txt`).
//!
//! Pieces: usage line (`Usage: bab dev start [OPTIONS]`), help text paragraphs, `Options`
//! panel (decls column `-h   --help` layout, metavars like `TEXT`, `INTEGER`,
//! `FLOAT RANGE`, `[SECONDS]`, `[gpu|cpu]`, `[default: ...]`, range hints `x>=10`), the
//! `Commands` panel with `name_with_aliases` (`queue, q`), argument display. Usage
//! errors: rich-click error format (usage line, `Try 'bab -h' for help`, error panel) on
//! stderr, exit 2. `ClickException`: rich-click "Error" rendering, exit 1.
//! `Aborted!` for `click.Abort`.

use super::commands::Command;
use crate::error::UsageError;

/// Print the help page of the command at `path` (`["bab", "dev"]`) to stdout.
pub fn print_help(path: &[String], command: &Command) {
    todo!()
}

/// Print a usage error the rich-click way to stderr.
pub fn print_usage_error(error: &UsageError) {
    todo!()
}

/// Print a `ClickException` message the rich-click way to stderr.
pub fn print_click_exception(message: &str) {
    todo!()
}

/// Print click's `Aborted!` to stderr.
pub fn print_aborted() {
    todo!()
}
