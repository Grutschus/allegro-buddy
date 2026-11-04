//! Differential tests: random inputs through the Rust ports and through the Python
//! reference (allegro-buddy 2.7 on Python 3.12), compared exactly.
//!
//! Inputs where Python raises an uncaught exception (a traceback in `ab`: `inf` in
//! `parse_int`) or that Slurm never produces (aware datetimes, `YYYYMMDD` dates with odd
//! time parts) are left out of the generators.
//!
//! Opt-in (CI stays hermetic): `BAB_DIFF_PYTHON=/path/to/venv/bin/python cargo test
//! difftest` with `allegro-buddy==2.7` installed in that interpreter. Known, documented
//! deviations (aware datetimes, Unicode digits) are excluded from the generators.

use crate::core::{gpu, parse, timefmt};
use crate::{fit, pyfmt, settings};
use serde_json::{Value, json};
use std::io::{BufRead, BufReader, Write};
use std::process::{Command, Stdio};

const PY_SERVER: &str = r#"
import json, sys, os, shlex
from datetime import datetime
from allegro_buddy import core, settings, fit
def iso(v):
    d = core.iso_to_dt(v)
    return None if d is None or d.tzinfo is not None else d.isoformat()
def layer(text):
    try:
        return [[list(k), v] for k, v in settings.parse_layer(text, 'f').items()]
    except settings.ConfigError as e:
        return {'error': str(e)}
def feats(spec):
    r = fit._features(spec)
    return None if r is None else [sorted(a) for a in r]
def path(t, j):
    p = core.resolve_slurm_output_path(t, j)
    return None if p is None else str(p)
def diag(arg):
    record, nodes, limits = arg
    req = fit.JobRequest.from_record(record)
    caps = [fit.NodeCapacity.from_node(n) for n in nodes]
    d = fit.diagnose(req, caps, limits)
    lead = d.lead_fix()
    return {
        'hint': fit.queue_hint(d),
        'skipped': [list(x) for x in d.skipped],
        'fixes': [[f.knob, f.old, f.new, list(f.nodes), f.command, fit.fix_phrase(f)] for f in d.fixes],
        'slots': [[[s.free.gpus, s.free.cpus, s.free.mem], list(s.nodes)] for s in d.slots],
        'lead': None if lead is None else lead.knob,
        'never': fit.never_fits_reason(d) if d.rows else None,
        'long': fit.skip_summary(d.skipped, short=False),
        'flags': [req.knob_flag(k) for k in ('mem', 'cpus', 'gpus')],
        'amount': [req.amount.gpus, req.amount.cpus, req.amount.mem],
        'ids': [req.display_id, req.update_id, req.pending_tasks],
    }
def tail(arg):
    data, n = arg
    path = os.path.join(os.environ['BAB_DIFF_SCRATCH'], 'py-tail.log')
    with open(path, 'wb') as f:
        f.write(bytes.fromhex(data))
    from pathlib import Path
    return core.read_log_tail(Path(path), max_lines=n)
F = {
    'tail': tail,
    'diagnose': diag,
    'prop': lambda s: core.parse_prop_line(s),
    'pipe': lambda s: core.parse_pipe_rows(s, ['A', 'B', 'C']),
    'hostlist': lambda s: sorted(core.expand_hostlist(s)),
    'slurm_time': lambda s: core.parse_slurm_time(s),
    'parse_int': lambda s: core.parse_int(s, -7),
    'seconds': lambda n: core.format_seconds(n),
    'index_blob': lambda s: core.parse_index_blob(s),
    'norm_gpu': lambda s: settings.normalize_gpu_type(s),
    'layer': layer,
    'g': lambda x: format(x, 'g'),
    'repr_float': lambda x: repr(x),
    'repr': lambda s: repr(s),
    'shlex': lambda s: shlex.quote(s),
    'iso': iso,
    'path': lambda t: path(t, '123_4'),
    'mem_to_mb': lambda s: fit.mem_to_mb(s),
    'array_tasks': lambda s: fit.count_array_tasks(s),
    'features': feats,
    'gpu_counts': lambda s: core.parse_gpu_type_counts(s),
    'node_gpu_types': lambda s: {str(k): v for k, v in core.parse_node_gpu_types(s).items()},
    'splitlines': lambda s: s.splitlines(),
    'nullish': lambda s: core.is_nullish(s),
    'mem_value': lambda s: core.format_mem_value(s),
    'history_end': lambda s: core.format_history_end(s, now=datetime(2024, 3, 15, 18, 0)),
    'pending_start': lambda s: core.format_pending_start(s, now=datetime(2026, 10, 6, 14, 30)),
}
for line in sys.stdin:
    name, arg = json.loads(line)
    try:
        out = F[name](arg)
    except Exception as e:
        out = {'exception': type(e).__name__}
    print(json.dumps(out), flush=True)
