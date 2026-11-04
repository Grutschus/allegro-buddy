//! GPU types, labels and GRES parsing from `core.py`. Owned by P2-C.
//!
//! GPU counts per type are [`GpuCounts`] (`BTreeMap`, deterministic). Python uses
//! insertion-ordered dicts, but no output depends on that order: display order always goes
//! through [`collect_display_gpu_types`], and `fit` sorts.

use regex::Regex;
use std::collections::BTreeMap;
use std::sync::LazyLock;

/// Canonical GPU type -> count.
pub type GpuCounts = BTreeMap<String, i64>;

/// `GPU_TYPE_SYNONYMS` (cluster-neutral; settings `[gpu-aliases]` win).
pub const GPU_TYPE_SYNONYMS: [(&str, &str); 4] = [
    ("tesla_v100", "v100"),
    ("tesla_a100", "a100"),
    ("nvidia_a100", "a100"),
    ("nvidia_h100", "h100"),
];

/// `GPU_TYPE_LABELS` (settings `[gpu-labels]` win).
pub const GPU_TYPE_LABELS: [(&str, &str); 5] = [
    ("a100", "A100"),
    ("h100", "H100"),
    ("h200", "H200"),
    ("v100", "V100"),
    ("generic", "GPU"),
];

pub const GPU_FEATURE_TYPE_HINTS: [&str; 8] = [
    "a5000", "a100", "h100", "h200", "v100", "gtx", "tesla", "titan",
];

/// `GPU_RESOURCE_CHUNK`: groups `type`, `count`, `meta`.
pub static GPU_RESOURCE_CHUNK: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"(?:^|[\s,])(?:gres/)?gpu(?::(?P<type>[A-Za-z0-9._-]+))?[:=](?P<count>\d+)(?:\((?P<meta>[^)]*)\))?",
    )
    .expect("GPU_RESOURCE_CHUNK")
});

/// `canonical_gpu_type(gpu_type)`: normalize; empty -> `generic`; then settings aliases,
/// then [`GPU_TYPE_SYNONYMS`], else the normalized name. Loads settings.
pub fn canonical_gpu_type(gpu_type: Option<&str>) -> String {
    todo!()
}

/// `gpu_type_label(gpu_type)`: settings label, [`GPU_TYPE_LABELS`], else
/// `upper().replace("_", "")`.
pub fn gpu_type_label(gpu_type: &str) -> String {
    todo!()
}

/// `parse_gpu_type_counts(spec)` (summed per canonical type, finditer order).
pub fn parse_gpu_type_counts(spec: Option<&str>) -> GpuCounts {
    todo!()
}

/// `infer_gpu_type_from_features(feature_blob)`.
pub fn infer_gpu_type_from_features(feature_blob: Option<&str>) -> Option<String> {
    todo!()
}

/// `parse_gpu_count(spec)`: total of [`parse_gpu_type_counts`].
pub fn parse_gpu_count(spec: Option<&str>) -> i64 {
    todo!()
}

/// `add_gpu_type_counts(target, source)`.
pub fn add_gpu_type_counts(target: &mut GpuCounts, source: &GpuCounts) {
    for (kind, count) in source {
        *target.entry(kind.clone()).or_insert(0) += count;
    }
}

/// `parse_gpu_ids(spec)`: sorted unique ids from every `IDX:...` in the spec.
pub fn parse_gpu_ids(spec: Option<&str>) -> Vec<i64> {
    todo!()
}

/// `parse_node_gpu_types(spec)`: GPU index -> canonical type (IDX metadata first, then
/// remaining indices filled in chunk order).
pub fn parse_node_gpu_types(spec: Option<&str>) -> BTreeMap<i64, String> {
    todo!()
}

/// `collect_display_gpu_types(count_maps)`: types with count > 0, ordered by settings
/// `gpu_labels` order, then `generic`, then the rest sorted.
pub fn collect_display_gpu_types(count_maps: &[&GpuCounts]) -> Vec<String> {
    todo!()
}

/// `format_gpu_type_header(prefix, gpu_type)`.
pub fn format_gpu_type_header(prefix: &str, gpu_type: &str) -> String {
    todo!()
}
