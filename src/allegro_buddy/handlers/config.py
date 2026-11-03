from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text

from allegro_buddy import settings
from allegro_buddy.core import (
    CONSOLE,
    collect_display_gpu_types,
    gpu_type_label,
    is_gpu_partition,
    load_nodes,
    load_partitions,
    muted,
    node_gpu_type_counts,
    render_table,
)

if TYPE_CHECKING:
    from allegro_buddy.core import TableRow


def display_key(section: str, key: str) -> str:
    # Lookup tables keep their keys verbatim; option keys show as typed: log-dir.
    return key if settings.SECTIONS.get(section) is None else key.replace('_', '-')


def cmd_config_show() -> None:
    current = settings.load()
    head = Text()
    head.append('Preset: ', style='dim')
    head.append(current.preset or 'none', style='bold')
    head.append(f' ({current.preset_reason})', style='dim')
    for label, path in (
        ('Site file', settings.site_config_path()),
        ('User file', settings.user_config_path()),
    ):
        head.append(f'\n{label}: ', style='dim')
        head.append(str(path))
        head.append('' if path.exists() else ' (not present)', style='dim')
    CONSOLE.print(head)
    CONSOLE.print()

    items = sorted(current.values.items())
    rows: list[TableRow] = [
        [Text(f'[{section}] {display_key(section, key)}'), Text(value), muted(source)]
        for (section, key), (value, source) in items
    ]
    breaks = {i for i in range(len(items) - 1) if items[i][0][0] != items[i + 1][0][0]}
    render_table(
        [('Setting', 'left'), ('Value', 'left'), ('Source', 'left')],
        rows,
        title='Settings',
        section_breaks=breaks,
    )
    CONSOLE.print()

    nodes = load_nodes(strict=False)
    partitions = load_partitions(strict=False)
    default = next(
        (p['PartitionName'] for p in partitions if p.get('Default') == 'YES'), None
    )
    gpu_types = collect_display_gpu_types([node_gpu_type_counts(node) for node in nodes])
    detected: list[TableRow] = [
        [
            'GPU partitions',
            ', '.join(
                p['PartitionName']
                for p in partitions
                if is_gpu_partition(p['PartitionName'])
            )
            or muted('none'),
        ],
        [
            'GPU types',
            ', '.join(f'{gpu_type_label(t)} ({t})' for t in gpu_types) or muted('none'),
        ],
        ['Default partition', default or muted('none')],
    ]
    if not nodes:
        CONSOLE.print(muted('Slurm did not answer; nothing detected.'))
        return
    render_table(
        [('Setting', 'left'), ('Value', 'left')], detected, title='Detected from Slurm'
    )