"#;

/// A tiny deterministic generator (no `rand` dependency).
struct Gen(u64);

impl Gen {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        self.0
    }

    fn below(&mut self, n: usize) -> usize {
        (self.next() % n as u64) as usize
    }

    fn string(&mut self, pieces: &[&str], max: usize) -> String {
        let len = self.below(max + 1);
        (0..len).map(|_| pieces[self.below(pieces.len())]).collect()
    }
}

fn rust_eval(name: &str, arg: &Value) -> Value {
    let s = arg.as_str().unwrap_or("");
    match name {
        "prop" => json!(parse::parse_prop_line(s)),
        "pipe" => json!(parse::parse_pipe_rows(s, &["A", "B", "C"])),
        "hostlist" => json!(parse::expand_hostlist(Some(s))),
        "slurm_time" => json!(timefmt::parse_slurm_time(s)),
        "parse_int" => json!(parse::parse_int(Some(s), -7)),
        "seconds" => json!(timefmt::format_seconds(arg.as_i64())),
        "index_blob" => json!(parse::parse_index_blob(s)),
        "norm_gpu" => json!(settings::normalize_gpu_type(s)),
        "layer" => match settings::parse_layer(s, "f") {
            Ok(layer) => json!(
                layer
                    .into_iter()
                    .map(|((sec, key), v)| json!([[sec, key], v]))
                    .collect::<Vec<_>>()
            ),
            Err(e) => json!({"error": e.0}),
        },
        "g" => json!(pyfmt::format_g(arg.as_f64().unwrap())),
        "repr_float" => json!(pyfmt::float_repr(arg.as_f64().unwrap())),
        "repr" => json!(pyfmt::repr_str(s)),
        "shlex" => json!(pyfmt::shlex_quote(s)),
        "iso" => json!(timefmt::iso_to_dt(s).map(timefmt::isoformat)),
        "path" => json!(
            crate::core::jobs::resolve_slurm_output_path(s, "123_4", "", "", "")
                .map(|p| p.display().to_string())
        ),
        "mem_to_mb" => json!(fit::mem_to_mb(s)),
        "array_tasks" => json!(fit::count_array_tasks(s)),
        "features" => {
            let record = json!({"features": s});
            let features = fit::JobRequest::from_record(&record).features;
            json!(features.map(|alts| {
                alts.into_iter()
                    .map(|a| a.into_iter().collect::<Vec<_>>())
                    .collect::<Vec<_>>()
            }))
        }
        "gpu_counts" => json!(gpu::parse_gpu_type_counts(Some(s))),
        "node_gpu_types" => json!(
            gpu::parse_node_gpu_types(Some(s))
                .into_iter()
                .map(|(k, v)| (k.to_string(), v))
                .collect::<std::collections::BTreeMap<_, _>>()
        ),
        "splitlines" => json!(pyfmt::splitlines(s)),
        "nullish" => json!(parse::is_nullish(Some(s))),
        "mem_value" => json!(parse::format_mem_value(Some(s))),
        "history_end" => json!(timefmt::format_history_end(
            s,
            timefmt::iso_to_dt("2024-03-15T18:00:00").unwrap()
        )),
        "pending_start" => json!(timefmt::format_pending_start(
            s,
            timefmt::iso_to_dt("2026-10-06T14:30:00").unwrap()
        )),
        "diagnose" => rust_diagnose(arg),
        "tail" => {
            let hex = arg[0].as_str().unwrap();
            let bytes: Vec<u8> = (0..hex.len())
                .step_by(2)
                .map(|i| u8::from_str_radix(&hex[i..i + 2], 16).unwrap())
                .collect();
            let path = scratch_dir().join("rs-tail.log");
            std::fs::write(&path, bytes).unwrap();
            let n = arg[1].as_u64().unwrap() as usize;
            json!(crate::core::jobs::read_log_tail(&path, n).unwrap())
        }
        other => panic!("unknown function {other}"),
    }
}

