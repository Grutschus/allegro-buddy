"""Write tests/render/cases.json: the render differential cases (see rich_ref.py).

    python3 tools/render/make_cases.py
"""

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
COLORS = ['none', 'standard', '256', 'truecolor']
cases = []


def case(name, ops, widths=(80,), colors=('standard',), no_color=(False,)):
    variants = [{'width': w, 'color': c, 'no_color': nc} for w in widths for c in colors for nc in no_color]
    cases.append({'name': name, 'variants': variants, 'ops': ops})


def T(plain=None, style='', **kw):
    spec = {'type': 'text', **kw}
    if plain is not None:
        spec['plain'] = plain
    if style:
        spec['style'] = style
    return spec


def P(spec, **kw):
    return {'print': spec, 'kw': kw} if kw else {'print': spec}


STYLES = [
    'bold', 'dim', 'italic', 'underline', 'bold red', 'bold yellow', 'bold green', 'bold blue',
    'bold cyan', 'green', 'yellow', 'blue', 'red', 'cyan', 'magenta', 'white', 'not bold',
    'bold not bold', 'on blue', 'red on white', '#ff8800', 'rgb(10,200,30)', 'color(200)',
    'color(9)', 'bright_red', 'grey50', 'status.spinner', 'repr.number', 'table.header', 'none',
    'bogus', 'b i u s', 'reverse blink2 conceal strike', 'underline2 frame encircle overline',
    'default on default', '#808080', '#123456 on #fedcba',
]
case('styles', [P(T(f'{s}!', s)) for s in STYLES], colors=COLORS, no_color=(False, True))

case('assemble', [
    P(T(parts=[['error: ', 'bold red'], 'something went wrong'])),
    P(T(parts=[['warning: ', 'bold yellow'], T('job 12 is ', 'white'), ['RUNNING', 'green']])),
    P(T('ⓘ `bab why` shows what is short', 'dim')),
    P(T(parts=['  ', T(parts=[['A100', 'cyan'], ' starts 123 now. This runs:'])])),
    P({'type': 'join', 'sep': T(' · '), 'items': [T('1 running', 'green'), T(parts=['2 pending (', ['in 3h', 'cyan'], ')'])]}),
    P({'type': 'join', 'sep': T(', '), 'items': [T(parts=['proj1', [' (default)', 'dim']]), T('proj2')]}),
    P(T('styled base', 'bold', stylize=[['red', 0, 6], ['underline', 3, 20]])),
    P(T('', 'bold')),
    P(T('end-less', 'green', end='')),
    P(T('!')),
    P(T('appended', append=[[' a', 'bold'], [' b', None], [' c', 'dim red']])),
], colors=COLORS)

LONG = ('The quick brown fox jumps over the lazy dog and keeps running past gpu101,gpu102,'
        'gpu201,gpu202,gpu203 while waiting for Resources (GPU-bound · max 3/4 free).')
case('wrap', [
    P(T(LONG)),
    P(T(LONG, 'dim')),
    P(T(LONG, justify='left')),
    P(T(LONG, justify='center', style='bold')),
    P(T(LONG, justify='right')),
    P(T(LONG, justify='full')),
    P(T('averyveryveryverylongwordwithoutanyspacesthatmustbefoldedsomewhere' * 2)),
    P(T('averyveryveryverylongwordwithoutanyspacesthatmustbefoldedsomewhere' * 2, overflow='ellipsis')),
    P(T('averyveryveryverylongwordwithoutanyspacesthatmustbefoldedsomewhere' * 2, overflow='crop')),
    P(T(LONG, no_wrap=True)),
    P(T(LONG), no_wrap=True, overflow='ellipsis'),
    P(T(LONG), soft_wrap=True),
    P(T('trailing spaces     ')),
    P(T('line one\nline two  \n\nline four\n')),
    P(T('tab\tseparated\tcolumns\t!', 'bold')),
    P(T('中文字符和全角字符混在一起的一行非常长的文本用于测试换行' * 2)),
    P(T('emoji 😃 and ❤️ and 👩‍💻 mixed ' * 4)),
    P(T(parts=[['styled ', 'red'], ['words ', 'bold'], 'wrap around ' * 8, ['the end', 'green']])),
    P(T(LONG), width=30),
    P(T(LONG), style='italic'),
], widths=(20, 40, 80), colors=('standard',))

