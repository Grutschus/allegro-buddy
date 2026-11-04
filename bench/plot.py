# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib==3.10.*"]
# ///
"""Plots and Markdown tables of the final ab vs bab comparison (bench/RESULTS.md).

    uv run bench/plot.py [--live bench/results/live/<run>] [--local bench/results/local]

Writes bench/plots/{live,local-nodelay,local-realtime,startup,speedup}.{svg,png} and
prints the tables of RESULTS.md. Means with one standard deviation as error bars;
speedup = mean(ab) / mean(bab).
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

HERE = Path(__file__).resolve().parent
AB_COLOR = '#3776ab'  # Python blue
BAB_COLOR = '#ce422b'  # Rust orange
TEXT = '#333333'
GRID = '#d0d0d0'

# live hyperfine export name -> label; order = plot order (top to bottom)
LIVE = {
    'version': '--version', 'help': '-h', 'info': 'info', 'info-cold': 'info (cold cache)',
    'free': 'free', 'free-nodes': 'free --nodes', 'q': 'q', 'q-all': 'q --all', 'why': 'why',
    'why-pending': 'why <pending job>', 'node': 'node gpu062', 'job-history': 'job history',
    'config-show': 'config show',
}
# bench.py label -> label
LOCAL = {
    '--version': '--version', '-h': '-h', 'info': 'info', 'free': 'free',
    'free --nodes': 'free --nodes', 'queue': 'q', 'q --all': 'q --all', 'why': 'why',
    'why {pending}': 'why <pending job>', 'why --nodes': 'why --nodes',
    'node gpu062': 'node gpu062', 'job history': 'job history', 'dev status': 'dev status',
    'config show': 'config show',
}


def stats(ms: list[float]) -> dict:
    return {'n': len(ms), 'mean': statistics.fmean(ms), 'stddev': statistics.stdev(ms),
            'median': statistics.median(ms), 'min': min(ms), 'max': max(ms)}


def load_live(run: Path) -> dict[str, dict[str, dict]]:
    out = {}
    for key, label in LIVE.items():
        path = run / f'{key}.json'
        if not path.exists():
            continue
        out[label] = {}
        for r in json.loads(path.read_text())['results']:
            ms = [m['time_wall_clock']['value'] * 1000 for m in r['measurements']]
            out[label][r['name']] = stats(ms)
    return out


def load_local(path: Path, rename: str | None = None) -> dict[str, dict[str, dict]]:
    data = json.loads(path.read_text())
    out = {}
    for key, label in LOCAL.items():
        if key in data:
            out[rename or label] = {k: stats(v['times_ms']) for k, v in data[key].items()}
    return out


def speedup(row: dict[str, dict]) -> float:
    return row['ab']['mean'] / row['bab']['mean']


def fmt_ms(v: float) -> str:
    return f'{v:.0f}' if v >= 100 else f'{v:.1f}' if v >= 1 else f'{v:.2f}'


def style() -> None:
    plt.rcParams.update({
        'font.family': 'DejaVu Sans', 'font.size': 10, 'text.color': TEXT,
        'axes.labelcolor': TEXT, 'axes.edgecolor': GRID, 'xtick.color': TEXT,
        'ytick.color': TEXT, 'axes.titleweight': 'bold', 'axes.titlesize': 13,
        'figure.facecolor': 'white', 'axes.facecolor': 'white', 'savefig.facecolor': 'white',
        'svg.hashsalt': 'bab', 'svg.fonttype': 'path',
    })


def bars(data: dict[str, dict[str, dict]], title: str, subtitle: str, out: Path, *,
         log: bool = False) -> None:
    labels = list(data)
    n = len(labels)
    fig, ax = plt.subplots(figsize=(9, 0.55 * n + 1.7))
    h = 0.38
    ys = range(n)
    for off, impl, color, name in ((-h / 2, 'ab', AB_COLOR, 'ab: allegro-buddy 2.7 (Python)'),
                                   (h / 2, 'bab', BAB_COLOR, 'bab: the Rust rewrite')):
        means = [data[lbl][impl]['mean'] for lbl in labels]
        errs = [data[lbl][impl]['stddev'] for lbl in labels]
        ax.barh([y + off for y in ys], means, height=h, color=color, label=name,
                xerr=errs, error_kw={'ecolor': TEXT, 'elinewidth': 0.8, 'capsize': 2})
        for y, m, e in zip(ys, means, errs):
            ax.text(m + e, y + off, f' {fmt_ms(m)}', va='center', fontsize=7.5, color=TEXT)
    xmax = max(data[lbl]['ab']['mean'] + data[lbl]['ab']['stddev'] for lbl in labels)
    if log:
        ax.set_xscale('log')
        xmin = min(data[lbl]['bab']['mean'] for lbl in labels) / 2
        ax.set_xlim(xmin, xmax * 12)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f'{v:g}'))
        label_x = xmax * 2.8
    else:
        ax.set_xlim(0, xmax * 1.32)
        label_x = xmax * 1.13
    for y, lbl in zip(ys, labels):
        ax.text(label_x, y, f'{speedup(data[lbl]):.1f}×', va='center', ha='left',
                fontsize=10, fontweight='bold', color=BAB_COLOR)
    ax.text(label_x, -0.85, 'speedup', ha='left', va='center', fontsize=8, color=TEXT)
    ax.set_yticks(list(ys), labels, fontfamily='DejaVu Sans Mono', fontsize=9)
    ax.set_ylim(n - 0.5, -1.3)
    ax.set_xlabel('wall time per invocation, ms' + (' (log scale)' if log else '')
                  + ' — mean ± σ')
    ax.grid(axis='x', color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    ax.set_title(title, loc='left', pad=22)
    ax.text(0, 1.015, subtitle, transform=ax.transAxes, fontsize=8.5, color='#666666')
    ax.legend(loc='upper left', ncol=2, frameon=False, fontsize=9, borderaxespad=0.2)
    fig.tight_layout()
    save(fig, out)


def speedup_plot(series: dict[str, dict[str, dict[str, dict]]], out: Path) -> None:
    labels = [lbl for lbl in LOCAL.values() if any(lbl in d for d in series.values())]
    labels.insert(labels.index('info') + 1, 'info (cold cache)')
    labels = [lbl for lbl in labels if any(lbl in d for d in series.values())]
    colors = ['#ce422b', '#e8916f', '#7a7a7a']
    n, k = len(labels), len(series)
    fig, ax = plt.subplots(figsize=(9, 0.5 * n + 1.7))
    h = 0.8 / k
    for i, ((name, data), color) in enumerate(zip(series.items(), colors)):
        ys = [y - 0.4 + h * (i + 0.5) for y in range(n)]
        vals = [speedup(data[lbl]) if lbl in data else 0 for lbl in labels]
        ax.barh(ys, vals, height=h, color=color, label=name)
        for y, v in zip(ys, vals):
            if v:
                ax.text(v, y, f' {v:.1f}×', va='center', fontsize=7.5, color=TEXT)
    ax.set_xscale('log')
    ax.axvline(1, color=TEXT, linewidth=0.8)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f'{v:g}×'))
    ax.set_xlim(0.8, 400)
    ax.set_yticks(range(n), labels, fontfamily='DejaVu Sans Mono', fontsize=9)
    ax.set_ylim(n - 0.5, -0.6)
    ax.set_xlabel('speedup = mean(ab) / mean(bab), log scale')
    ax.grid(axis='x', color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    ax.set_title('How many times faster? (bigger is rustier)', loc='left', pad=22)
    ax.text(0, 1.015, 'live: real Slurm on Allegro · realtime: replayed Slurm latencies · '
            'no delay: instant fake Slurm (pure tool overhead)', transform=ax.transAxes,
            fontsize=8.5, color='#666666')
    ax.legend(loc='upper center', bbox_to_anchor=(0.45, -0.07), ncol=3, frameon=False,
              fontsize=9)
    fig.tight_layout()
    save(fig, out)


def save(fig, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out.with_suffix('.svg'), metadata={'Date': None})
    fig.savefig(out.with_suffix('.png'), dpi=150)
    plt.close(fig)
    print(f'wrote {out}.svg/.png')


def table(data: dict[str, dict[str, dict]]) -> str:
    rows = ['| command | ab mean ± σ (ms) | ab min | bab mean ± σ (ms) | bab min | speedup |',
            '|---|---:|---:|---:|---:|---:|']
    for lbl, row in data.items():
        a, b = row['ab'], row['bab']
        rows.append(f"| `{lbl}` | {a['mean']:.1f} ± {a['stddev']:.1f} | {a['min']:.1f} | "
                    f"{b['mean']:.2f} ± {b['stddev']:.2f} | {b['min']:.2f} | "
                    f"**{speedup(row):.1f}×** |")
    return '\n'.join(rows)


def summary(name: str, data: dict[str, dict[str, dict]]) -> str:
    sp = {lbl: speedup(row) for lbl, row in data.items()}
    best = max(sp, key=sp.get)
    worst = min(sp, key=sp.get)
    return (f'{name}: median speedup {statistics.median(sp.values()):.1f}× '
            f'(geo-mean {statistics.geometric_mean(sp.values()):.1f}×), '
            f'best `{best}` {sp[best]:.1f}×, worst `{worst}` {sp[worst]:.1f}×')


def main() -> int:
    ap = argparse.ArgumentParser()
    runs = sorted((HERE / 'results/live').glob('live-*'))
    ap.add_argument('--live', type=Path, default=runs[0] if runs else None)
    ap.add_argument('--local', type=Path, default=HERE / 'results/local')
    ap.add_argument('--plots', type=Path, default=HERE / 'plots')
    args = ap.parse_args()
    style()

    live = load_live(args.live)
    env = dict(line.split('=', 1) for line in (args.live / 'env.txt').read_text().splitlines())
    nodelay = load_local(args.local / 'nodelay.json')
    realtime = load_local(args.local / 'realtime.json')
    for name, target in (('info-cold-nodelay', nodelay), ('info-cold-realtime', realtime)):
        cold = load_local(args.local / f'{name}.json', rename='info (cold cache)')
        items = list(target.items())
        at = [k for k, _ in items].index('info') + 1
        target.clear()
        target.update(items[:at] + list(cold.items()) + items[at:])

    when = env['date_start'][:16].replace('T', ' ')
    bars(live, 'Rewrite it in Rust: actually worth it',
         f"live on Allegro (Slurm {env['slurm'].split()[-1]}, {env['jobs_total']} jobs, "
         f"{env['nodes']} nodes), {when} CET, login node; 10 runs + 1 warmup each",
         args.plots / 'live')
    bars(nodelay, 'Python startup is the whole story',
         'local replay of Allegro, instant fake Slurm (≈1 ms per call): what each tool costs '
         'on its own; 30 runs, pinned CPUs', args.plots / 'local-nodelay', log=True)
    bars(realtime, 'Same cluster, same answers, less waiting',
         'local replay of Allegro with the recorded Slurm latencies (slurmctld round trips '
         'as measured live); 30 runs, pinned CPUs', args.plots / 'local-realtime')
    startup = {}
    for lbl in ('--version', '-h'):
        startup[f'{lbl} (fox)'] = nodelay[lbl]
        startup[f'{lbl} (Allegro)'] = live[lbl]
    bars(startup, 'Hello, is this thing on?',
         'pure start-up: no Slurm call at all (fox: local workstation; Allegro: login node)',
         args.plots / 'startup', log=True)
    speedup_plot({'live (Allegro)': live, 'local, realtime replay': realtime,
                  'local, no delay': nodelay}, args.plots / 'speedup')

    user_rt = load_local(args.local / 'as-user-a-realtime.json')
    user_nd = load_local(args.local / 'as-user-a-nodelay.json')
    for name, data in (('live', live), ('local realtime', realtime),
                       ('local no-delay', nodelay), ('as-user-a realtime', user_rt),
                       ('as-user-a no-delay', user_nd)):
        print(f'\n### {name}\n')
        print(summary(name, data) + '\n')
        print(table(data))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
