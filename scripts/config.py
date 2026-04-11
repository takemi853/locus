"""パス定数と設定の読み込み。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ── パス ──────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
DAILY_DIR = ROOT_DIR / "daily"
KNOWLEDGE_DIR = ROOT_DIR / "knowledge"
DRAFT_DIR = KNOWLEDGE_DIR / "draft"
CONCEPTS_DIR = KNOWLEDGE_DIR / "concepts"       # verified
CONNECTIONS_DIR = KNOWLEDGE_DIR / "connections"  # verified
DRAFT_CONCEPTS_DIR = DRAFT_DIR / "concepts"
DRAFT_CONNECTIONS_DIR = DRAFT_DIR / "connections"
QA_DIR = KNOWLEDGE_DIR / "qa"
REPORTS_DIR = ROOT_DIR / "reports"
SCRIPTS_DIR = ROOT_DIR / "scripts"
HOOKS_DIR = ROOT_DIR / "hooks"
AGENTS_FILE = ROOT_DIR / "AGENTS.md"

INDEX_FILE = KNOWLEDGE_DIR / "index.md"
LOG_FILE = KNOWLEDGE_DIR / "log.md"
STATE_FILE = SCRIPTS_DIR / "state.json"
SETTINGS_FILE = ROOT_DIR / "settings.yaml"


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
