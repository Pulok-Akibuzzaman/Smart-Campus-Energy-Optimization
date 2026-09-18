"""
Provider chain failover tests.

Patches httpx.AsyncClient to inject canned provider responses and asserts
that interpret_notes() walks the chain in the configured order, falls through
on errors, and never crashes.

Run: PYTHONPATH=src python -m pytest tests/test_provider_chain.py -v
     (or simply `python tests/test_provider_chain.py`)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from gridwise import interpreter  # noqa: E402
from gridwise.config import CFG  # noqa: E402


# Helpers: build a fake httpx.Response with given status + JSON body.
def _resp(status: int, body: Dict[str, Any]):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    r.raise_for_status = MagicMock(
        side_effect=(lambda: (_ for _ in ()).throw(Exception(f"HTTP {status}")))
        if status >= 400
        else (lambda: None)
    )
    return r


def _make_mock_client(routes: Dict[str, Any]):
    """Build a MagicMock that mimics httpx.AsyncClient.post(url, ...).

    `routes` maps a substring in the URL to either:
      - a dict {"status": int, "body": dict} → returns that response
      - an Exception instance → raised
    Any URL not matched raises an AssertionError so tests catch unintended calls.
    """
    client = MagicMock()

    async def fake_post(url, *args, **kwargs):
        for substr, action in routes.items():
            if substr in url:
                if isinstance(action, Exception):
                    raise action
                return _resp(action["status"], action["body"])
        raise AssertionError(f"unexpected URL called: {url}")

    client.post = fake_post
    return client


def _patch_async_client(client):
    """Patch httpx.AsyncClient so that `async with httpx.AsyncClient(...) as c:`
    yields our `client`."""
    real_init = httpx.AsyncClient.__init__

    def fake_init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        # Replace instance post with bound mock
        self.post = client.post

    return patch.object(httpx.AsyncClient, "__init__", fake_init)


# Map provider name -> CFG attribute holding its key. Each _call_* function
# short-circuits to None when its key is unset/placeholder, so the tests must
# patch all relevant keys to dummy non-placeholder values.
_PROVIDER_KEY_ATTR = {
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "puku": "PUKU_API_KEY",
}


def _enable_keys(*provider_names: str):
    """Return a combined patch.object() context that sets dummy API keys for
    the listed providers so _call_<provider> reaches client.post()."""
    from contextlib import ExitStack

    stack = ExitStack()
    for name in provider_names:
        attr = _PROVIDER_KEY_ATTR[name]
        stack.enter_context(patch.object(CFG, attr, f"dummy_{name}_key"))
    return stack


# ─────────────────────── Chain semantics ──────────────────────────────


def test_first_provider_succeeds():
    """If groq returns valid JSON, gemini and openrouter are NEVER called."""

    client = _make_mock_client({
        "groq.com": {
            "status": 200,
            "body": {"choices": [{"message": {"content": '{"directives": [{"note_index":0,"applies":false,"directive_type":"no_op","structured_adjustment":null,"explanation":"x"}]}'}}]},
        },
    })

    async def run():
        async with httpx.AsyncClient() as c:
            return await interpreter.interpret_notes(["any note"], battery_capacity_kwh=500.0)

    with _patch_async_client(client), _enable_keys("groq"), patch.object(CFG, "LLM_PROVIDER_ORDER", "groq"):
        parsed, provider = asyncio.run(run())
    assert provider == "groq"
    assert "directives" in parsed


def test_first_provider_fails_falls_through_to_second():
    """If groq returns 500, gemini is tried and its response is used."""

    client = _make_mock_client({
        "groq.com": {"status": 500, "body": {"error": "boom"}},
        "generativelanguage.googleapis.com": {
            "status": 200,
            "body": {"candidates": [{"content": {"parts": [{"text": '{"directives": [{"note_index":0,"applies":false,"directive_type":"no_op","structured_adjustment":null,"explanation":"ok"}]}'}]}}]},
        },
    })

    async def run():
        async with httpx.AsyncClient() as c:
            return await interpreter.interpret_notes(["any"], battery_capacity_kwh=500.0)

    with _patch_async_client(client), _enable_keys("groq", "gemini"), patch.object(CFG, "LLM_PROVIDER_ORDER", "groq,gemini"):
        parsed, provider = asyncio.run(run())
    assert provider == "gemini"


def test_first_two_fail_falls_through_to_third():
    """groq + gemini both fail → openrouter is tried."""

    client = _make_mock_client({
        "groq.com": {"status": 500, "body": {"error": "boom"}},
        "generativelanguage.googleapis.com": {"status": 500, "body": {"error": "boom"}},
        "openrouter.ai": {
            "status": 200,
            "body": {"choices": [{"message": {"content": '{"directives": [{"note_index":0,"applies":false,"directive_type":"no_op","structured_adjustment":null,"explanation":"fallback"}]}'}}]},
        },
    })

    async def run():
        async with httpx.AsyncClient() as c:
            return await interpreter.interpret_notes(["any"], battery_capacity_kwh=500.0)

    with _patch_async_client(client), _enable_keys("groq", "gemini", "openrouter"), patch.object(CFG, "LLM_PROVIDER_ORDER", "groq,gemini,openrouter"):
        parsed, provider = asyncio.run(run())
    assert provider == "openrouter"


def test_all_providers_fail_uses_regex_fallback():
    """When every provider 5xxs, interpret_notes returns the regex safety-net output."""

    client = _make_mock_client({
        "groq.com": {"status": 500, "body": {"error": "boom"}},
        "generativelanguage.googleapis.com": {"status": 500, "body": {"error": "boom"}},
        "openrouter.ai": {"status": 500, "body": {"error": "boom"}},
        "puku.sh": {"status": 500, "body": {"error": "boom"}},
    })

    async def run():
        async with httpx.AsyncClient() as c:
            return await interpreter.interpret_notes(
                ["Solar drops to 20% from noon to 2 PM", "Cafeteria menu tomorrow"],
                battery_capacity_kwh=500.0,
            )

    with _patch_async_client(client), _enable_keys("groq", "gemini", "openrouter", "puku"), patch.object(CFG, "LLM_PROVIDER_ORDER", "groq,gemini,openrouter,puku"):
        parsed, provider = asyncio.run(run())
    assert provider == "regex"
    dirs = parsed["directives"]
    # Solar note should produce a solar_reduction
    assert dirs[0]["directive_type"] == "solar_reduction"
    # Distractor note should be no_op
    assert dirs[1]["directive_type"] == "no_op"


def test_unparseable_response_skips_provider():
    """If a provider returns HTTP 200 but the content isn't JSON, fall through."""

    client = _make_mock_client({
        "groq.com": {"status": 200, "body": {"choices": [{"message": {"content": "this is not json at all"}}]}},
        "generativelanguage.googleapis.com": {
            "status": 200,
            "body": {"candidates": [{"content": {"parts": [{"text": '{"directives": [{"note_index":0,"applies":false,"directive_type":"no_op","structured_adjustment":null,"explanation":"ok"}]}'}]}}]},
        },
    })

    async def run():
        async with httpx.AsyncClient() as c:
            return await interpreter.interpret_notes(["n"], battery_capacity_kwh=500.0)

    with _patch_async_client(client), _enable_keys("groq", "gemini"), patch.object(CFG, "LLM_PROVIDER_ORDER", "groq,gemini"):
        parsed, provider = asyncio.run(run())
    assert provider == "gemini"