STRS = [
    'Left unchanged.', 'Canceled 123, 456_7.', 'Canceled 70110_3, 70111.',
    'every 10s · 12:34:56 · Ctrl-C to quit', 'every 12.5s · 01:02:03 · Ctrl-C to quit',
    "quoted 'single' and \"double\" strings", 'path /home/alice/run.sh and /tmp/', 'url https://example.com/x?y=1',
    'uuid 123e4567-e89b-12d3-a456-426614174000', 'ip 10.0.0.1 and ::1 and fe80::1', 'True False None ...',
    'call(foo) <tag attr="v"> x=1', 'numbers -1 2.5 3e10 0xff 4j 1h25m 5/12 ≤73G', '[bold]markup[/bold] [0-3] [123] job[abc]x',
    r'escaped \[bold] and \\[red]x', ':cat: :smiley-emoji: 12:00: x:y:', '[red]unclosed',
    'brackets [] {} ()', 'ab-dev', 'k' * 60 + '=v1 a="b"c=d e=', 'dead-beef-0000-1111 ab:cd x.y.z <a>', 'gpu[101-104]', '', '   ', 'tab\there',
]
case('strings', [P(s) for s in STRS] + [P(s, style='dim') for s in STRS[:4]] + [P(s, highlight=False) for s in STRS[:3]] + [P(s, markup=False) for s in STRS[13:16]] + [P(s, emoji=False) for s in STRS[15:16]], colors=COLORS)
case('strings-narrow', [P(s) for s in STRS], widths=(10,), colors=('standard',))
case('misc', [{'newline': 1}, P(T('x'), end=''), P('y', end='!\n'), {'clear': 1}, {'newline': 1}], colors=('standard',))


def simple(title, columns, rows, **opts):
    return {'type': 'table', 'simple': True, 'title': title, 'columns': columns, 'rows': rows, 'options': opts}


def col(header, justify='left', **kw):
    return {'header': header, 'justify': justify, **kw}


DASH = T('-', 'dim')
overview = simple('Resource overview', [col('Partition'), col('Time limit'), col('Idle nodes', 'right'), col('Free GPUs', 'right'), col('Free CPUs', 'right'), col('Free memory', 'right')], [
    {'cells': [T('all', 'bold'), DASH, '1/5', T(parts=[['5', 'green'], ['/12', 'dim']]), '44/80', '306/450G'], 'end_section': True},
    {'cells': [T('gpumicro', 'bold green'), T('1h'), '0/3', '5/12', '20/48', '158/270G']},
    {'cells': [T('gpu', 'bold green'), T('2d'), '0/3', '5/12', '20/48', '158/270G'], 'end_section': True},
    {'cells': [T('micro', 'bold blue'), T('1h'), '0/1', DASH, '8/16', '58/90G']},
    {'cells': [T('small', 'bold blue'), T('2d2h'), '0/1', DASH, '8/16', '58/90G']},
])
queue = simple('Queue', [col('JobID'), col('Name'), col('State'), col('Partition'), col('Elapsed', 'right'), col('Time left', 'right'), col('Start'), col('Node/Reason')], [
    {'cells': [T('70110', 'cyan'), 'ab-dev', T('RUNNING', 'green'), T('gpu', 'bold green'), T('1h25m'), T('6h35m'), T(''), T('gpu101', 'green')]},
    {'cells': [T('70120', 'cyan'), 'train-large', T('PENDING', 'yellow'), T('gpu', 'bold green'), T(''), T('1d'), 'in 2h10m', T('GPU-bound · max 3/4 free', 'yellow')]},
    {'cells': [T('70122', 'cyan'), 'finetune-xl-with-a-really-long-name', T('PENDING', 'yellow'), T('gpu', 'bold green'), T(''), T('12h'), DASH, T('starts now w/ mem ≤ 73G', 'yellow')]},
    {'cells': [T('71000_[1-3]', 'cyan'), 'task [x] :cat: [bold]b[/]', T('RUNNING', 'green'), T('small', 'bold blue'), T('3m'), T('9h57m'), '', T('cmp201', 'blue')]},
])
reservations = simple('Reservations', [col('Reservation'), col('Nodes'), col('When'), col('For')], [
    {'cells': ['maint-nov', 'gpu101,gpu102,gpu201,gpu202,gpu203,gpu204,gpu205', 'in 6d22h, for 10h', 'others']},
])
untitled = simple(None, [col('Key'), col('Value'), col('Source')], [
    {'cells': [T('[dev] partition'), T('gpu'), T('~/.config/allegro-buddy/config.ini', 'dim')]},
    {'cells': [T('[cluster] gpu_partitions'), T('gpumicro, gpushort, gpusmall, gpu, gpularge, gpuverylarge'), T('preset allegro', 'dim')]},
])
for name, table in (('overview', overview), ('queue', queue), ('reservations', reservations), ('untitled', untitled)):
    case(f'table-{name}', [P(table), P(table, width=60), P(T('free/total', 'dim'))], widths=(40, 80, 160), colors=('standard',))
