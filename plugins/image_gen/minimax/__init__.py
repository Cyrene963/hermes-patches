"""MiniMax image generation backend.

Exposes MiniMax's ``image-01`` and ``image-01-live`` models as an
:class:`ImageGenProvider` implementation. Text-to-image requests are sent to
the regional ``/v1/image_generation`` endpoint (``api.minimax.io`` for the
global route, ``api.minimaxi.com`` for the China route) and the returned
URLs / base64 payloads are cached under ``$HERMES_HOME/cache/images/``.

Output handling
---------------
The API returns ``data.image_urls`` when ``response_format=url`` (the
default; result URLs expire after 24h) and ``data.image_base64`` when
``response_format=base64``. URL results are materialised locally with
:func:`save_url_image` so downstream consumers get a stable file instead of
an expiring link; base64 results are decoded with :func:`save_b64_image`.

Selection precedence (first hit wins):

1. ``MINIMAX_IMAGE_MODEL`` env var (escape hatch for scripts / tests)
2. ``image_gen.minimax.model`` in ``config.yaml``
3. ``image_gen.model`` in ``config.yaml`` (when it is one of our model IDs)
4. :data:`DEFAULT_MODEL` — ``image-01``

Endpoint precedence:

1. ``MINIMAX_API_BASE`` env var
2. ``image_gen.minimax.base_url`` in ``config.yaml``
3. Regional endpoint selected by ``image_gen.minimax.region`` (or the
   ``MINIMAX_REGION`` env var): ``cn_zh`` → ``https://api.minimaxi.com/v1``,
   otherwise the global ``https://api.minimax.io/v1``.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import requests

from agent.image_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    ImageGenProvider,
    error_response,
    resolve_aspect_ratio,
    save_b64_image,
    save_url_image,
    success_response,
)

logger = logging.getLogger(__name__)


def _get_env_value(key: str) -> Optional[str]:
    """Read a secret/config env value through Hermes' .env resolver.

    Falls back to ``os.environ`` when the Hermes config layer is not
    importable (e.g. tests run against a bare patch checkout).
    """
    try:
        from hermes_cli.config import get_env_value

        value = get_env_value(key)
        if value:
            return value
    except Exception as exc:
        logger.debug("Could not resolve %s via Hermes .env: %s", key, exc)
    return os.environ.get(key)


# ---------------------------------------------------------------------------
# Model catalog
# ---------------------------------------------------------------------------

_MODELS: Dict[str, Dict[str, Any]] = {
    "image-01": {
        "display": "MiniMax Image 01",
        "strengths": "General-purpose text-to-image",
    },
    "image-01-live": {
        "display": "MiniMax Image 01 Live",
        "strengths": "Low-latency generation",
    },
}

DEFAULT_MODEL = "image-01"

# Unified Hermes aspect ratios → MiniMax aspect_ratio enum.
_ASPECT_RATIOS: Dict[str, str] = {
    "landscape": "16:9",
    "square": "1:1",
    "portrait": "9:16",
}

# Regional /v1 base URLs.
_REGIONAL_BASE_URLS: Dict[str, str] = {
    "global_en": "https://api.minimax.io/v1",
    "cn_zh": "https://api.minimaxi.com/v1",
}

_IMAGE_GENERATION_PATH = "/image_generation"


def _load_image_gen_config() -> Dict[str, Any]:
    """Read ``image_gen`` from config.yaml (returns {} on any failure)."""
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        section = cfg.get("image_gen") if isinstance(cfg, dict) else None
        return section if isinstance(section, dict) else {}
    except Exception as exc:
        logger.debug("Could not load image_gen config: %s", exc)
        return {}


def _resolve_model() -> Tuple[str, Dict[str, Any]]:
    """Decide which model to use and return ``(model_id, meta)``."""
    env_override = os.environ.get("MINIMAX_IMAGE_MODEL")
    if env_override and env_override in _MODELS:
        return env_override, _MODELS[env_override]

    cfg = _load_image_gen_config()
    minimax_cfg = cfg.get("minimax") if isinstance(cfg.get("minimax"), dict) else {}
    candidate: Optional[str] = None
    value = minimax_cfg.get("model")
    if isinstance(value, str) and value in _MODELS:
        candidate = value
    if candidate is None:
        top = cfg.get("model")
        if isinstance(top, str) and top in _MODELS:
            candidate = top

    if candidate is not None:
        return candidate, _MODELS[candidate]

    return DEFAULT_MODEL, _MODELS[DEFAULT_MODEL]


def _resolve_base_url() -> str:
    """Resolve the regional ``/v1`` base URL for the image endpoint."""
    env_override = _get_env_value("MINIMAX_API_BASE")
    if env_override and env_override.strip():
        return env_override.strip().rstrip("/")

    cfg = _load_image_gen_config()
    minimax_cfg = cfg.get("minimax") if isinstance(cfg.get("minimax"), dict) else {}
    base_url = minimax_cfg.get("base_url")
    if isinstance(base_url, str) and base_url.strip():
        return base_url.strip().rstrip("/")

    region = os.environ.get("MINIMAX_REGION")
    if not region:
        raw = minimax_cfg.get("region")
        if isinstance(raw, str) and raw.strip():
            region = raw.strip()
    region = (region or "").lower()
    return _REGIONAL_BASE_URLS.get(region, _REGIONAL_BASE_URLS["global_en"])


def _resolve_response_format() -> str:
    """Resolve ``response_format`` (``"url"`` default or ``"base64"``)."""
    cfg = _load_image_gen_config()
    minimax_cfg = cfg.get("minimax") if isinstance(cfg.get("minimax"), dict) else {}
    raw = minimax_cfg.get("response_format")
    if isinstance(raw, str) and raw.strip().lower() in {"url", "base64"}:
        return raw.strip().lower()
    return "url"


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class MiniMaxImageGenProvider(ImageGenProvider):
    """MiniMax ``/v1/image_generation`` backend — image-01 / image-01-live."""

    @property
    def name(self) -> str:
        return "minimax"

    @property
    def display_name(self) -> str:
        return "MiniMax"

    def is_available(self) -> bool:
        return bool(_get_env_value("MINIMAX_API_KEY"))

    def list_models(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": model_id,
                "display": meta["display"],
                "strengths": meta["strengths"],
            }
            for model_id, meta in _MODELS.items()
        ]

    def default_model(self) -> Optional[str]:
        return DEFAULT_MODEL

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "MiniMax",
            "badge": "paid",
            "tag": "image-01 / image-01-live text-to-image",
            "env_vars": [
                {
                    "key": "MINIMAX_API_KEY",
                    "prompt": "MiniMax API key",
                    "url": "https://platform.minimax.io/user-center/basic-information/interface-key",
                },
            ],
        }

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        prompt = (prompt or "").strip()
        aspect = resolve_aspect_ratio(aspect_ratio)

        if not prompt:
            return error_response(
                error="Prompt is required and must be a non-empty string",
                error_type="invalid_argument",
                provider="minimax",
                aspect_ratio=aspect,
            )

        api_key = _get_env_value("MINIMAX_API_KEY")
        if not api_key:
            return error_response(
                error=(
                    "MINIMAX_API_KEY not set. Run `hermes tools` → Image "
                    "Generation → MiniMax to configure, or `hermes setup` "
                    "to add the key."
                ),
                error_type="auth_required",
                provider="minimax",
                aspect_ratio=aspect,
            )

        model_id, _ = _resolve_model()
        requested = kwargs.get("model")
        if isinstance(requested, str) and requested in _MODELS:
            model_id = requested

        endpoint = f"{_resolve_base_url()}{_IMAGE_GENERATION_PATH}"
        response_format = _resolve_response_format()

        # Wire payload: required fields model+prompt plus the optional
        # request fields the API accepts for text-to-image.
        payload: Dict[str, Any] = {
            "model": model_id,
            "prompt": prompt,
            "aspect_ratio": _ASPECT_RATIOS.get(aspect, "1:1"),
            "response_format": response_format,
            "n": 1,
        }
        seed = kwargs.get("seed")
        if isinstance(seed, int):
            payload["seed"] = seed
        prompt_optimizer = kwargs.get("prompt_optimizer")
        if isinstance(prompt_optimizer, bool):
            payload["prompt_optimizer"] = prompt_optimizer

        try:
            response = requests.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            logger.debug("MiniMax image generation failed", exc_info=True)
            return error_response(
                error=f"MiniMax image generation failed: {exc}",
                error_type="api_error",
                provider="minimax",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        if not isinstance(body, dict):
            return error_response(
                error="MiniMax returned a non-JSON object response",
                error_type="invalid_response",
                provider="minimax",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        base_resp = body.get("base_resp")
        status_code = base_resp.get("status_code") if isinstance(base_resp, dict) else None
        if status_code not in (None, 0):
            status_msg = (
                base_resp.get("status_msg", "") if isinstance(base_resp, dict) else ""
            )
            return error_response(
                error=(
                    f"MiniMax image generation failed (status {status_code}): {status_msg}"
                ),
                error_type="api_error",
                provider="minimax",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        data = body.get("data")
        if not isinstance(data, dict):
            return error_response(
                error="MiniMax returned no image data",
                error_type="empty_response",
                provider="minimax",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        if response_format == "base64":
            b64_items = data.get("image_base64")
            if not isinstance(b64_items, list) or not b64_items:
                return error_response(
                    error="MiniMax returned no base64 image data",
                    error_type="empty_response",
                    provider="minimax",
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )
            try:
                saved_path = save_b64_image(
                    str(b64_items[0]).strip(), prefix=f"minimax_{model_id}"
                )
                image_ref = str(saved_path)
            except Exception as exc:
                return error_response(
                    error=f"Could not save image to cache: {exc}",
                    error_type="io_error",
                    provider="minimax",
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )
        else:
            url_items = data.get("image_urls")
            if not isinstance(url_items, list) or not url_items:
                return error_response(
                    error="MiniMax returned no image URLs",
                    error_type="empty_response",
                    provider="minimax",
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )
            image_url = url_items[0]
            if not isinstance(image_url, str) or not image_url.strip():
                return error_response(
                    error="MiniMax returned an empty image URL",
                    error_type="empty_response",
                    provider="minimax",
                    model=model_id,
                    prompt=prompt,
                    aspect_ratio=aspect,
                )
            image_url = image_url.strip()
            # MiniMax result URLs expire after 24h — materialise the bytes
            # locally so downstream consumers get a stable file. Fall back to
            # the bare URL if the download fails.
            try:
                saved_path = save_url_image(image_url, prefix=f"minimax_{model_id}")
                image_ref = str(saved_path)
            except Exception as exc:
                logger.warning(
                    "MiniMax image URL %s could not be cached (%s); falling back to bare URL.",
                    image_url,
                    exc,
                )
                image_ref = image_url

        metadata = body.get("metadata")
        extra: Dict[str, Any] = {
            "minimax_aspect_ratio": _ASPECT_RATIOS.get(aspect, "1:1"),
            "response_format": response_format,
        }
        if isinstance(metadata, dict):
            for key in ("success_count", "failed_count"):
                if key in metadata and metadata[key] is not None:
                    extra[key] = metadata[key]

        return success_response(
            image=image_ref,
            model=model_id,
            prompt=prompt,
            aspect_ratio=aspect,
            provider="minimax",
            extra=extra,
        )


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------


def register(ctx) -> None:
    """Plugin entry point — wire ``MiniMaxImageGenProvider`` into the registry."""
    ctx.register_image_gen_provider(MiniMaxImageGenProvider())
