//! Layered configuration: shipped cluster preset < site file < user file. Port of
//! `settings.py`. Owned by P2-C.
//!
//! # Contract
//!
//! * [`load`] == `functools.cache`d `settings.load()`: computed once per process on
//!   success (a `OnceLock`); errors are NOT cached (Python re-raises next call).
//!   [`get`] is the infallible accessor for code that runs after the cli layer has loaded
//!   settings successfully (it builds the `[dev]` default map first, turning a
//!   [`ConfigError`] into `AbError::Click(message)`); `get` panics if `load` would fail,
//!   so completion callbacks must use [`load`] and degrade gracefully.
//! * Values keep Python dict insertion order across layers (a key first set by the preset
//!   keeps its position when the user file overrides it): `gpu_labels` order is the
//!   display order of GPU columns. `config show` sorts by (section, key) itself.
//! * INI parsing must match `configparser.ConfigParser(interpolation=None,
//!   inline_comment_prefixes=('#', ';'))` incl. its error messages in `cannot parse
//!   {source}: {exc}` (e.g. `MissingSectionHeaderError`, `DuplicateOptionError`,
//!   `DuplicateSectionError`, `ParsingError` texts), keys lower-cased (optionxform),
//!   multi-line continuation values, `[DEFAULT]` semantics (DEFAULT is not in
//!   `sections()` but its keys appear in every section's `items()`!), `=`/`:` delimiters,
//!   full-line comments `#`/`;`, empty lines.
//! * Error messages use Python `repr` (`{raw_key!r}`, `sorted(...)` lists): see
//!   [`crate::pyfmt`].
//! * Presets are embedded with `include_str!` ([`PRESETS`]).
//! * The cluster name cache lives at `$XDG_CACHE_HOME|~/.cache/allegro-buddy/
//!   cluster-name.<hostname>` (hostname via [`crate::hooks::hostname`]); probed with
//!   `scontrol show config` (direct subprocess, NOT `core::slurm::run`: a missing scontrol
//!   is just None), regex `^ClusterName\s*=\s*(\S+)` multiline, rc must be 0. Write errors
//!   ignored.

use std::path::PathBuf;
use std::sync::OnceLock;

/// `ab dev start` options settable in `[dev]`: config key -> click parameter name.
pub const DEV_START_KEYS: [(&str, &str); 9] = [
    ("partition", "partition"),
    ("time", "time_limit"),
    ("gpu", "gpu"),
    ("gpu_type", "gpu_type"),
    ("cpus", "cpus"),
    ("mem", "mem"),
    ("account", "account"),
    ("constraint", "constraint"),
    ("exclude", "exclude"),
];

/// Allowed sections and keys; `None` = any key (lookup table). Python `SECTIONS`
/// (`dev` = DEV_START_KEYS + `log_dir`, `max_allocations`).
pub const SECTIONS: [(&str, Option<&[&str]>); 4] = [
    (
        "dev",
        Some(&[
            "partition",
            "time",
            "gpu",
            "gpu_type",
            "cpus",
            "mem",
            "account",
            "constraint",
            "exclude",
            "log_dir",
            "max_allocations",
        ]),
    ),
    ("cluster", Some(&["preset", "gpu_partitions", "node_login"])),
    ("gpu-aliases", None),
    ("gpu-labels", None),
];

pub const NODE_LOGIN_METHODS: [&str; 2] = ["ssh", "srun"];

/// Shipped presets (name, INI text), sorted by name (`preset_names()`).
pub const PRESETS: [(&str, &str); 2] = [
    ("allegro", include_str!("../presets/allegro.ini")),
    ("bhlrn4", include_str!("../presets/bhlrn4.ini")),
];

/// `settings.ConfigError`; the message is shown verbatim.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConfigError(pub String);

impl std::fmt::Display for ConfigError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for ConfigError {}

/// One merged value: `(section, key) -> (value, source)`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Entry {
    pub section: String,
    pub key: String,
    pub value: String,
    /// `preset allegro`, `site file`, `user file`.
    pub source: String,
}