case('table-colors', [P(overview), P(queue)], widths=(100,), colors=COLORS, no_color=(False, True))
case('table-empty', [P(simple('Empty', [col('A'), col('B', 'right')], [])), P(simple(None, [], []))], colors=('standard',))
case('table-center', [P(simple('Centered title over a narrow table', [col('A', 'center'), col('B', 'right')], [
    {'cells': ['x', 'y']}, {'cells': ['longer cell', 'z']}]))], widths=(20, 80), colors=('standard',))

you = {'type': 'table', 'grid': [0, 2], 'columns': [{'style': 'dim', 'no_wrap': True}, {}], 'rows': [
    {'cells': ['user', 'alice']},
    {'cells': ['accounts', {'type': 'join', 'sep': T(', '), 'items': [T(parts=['ml-lab', [' (default)', 'dim']]), T('teaching'), T('a-very-long-account-name'), T('another-account')]}]},
    {'cells': ['qos', 'long, normal, short, preempt, gpu-hog, interactive, overflow-queue']},
    {'cells': ['jobs', {'type': 'join', 'sep': T(' · '), 'items': [T(parts=['25 running (next ends in ', ['6h35m', 'cyan'], ')']), T('3 pending')]}]},
]}
case('grid-you', [P(T('You', 'bold')), P(you), P(you, width=40)], widths=(30, 50, 80, 120), colors=('none', 'standard'))

# rich-click-like help panels: HORIZONTALS_TOP table inside a SIMPLE-less layout, ratio columns.
opts_table = {'type': 'table', 'options': {'box': 'HORIZONTALS_TOP', 'show_header': False, 'expand': True, 'pad_edge': False, 'padding': [0, 1], 'highlight': True}, 'columns': [
    {'style': 'bold cyan', 'no_wrap': True}, {'style': 'bold green', 'no_wrap': True}, {'style': 'bold yellow'}, {'ratio': 1}], 'rows': [
    {'cells': ['-w', '--watch', '[SECONDS]', T('refresh every SECONDS (default 10) until Ctrl-C')]},
    {'cells': ['', '--all', '', T('show all users\' jobs, which can be a lot of output on a busy cluster and wraps')]},
    {'cells': ['-h', '--help', '', T('Show this message and exit.')]},
]}
case('help-like', [P({'type': 'padding', 'renderable': opts_table, 'pad': [0, 1, 0, 1]}), P(opts_table)], widths=(40, 80, 100), colors=('none', 'standard'))
for box in ('ROUNDED', 'SQUARE', 'HEAVY_HEAD', 'MINIMAL', 'SIMPLE_HEAD', 'DOUBLE_EDGE', 'ASCII', 'MARKDOWN', 'HORIZONTALS'):
    t = {'type': 'table', 'options': {'box': box, 'title': 'Title', 'caption': 'caption text', 'show_lines': box == 'ROUNDED',
         'row_styles': ['dim', ''] if box == 'SQUARE' else [], 'border_style': 'blue', 'show_footer': box == 'HEAVY_HEAD'},
         'columns': [{'header': 'Name', 'footer': 'total'}, {'header': 'Count', 'justify': 'right', 'footer': '3'},
                     {'header': 'Note', 'vertical': 'middle'}],
         'rows': [{'cells': ['a', '1', 'short']}, {'cells': ['b', '2', 'a much longer note that will wrap on narrow widths'], 'style': 'italic'},
                  {'cells': ['c', '3', T('styled', 'red')], 'end_section': True}, {'cells': ['d', '4', '']}]}
    case(f'box-{box}', [P(t)], widths=(30, 80), colors=('standard',))
