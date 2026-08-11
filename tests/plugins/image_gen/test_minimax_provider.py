"""Tests for the bundled MiniMax image_gen plugin (image-01 / image-01-live)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import plugins.image_gen.minimax as minimax_plugin


def _http_response(body: dict, *, status_code: int = 200, exc: Exception | None = None):
    """Build a fake ``requests.Response``-like object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock(side_effect=exc if exc is not None else None)
    resp.json.return_value = body
    return resp


def _url_body(image_url: str = "https://api.minimax.io/generated/img.png", success_count: int = 1) -> dict:
    return {
        "id": "trace-123",
        "data": {"image_urls": [image_url]},
        "metadata": {"success_count": success_count, "failed_count": 0},
        "base_resp": {"status_code": 0, "status_msg": "success"},
    }


def _b64_body(b64: str, success_count: int = 1) -> dict:
    return {
        "id": "trace-456",
        "data": {"image_urls": [b64]},
        "metadata": {"success_count": success_count, "failed_count": 0},
        "base_resp": {"status_code": 0, "status_msg": "success"},
    }


@pytest.fixture(autouse=True)
def _tmp_hermes_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    yield tmp_path


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    return minimax_plugin.MiniMaxImageGenProvider()


# ── Metadata ────────────────────────────────────────────────────────────────


class TestMetadata:
    def test_name(self, provider):
        assert provider.name == "minimax"

    def test_display_name(self, provider):
        assert provider.display_name == "MiniMax"

    def test_default_model(self, provider):
        assert provider.default_model() == "image-01"

    def test_list_models(self, provider):
        ids = [m["id"] for m in provider.list_models()]
        assert ids == ["image-01", "image-01-live"]

    def test_catalog_entries_have_display_strengths(self, provider):
        for entry in provider.list_models():
            assert entry["display"]
            assert entry["strengths"]

    def test_get_setup_schema(self, provider):
        schema = provider.get_setup_schema()
        assert schema["name"] == "MiniMax"
        assert schema["env_vars"][0]["key"] == "MINIMAX_API_KEY"


# ── Availability ────────────────────────────────────────────────────────────


class TestAvailability:
    def test_no_api_key_unavailable(self, monkeypatch):
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        assert minimax_plugin.MiniMaxImageGenProvider().is_available() is False

    def test_api_key_set_available(self, monkeypatch):
        monkeypatch.setenv("MINIMAX_API_KEY", "test")
        assert minimax_plugin.MiniMaxImageGenProvider().is_available() is True


# ── Model resolution ────────────────────────────────────────────────────────


class TestModelResolution:
    def test_default_is_image_01(self, monkeypatch):
        monkeypatch.setattr(minimax_plugin, "_load_image_gen_config", lambda: {})
        model_id, meta = minimax_plugin._resolve_model()
        assert model_id == "image-01"
        assert meta == minimax_plugin._MODELS["image-01"]

    def test_env_var_override(self, monkeypatch):
        monkeypatch.setenv("MINIMAX_IMAGE_MODEL", "image-01-live")
        monkeypatch.setattr(minimax_plugin, "_load_image_gen_config", lambda: {})
        model_id, _ = minimax_plugin._resolve_model()
        assert model_id == "image-01-live"

    def test_env_var_unknown_falls_back(self, monkeypatch):
        monkeypatch.setenv("MINIMAX_IMAGE_MODEL", "bogus-model")
        monkeypatch.setattr(minimax_plugin, "_load_image_gen_config", lambda: {})
        model_id, _ = minimax_plugin._resolve_model()
        assert model_id == minimax_plugin.DEFAULT_MODEL

    def test_config_minimax_model(self, monkeypatch):
        monkeypatch.setattr(
            minimax_plugin,
            "_load_image_gen_config",
            lambda: {"minimax": {"model": "image-01-live"}},
        )
        model_id, _ = minimax_plugin._resolve_model()
        assert model_id == "image-01-live"

    def test_config_top_level_model(self, monkeypatch):
        monkeypatch.setattr(
            minimax_plugin,
            "_load_image_gen_config",
            lambda: {"model": "image-01-live"},
        )
        model_id, _ = minimax_plugin._resolve_model()
        assert model_id == "image-01-live"


# ── Endpoint resolution ─────────────────────────────────────────────────────


