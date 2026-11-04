//! click-compatible argument parser (click 8.3.2 semantics). Owned by P2-B.
//!
//! Must reproduce click's behaviour and error messages for the tree in
//! [`super::commands`]: option forms (`-p x`, `-px`, `--partition x`, `--partition=x`,
//! clustered short flags `-yG`?, `--` end of options), optional-value options
//! (`flag_value`: `-w`, `-w 15`, `--watch=15`; a following token that looks like an
//! option is not consumed), unknown options with click's "Did you mean" suggestions
//! (`No such option: --nod (Possible options: --nodes)`), missing values
//! (`Option '--user' requires an argument.`), type conversion errors
//! (`Invalid value for '-w' / '--watch': '5' is not in the range x>=10.`,
//! `'abc' is not a valid float.`, `'x' is not one of 'gpu', 'cpu'.`), missing required
//! arguments (`Missing argument 'JOBID'.`), extra arguments (`Got unexpected extra
//! argument (x)`), unknown commands (`No such command 'x'.`), multiple uses (last wins),
//! `-h/--help` (eager; prints help and exits 0, also on groups without subcommand).
//! Groups without `invoke_without_command` and no subcommand print their help and exit
//! 0 (click 8.3: actually `NoArgsIsHelpError` -> help on stderr? verify exit code/stream).
//!
//! Default resolution order (click): command line > `default_map` (main sets
//! `ctx.default_map = {'dev': {'start': {...}}}` from config `[dev]`, values are strings
//! converted by the param type and passed through callbacks; a bad value is a
//! `BadParameter` usage error) > param default. `callback=_normalize_gpu_type` runs on
//! the final value (also on defaults from the map).
//!
//! Order of events (click): main group parses its own args; `--version`/`--help` are eager
//! and exit before anything else; then the group callback runs (`load_default_map`, which
//! may fail with `AbError::Click(config error)`), THEN the subcommand's args are parsed
//! (so `bab info --help` with a broken config shows the config error).

use super::commands::{Command, Param};
use crate::error::Result;

/// A parsed parameter value.
#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    None,
    Bool(bool),
    Str(String),
    Int(i64),
    Float(f64),
}

/// Values for one invoked command, by `dest`.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Args {
    pub values: Vec<(&'static str, Value)>,
}

impl Args {
    pub fn get(&self, dest: &str) -> &Value {
        self.values
            .iter()
            .find(|(d, _)| *d == dest)
            .map(|(_, v)| v)
            .unwrap_or(&Value::None)
    }

    /// Flag value (`false` when absent).
    pub fn flag(&self, dest: &str) -> bool {
        matches!(self.get(dest), Value::Bool(true))
    }

    pub fn opt_str(&self, dest: &str) -> Option<&str> {
        match self.get(dest) {
            Value::Str(s) => Some(s),
            _ => None,
        }
    }

    pub fn str(&self, dest: &str) -> &str {
        self.opt_str(dest)
            .unwrap_or_else(|| panic!("{dest}: no string value"))
    }

    pub fn opt_int(&self, dest: &str) -> Option<i64> {
        match self.get(dest) {
            Value::Int(i) => Some(*i),
            _ => None,
        }
    }

    pub fn int(&self, dest: &str) -> i64 {
        self.opt_int(dest)
            .unwrap_or_else(|| panic!("{dest}: no int value"))
    }

    pub fn opt_float(&self, dest: &str) -> Option<f64> {
        match self.get(dest) {
            Value::Float(f) => Some(*f),
            _ => None,
        }
    }

    pub fn float(&self, dest: &str) -> f64 {
        self.opt_float(dest)
            .unwrap_or_else(|| panic!("{dest}: no float value"))
    }
}

/// The outcome of parsing argv.
#[derive(Debug, Clone, PartialEq)]
pub enum Parsed {
    /// Run `command` (a leaf, or the main group's `invoke_without_command` default) with
    /// `args`; `path` is the command path for messages (`["bab", "dev", "start"]`).
    Run {
        path: Vec<String>,
        command: &'static Command,
        args: Args,
    },
    /// Help/version already printed (exit 0).
    Done,
}

/// `[dev]` default map entries: click param dest -> raw string from config.
pub type DefaultMap = Vec<(&'static str, String)>;

/// Parse `argv` (without argv[0]) against [`super::commands::MAIN`]. `load_default_map`
/// is called at the point where click runs the main group callback (see module docs).
pub fn parse(argv: &[String], load_default_map: &dyn Fn() -> Result<DefaultMap>) -> Result<Parsed> {
    todo!()
}

/// Convert/validate one raw value for `param` (click `ParamType.convert`), giving the
/// click `BadParameter` message on failure.
pub fn convert(param: &Param, raw: &str) -> std::result::Result<Value, String> {
    todo!()
}