case('table-misc', [
    P({'type': 'table', 'options': {'leading': 1, 'expand': True, 'min_width': 50}, 'columns': [{'header': 'A', 'ratio': 2}, {'header': 'B', 'ratio': 1, 'min_width': 5}, {'header': 'C', 'width': 6, 'overflow': 'fold'}],
       'rows': [{'cells': ['one', 'two', 'threefourfive']}, {'cells': ['x' * 30, 'y', 'z']}]}),
    P({'type': 'table', 'options': {'width': 50, 'padding': [1, 2], 'collapse_padding': True}, 'columns': [{'header': 'L', 'max_width': 8}, {'header': 'R', 'justify': 'center'}],
       'rows': [{'cells': ['abcdefghijkl mnop', 'q']}, {'cells': ['r', 's t u v w']}]}),
    P({'type': 'table', 'columns': [{'header': 'Outer'}, {'header': 'Nested'}], 'rows': [{'cells': ['n', {'type': 'table', 'grid': [0, 1], 'columns': [{}, {}], 'rows': [{'cells': ['k', 'v']}]}]}]}),
    P({'type': 'padding', 'renderable': T('padded text that wraps around', 'bold'), 'pad': [1, 3, 1, 2]}),
    P({'type': 'padding', 'renderable': 'unexpanded [b]str[/b]', 'pad': [0, 2], 'expand': False}),
], widths=(25, 60), colors=('standard',))

# Seeded random cases: broad coverage of wrapping and the column width algorithm.
import random

rng = random.Random(15)
WORDS = ['gpu', 'a100', 'RUNNING', 'x', 'node[01-04]', 'averyveryverylongtoken', '中文', '全角字符', 'ⓘ', '·', '…',
         '12:34', '5/12', 'job_1', '[bold]b[/]', ':cat:', 'tab\tx', '  ', 'dash-ed', 'emoji😃', 'Ä', 'ß', '→', '≤']
RSTYLES = ['', '', 'bold', 'dim', 'red', 'bold green', 'cyan', 'italic', 'reverse']


def rwords(n):
    return ' '.join(rng.choice(WORDS) for _ in range(n))


def rcell():
    kind = rng.random()
    if kind < 0.4:
        return rwords(rng.randint(0, 6))
    if kind < 0.8:
        return T(rwords(rng.randint(0, 6)), rng.choice(RSTYLES))
    return T(parts=[[rwords(rng.randint(1, 3)), rng.choice(RSTYLES)], ' ', rwords(rng.randint(0, 3))])


for i in range(int(__import__("os").environ.get("BAB_RANDOM_TABLES", "40"))):
    ncols = rng.randint(1, 6)
    columns = []
    for _ in range(ncols):
        c = {'header': rwords(rng.randint(0, 2)), 'justify': rng.choice(['left', 'right', 'center', 'full', 'default'])}
        if rng.random() < 0.25:
            c['no_wrap'] = True
        if rng.random() < 0.15:
            c['overflow'] = rng.choice(['fold', 'crop', 'ellipsis'])
        if rng.random() < 0.1:
            c['max_width'] = rng.randint(1, 12)
        if rng.random() < 0.1:
            c['min_width'] = rng.randint(1, 12)
        if rng.random() < 0.15:
            c['style'] = rng.choice(RSTYLES[1:])
        columns.append(c)
    rows = [{'cells': [rcell() for _ in range(ncols)], 'end_section': rng.random() < 0.2} for _ in range(rng.randint(0, 6))]
    flavour = rng.random()
    if flavour < 0.5:
        table = simple(rwords(rng.randint(0, 4)) or None, columns, rows)
    elif flavour < 0.7:
        table = {'type': 'table', 'grid': [0, rng.randint(0, 3)], 'columns': columns, 'rows': rows}
    else:
        table = {'type': 'table', 'columns': columns, 'rows': rows, 'options': {
            'box': rng.choice(['ROUNDED', 'SIMPLE', 'HORIZONTALS_TOP', 'MINIMAL', 'SQUARE']),
            'expand': rng.random() < 0.3, 'show_header': rng.random() < 0.7, 'pad_edge': rng.random() < 0.5,
            'show_edge': rng.random() < 0.6, 'collapse_padding': rng.random() < 0.2}}
    case(f'random-table-{i}', [P(table)], widths=(rng.randint(8, 30), rng.randint(31, 120)), colors=('standard',))

for i in range(int(__import__("os").environ.get("BAB_RANDOM_TEXTS", "20"))):
    spec = T(rwords(rng.randint(5, 40)), rng.choice(RSTYLES), justify=rng.choice(['left', 'right', 'center', 'full', 'default']),
             overflow=rng.choice(['fold', 'crop', 'ellipsis']), no_wrap=rng.random() < 0.2)
    case(f'random-text-{i}', [P(spec), P(rwords(rng.randint(3, 20)))], widths=(rng.randint(3, 25), rng.randint(26, 90)), colors=('standard',))

(ROOT / 'tests/render/cases.json').write_text(json.dumps(cases, indent=1, ensure_ascii=False) + '\n')
print(len(cases), 'cases,', sum(len(c['variants']) for c in cases), 'variants')
