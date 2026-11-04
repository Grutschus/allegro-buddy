//! Shell completion: click 8.3.2's completion protocol and scripts, plus `bab completion`.
//! Owned by P2-B (protocol, scripts) and P3-F (command wiring/`--install`).
//!
//! * Protocol: when `_BAB_COMPLETE` (click: `_{PROG}_COMPLETE` with the prog name
//!   upper-cased and `-`/`.` replaced by `_`; prog = basename of argv[0]) is set to
//!   `bash_source|zsh_source|fish_source`, print the script; `bash_complete|zsh_complete|
//!   fish_complete` answer a request from `COMP_WORDS`/`COMP_CWORD` with click's output
//!   format (`plain,<value>` lines for bash; `plain\n<value>\n<help>` for zsh; fish
//!   `plain,<value>\t<help>`?: copy click's `BashComplete/ZshComplete/FishComplete`
//!   exactly). Dynamic completers: [`super::commands::Completer`]. Exit 0 (click returns 1
//!   for an unknown instruction).
//! * `bab completion [SHELL] [--prog P] [--install]`: Python `completion_command`,
//!   `_completion_var` (note: Python's own normalisation, `_AB_COMPLETE` fallback for an
//!   empty name), `_completion_destinations`, `_install_completion` (zsh compinit
//!   prelude, rc line `[ -f '<script>' ] && . '<script>'`, messages via click.echo).

use crate::error::Result;

/// Handle a completion request if the completion env var for `prog_name` is set.
/// Returns `Some(exit_code)` when it was a completion invocation.
pub fn handle_env_request(prog_name: &str) -> Option<i32> {
    todo!()
}

/// `_completion_var(prog)`.
pub fn completion_var(prog: &str) -> String {
    todo!()
}

/// Click's completion script for `shell` (`bash`, `zsh`, `fish`), `prog`, `complete_var`
/// (`ShellComplete.source()`).
pub fn source(shell: &str, prog: &str, complete_var: &str) -> String {
    todo!()
}

/// `completion_command(shell, prog, install)`.
pub fn cmd_completion(shell: Option<&str>, prog: &str, install: bool) -> Result<()> {
    todo!()
}
