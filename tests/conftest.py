"""
Pytest fixtures for the locus test suite.

Provides an isolated temp `data_dir` so tests don't touch real
locus-private content. Tests that need it depend on `kb_dir`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make scripts/ importable for tests.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture
def kb_dir(tmp_path: Path, monkeypatch) -> Path:
    """
    A throw-away knowledge-base layout under tmp_path, with all relevant
    config.* and utils.* path constants redirected so module-level imports
    don't have to be re-done.

    Layout:
        kb_dir/
        ├── knowledge/
        │   ├── daily/
        │   ├── wiki/
        │   ├── inbox/wiki/
        │   ├── qa/
        │   ├── archive/
        │   └── index.md
        ├── reports/
        └── scripts/state.json
    """
    knowledge = tmp_path / "knowledge"
    daily = knowledge / "daily"
    wiki = knowledge / "wiki"
    inbox_wiki = knowledge / "inbox" / "wiki"
    qa = knowledge / "qa"
    archive = knowledge / "archive"
    reports = tmp_path / "reports"
    scripts = tmp_path / "scripts"

    for d in (daily, wiki, inbox_wiki, qa, archive, reports, scripts):
        d.mkdir(parents=True, exist_ok=True)

    (knowledge / "index.md").write_text("# index\n", encoding="utf-8")
    (archive / "build-log.md").write_text("# build log\n", encoding="utf-8")
    state_file = scripts / "state.json"
    state_file.write_text('{"ingested": {}, "query_count": 0, "last_lint": null, "total_cost": 0.0}', encoding="utf-8")

    # Redirect every module that has cached the old constants.
    # NOTE: `from config import X` rebinds X in the importing module's namespace,
    # so each consumer module must be patched individually.
    import config
    import utils
    import lint_fix

    targets = [
        ("DATA_DIR", tmp_path),
        ("KNOWLEDGE_DIR", knowledge),
        ("DAILY_DIR", daily),
        ("WIKI_DIR", wiki),
        ("DRAFT_DIR", knowledge / "inbox"),
        ("CONCEPTS_DIR", knowledge / "concepts"),
        ("CONNECTIONS_DIR", knowledge / "connections"),
        ("DRAFT_CONCEPTS_DIR", knowledge / "inbox" / "concepts"),
        ("DRAFT_CONNECTIONS_DIR", knowledge / "inbox" / "connections"),
        ("QA_DIR", qa),
        ("REPORTS_DIR", reports),
        ("INDEX_FILE", knowledge / "index.md"),
        ("LOG_FILE", archive / "build-log.md"),
        ("STATE_FILE", state_file),
    ]
    for module in (config, utils, lint_fix):
        for name, value in targets:
            monkeypatch.setattr(module, name, value, raising=False)

    return tmp_path