/// `Settings` (frozen dataclass + cached properties).
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Settings {
    pub preset: Option<String>,
    pub preset_reason: String,
    /// Insertion-ordered like the Python dict (see module docs).
    pub values: Vec<Entry>,
    /// `gpu_aliases`: normalized alias -> normalized target (ordered).
    pub gpu_aliases: Vec<(String, String)>,
    /// `gpu_labels`: canonical type -> label, configured (display) order.
    pub gpu_labels: Vec<(String, String)>,
}

impl Settings {
    /// `get(section, key)`.
    pub fn get(&self, section: &str, key: &str) -> Option<&str> {
        todo!()
    }

    /// `get_list(section, key)`: comma-split, stripped, empties dropped.
    pub fn get_list(&self, section: &str, key: &str) -> Vec<String> {
        todo!()
    }

    /// `section(section)`: key -> value pairs in order.
    pub fn section(&self, section: &str) -> Vec<(String, String)> {
        todo!()
    }

    /// `gpu_aliases.get(normalized)`.
    pub fn gpu_alias(&self, normalized: &str) -> Option<&str> {
        todo!()
    }

    /// `gpu_labels.get(gpu_type)`.
    pub fn gpu_label(&self, gpu_type: &str) -> Option<&str> {
        todo!()
    }
}

static SETTINGS: OnceLock<Settings> = OnceLock::new();

/// `settings.load()`, cached on success.
pub fn load() -> Result<&'static Settings, ConfigError> {
    todo!()
}

/// Settings after a successful [`load`] (see module docs); loads if needed and panics
/// on a config error.
pub fn get() -> &'static Settings {
    load().unwrap_or_else(|e| panic!("settings::get() before a successful load: {e}"))
}

/// `user_config_path()`: `$XDG_CONFIG_HOME|~/.config` + `/allegro-buddy/config.ini`.
pub fn user_config_path() -> PathBuf {
    todo!()
}

/// `site_config_path()`: `$AB_SITE_CONFIG` or `/etc/allegro-buddy/config.ini`.
pub fn site_config_path() -> PathBuf {
    todo!()
}

/// `preset_names()`.
pub fn preset_names() -> Vec<&'static str> {
    PRESETS.iter().map(|(name, _)| *name).collect()
}

/// `preset_text(name)`.
pub fn preset_text(name: &str) -> Option<&'static str> {
    PRESETS
        .iter()
        .find(|(n, _)| *n == name)
        .map(|(_, text)| *text)
}

/// `cluster_name_cache_path()`.
pub fn cluster_name_cache_path() -> PathBuf {
    todo!()
}

/// `slurm_cluster_name()`: cached per host (process-wide memo too: Python reads the file
/// each call, which is equivalent).
pub fn slurm_cluster_name() -> Option<String> {
    todo!()
}

/// `probe_cluster_name()`.
pub fn probe_cluster_name() -> Option<String> {
    todo!()
}

/// `normalize_gpu_type("RTX-A5000")` -> `rtx_a5000`.
pub fn normalize_gpu_type(name: &str) -> String {
    todo!()
}

/// `normalize_key(section, key)`.
pub fn normalize_key(section: &str, key: &str) -> String {
    todo!()
}

/// One config layer: ordered `((section, key), value)` pairs (later duplicates win).
pub type Layer = Vec<((String, String), String)>;

/// `parse_layer(text, source)`.
pub fn parse_layer(text: &str, source: &str) -> Result<Layer, ConfigError> {
    todo!()
}

/// `read_file_layer(path)`: missing file -> empty; other OSError -> `cannot read {path}:
/// {exc}` (Python `str(OSError)`, e.g. `[Errno 21] Is a directory: '/x'`).
pub fn read_file_layer(path: &std::path::Path) -> Result<Layer, ConfigError> {
    todo!()
}

/// `pick_preset(file_choice)` -> (preset, reason).
pub fn pick_preset(file_choice: Option<&str>) -> Result<(Option<String>, String), ConfigError> {
    todo!()
}

/// `validate(settings)`.
pub fn validate(settings: &Settings) -> Result<(), ConfigError> {
    todo!()
}
