"""Run the Python reference CLI (allegro-buddy 2.7, click 8.3.2, rich-click 1.9.9) as `bab`.

Usage: python ref_bab.py ARGS...   (the venv must have the pinned packages installed)

With BAB_REF_STUB=1 the handlers are replaced by stubs that print the arguments they get,
so parsing/dispatch can be compared without Slurm.
"""

import os
import sys

from allegro_buddy import core

core.CLI_NAME = 'bab'

from allegro_buddy import cli  # noqa: E402

cli.l_command.short_help = cli.l_command.short_help.replace('short for ab ', 'short for bab ')
cli.dev_start_command.help = cli.dev_start_command.help.replace('(ab config', '(bab config')
for _param in cli.completion_command.params:
    if _param.name == 'prog':
        _param.default = 'bab'

if os.environ.get('BAB_REF_STUB') == '1':

    def _stub(name):
        def handler(*args, **kwargs):
            items = [repr(a) for a in args] + [f'{k}={v!r}' for k, v in kwargs.items()]
            print(f'{name}({", ".join(items)})')

        return handler

    for _name in (
        'cmd_info', 'cmd_queue', 'cmd_free', 'cmd_node', 'cmd_why', 'cmd_job_history',
        'cmd_job_output', 'cmd_dev_start', 'cmd_dev_status', 'cmd_dev_login', 'cmd_dev_stop',
    ):
        setattr(cli, _name, _stub(_name))

    def _run_watched(render, interval):
        print(f'watch={interval!r}')
        render()

    cli.run_watched = _run_watched
    cli.find_dev_jobs = lambda: [{'JobId': '4711'}, {'JobId': '4712'}, {'JobId': '5000'}]
    cli.load_user_pending_jobs = lambda: [{'JobID': '333'}, {'JobID': '344'}, {'JobID': '444_[1-3]'}]
    cli.job_history_completion_ids = lambda incomplete: [
        i for i in ('1001', '1002', '2001') if i.startswith(incomplete)
    ]
    import allegro_buddy.handlers.config as _config

    _config.cmd_config_show = _stub('cmd_config_show')

cli.main(prog_name='bab')
