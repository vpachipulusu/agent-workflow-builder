"""Tell a language model what it may and may not change when editing the definition.

The model's answer is validated afterwards, so this text is there to make a valid
answer likely, not to enforce anything.
"""

from weekend_saver.custom.catalog import CORE_STEPS, CoreStep
from weekend_saver.custom.definition import DEFINITION_NAME
from weekend_saver.executors import DEFAULT_ROUTES, LOAD_TARGETS_ID, REPORT_ID

_RULES = f"""\
Keep every built-in executor exactly as it is: same "name", "type": "builtin", same
"ref". Change its "config" only when the user asks to change one of its settings.

Every edge that leaves a built-in step uses one of that step's outcome names as its
"condition". Each outcome must still arrive at the same built-in step as listed above,
either directly or through steps you add.

You may add three kinds of step:
- An AI note step: "type": "agent" with "instructions". It comments on the run and
  passes it on unchanged. It has exactly one outgoing edge, with "condition": null.
  To put it between X and Y, replace the edge X -> Y (keep its condition on the new
  edge X -> new_step) and add new_step -> Y with "condition": null.
- An AI gate: an agent step with one outgoing edge with "condition": null (continue)
  plus one or more edges to "{REPORT_ID}" whose "condition" says in plain words when
  to stop the run. A gate may only sit before "apply": never on a path that arrives
  at "{REPORT_ID}" or "verify".
- A pass-through step: "type": "function", one outgoing edge with "condition": null.

Do not remove, rename, duplicate or reorder built-in steps. Do not add edges that
leave "{REPORT_ID}". Do not use "fan_in". Keep "name": "{DEFINITION_NAME}". "start"
is "{LOAD_TARGETS_ID}" or an added step that leads to it.
"""


def edit_guidance() -> str:
    steps = "\n".join(_describe(step) for step in CORE_STEPS)
    return (
        f"## Rules for the {DEFINITION_NAME} workflow\n"
        "This workflow really switches Azure resources off and on. It is built around "
        "six built-in steps:\n"
        f"{steps}\n\n{_RULES}"
    )


def _describe(step: CoreStep) -> str:
    routes = DEFAULT_ROUTES.get(step.step_id, {})
    outcomes = ", ".join(f'"{outcome}" -> {target}' for outcome, target in routes.items())
    settings = ", ".join(
        f"{setting.name} ({setting.kind.__name__}, default {setting.default!r})"
        for setting in step.settings
    )
    return (
        f'- {step.step_id} (ref "{step.ref}"): {step.description}'
        f" Outcomes: {outcomes or 'none, it ends the run'}."
        f" Settings: {settings or 'none'}."
    )