fn rust_diagnose(arg: &Value) -> Value {
    use crate::core::nodes::Node;
    let request = fit::JobRequest::from_record(&arg[0]);
    let field = |n: &Value, k: &str| n[k].as_str().unwrap_or("").to_owned();
    let nodes: Vec<fit::NodeCapacity> = arg[1]
        .as_array()
        .unwrap()
        .iter()
        .map(|n| {
            fit::NodeCapacity::from_node(&Node {
                name: field(n, "NodeName"),
                state: field(n, "State"),
                cpu_tot: field(n, "CPUTot"),
                cpu_alloc: field(n, "CPUAlloc"),
                real_memory: field(n, "RealMemory"),
                alloc_mem: field(n, "AllocMem"),
                gres: field(n, "Gres"),
                gres_used: field(n, "GresUsed"),
                partitions: field(n, "Partitions"),
                active_features: field(n, "ActiveFeatures"),
                features: field(n, "Features"),
                reservation: field(n, "Reservation"),
                spec_mem: field(n, "SpecMem"),
            })
        })
        .collect();
    let limits: fit::MemLimits = arg[2]
        .as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.clone(), v.as_i64()))
        .collect();
    let d = fit::diagnose(&request, &nodes, &limits);
    let amount = request.amount();
    json!({
        "hint": fit::queue_hint(&d),
        "skipped": d.skipped,
        "fixes": d.fixes.iter().map(|f| json!([f.knob.as_str(), f.old, f.new, f.nodes, f.command, fit::fix_phrase(f)])).collect::<Vec<_>>(),
        "slots": d.slots.iter().map(|s| json!([[s.free.gpus, s.free.cpus, s.free.mem], s.nodes])).collect::<Vec<_>>(),
        "lead": d.lead_fix().map(|f| f.knob.as_str()),
        "never": (!d.rows.is_empty()).then(|| fit::never_fits_reason(&d)),
        "long": fit::skip_summary(&d.skipped, false),
        "flags": ([fit::Dim::Mem, fit::Dim::Cpus, fit::Dim::Gpus].map(|k| request.knob_flag(k))),
        "amount": [amount.gpus, amount.cpus, amount.mem],
        "ids": [json!(request.display_id), json!(request.update_id), json!(request.pending_tasks)],
    })
}

