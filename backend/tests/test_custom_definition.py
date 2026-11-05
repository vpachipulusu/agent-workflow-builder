"""Which edited workflow definitions are accepted, and why the others are not."""

import pytest

from weekend_saver.custom.definition import (
    AGENT,
    FUNCTION,
    EdgeDef,
    StepDef,
    WorkflowDef,
    default_definition,
    definition_to_dict,
    parse_definition,
)
from weekend_saver.custom.validation import core_routes, validate
from weekend_saver.errors import ConfigError
from weekend_saver.executors import DEFAULT_ROUTES


def with_changes(
    definition: WorkflowDef,
    *,
    add_steps: tuple[StepDef, ...] = (),
    add_edges: tuple[EdgeDef, ...] = (),
    drop_edges: tuple[tuple[str, str], ...] = (),
    drop_steps: tuple[str, ...] = (),
    start: str | None = None,
) -> WorkflowDef:
    return WorkflowDef(
        definition.name,
        definition.description,
        start or definition.start,
        (*(step for step in definition.steps if step.name not in drop_steps), *add_steps),
        (
            *(
                edge
                for edge in definition.edges
                if (edge.source, edge.target) not in drop_edges
            ),
            *add_edges,
        ),
    )


def agent(name: str, instructions: str = "Summarize what happened in two sentences.") -> StepDef:
    return StepDef(name, AGENT, instructions)


def summary_before_report() -> WorkflowDef:
    """verify -> summary -> report instead of verify -> report."""
    return with_changes(
        default_definition(),
        add_steps=(agent("summary"),),
        drop_edges=(("verify", "report"),),
        add_edges=(EdgeDef("verify", "summary", "verified"), EdgeDef("summary", "report")),
    )


def holiday_gate() -> WorkflowDef:
    """load_targets -> holiday_check -> resolve_state, with a stop edge to report."""
    return with_changes(
        default_definition(),
        add_steps=(agent("holiday_check", "Decide whether this is a public-holiday week."),),
        drop_edges=(("load_targets", "resolve_state"),),
        add_edges=(
            EdgeDef("load_targets", "holiday_check", "valid"),
            EdgeDef("holiday_check", "resolve_state"),
            EdgeDef("holiday_check", "report", "it is a public-holiday week"),
        ),
    )


def test_the_default_definition_is_valid():
    assert validate(default_definition()) == ()


def test_the_default_definition_gives_the_default_routes():
    assert core_routes(default_definition()) == {
        step: dict(routes) for step, routes in DEFAULT_ROUTES.items()
    }


def test_an_ai_step_can_be_placed_between_two_core_steps():
    definition = summary_before_report()

    assert validate(definition) == ()
    assert core_routes(definition)["verify"] == {"verified": "summary"}


def test_a_gate_before_the_plan_is_valid():
    assert validate(holiday_gate()) == ()


def test_the_start_can_be_a_custom_step_that_leads_to_load_targets():
    definition = with_changes(
        default_definition(),
        add_steps=(StepDef("log_start", FUNCTION),),
        add_edges=(EdgeDef("log_start", "load_targets"),),
        start="log_start",
    )

    assert validate(definition) == ()


def test_one_custom_step_may_sit_on_several_paths_to_the_same_step():
    definition = with_changes(
        default_definition(),
        add_steps=(agent("summary"),),
        drop_edges=(("verify", "report"), ("approval", "report")),
        add_edges=(
            EdgeDef("verify", "summary", "verified"),
            EdgeDef("approval", "summary", "ended"),
            EdgeDef("summary", "report"),
        ),
    )

    assert validate(definition) == ()


def test_a_single_outcome_step_may_use_an_edge_without_a_condition():
    definition = with_changes(
        default_definition(),
        drop_edges=(("apply", "verify"),),
        add_edges=(EdgeDef("apply", "verify"),),
    )

    assert validate(definition) == ()
    assert core_routes(definition)["apply"] == {"applied": "verify"}