class TestEndpointResolution:
    def test_default_global_en(self, monkeypatch):
        monkeypatch.setattr(minimax_plugin, "_load_image_gen_config", lambda: {})
        assert minimax_plugin._resolve_base_url() == "https://api.minimax.io/v1"

    def test_cn_zh_region(self, monkeypatch):
        monkeypatch.setattr(
            minimax_plugin,
            "_load_image_gen_config",
            lambda: {"minimax": {"region": "cn_zh"}},
        )
        assert minimax_plugin._resolve_base_url() == "https://api.minimaxi.com/v1"

    def test_region_env_override(self, monkeypatch):
        monkeypatch.setenv("MINIMAX_REGION", "cn_zh")
        monkeypatch.setattr(minimax_plugin, "_load_image_gen_config", lambda: {})
        assert minimax_plugin._resolve_base_url() == "https://api.minimaxi.com/v1"

    def test_env_base_url_override(self, monkeypatch):
        monkeypatch.setenv("MINIMAX_API_BASE", "https://example.com/v1/")
        monkeypatch.setattr(minimax_plugin, "_load_image_gen_config", lambda: {})
        assert minimax_plugin._resolve_base_url() == "https://example.com/v1"

    def test_config_base_url_override(self, monkeypatch):
        monkeypatch.setattr(
            minimax_plugin,
            "_load_image_gen_config",
            lambda: {"minimax": {"base_url": "https://example.com/v1"}},
        )
        assert minimax_plugin._resolve_base_url() == "https://example.com/v1"

    def test_unknown_region_falls_back_to_global(self, monkeypatch):
        monkeypatch.setattr(
            minimax_plugin,
            "_load_image_gen_config",
            lambda: {"minimax": {"region": "eu"}},
        )
        assert minimax_plugin._resolve_base_url() == "https://api.minimax.io/v1"


# ── Response format ─────────────────────────────────────────────────────────


class TestResponseFormat:
    def test_default_url(self, monkeypatch):
        monkeypatch.setattr(minimax_plugin, "_load_image_gen_config", lambda: {})
        assert minimax_plugin._resolve_response_format() == "url"

    def test_config_base64(self, monkeypatch):
        monkeypatch.setattr(
            minimax_plugin,
            "_load_image_gen_config",
            lambda: {"minimax": {"response_format": "base64"}},
        )
        assert minimax_plugin._resolve_response_format() == "base64"

    def test_config_invalid_falls_back_to_url(self, monkeypatch):
        monkeypatch.setattr(
            minimax_plugin,
            "_load_image_gen_config",
            lambda: {"minimax": {"response_format": "webp"}},
        )
        assert minimax_plugin._resolve_response_format() == "url"


# ── Generate ────────────────────────────────────────────────────────────────


