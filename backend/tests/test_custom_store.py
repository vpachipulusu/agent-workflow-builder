"""Saving and loading the customized definition, and what runs when it is broken."""

from dataclasses import replace

import pytest
import yaml

from tests.test_custom_definition import summary_before_report, with_changes
from weekend_saver.custom.compiler import DefinitionError
from weekend_saver.custom.definition import (
    DEFINITION_NAME,
    WorkflowDef,
    default_definition,
    definition_to_dict,
)
from weekend_saver.custom.store import DefinitionStore
from weekend_saver.errors import ConfigError
from weekend_saver.models import Action


@pytest.fixture
def store(tmp_path) -> DefinitionStore:
    return DefinitionStore(tmp_path / "weekend_saver" / "workflow.yaml")


def broken() -> WorkflowDef:
    return with_changes(default_definition(), drop_steps=("approval",))


def test_nothing_saved_yet_means_the_default(store):
    assert store.load() == default_definition()


def test_ensure_writes_the_default_once(store):
    store.ensure()
    store.save(summary_before_report())

    store.ensure()

    assert store.load() == summary_before_report()


def test_a_saved_definition_is_read_back(store):
    store.save(summary_before_report())

    assert store.load() == summary_before_report()


def test_an_invalid_definition_is_not_saved(store):
    store.save(summary_before_report())

    with pytest.raises(DefinitionError):
        store.save(broken())

    assert store.load() == summary_before_report()


def test_the_previous_version_is_kept_as_a_backup(store):
    store.save(default_definition())
    store.save(summary_before_report())

    backup = DefinitionStore(store.backup_path)

    assert backup.load() == default_definition()


def test_reset_restores_the_default(store):
    store.save(summary_before_report())

    assert store.reset() == default_definition()
    assert store.load() == default_definition()


def test_the_saved_definition_always_carries_the_reserved_name(store):
    store.save(replace(summary_before_report(), name="my_weekend_flow"))

    assert store.load().name == DEFINITION_NAME


def test_an_unreadable_file_is_a_config_error(store):
    store.path.parent.mkdir(parents=True)
    store.path.write_text("executors: [unclosed", encoding="utf-8")

    with pytest.raises(ConfigError):
        store.load()


def test_a_valid_definition_is_what_runs(store):
    store.save(summary_before_report())

    definition, problem = store.runnable(Action.DISABLE)

    assert definition == summary_before_report()
    assert problem == ""


def _write_raw(store: DefinitionStore, text: str) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(text, encoding="utf-8")


def _broken_yaml() -> str:
    return yaml.safe_dump(definition_to_dict(broken()))


def test_enable_falls_back_to_the_default_when_the_saved_definition_is_broken(store):
    _write_raw(store, _broken_yaml())

    definition, problem = store.runnable(Action.ENABLE)

    assert definition == default_definition()
    assert "default" in problem


def test_enable_falls_back_to_the_default_when_the_file_is_unreadable(store):
    _write_raw(store, "executors: [unclosed")

    definition, problem = store.runnable(Action.ENABLE)

    assert definition == default_definition()
    assert problem


def test_disable_refuses_to_run_a_broken_definition(store):
    _write_raw(store, _broken_yaml())

    with pytest.raises(ConfigError):
        store.runnable(Action.DISABLE)