@pytest.mark.parametrize("missing", ["load_targets", "approval", "apply", "verify", "report"])
def test_a_core_step_cannot_be_removed(missing):
    definition = with_changes(default_definition(), drop_steps=(missing,))

    assert any(f"'{missing}' is missing" in error for error in validate(definition))


def test_a_core_step_cannot_be_bypassed():
    # resolve_state hands the plan straight to apply, skipping approval
    definition = with_changes(
        default_definition(),
        drop_edges=(("resolve_state", "approval"),),
        add_edges=(EdgeDef("resolve_state", "apply", "planned"),),
    )

    errors = validate(definition)

    assert any("must lead to 'approval'" in error for error in errors)


def test_a_custom_step_cannot_redirect_to_a_different_core_step():
    definition = with_changes(
        default_definition(),
        add_steps=(agent("shortcut"),),
        drop_edges=(("resolve_state", "approval"),),
        add_edges=(EdgeDef("resolve_state", "shortcut", "planned"), EdgeDef("shortcut", "apply")),
    )

    assert any("must lead to 'approval'" in error for error in validate(definition))


def test_an_outcome_without_an_edge_is_reported():
    definition = with_changes(default_definition(), drop_edges=(("approval", "load_targets"),))

    assert any("'approval'" in error and "'replan'" in error for error in validate(definition))


def test_an_edge_with_an_unknown_outcome_is_reported():
    definition = with_changes(
        default_definition(), add_edges=(EdgeDef("verify", "report", "all good"),)
    )

    assert any("'all good'" in error for error in validate(definition))


def test_report_must_be_the_last_step():
    definition = with_changes(
        default_definition(),
        add_steps=(agent("afterwards"),),
        add_edges=(EdgeDef("report", "afterwards"), EdgeDef("afterwards", "report")),
    )

    assert any("'report' ends the run" in error for error in validate(definition))


def test_a_custom_step_needs_exactly_one_way_forward():
    definition = with_changes(
        summary_before_report(), add_edges=(EdgeDef("summary", "approval"),)
    )

    assert any("exactly one edge without a condition" in error for error in validate(definition))


def test_a_stop_edge_must_point_at_report():
    definition = with_changes(
        holiday_gate(), add_edges=(EdgeDef("holiday_check", "apply", "it is urgent"),)
    )

    assert any("can only point at 'report'" in error for error in validate(definition))


def test_a_function_step_cannot_be_a_gate():
    definition = with_changes(
        default_definition(),
        add_steps=(StepDef("check", FUNCTION),),
        drop_edges=(("load_targets", "resolve_state"),),
        add_edges=(
            EdgeDef("load_targets", "check", "valid"),
            EdgeDef("check", "resolve_state"),
            EdgeDef("check", "report", "something is off"),
        ),
    )

    assert any("Only AI steps can stop a run" in error for error in validate(definition))


def test_a_gate_after_the_changes_is_rejected():
    definition = with_changes(
        default_definition(),
        add_steps=(agent("too_late"),),
        drop_edges=(("apply", "verify"),),
        add_edges=(
            EdgeDef("apply", "too_late", "applied"),
            EdgeDef("too_late", "verify"),
            EdgeDef("too_late", "report", "something looks wrong"),
        ),
    )

    assert any("before 'apply'" in error for error in validate(definition))


def test_a_loop_of_custom_steps_is_reported():
    definition = with_changes(
        default_definition(),
        add_steps=(agent("one"), agent("two")),
        drop_edges=(("verify", "report"),),
        add_edges=(
            EdgeDef("verify", "one", "verified"),
            EdgeDef("one", "two"),
            EdgeDef("two", "one"),
        ),
    )

    assert any("never reaches" in error for error in validate(definition))


def test_an_unconnected_step_is_reported():
    definition = with_changes(
        default_definition(),
        add_steps=(agent("orphan"),),
        add_edges=(EdgeDef("orphan", "report"),),
    )

    assert any("'orphan' is not on any path" in error for error in validate(definition))


