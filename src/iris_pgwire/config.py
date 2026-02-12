"""Global configuration objects for the IRIS PGWire stack."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DDLTranslationConfig:
    """Configuration knobs for the DDL translation workflow."""

    strict_mode: bool = True
    auto_quote_reserved_words: bool = True
    validate_precision: bool = True
    lock_timeout_seconds: int = 30
    fail_fast: bool = False
