import pytest

from acm.config.refs import ModelRef, RoleRef, parse_credential, parse_ref
from acm.core.errors import ConfigError


def test_credential_forms():
    assert parse_credential("sk-plain").is_reference is False
    r = parse_credential("${VMR_KEY}")
    assert r.var == "VMR_KEY" and r.default is None
    r = parse_credential("${VMR_KEY:-fallback}")
    assert r.default == "fallback"
    assert parse_credential("").resolve({}) == ""


@pytest.mark.parametrize("bad", ["x${A}", "${A}x", "${A:-${B}}", "${1A}", "}"])
def test_credential_rejects_interpolation(bad):
    with pytest.raises(ConfigError):
        parse_credential(bad)


def test_credential_resolution():
    r = parse_credential("${K}")
    with pytest.raises(ConfigError, match="K is not set"):
        r.resolve({})
    with pytest.raises(ConfigError):
        r.resolve({"K": ""})
    assert r.resolve({"K": "v"}) == "v"
    assert parse_credential("${K:-d}").resolve({}) == "d"
    assert r.try_resolve({}) is None


def test_refs_split_on_first_dot_only_when_provider_matches():
    provs = {"vmr": 1, "ds": 1}
    assert parse_ref("vmr.claude-opus-4.6", provs) == ModelRef("vmr", "claude-opus-4.6")
    assert parse_ref("gpt-4.1", provs) == ModelRef(None, "gpt-4.1")  # "gpt-4" is not a provider
    assert parse_ref("vmr@fast", provs) == RoleRef("vmr", "fast")
    with pytest.raises(ConfigError, match="unknown provider"):
        parse_ref("nope@fast", provs)
    with pytest.raises(ConfigError, match="unknown role"):
        parse_ref("vmr@planner", provs)
    with pytest.raises(ConfigError):
        parse_ref("  ", provs)