def test_an_ai_step_needs_instructions():
    definition = with_changes(
        summary_before_report(), drop_steps=("summary",), add_steps=(agent("summary", "  "),)
    )

    assert any("needs instructions" in error for error in validate(definition))


def test_step_names_must_be_unique_and_simple():
    definition = with_changes(
        default_definition(), add_steps=(agent("Bad Name"), StepDef("report", FUNCTION))
    )

    errors = validate(definition)

    assert any("'Bad Name'" in error for error in errors)
    assert any("more than once" in error for error in errors)


def test_an_edge_to_an_unknown_step_is_reported():
    definition = with_changes(default_definition(), add_edges=(EdgeDef("verify", "nowhere"),))

    assert any("'nowhere'" in error for error in validate(definition))


def test_fan_in_is_not_supported():
    data = definition_to_dict(default_definition())
    data["edges"][0]["fan_in"] = True

    assert any("fan-in" in error for error in validate(parse_definition(data)))


def test_a_builtin_step_must_keep_its_name():
    data = definition_to_dict(default_definition())
    data["executors"][0]["name"] = "read_the_list"

    errors = validate(parse_definition(data))

    assert any("must be named 'load_targets'" in error for error in errors)


def test_an_unknown_builtin_step_is_reported():
    data = definition_to_dict(default_definition())
    data["executors"].append(
        {"name": "delete_everything", "type": "builtin", "ref": "weekend_saver.delete"}
    )

    assert any("'weekend_saver.delete'" in error for error in validate(parse_definition(data)))


@pytest.mark.parametrize(
    ("step", "config"),
    [
        ("approval", {"require_approval": "no"}),
        ("verify", {"attempts": 0}),
        ("verify", {"interval_seconds": 9999}),
        ("verify", {"retries": 3}),
        ("resolve_state", {"max_snapshot_age_days": 1.5}),
        ("report", {"notify": 1}),
        ("apply", {"force": True}),
    ],
)
def test_bad_step_settings_are_reported(step, config):
    data = definition_to_dict(default_definition())
    next(item for item in data["executors"] if item["name"] == step)["config"] = config

    errors = validate(parse_definition(data))

    assert any(f"'{step}'" in error for error in errors), errors


def test_good_step_settings_are_accepted():
    data = definition_to_dict(default_definition())
    settings = {
        "approval": {"require_approval": False},
        "verify": {"attempts": 3, "interval_seconds": 5},
        "resolve_state": {"max_snapshot_age_days": 3},
        "report": {"notify": False},
    }
    for item in data["executors"]:
        item["config"] = settings.get(item["name"], {})

    assert validate(parse_definition(data)) == ()


def test_too_many_steps_are_rejected():
    extra = tuple(agent(f"extra_{index}") for index in range(40))

    errors = validate(with_changes(default_definition(), add_steps=extra))

    assert any("at most" in error for error in errors)


def test_a_definition_survives_a_round_trip_through_the_builder_format():
    definition = holiday_gate()

    assert parse_definition(definition_to_dict(definition)) == definition


def test_the_builder_format_uses_the_builders_field_names():
    data = definition_to_dict(summary_before_report())

    assert set(data) == {"name", "description", "start", "executors", "edges"}
    summary = next(item for item in data["executors"] if item["name"] == "summary")
    assert summary["type"] == "agent"
    assert {"source": "summary", "target": "report", "condition": None, "fan_in": False} in data[
        "edges"
    ]


@pytest.mark.parametrize(
    "data",
    [
        [],
        {"name": "weekend_saver"},
        {"name": "x", "description": "", "start": "a", "executors": "nope", "edges": []},
        {"name": "x", "description": "", "start": "a", "executors": [42], "edges": []},
        {"name": "x", "description": "", "start": "a", "executors": [], "edges": [{"source": 1}]},
        {
            "name": "x",
            "description": "",
            "start": "a",
            "executors": [{"name": "a", "type": "agent", "config": []}],
            "edges": [],
        },
    ],
)
def test_a_malformed_definition_is_a_config_error(data):
    with pytest.raises(ConfigError):
        parse_definition(data)