fn random_diagnosis_case(g: &mut Gen) -> Value {
    use crate::fit::records::{array_job, cpu_job, n, plain_gpu_job, with};
    let base = match g.below(3) {
        0 => array_job(),
        1 => plain_gpu_job(),
        _ => cpu_job(),
    };
    let pick = |g: &mut Gen, items: &[Value]| items[g.below(items.len())].clone();
    let mut overrides = serde_json::Map::new();
    let mut maybe = |g: &mut Gen, key: &str, items: &[Value]| {
        if g.below(3) == 0 {
            overrides.insert(key.to_owned(), pick(g, items));
        }
    };
    maybe(
        g,
        "node_count",
        &[n(Some(1)), n(Some(2)), n(Some(3)), n(None)],
    );
    maybe(
        g,
        "cpus",
        &[
            n(Some(2)),
            n(Some(4)),
            n(Some(8)),
            n(Some(20)),
            n(Some(56)),
            n(None),
        ],
    );
    maybe(
        g,
        "minimum_cpus_per_node",
        &[n(Some(1)), n(Some(4)), n(Some(12))],
    );
    maybe(
        g,
        "tres_per_node",
        &[
            json!(""),
            json!("gres/gpu:1"),
            json!("gres/gpu:RTX-A5000:2"),
            json!("gres/gpu:GTX-1080ti:4"),
            json!("gres/gpu:4,gres/tmp:10G"),
        ],
    );
    maybe(
        g,
        "tres_per_job",
        &[json!(""), json!("gres/gpu:4"), json!("gres/gpu:3")],
    );
    maybe(
        g,
        "cpus_per_tres",
        &[json!(""), json!("gres/gpu:2"), json!("gres/gpu:6")],
    );
    maybe(
        g,
        "memory_per_tres",
        &[json!(""), json!("gres/gpu:4096"), json!("gres/gpu:20480")],
    );
    maybe(
        g,
        "memory_per_cpu",
        &[n(None), n(Some(2048)), n(Some(3000))],
    );
    maybe(
        g,
        "memory_per_node",
        &[
            n(None),
            n(Some(0)),
            n(Some(8192)),
            n(Some(12288)),
            n(Some(90000)),
        ],
    );
    maybe(
        g,
        "features",
        &[
            json!(""),
            json!("RTX-A5000"),
            json!("Intel&X4112"),
            json!("RTX-A5000|GTX-1080ti"),
            json!("[a|b]*2"),
        ],
    );
    maybe(
        g,
        "partition",
        &[json!("gpu"), json!("gpu,big"), json!("big"), json!("small")],
    );
    maybe(g, "resv_name", &[json!(""), json!("maint"), json!("lab")]);
    maybe(g, "shared", &[json!([]), json!(["none"])]);
    maybe(g, "excluded_nodes", &[json!(""), json!("n[1-2]")]);
    maybe(g, "required_nodes", &[json!(""), json!("n3")]);
    maybe(g, "state_reason", &[json!("Resources"), json!("Priority")]);
    maybe(
        g,
        "array_task_string",
        &[json!(""), json!("0-11%2"), json!("1,3,5-7")],
    );
    let record = with(&base, Value::Object(overrides));
    let count = g.below(7);
    let nodes: Vec<Value> = (0..count)
        .map(|i| {
            let gres = pick(g, &[json!("gpu:RTX-A5000:4"), json!("gpu:GTX-1080ti:4"), json!("(null)"), json!("gpu:4"), json!("gpu:a100:2,gpu:h100:2")]);
            let gres_s = gres.as_str().unwrap().to_owned();
            let total = if gres_s == "(null)" { 0 } else { 4 };
            let used = g.below(total + 1);
            let gres_used = if gres_s == "(null)" {
                String::new()
            } else if g.below(4) == 0 {
                format!("gpu:{used}")
            } else {
                format!("{}:{used}(IDX:N/A)", gres_s.rsplit_once(':').unwrap().0)
            };
            let cpus = [16, 48][g.below(2)];
            let mem = [92000, 192000][g.below(2)];
            json!({
                "NodeName": format!("n{i}"),
                "State": pick(g, &[json!("MIXED"), json!("IDLE"), json!("ALLOCATED"), json!("DOWN+DRAIN"), json!("MIXED+PLANNED"), json!("IDLE+RESERVED+MAINT"), json!("IDLE+NOT_RESPONDING")]),
                "CPUTot": cpus.to_string(),
                "CPUAlloc": g.below(cpus + 1).to_string(),
                "RealMemory": mem.to_string(),
                "AllocMem": (g.below(mem / 1000 + 1) * 1000).to_string(),
                "SpecMem": (["0", "2048"][g.below(2)]),
                "Gres": gres_s,
                "GresUsed": gres_used,
                "Partitions": pick(g, &[json!("gpu"), json!("big"), json!("small,big"), json!("gpu,big")]),
                "ActiveFeatures": pick(g, &[json!("Intel,X4112,RTX-A5000"), json!("Intel,GTX-1080ti"), json!("Intel"), json!("")]),
                "Features": "",
                "Reservation": pick(g, &[json!(""), json!(""), json!("maint"), json!("lab")]),
            })
        })
        .collect();
    let limits = pick(
        g,
        &[
            json!({}),
            json!({"small": 3000, "big": null}),
            json!({"gpu": 4000, "big": 2000}),
        ],
    );
    json!([record, nodes, limits])
}

