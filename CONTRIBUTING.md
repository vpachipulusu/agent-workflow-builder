# Contributing

Thank you for your interest in contributing! This document provides guidelines for contributing to the Agent & Workflow Builder project.

## Getting Started

1. **Fork** the repository
2. **Clone** your fork: `git clone https://github.com/<your-username>/agent-workflow-builder.git`
3. **Create a branch**: `git checkout -b feature/my-feature`
4. **Make changes** and commit
5. **Push** to your fork: `git push origin feature/my-feature`
6. Open a **Pull Request** against the `main` branch

## Development Setup

Follow the [Quick Start](README.md#quick-start) instructions in the README.

## Code Style

### Python (Backend)
- Follow [PEP 8](https://peps.python.org/pep-0008/)
- Use type hints for function signatures
- Add docstrings for public functions
- Use `from __future__ import annotations` for modern type syntax

### TypeScript (Frontend)
- Use functional components with hooks
- Keep component files focused and reasonably sized
- Use CSS custom properties (variables) for colors — never hardcode hex values

## Commit Messages

Use clear, descriptive commit messages:

```
feat: add conditional edge evaluation with LLM
fix: resolve drag-to-resize handle visibility
docs: update API reference in README
```

## Reporting Issues

When reporting bugs, please include:
- Steps to reproduce
- Expected vs actual behavior
- Browser / OS / Python version
- Relevant error messages or screenshots

## Adding New Skills

If you'd like to add a new skill (e.g., `test-creator`):

1. Create a folder under `backend/skills/<skill-name>/`
2. Add a `SKILL.md` describing the skill's purpose and guidelines
3. Add validation scripts under `scripts/`
4. Add reference documents under `references/`
5. Update the orchestrator to integrate the new skill

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
