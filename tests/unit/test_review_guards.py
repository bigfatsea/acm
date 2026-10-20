"""Guards added after the 0.4 review: masking of size fields, credential stores, owned paths."""

from pathlib import Path

import pytest
from fakes import FakeAdapter, Harness, plan_of

from acm.adapters.registry import all_adapters
from acm.core.context import Ctx
from acm.core.masking import is_sensitive_key, mask_value_at
from acm.engine.model import FileSpec, OwnedFile


@pytest.mark.parametrize(
    ("key", "sensitive"),
    [
        ("ANTHROPIC_AUTH_TOKEN", True),
        ("apiKey", True),
        ("experimental_bearer_token", True),
        ("CLAUDE_CODE_MAX_CONTEXT_TOKENS", False),
        ("maxTokens", False),
        ("max_output_tokens", False),
        ("apiKeyHelper", False),
    ],
)
def test_size_fields_are_not_secrets(key, sensitive):
    assert is_sensitive_key(key) is sensitive


def test_context_window_is_shown():
    assert mask_value_at(("env", "CLAUDE_CODE_MAX_CONTEXT_TOKENS"), "400000") == "400000"


# Where agents keep subscription / OAuth logins. acm must never manage these files, so
# restoring acm's fields always hands the agent back to its own login.
CREDENTIAL_STORES = {"auth.json", ".credentials.json", "auth-profiles.json", ".env"}


def test_no_adapter_manages_a_login_store(ctx: Ctx):
    for a in all_adapters():
        for spec in a.files(ctx):
            assert spec.path.name not in CREDENTIAL_STORES, (a.id, spec.path)


def test_owned_file_outside_acm_home_is_refused(ctx: Ctx, tmp_path: Path):
    class Stray(FakeAdapter):
        def files(self, c: Ctx) -> list[FileSpec]:
            return [FileSpec("catalog", tmp_path / "elsewhere.json", "json", True)]

    h = Harness(ctx, Stray())
    res = h.apply(plan_of(OwnedFile("catalog", b"{}")))
    assert res.status == "blocked" and "outside" in res.message
    assert not (tmp_path / "elsewhere.json").exists()