/// Normalize JSON for comparison: Python dicts and Rust maps compare as sorted maps.
fn canonical(v: Value) -> Value {
    serde_json::from_str(&v.to_string()).unwrap()
}

fn cases() -> Vec<(&'static str, Value)> {
    let mut g = Gen(0x9E37_79B9_7F4A_7C15);
    let mut out: Vec<(&'static str, Value)> = Vec::new();
    let mut add = |name: &'static str, count: usize, f: &mut dyn FnMut(&mut Gen) -> Value| {
        for _ in 0..count {
            out.push((name, f(&mut g)));
        }
    };
    let prop = [
        "A", "Key", "=", "==", " ", "  ", "\t", "x", "1", "[", "]", ",", "\n", "é", "\x0b",
    ];
    add("prop", 3000, &mut |g| json!(g.string(&prop, 14)));
    add("pipe", 500, &mut |g| {
        json!(g.string(&["a", "|", "\n", " ", "\r\n", "\x1c", "b"], 12))
    });
    let host = [
        "gpu", "[", "]", "0", "1", "9", "01", "-", ",", " ", "x", "+", "_",
    ];
    add("hostlist", 3000, &mut |g| json!(g.string(&host, 12)));
    let time = [
        "1",
        "0",
        "12",
        "-",
        ":",
        " ",
        "+",
        "_",
        "x",
        "UNLIMITED",
        "n/a",
    ];
    add("slurm_time", 3000, &mut |g| json!(g.string(&time, 8)));
    let num = [
        "1", "0", ".", "-", "+", "e", "_", " ", "nan", "x", "(null)", "N/A",
    ];
    add("parse_int", 2000, &mut |g| json!(g.string(&num, 6)));
    add("seconds", 500, &mut |g| {
        json!(g.next() as i64 % 400_000 - 1000)
    });
    add("index_blob", 1000, &mut |g| {
        json!(g.string(&["0", "3", "-", ",", " ", "x", "12"], 8))
    });
    add("norm_gpu", 1000, &mut |g| {
        json!(g.string(&["RTX", "-", "a", "5000", " ", "_", "!", "É", "ß"], 6))
    });
    let ini = [
        "[dev]\n",
        "[cluster]\n",
        "[gpu-labels]\n",
        "[DEFAULT]\n",
        "[Dev]\n",
        "[]\n",
        "gpu = 1\n",
        "Mem: 8G\n",
        "time=1 ;c\n",
        "  cont\n",
        "\n",
        "# c\n",
        "; c\n",
        "junk\n",
        "= x\n",
        "a5000 = A5000 # z\n",
        "gpu-type = x\n",
        "preset=allegro\n",
        "x#y = 1\n",
        "\tgpu = 2\n",
        "[dev] tail\n",
        "node-login = ssh\n",
    ];
    add("layer", 3000, &mut |g| json!(g.string(&ini, 6)));
    let floats = [
        0.0,
        -0.0,
        10.0,
        2.5,
        1e16,
        1e15,
        1e-5,
        1e-4,
        123456.0,
        1234567.0,
        999999.5,
        0.1,
        1.0 / 3.0,
        5e-324,
        1.7976931348623157e308,
        100.0,
        15.0,
    ];
    for x in floats {
        out.push(("g", json!(x)));
        out.push(("repr_float", json!(x)));
    }
    let mut g2 = Gen(42);
    for _ in 0..500 {
        let x = f64::from_bits(g2.next() >> 2) * if g2.below(2) == 0 { 1.0 } else { -1.0 };
        if x.is_finite() {
            out.push(("g", json!(x)));
            out.push(("repr_float", json!(x)));
        }
        let small = (g2.next() % 10_000_000) as f64 / 10f64.powi(g2.below(12) as i32);
        out.push(("g", json!(small)));
        out.push(("repr_float", json!(small)));
    }
    let mut g = Gen(7);
    let text = [
        "a",
        "'",
        "\"",
        "\\",
        "\n",
        "\t",
        "\x07",
        "\u{a0}",
        "é",
        "\u{200b}",
        " ",
        "$",
        "%",
        "-",
        "=",
        "@",
        "\u{1F600}",
        "\u{e000}",
    ];
    for _ in 0..2000 {
        let s = g.string(&text, 6);
        out.push(("repr", json!(s.clone())));
        out.push(("shlex", json!(s)));
    }
    let iso = [
        "2024", "-", "01", "15", "T", " ", "10", ":", "30", "00", ".", ",", "5", "1234567", "24",
        "60", "Z", "x", "\u{2603}", "\u{e9}",
    ];
    for _ in 0..4000 {
        let s = g.string(&iso, 10);
        // Basic-format dates (`YYYYMMDD...`) follow CPython's C parser quirks we skip.
        if !s.contains('Z') && s.get(4..5).is_none_or(|c| c == "-") {
            out.push(("iso", json!(s.clone())));
            out.push(("history_end", json!(s.clone())));
            out.push(("pending_start", json!(s)));
        }
    }
    for prefix in [
        "2024-03-1",
        "2024-03-0",
        "2023-12-3",
        "2026-10-0",
        "2026-10-1",
        "2026-11-0",
    ] {
        for d in 0..10 {
            for t in [
                "T00:00:00",
                "T14:29:59",
                "T14:30:00",
                "T23:59:59.999999",
                "",
            ] {
                let s = format!("{prefix}{d}{t}");
                out.push(("history_end", json!(s.clone())));
                out.push(("pending_start", json!(s)));
            }
        }
    }
    let tpl = [
        "/x/", "%", "j", "J", "A", "a", "x", "u", "N", "%%", "4", "0", "//", "./", "~", "$HOME",
        "${HOME}", "$", "{", "}", "\n",
    ];
    for _ in 0..3000 {
        out.push(("path", json!(g.string(&tpl, 8))));
    }
    let mem = [
        "1", "40", ".", "5", "G", "g", "M", "K", "T", "P", "x", " ", "0",
    ];
    for _ in 0..2000 {
        out.push(("mem_to_mb", json!(g.string(&mem, 5))));
    }
    let arr = ["0", "1", "11", "-", ",", ":", "2", "%", "x", "-3", "0"];
    for _ in 0..2000 {
        out.push(("array_tasks", json!(g.string(&arr, 7))));
    }
    let feat = [
        "Intel",
        "&",
        "|",
        ",",
        "[",
        "]",
        "*2",
        " ",
        "RTX-A5000",
        "a.b",
        "\n",
        "é",
    ];
    for _ in 0..2000 {
        out.push(("features", json!(g.string(&feat, 5))));
    }
    let gres = [
        "gpu",
        "gres/",
        ":",
        "=",
        "a5000",
        "RTX-A5000",
        "4",
        "2",
        "(",
        ")",
        "IDX:",
        "0-1",
        ",",
        " ",
        "S:0-1",
        "x",
        "tesla_v100",
    ];
    for _ in 0..3000 {
        let s = g.string(&gres, 10);
        out.push(("gpu_counts", json!(s.clone())));
        out.push(("node_gpu_types", json!(s)));
    }
    let mut gd = Gen(99);
    for _ in 0..4000 {
        out.push(("diagnose", random_diagnosis_case(&mut gd)));
    }
    let tail_bytes: [&[u8]; 8] = [
        b"a",
        b"bc",
        b"\n",
        b"\r",
        b"\r\n",
        b"\xe2\x98",
        b"\x83",
        b"\xff",
    ];
    for _ in 0..1500 {
        let count = g.below(40);
        let hex: String = (0..count)
            .flat_map(|_| tail_bytes[g.below(tail_bytes.len())].iter())
            .map(|b| format!("{b:02x}"))
            .collect();
        let n = [0, 1, 2, 3, 7, 50][g.below(6)];
        out.push(("tail", json!([hex, n])));
    }
    let lines = [
        "a", "\n", "\r", "\r\n", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\u{85}", "\u{2028}",
        "\u{2029}", " ",
    ];
    for _ in 0..1000 {
        out.push(("splitlines", json!(g.string(&lines, 6))));
    }
    let nullish = [
        "", " ", "(null)", "None", "N/A", "unknown", "UNKNOWN", "\x1c", "0", "12", "1G", "\t",
    ];
    for _ in 0..500 {
        let s = g.string(&nullish, 3);
        out.push(("nullish", json!(s.clone())));
        out.push(("mem_value", json!(s)));
    }
    out
}

