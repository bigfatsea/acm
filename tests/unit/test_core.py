import fcntl
import os

import pytest

from acm.core.context import Ctx
from acm.core.errors import SafetyBlockedError
from acm.core.lock import WriteLock
from acm.core.masking import is_sensitive_key, mask_in_obj, mask_secret, mask_value_at


def test_ctx_paths_follow_home_and_acm_home(tmp_path):
    ctx = Ctx.from_env({"HOME": str(tmp_path)}, interactive=False)
    assert ctx.acm_home == tmp_path / ".acm"
    assert ctx.state_dir == tmp_path / ".acm" / "state"
    ctx2 = Ctx.from_env({"HOME": str(tmp_path), "ACM_HOME": str(tmp_path / "x")}, interactive=False)
    assert ctx2.config_path == tmp_path / "x" / "config.yaml"
    assert ctx.expand("~/a/b") == tmp_path / "a" / "b"


def test_lock_is_exclusive_and_released(ctx):
    a = WriteLock(ctx)
    a.acquire()
    try:
        with pytest.raises(SafetyBlockedError):
            WriteLock(ctx).acquire()
    finally:
        a.release()
    with WriteLock(ctx):
        pass
    assert oct(os.stat(ctx.state_dir).st_mode & 0o777) == "0o700"
    # lock file is really released: a raw flock succeeds
    fd = os.open(ctx.lock_path, os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.close(fd)


def test_masking():
    assert mask_secret("sk-abcdefghijkl") == "sk-...jkl"
    assert mask_secret("short") == "***"
    assert mask_secret("${VMR_KEY}") == "${VMR_KEY}"
    assert mask_secret("sk-abcdefghijkl", show_secrets=True) == "sk-abcdefghijkl"
    assert is_sensitive_key("ANTHROPIC_AUTH_TOKEN")
    assert not is_sensitive_key("apiKeyHelper")
    assert mask_in_obj({"env": {"API_KEY": "sk-abcdefghijkl", "X": "y"}}) == {
        "env": {"API_KEY": "sk-...jkl", "X": "y"}
    }
    assert mask_value_at(("env", "ANTHROPIC_AUTH_TOKEN"), "sk-abcdefghijkl") == "sk-...jkl"
    assert mask_value_at(("model",), "gpt") == "gpt"
