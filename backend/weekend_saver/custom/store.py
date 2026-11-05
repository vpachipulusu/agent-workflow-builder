"""Keep the customized definition on disk, in the builder's workflow folder."""

import logging
from dataclasses import replace
from pathlib import Path

import yaml

from weekend_saver.custom.definition import (
    DEFINITION_NAME,
    WorkflowDef,
    default_definition,
    definition_to_dict,
    parse_definition,
)
from weekend_saver.custom.validation import DefinitionError, validate
from weekend_saver.errors import ConfigError
from weekend_saver.files import write_text_atomically
from weekend_saver.models import Action

logger = logging.getLogger(__name__)

# A fixed sentence: this ends up in chat webhooks, where a parser's excerpt of the
# broken file does not belong
_FALLBACK_NOTICE = (
    "The saved workflow could not be used, so this enable run used the default "
    "workflow instead. Open the Weekend Saver page to see what is wrong with it."
)


class DefinitionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.backup_path = path.with_suffix(path.suffix + ".bak")

    def load(self) -> WorkflowDef:
        """The saved definition, or the default when nothing was saved yet."""
        if not self.path.exists():
            return default_definition()
        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError, yaml.YAMLError) as exc:
            # ValueError: not UTF-8. RecursionError: nested absurdly deep. Either way
            # the file is unusable, and callers rely on ConfigError to fall back.
            raise ConfigError(
                f"The saved workflow file could not be read ({_where(exc)})."
            ) from exc
        return parse_definition(data)

    def save(self, definition: WorkflowDef) -> WorkflowDef:
        """Store a definition that passes validation; raises DefinitionError otherwise."""
        # The file's folder is the workflow's identity in the builder, so the name is fixed
        definition = replace(definition, name=DEFINITION_NAME)
        errors = validate(definition)
        if errors:
            raise DefinitionError(errors)
        self._back_up_current()
        text = yaml.safe_dump(definition_to_dict(definition), sort_keys=False, allow_unicode=True)
        write_text_atomically(self.path, text)
        return definition

    def _back_up_current(self) -> None:
        """Keep the version being replaced, unless it was unusable anyway.

        Backing up a broken file would overwrite the last good version with it.
        """
        try:
            usable = self.path.exists() and not validate(self.load())
        except ConfigError:
            usable = False
        if usable:
            write_text_atomically(self.backup_path, self.path.read_text(encoding="utf-8"))

    def ensure(self) -> None:
        """Write the default if there is no file yet, so the builder lists the workflow."""
        if not self.path.exists():
            self.save(default_definition())

    def reset(self) -> WorkflowDef:
        return self.save(default_definition())

    def runnable(self, action: Action) -> tuple[WorkflowDef, str]:
        """The definition a run should use, and a notice when that is not the saved one.

        A broken definition must not keep resources switched off, so enable falls back
        to the default pipeline. Disable does not: skipping one saving is the safe side.
        """
        try:
            definition = self.load()
            errors = validate(definition)
            if errors:
                raise DefinitionError(errors)
        except ConfigError as exc:
            if action is not Action.ENABLE:
                raise
            logger.warning("Using the default workflow instead of the saved one: %s", exc)
            return default_definition(), _FALLBACK_NOTICE
        return definition, ""


def _where(exc: Exception) -> str:
    """Name the problem, with the line for a YAML error, without quoting the file."""
    mark = getattr(exc, "problem_mark", None)
    line = f", line {mark.line + 1}" if mark is not None else ""
    return f"{type(exc).__name__}{line}"