/// Where both sides write the `tail` test files.
fn scratch_dir() -> std::path::PathBuf {
    let dir = std::env::current_exe()
        .unwrap()
        .parent()
        .unwrap()
        .join(format!("bab-difftest-scratch-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

#[test]
fn rust_ports_match_python() {
    let Some(python) = std::env::var_os("BAB_DIFF_PYTHON") else {
        eprintln!("BAB_DIFF_PYTHON not set: skipping the differential test");
        return;
    };
    let empty = std::env::current_exe()
        .unwrap()
        .parent()
        .unwrap()
        .join("bab-difftest-empty");
    let mut child = Command::new(python)
        .args(["-c", PY_SERVER])
        .env("BAB_DIFF_SCRATCH", scratch_dir())
        .env("AB_CLUSTER", "allegro")
        .env("XDG_CONFIG_HOME", &empty)
        .env("XDG_CACHE_HOME", &empty)
        .env("AB_SITE_CONFIG", empty.join("site.ini"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .expect("python");
    let mut stdin = child.stdin.take().unwrap();
    let cases = cases();
    let writer = std::thread::spawn({
        let cases = cases.clone();
        move || {
            for (name, arg) in cases {
                writeln!(stdin, "{}", json!([name, arg])).unwrap();
            }
        }
    });
    let mut reader = BufReader::new(child.stdout.take().unwrap());
    let mut failures = Vec::new();
    let mut hint_kinds = std::collections::BTreeSet::new();
    for (name, arg) in &cases {
        let mut line = String::new();
        reader.read_line(&mut line).unwrap();
        let expected = canonical(serde_json::from_str(&line).unwrap());
        // `~unknownuser` paths: pathlib raises RuntimeError (a traceback in `ab`).
        if *name == "path" && expected == json!({"exception": "RuntimeError"}) {
            continue;
        }
        if *name == "diagnose" {
            let hint = expected["hint"].as_str().unwrap_or("");
            hint_kinds.insert(hint.split([' ', ':']).take(2).collect::<Vec<_>>().join(" "));
        }
        let actual = canonical(rust_eval(name, arg));
        if expected != actual {
            failures.push(format!("{name}({arg}): python {expected} rust {actual}"));
        }
    }
    writer.join().unwrap();
    let _ = std::fs::remove_dir_all(scratch_dir());
    assert!(
        hint_kinds.len() >= 6,
        "diagnosis cases too uniform: {hint_kinds:?}"
    );
    let _ = child.wait();
    assert!(
        failures.is_empty(),
        "{} of {} differ:\n{}",
        failures.len(),
        cases.len(),
        failures
            .iter()
            .take(40)
            .cloned()
            .collect::<Vec<_>>()
            .join("\n")
    );
}
