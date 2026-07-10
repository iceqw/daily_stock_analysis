# -*- coding: utf-8 -*-
"""Minimal filesystem prompt loader for AI opinion generation."""

from __future__ import annotations

from pathlib import Path
from typing import Dict


PROMPTS_ROOT = Path(__file__).resolve().parents[1] / "prompts"


def load_prompt(name: str, version: str) -> Dict[str, str]:
    base = PROMPTS_ROOT / name / version
    system_path = base / "system.md"
    user_path = base / "user.md"
    return {
        "system": system_path.read_text(encoding="utf-8"),
        "user": user_path.read_text(encoding="utf-8"),
    }
