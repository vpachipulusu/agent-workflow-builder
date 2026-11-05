"""Notes that custom workflow steps attach to a run.

Notes live in the workflow's shared state, so a step can add one without changing the
message it passes on. Approval shows them with the plan and Report puts them in the
run report.
"""

from typing import Any, Protocol

from weekend_saver.models import StepNote

NOTES_STATE_KEY = "weekend_saver.notes"
# Notes end up in chat webhooks and the run history; a runaway model answer must not
MAX_NOTE_CHARS = 2000


class _StateContext(Protocol):
    def get_state(self, key: str, default: Any = None) -> Any: ...

    def set_state(self, key: str, value: Any) -> None: ...


def read_notes(ctx: _StateContext) -> tuple[StepNote, ...]:
    return tuple(ctx.get_state(NOTES_STATE_KEY, ()))


def add_note(ctx: _StateContext, step: str, text: str) -> None:
    """Record what `step` has to say; a step that speaks again replaces its earlier note.

    An approved run is planned a second time, so a step before approval runs twice.
    Its second note describes the plan that is actually applied.
    """
    # Model text ends up in chat webhooks, where <...> is markup and can ping people
    text = text.strip().replace("<", "(").replace(">", ")")[:MAX_NOTE_CHARS]
    if text:
        others = tuple(note for note in read_notes(ctx) if note.step != step)
        ctx.set_state(NOTES_STATE_KEY, (*others, StepNote(step, text)))
