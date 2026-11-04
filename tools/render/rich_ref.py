"""Render tests/render/cases.json with the real rich==15.0.0 (the differential reference).

    $BAB_RICH_PY tools/render/rich_ref.py tests/render/cases.json > tests/render/expected.json

Each case (rendered once per variant: width, colour system, NO_COLOR) is a list of console operations on Console(file=StringIO, width=W, height=25,
color_system=..., no_color=..., force_terminal=True, _environ={}). The spec format is shared
with tests/render_diff.rs (keep both interpreters in sync).
"""

import io
import json
import sys

import rich.box
from rich.console import Console
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

try:
    import rich_click.rich_box as rcbox
except ImportError:  # pragma: no cover
    rcbox = None


def get_box(name):
    if name is None:
        return None
    if hasattr(rich.box, name):
        return getattr(rich.box, name)
    return getattr(rcbox, name)


def text_part(part):
    if isinstance(part, str):
        return part
    if isinstance(part, list):
        return (part[0], part[1])
    return build(part)


def build(spec):
    if isinstance(spec, str):
        return spec
    kind = spec['type']
    if kind == 'text':
        kwargs = {k: spec[k] for k in ('justify', 'overflow', 'no_wrap', 'end') if k in spec}
        if 'plain' in spec:
            text = Text(spec['plain'], style=spec.get('style', ''), **kwargs)
        else:
            text = Text.assemble(*[text_part(p) for p in spec.get('parts', [])], style=spec.get('style', ''), **kwargs)
        for style, start, end in spec.get('stylize', []):
            text.stylize(style, start, end)
        for value, style in spec.get('append', []):
            text.append(value, style=style)
        return text
    if kind == 'join':
        return build(spec['sep']).join([build(item) for item in spec['items']])
    if kind == 'padding':
        return Padding(build(spec['renderable']), tuple(spec['pad']), expand=spec.get('expand', True))
    if kind == 'table':
        if spec.get('simple'):
            table = Table(
                title=spec.get('title'),
                title_style='bold',
                box=rich.box.SIMPLE,
                show_edge=False,
                pad_edge=False,
                header_style='bold',
            )
        elif 'grid' in spec:
            table = Table.grid(padding=tuple(spec['grid']))
        else:
            table = Table()
        for key, value in spec.get('options', {}).items():
            if key == 'box':
                value = get_box(value)
            elif key in ('title', 'caption') and isinstance(value, dict):
                value = build(value)
            elif key == 'padding':
                value = tuple(value)
            setattr(table, key, value)
        for column in spec.get('columns', []):
            column = dict(column)
            if isinstance(column.get('header'), dict):
                column['header'] = build(column['header'])
            table.add_column(**column)
        for row in spec.get('rows', []):
            table.add_row(*[build(c) for c in row['cells']], style=row.get('style'), end_section=row.get('end_section', False))
        return table
    raise ValueError(kind)


SYSTEMS = {'none': None, 'standard': 'standard', '256': '256', 'truecolor': 'truecolor'}


def variant_name(case, variant):
    suffix = '-nocolor' if variant['no_color'] else ''
    return f"{case['name']}-w{variant['width']}-{variant['color']}{suffix}"


def run(case, variant):
    out = io.StringIO()
    console = Console(
        file=out,
        width=variant['width'],
        height=25,
        color_system=SYSTEMS[variant['color']],
        no_color=variant['no_color'],
        force_terminal=True,
        legacy_windows=False,
        _environ={},
    )
    for op in case['ops']:
        if 'print' in op:
            console.print(build(op['print']), **op.get('kw', {}))
        elif 'newline' in op:
            console.print()
        elif 'clear' in op:
            console.clear()
        else:
            raise ValueError(op)
    return out.getvalue()


def main():
    with open(sys.argv[1]) as fh:
        cases = json.load(fh)
    if len(sys.argv) > 2:
        # Rich caches SGR codes per Style instance regardless of the colour system, so each
        # colour system is rendered in its own process (bab processes use only one).
        color = sys.argv[2]
        result = {
            variant_name(case, v): run(case, v) for case in cases for v in case['variants'] if v['color'] == color
        }
    else:
        import subprocess

        result = {}
        for color in SYSTEMS:
            out = subprocess.run([sys.executable, __file__, sys.argv[1], color], check=True, capture_output=True)
            result.update(json.loads(out.stdout))
    json.dump(result, sys.stdout, indent=1, ensure_ascii=False, sort_keys=True)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