class TestGenerate:
    def test_empty_prompt_rejected(self, provider):
        result = provider.generate("", aspect_ratio="square")
        assert result["success"] is False
        assert result["error_type"] == "invalid_argument"

    def test_missing_api_key(self, monkeypatch):
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        result = minimax_plugin.MiniMaxImageGenProvider().generate("a cat")
        assert result["success"] is False
        assert result["error_type"] == "auth_required"

    def test_url_happy_path_caches_image(self, provider, tmp_path):
        resp = _http_response(_url_body("https://cdn.minimax.io/img.png"))
        with patch("plugins.image_gen.minimax.requests.post", return_value=resp) as mock_post, \
             patch(
                 "plugins.image_gen.minimax.save_url_image",
                 return_value=Path("/tmp/minimax_image-01_test.png"),
             ) as mock_save:
            result = provider.generate("a cat", aspect_ratio="landscape")

        assert result["success"] is True
        assert result["image"] == "/tmp/minimax_image-01_test.png"
        assert result["model"] == "image-01"
        assert result["aspect_ratio"] == "landscape"
        assert result["provider"] == "minimax"
        assert result["response_format"] == "url"
        assert result["success_count"] == 1
        assert result["failed_count"] == 0
        mock_save.assert_called_once()

        post_kwargs = mock_post.call_args.kwargs
        assert post_kwargs["json"]["model"] == "image-01"
        assert post_kwargs["json"]["prompt"] == "a cat"
        assert post_kwargs["json"]["aspect_ratio"] == "16:9"
        assert post_kwargs["json"]["response_format"] == "url"
        assert post_kwargs["headers"]["Authorization"] == "Bearer test-key"
        assert mock_post.call_args[0][0] == "https://api.minimax.io/v1/image_generation"

    def test_model_kwarg_overrides_configured_model(self, provider):
        resp = _http_response(_url_body())
        with patch("plugins.image_gen.minimax.requests.post", return_value=resp) as mock_post, \
             patch(
                 "plugins.image_gen.minimax.save_url_image",
                 return_value=Path("/tmp/x.png"),
             ):
            result = provider.generate("a cat", model="image-01-live")

        assert result["model"] == "image-01-live"
        assert mock_post.call_args.kwargs["json"]["model"] == "image-01-live"

    @pytest.mark.parametrize("aspect,expected", [
        ("landscape", "16:9"),
        ("square", "1:1"),
        ("portrait", "9:16"),
    ])
    def test_aspect_ratio_mapping(self, provider, aspect, expected):
        resp = _http_response(_url_body())
        with patch("plugins.image_gen.minimax.requests.post", return_value=resp) as mock_post, \
             patch(
                 "plugins.image_gen.minimax.save_url_image",
                 return_value=Path("/tmp/x.png"),
             ):
            provider.generate("a cat", aspect_ratio=aspect)

        assert mock_post.call_args.kwargs["json"]["aspect_ratio"] == expected

    def test_b64_wire_format_uses_base64_branch(self, provider, monkeypatch):
        monkeypatch.setattr(
            minimax_plugin,
            "_load_image_gen_config",
            lambda: {"minimax": {"response_format": "base64"}},
        )
        resp = _http_response(_b64_body("aGVsbG8="))
        with patch("plugins.image_gen.minimax.requests.post", return_value=resp) as mock_post, \
             patch(
                 "plugins.image_gen.minimax.save_b64_image",
                 return_value=Path("/tmp/minimax_image-01_b64.png"),
             ) as mock_save:
            result = provider.generate("a cat", aspect_ratio="square")

        assert result["success"] is True
        assert result["image"] == "/tmp/minimax_image-01_b64.png"
        assert result["response_format"] == "base64"
        assert mock_post.call_args.kwargs["json"]["response_format"] == "base64"
        mock_save.assert_called_once()

    def test_base64_requested_via_config(self, provider, monkeypatch):
        monkeypatch.setattr(
            minimax_plugin,
            "_load_image_gen_config",
            lambda: {"minimax": {"response_format": "base64"}},
        )
        resp = _http_response(_b64_body("aGVsbG8="))
        with patch("plugins.image_gen.minimax.requests.post", return_value=resp) as mock_post, \
             patch(
                 "plugins.image_gen.minimax.save_b64_image",
                 return_value=Path("/tmp/minimax_image-01_b64.png"),
             ) as mock_save:
            result = provider.generate("a cat")

        assert result["success"] is True
        assert result["response_format"] == "base64"
        assert mock_post.call_args.kwargs["json"]["response_format"] == "base64"
        mock_save.assert_called_once()

    def test_seed_and_prompt_optimizer_passed_through(self, provider):
        resp = _http_response(_url_body())
        with patch("plugins.image_gen.minimax.requests.post", return_value=resp) as mock_post, \
             patch(
                 "plugins.image_gen.minimax.save_url_image",
                 return_value=Path("/tmp/x.png"),
             ):
            provider.generate("a cat", seed=42, prompt_optimizer=True)

        payload = mock_post.call_args.kwargs["json"]
        assert payload["seed"] == 42
        assert payload["prompt_optimizer"] is True
        assert payload["n"] == 1

    def test_api_error_returns_error_response(self, provider):
        resp = _http_response({}, exc=RuntimeError("boom"))
        with patch("plugins.image_gen.minimax.requests.post", return_value=resp):
            result = provider.generate("a cat")

        assert result["success"] is False
        assert result["error_type"] == "api_error"
        assert "boom" in result["error"]

    def test_nonzero_base_resp_status_returns_error(self, provider):
        resp = _http_response({
            "data": {"image_urls": ["https://cdn.minimax.io/img.png"]},
            "base_resp": {"status_code": 1004, "status_msg": "auth failed"},
        })
        with patch("plugins.image_gen.minimax.requests.post", return_value=resp):
            result = provider.generate("a cat")

        assert result["success"] is False
        assert result["error_type"] == "api_error"
        assert "1004" in result["error"]

    def test_empty_image_urls_returns_error(self, provider):
        resp = _http_response({
            "data": {"image_urls": []},
            "metadata": {"success_count": 0, "failed_count": 1},
            "base_resp": {"status_code": 0, "status_msg": "success"},
        })
        with patch("plugins.image_gen.minimax.requests.post", return_value=resp):
            result = provider.generate("a cat")

        assert result["success"] is False
        assert result["error_type"] == "empty_response"

    def test_missing_data_returns_error(self, provider):
        resp = _http_response({
            "metadata": {"success_count": 0, "failed_count": 0},
            "base_resp": {"status_code": 0, "status_msg": "success"},
        })
        with patch("plugins.image_gen.minimax.requests.post", return_value=resp):
            result = provider.generate("a cat")

        assert result["success"] is False
        assert result["error_type"] == "empty_response"

    def test_url_cache_failure_falls_back_to_bare_url(self, provider):
        resp = _http_response(_url_body("https://cdn.minimax.io/img.png"))
        with patch("plugins.image_gen.minimax.requests.post", return_value=resp), \
             patch(
                 "plugins.image_gen.minimax.save_url_image",
                 side_effect=RuntimeError("download failed"),
             ):
            result = provider.generate("a cat")

        assert result["success"] is True
        assert result["image"] == "https://cdn.minimax.io/img.png"
