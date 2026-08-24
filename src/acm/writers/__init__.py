# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Format writers and AST mutation tools with fidelity contracts."""

from typing import Literal

from pydantic import BaseModel

FidelityGuarantee = Literal["guaranteed", "fixture_defined", "not_applicable", "best_effort"]


class WriterCapabilities(BaseModel):
    """Capabilities and fidelity guarantees of a format writer."""

    format_name: str
    semantics: FidelityGuarantee
    comments: FidelityGuarantee
    key_order: FidelityGuarantee
    whitespace: FidelityGuarantee
    description: str


JSON_CAPABILITIES = WriterCapabilities(
    format_name="json",
    semantics="guaranteed",
    comments="not_applicable",
    key_order="guaranteed",
    whitespace="best_effort",
    description="Preserves key order (OrderedDict), detects indent (2/4/tabs), trailing newline, and non-ASCII representation.",
)

TOML_CAPABILITIES = WriterCapabilities(
    format_name="toml",
    semantics="guaranteed",
    comments="fixture_defined",
    key_order="fixture_defined",
    whitespace="fixture_defined",
    description="Full round-trip AST editing via tomlkit, preserving inline and header comments, table order, and blank lines.",
)
