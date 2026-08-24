# // Ver 2026-08-24 22:05, by gemini-3.7-flash
"""Unit tests for token masking and sensitive field detection."""

from acm.masking import is_sensitive_key, mask_secret, mask_secrets_in_obj


def test_is_sensitive_key() -> None:
    """Test sensitive key detection on dot-paths."""
    assert is_sensitive_key("env.ANTHROPIC_AUTH_TOKEN") is True
    assert is_sensitive_key("env.ANTHROPIC_API_KEY") is True
    assert is_sensitive_key("providers.vmr.apiKey") is True
    assert is_sensitive_key("model_providers.custom.api_key") is True
    assert is_sensitive_key("password") is True
    assert is_sensitive_key("model") is False
    assert is_sensitive_key("base_url") is False
    assert is_sensitive_key("effortLevel") is False


def test_mask_secret() -> None:
    """Test secret masking behavior."""
    assert mask_secret("sk-ant-api03-1234567890abcdef") == "sk-...def"
    assert mask_secret("short") == "***"
    assert mask_secret("${VMR_KEY}") == "${VMR_KEY}"  # Unresolved reference preserved
    assert (
        mask_secret("sk-ant-api03-1234567890abcdef", show_secrets=True)
        == "sk-ant-api03-1234567890abcdef"
    )


def test_mask_secrets_in_obj() -> None:
    """Test recursive masking in nested dictionaries and lists."""
    nested = {
        "baseUrl": "http://127.0.0.1:8800",
        "apiKey": "sk-pi-secret-1234567890",
        "models": [
            {"id": "model-1", "auth_token": "secret-token-999"},
            {"id": "model-2", "public": True},
        ],
    }
    masked = mask_secrets_in_obj(nested)
    assert masked["baseUrl"] == "http://127.0.0.1:8800"
    assert masked["apiKey"] == "sk-...890"
    assert masked["models"][0]["auth_token"] == "sec...999"
    assert masked["models"][1]["public"] is True

    # With show_secrets=True, secrets remain unmodified
    unmasked = mask_secrets_in_obj(nested, show_secrets=True)
    assert unmasked["apiKey"] == "sk-pi-secret-1234567890"
