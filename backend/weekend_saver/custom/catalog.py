"""The built-in steps a workflow definition can use, and the settings each one accepts."""

from dataclasses import dataclass
from typing import Any

from weekend_saver.executors import (
    APPLY_ID,
    APPROVAL_ID,
    DEFAULT_MAX_SNAPSHOT_AGE,
    DEFAULT_ROUTES,
    DEFAULT_VERIFY_ATTEMPTS,
    DEFAULT_VERIFY_INTERVAL_SECONDS,
    LOAD_TARGETS_ID,
    REPORT_ID,
    RESOLVE_STATE_ID,
    VERIFY_ID,
)

REF_PREFIX = "weekend_saver."

_KIND_LABELS = {bool: "true or false", int: "a whole number", float: "a number"}


@dataclass(frozen=True)
class Setting:
    name: str
    kind: type
    default: Any
    description: str
    minimum: float | None = None
    maximum: float | None = None

    def problem_with(self, value: Any) -> str:
        """Why `value` is not acceptable, or an empty string when it is."""
        if not self._has_right_type(value):
            return f"must be {_KIND_LABELS[self.kind]}"
        too_small = self.minimum is not None and value < self.minimum
        too_large = self.maximum is not None and value > self.maximum
        return f"must be {self._allowed_range()}" if too_small or too_large else ""

    def _allowed_range(self) -> str:
        if self.minimum is None:
            return f"at most {self.maximum:g}"
        if self.maximum is None:
            return f"at least {self.minimum:g}"
        return f"between {self.minimum:g} and {self.maximum:g}"

    def _has_right_type(self, value: Any) -> bool:
        # bool is a subclass of int, so it has to be ruled out for the number kinds
        if self.kind is bool:
            return isinstance(value, bool)
        if isinstance(value, bool):
            return False
        return isinstance(value, int if self.kind is int else (int, float))


@dataclass(frozen=True)
class CoreStep:
    step_id: str
    description: str
    settings: tuple[Setting, ...] = ()

    @property
    def ref(self) -> str:
        return f"{REF_PREFIX}{self.step_id}"

    @property
    def outcomes(self) -> tuple[str, ...]:
        return tuple(DEFAULT_ROUTES.get(self.step_id, {}))


CORE_STEPS: tuple[CoreStep, ...] = (
    CoreStep(LOAD_TARGETS_ID, "Check the list of resources before anything talks to Azure."),
    CoreStep(
        RESOLVE_STATE_ID,
        "Read each resource's current state and plan what this run will do to it.",
        (
            Setting(
                "max_snapshot_age_days",
                int,
                DEFAULT_MAX_SNAPSHOT_AGE.days,
                "How old the record of the last disable run may be before enable refuses it.",
                1,
                30,
            ),
        ),
    ),
    CoreStep(
        APPROVAL_ID,
        "Show the plan and wait for a yes or no. Dry runs end here.",
        (
            Setting(
                "require_approval",
                bool,
                True,
                "Ask before a manually started run changes anything.",
            ),
        ),
    ),
    CoreStep(APPLY_ID, "Disable or enable the resources in the approved plan."),
    CoreStep(
        VERIFY_ID,
        "Confirm each resource reached its target state.",
        (
            Setting(
                "attempts", int, DEFAULT_VERIFY_ATTEMPTS, "How many times to check.", 1, 60
            ),
            Setting(
                "interval_seconds",
                float,
                DEFAULT_VERIFY_INTERVAL_SECONDS,
                "Seconds to wait between checks.",
                0,
                300,
            ),
        ),
    ),
    CoreStep(
        REPORT_ID,
        "Send the notification (if configured) and end the run with its report.",
        (Setting("notify", bool, True, "Post the report to the configured webhook."),),
    ),
)

CORE_BY_ID: dict[str, CoreStep] = {step.step_id: step for step in CORE_STEPS}
CORE_BY_REF: dict[str, CoreStep] = {step.ref: step for step in CORE_STEPS}


def catalog_to_json() -> list[dict[str, Any]]:
    """The catalog as plain data, for the API and for the chat-edit prompt."""
    return [
        {
            "name": step.step_id,
            "ref": step.ref,
            "description": step.description,
            "outcomes": {
                outcome: DEFAULT_ROUTES[step.step_id][outcome] for outcome in step.outcomes
            },
            "settings": [
                {
                    "name": setting.name,
                    "type": setting.kind.__name__,
                    "default": setting.default,
                    "description": setting.description,
                    "minimum": setting.minimum,
                    "maximum": setting.maximum,
                }
                for setting in step.settings
            ],
        }
        for step in CORE_STEPS
    ]
