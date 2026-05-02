"""パス定数と設定の読み込み。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ── システムパス（コードの場所）────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT_DIR / "scripts"
HOOKS_DIR = ROOT_DIR / "hooks"
AGENTS_FILE = ROOT_DIR / "AGENTS.md"
SETTINGS_FILE = ROOT_DIR / "settings.yaml"

# ── データパス（settings.yaml の data_dir で変更可能）─────────────────
def _resolve_data_dir() -> Path:
    """settings.yaml の data_dir を読む。未設定なら ROOT_DIR（後方互換）。"""
    if not SETTINGS_FILE.exists():
        return ROOT_DIR
    try:
        import yaml  # type: ignore
        raw = yaml.safe_load(SETTINGS_FILE.read_text(encoding="utf-8")) or {}
        data_dir = raw.get("data_dir", "")
        if data_dir:
            return Path(data_dir).expanduser().resolve()
    except Exception:
        pass
    return ROOT_DIR

DATA_DIR = _resolve_data_dir()
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
LOGS_DIR = KNOWLEDGE_DIR / "logs"  # 日々の記録(daily / weekly / monthly)を統合
DAILY_DIR = LOGS_DIR / "daily"  # Quartz serves knowledge/, daily must be inside it
WIKI_DIR = KNOWLEDGE_DIR / "wiki"
DRAFT_DIR = KNOWLEDGE_DIR / "inbox"
CONCEPTS_DIR = KNOWLEDGE_DIR / "concepts"   # legacy alias
CONNECTIONS_DIR = KNOWLEDGE_DIR / "connections"  # legacy alias
DRAFT_CONCEPTS_DIR = DRAFT_DIR / "concepts"
DRAFT_CONNECTIONS_DIR = DRAFT_DIR / "connections"
QA_DIR = KNOWLEDGE_DIR / "qa"
REPORTS_DIR = DATA_DIR / "reports"
WEEKLY_DIR = LOGS_DIR / "weekly"
MONTHLY_DIR = LOGS_DIR / "monthly"
PROJECTS_DIR = KNOWLEDGE_DIR / "projects"
NEWS_DIR = KNOWLEDGE_DIR / "news"

INDEX_FILE = KNOWLEDGE_DIR / "index.md"
LOG_FILE = KNOWLEDGE_DIR / "archive" / "build-log.md"  # compile.py のビルドログ（旧 knowledge/log.md）
STATE_FILE = SCRIPTS_DIR / "state.json"  # ランタイム状態はシステム側に置く


# ── 設定クラス ────────────────────────────────────────────────────────

@dataclass
class AnthropicConfig:
    api_key_env: str = "ANTHROPIC_API_KEY"


@dataclass
class VertexAIConfig:
    project_id: str = ""
    location: str = "us-central1"


@dataclass
class LLMConfig:
    backend: str = "claude_code"
    model: str = "claude-sonnet-4-6"
    anthropic: AnthropicConfig = field(default_factory=AnthropicConfig)
    vertex_ai: VertexAIConfig = field(default_factory=VertexAIConfig)


@dataclass
class KnowledgeConfig:
    compile_after_hour: int = 18
    min_turns_to_flush: int = 1
    language: str = "ja"


@dataclass
class Settings:
    environment: str = "private"
    llm: LLMConfig = field(default_factory=LLMConfig)
    knowledge: KnowledgeConfig = field(default_factory=KnowledgeConfig)

    @classmethod
    def load(cls) -> "Settings":
        """settings.yaml を読み込んで Settings を返す。ファイルがなければデフォルト値を使用。"""
        if not SETTINGS_FILE.exists():
            return cls()

        try:
            import yaml  # type: ignore
        except ImportError:
            # PyYAML が入っていなければデフォルト値を返す
            return cls()

        raw = yaml.safe_load(SETTINGS_FILE.read_text(encoding="utf-8")) or {}

        llm_raw = raw.get("llm", {})
        anthropic_raw = llm_raw.get("anthropic", {})
        vertex_raw = llm_raw.get("vertex_ai", {})
        kb_raw = raw.get("knowledge", {})

        return cls(
            environment=raw.get("environment", "private"),
            llm=LLMConfig(
                backend=llm_raw.get("backend", "claude_code"),
                model=llm_raw.get("model", "claude-sonnet-4-6"),
                anthropic=AnthropicConfig(
                    api_key_env=anthropic_raw.get("api_key_env", "ANTHROPIC_API_KEY"),
                ),
                vertex_ai=VertexAIConfig(
                    project_id=vertex_raw.get("project_id", ""),
                    location=vertex_raw.get("location", "us-central1"),
                ),
            ),
            knowledge=KnowledgeConfig(
                compile_after_hour=kb_raw.get("compile_after_hour", 18),
                min_turns_to_flush=kb_raw.get("min_turns_to_flush", 1),
                language=kb_raw.get("language", "ja"),
            ),
        )


# ── タイムゾーン ──────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def today_iso() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
