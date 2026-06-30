"""Regression test: chunk_task MUST NOT write fact_extraction_status.

C2 review fix: chunk_task used to call ``_update_fact_extraction_status``
in its body, but the index_task's ``finally`` block overwrote that value
unconditionally.  So the chunk_task write was dead code that cost an
extra DB round-trip per pipeline run.

This test pins the contract: ``_run_chunk`` (the body of the chunk
Celery task) must not call ``_update_fact_extraction_status``.  The
index_task is the single source of truth for that column.

Note: this is a source-level check.  A behavioural test (run chunk_task,
inspect the DB row) would be stronger but requires Celery + Redis
infrastructure to be running.  For now the static check is enough to
catch a copy-paste regression; tighten later if the chunk_task grows
more side effects.
"""

from __future__ import annotations

import inspect


def test_run_chunk_does_not_write_fact_extraction_status():
    """The chunk_task body must not call ``_update_fact_extraction_status``.

    If you find yourself needing to write to the DB from chunk_task,
    do it in index_task's finally block (where the memory count is
    authoritative) or in a new dedicated function.
    """
    from emerald.pipeline import tasks

    source = inspect.getsource(tasks._run_chunk)
    assert "_update_fact_extraction_status" not in source, (
        "_run_chunk must not write fact_extraction_status — "
        "index_task's finally block is the single source of truth "
        "and would overwrite this value unconditionally. See the "
        "C2 review fix in CHANGELOG."
    )


def test_index_task_is_only_writer_of_fact_extraction_status():
    """The fact_extraction_status column is written exclusively by index_task.

    This test fails if anyone re-introduces the dead write in chunk_task
    or extract_task.  It enumerates all callers of the helper to lock
    down the invariant.
    """
    from emerald.pipeline import tasks

    caller_writes = []
    for name, member in inspect.getmembers(tasks):
        # Skip the helper itself (it obviously contains its own name) and
        # only look at the task bodies that might re-introduce the write.
        if name.startswith("_") and inspect.iscoroutinefunction(member) \
                and name != "_update_fact_extraction_status":
            try:
                src = inspect.getsource(member)
            except (OSError, TypeError):
                continue
            if "_update_fact_extraction_status" in src:
                caller_writes.append(name)

    assert caller_writes == ["_run_index"], (
        f"fact_extraction_status must only be written by _run_index; "
        f"found writers: {caller_writes}.  See C2 review fix."
    )
