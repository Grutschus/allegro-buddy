from __future__ import annotations

from rich.text import Text

from allegro_buddy.core import (
    CONSOLE,
    DEFAULT_JOB_OUTPUT_TAIL_LINES,
    base_job_id,
    build_job_history_rows,
    current_user,
    die,
    get_job_detail,
    get_job_output,
    get_user_job_history,
    muted,
    render_table,
    user_from_userid,
)


def cmd_job_history(*, limit: int) -> None:
    jobs = get_user_job_history(finished_only=True)
    if not jobs:
        CONSOLE.print(muted('No finished jobs in your history.'))
        return

    shown = jobs if limit <= 0 else jobs[:limit]
    render_table(
        [
            ('JobID', 'left'),
            ('Name', 'left'),
            ('State', 'left'),
            ('Exit code', 'left'),
            ('Ended', 'left'),
        ],
        build_job_history_rows(shown),
        title='Finished jobs',
    )


def cmd_job_output(*, jobid: str, stderr: bool) -> None:
    stream = 'stderr' if stderr else 'stdout'

    # Pre-check ownership so we can surface a clearer error than the generic
    # "could not resolve <stream> path" message raised by core.get_job_output.
    detail = get_job_detail(jobid) or get_job_detail(base_job_id(jobid))
    if detail is not None:
        owner = user_from_userid(detail.get('UserId', ''))
        if owner and owner != current_user():
            die(f'job {jobid} belongs to {owner}; you can only read your own output')

    output_path, output_text = get_job_output(
        jobid,
        stream=stream,
        tail_lines=DEFAULT_JOB_OUTPUT_TAIL_LINES,
    )

    # The path is the one thing to act on (open the whole file); say so when cut.
    header = muted(str(output_path))
    if len(output_text.splitlines()) >= DEFAULT_JOB_OUTPUT_TAIL_LINES:
        header.append(f' · last {DEFAULT_JOB_OUTPUT_TAIL_LINES} lines')
    CONSOLE.print(header)

    if not output_text.strip():
        CONSOLE.print(muted('The file is empty.'))
        return

    CONSOLE.print(Text(output_text.rstrip('\n')))
