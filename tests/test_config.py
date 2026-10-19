from pathlib import Path

import pytest

import aiv.config as config


@pytest.fixture
def write_config(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    monkeypatch.setattr(config, "CONFIG_FILE", path)
    config.get_config.cache_clear()

    def write(text):
        path.write_text(text, encoding="utf-8")
        config.get_config.cache_clear()
        return path

    yield write
    config.get_config.cache_clear()


def test_missing_config(write_config):
    with pytest.raises(FileNotFoundError, match="config file not found"):
        config.get_config()


def test_legacy_flat_config(write_config):
    write_config(
        """
api_key = "legacy-key"
model = "legacy-model"
max_tokens = 1234
"""
    )

    assert config.get_config()["provider"] == "anthropic"
    assert config.get_provider_settings("anthropic") == {
        "type": "anthropic",
        "api_key": "legacy-key",
        "api_key_file": None,
        "model": "legacy-model",
        "max_tokens": 1234,
        "options": {},
    }


@pytest.mark.parametrize("provider", config.VALID_PROVIDER_TYPES)
def test_builtin_without_table_uses_flat_settings(write_config, provider):
    write_config('api_key = "fallback-key"\nmodel = "fallback-model"\n')

    settings = config.get_provider_settings(provider)

    assert settings["type"] == provider
    assert settings["api_key"] == "fallback-key"
    assert settings["model"] == "fallback-model"


@pytest.mark.parametrize("provider", config.VALID_PROVIDER_TYPES)
def test_legacy_provider_table_infers_type(write_config, provider):
    write_config(
        f"""
[providers.{provider}]
model = "legacy-model"
"""
    )

    assert config.get_provider_settings(provider)["type"] == provider


def test_custom_default_profile(write_config):
    write_config(
        """
provider = "deep"

[providers.deep]
type = "openai-reasoning"
model = "o3-mini"
max_tokens = 16384

[providers.deep.options]
reasoning_effort = "high"
"""
    )

    assert config.get_config()["provider"] == "deep"
    settings = config.get_provider_settings("deep")
    assert settings["type"] == "openai-reasoning"
    assert settings["model"] == "o3-mini"
    assert settings["max_tokens"] == 16384
    assert settings["options"] == {"reasoning_effort": "high"}


def test_explicit_type_overrides_builtin_name(write_config):
    write_config(
        """
[providers.openai]
type = "openai-reasoning"
"""
    )

    assert config.get_provider_settings("openai")["type"] == "openai-reasoning"


def test_custom_profile_requires_type(write_config):
    write_config('[providers.deep]\nmodel = "o3-mini"\n')

    with pytest.raises(ValueError, match="requires a type"):
        config.get_config()


def test_invalid_type(write_config):
    write_config('[providers.deep]\ntype = "unsupported"\n')

    with pytest.raises(ValueError, match="invalid type"):
        config.get_config()


def test_unknown_default_profile(write_config):
    write_config('provider = "typo"\n')

    with pytest.raises(ValueError, match="unknown provider"):
        config.get_config()


def test_unknown_requested_profile(write_config):
    write_config('api_key = "fallback-key"\n')

    with pytest.raises(ValueError, match="unknown provider"):
        config.get_provider_settings("typo")


@pytest.mark.parametrize("value", ['""', "123", '["openai"]'])
def test_invalid_default_provider(write_config, value):
    write_config(f"provider = {value}\n")

    with pytest.raises(ValueError, match="non-empty string"):
        config.get_config()


def test_providers_must_be_table(write_config):
    write_config('providers = "invalid"\n')

    with pytest.raises(ValueError, match="'providers' must be a table"):
        config.get_config()


def test_provider_entry_must_be_table(write_config):
    write_config('[providers]\ndeep = "invalid"\n')

    with pytest.raises(ValueError, match="providers.deep must be a table"):
        config.get_config()


def test_options_must_be_table(write_config):
    write_config(
        """
[providers.deep]
type = "openai-reasoning"
options = "invalid"
"""
    )

    with pytest.raises(ValueError, match="options.*must be a table"):
        config.get_config()


def test_partial_profile_inherits_flat_settings(write_config):
    write_config(
        """
api_key = "fallback-key"
model = "fallback-model"
max_tokens = 8000

[providers.deep]
type = "openai-reasoning"
"""
    )

    settings = config.get_provider_settings("deep")
    assert settings["api_key"] == "fallback-key"
    assert settings["model"] == "fallback-model"
    assert settings["max_tokens"] == 8000


def test_profile_fields_override_flat_settings(write_config):
    write_config(
        """
api_key = "fallback-key"
model = "fallback-model"
max_tokens = 8000

[providers.deep]
type = "openai-reasoning"
api_key = "profile-key"
model = "profile-model"
max_tokens = 16000
"""
    )

    settings = config.get_provider_settings("deep")
    assert settings["api_key"] == "profile-key"
    assert settings["model"] == "profile-model"
    assert settings["max_tokens"] == 16000


def test_builtin_defaults(write_config):
    write_config("")

    settings = config.get_provider_settings("anthropic")
    assert settings["api_key"] is None
    assert settings["api_key_file"] is None
    assert settings["model"] is None
    assert settings["max_tokens"] == config.DEFAULT_MAX_TOKENS
    assert settings["options"] == {}


def test_profile_inline_key_does_not_inherit_flat_key_file(write_config, tmp_path):
    key_file = tmp_path / "fallback.key"
    key_file.write_text("fallback-key\n")

    write_config(
        f"""
api_key_file = "{key_file.as_posix()}"

[providers.deep]
type = "openai-reasoning"
api_key = "profile-key"
"""
    )

    settings = config.get_provider_settings("deep")
    assert settings["api_key"] == "profile-key"
    assert settings["api_key_file"] is None


def test_profile_key_file_overrides_flat_inline_key(write_config, tmp_path):
    key_file = tmp_path / "profile.key"
    key_file.write_text("  profile-key\n")

    write_config(
        f"""
api_key = "fallback-key"

[providers.deep]
type = "openai-reasoning"
api_key_file = "{key_file.as_posix()}"
"""
    )

    settings = config.get_provider_settings("deep")
    assert settings["api_key"] == "profile-key"
    assert settings["api_key_file"] == str(key_file)


def test_profile_inherits_flat_key_file_pair(write_config, tmp_path):
    key_file = tmp_path / "fallback.key"
    key_file.write_text("fallback-key\n")

    write_config(
        f"""
api_key_file = "{key_file.as_posix()}"

[providers.deep]
type = "openai-reasoning"
"""
    )

    settings = config.get_provider_settings("deep")
    assert settings["api_key"] == "fallback-key"
    assert settings["api_key_file"] == str(key_file)


def test_inline_key_keeps_legacy_precedence(write_config):
    write_config(
        """
api_key = "inline-key"
api_key_file = "/missing/key"
"""
    )

    settings = config.get_provider_settings("anthropic")
    assert settings["api_key"] == "inline-key"
    assert settings["api_key_file"] is None


def test_key_file_path_is_expanded_and_absolute(write_config, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    key_file = tmp_path / "api.key"
    key_file.write_text("secret\n")
    write_config('api_key_file = "~/api.key"\n')

    settings = config.get_provider_settings("anthropic")
    assert settings["api_key_file"] == str(key_file)
    assert settings["api_key"] == "secret"


def test_missing_key_file(write_config, tmp_path):
    missing = tmp_path / "missing.key"
    write_config(f'api_key_file = "{missing.as_posix()}"\n')

    with pytest.raises(FileNotFoundError, match="api_key_file not found"):
        config.get_config()


def test_options_are_profile_local(write_config):
    write_config(
        """
[providers.deep]
type = "openai-reasoning"
options.reasoning_effort = "high"

[providers.fast]
type = "openai"
"""
    )

    assert config.get_provider_settings("fast")["options"] == {}


def test_returned_settings_do_not_mutate_cached_config(write_config):
    write_config(
        """
[providers.deep]
type = "openai-reasoning"
model = "original"
options.nested.value = "original"
"""
    )

    settings = config.get_provider_settings("deep")
    settings["model"] = "changed"
    settings["options"]["nested"]["value"] = "changed"

    fresh = config.get_provider_settings("deep")
    assert fresh["model"] == "original"
    assert fresh["options"]["nested"]["value"] == "original"


def test_global_prompt_defaults_preserved(write_config):
    write_config("")

    resolved = config.get_config()
    assert resolved["sys_prompt"] == config.DEFAULT_SYS_PROMPT
    assert resolved["prompt_marker"] == config.DEFAULT_PROMPT_MARKER
    assert resolved["mode_chat_suffix"].startswith("\n\n")
    assert resolved["mode_code_suffix"].startswith("\n\n")


def test_legacy_system_prompt_alias(write_config):
    write_config('system_prompt = "custom system prompt"\n')

    assert config.get_config()["sys_prompt"] == "custom system prompt"