def test_json_in_code_fences_is_parsed():
    """LLM wraps the JSON in ```json ... ``` fences; we strip and parse."""

    client = _make_mock_client({
        "groq.com": {
            "status": 200,
            "body": {"choices": [{"message": {"content": '```json\n{"directives": [{"note_index":0,"applies":false,"directive_type":"no_op","structured_adjustment":null,"explanation":"x"}]}\n```'}}]},
        },
    })

    async def run():
        async with httpx.AsyncClient() as c:
            return await interpreter.interpret_notes(["n"], battery_capacity_kwh=500.0)

    with _patch_async_client(client), _enable_keys("groq"), patch.object(CFG, "LLM_PROVIDER_ORDER", "groq"):
        parsed, provider = asyncio.run(run())
    assert provider == "groq"
    assert "directives" in parsed


def test_unknown_provider_silently_skipped():
    """Order contains an unknown provider name → skipped, not crashed."""

    client = _make_mock_client({
        "groq.com": {
            "status": 200,
            "body": {"choices": [{"message": {"content": '{"directives": [{"note_index":0,"applies":false,"directive_type":"no_op","structured_adjustment":null,"explanation":"x"}]}'}}]},
        },
    })

    async def run():
        async with httpx.AsyncClient() as c:
            return await interpreter.interpret_notes(["n"], battery_capacity_kwh=500.0)

    with _patch_async_client(client), _enable_keys("groq"), patch.object(CFG, "LLM_PROVIDER_ORDER", "fakeai,groq"):
        parsed, provider = asyncio.run(run())
    assert provider == "groq"


# ─────────────────────── Runner ───────────────────────────────────────


def _run_all() -> int:
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERR   {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{passed + failed} tests passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_run_all())
