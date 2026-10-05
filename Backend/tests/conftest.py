"""
Settings for the whole test suite.

Automated tests must never call a real LLM or search provider, even if
Backend/.env says LLM_MODE=live or SEARCH_PROVIDERS=serpapi,tavily.
Environment variables win over .env, so forcing them here (before the app
is imported) keeps every test on FakeLLMProvider and MockSearchProvider —
no network, no keys used, no credits spent.

Real-provider tests live in tests/live/ and build their own live settings;
they are skipped unless RUN_LIVE_LLM_TESTS=1 (see tests/live/test_groq_live.py).
"""
import os

os.environ["LLM_MODE"] = "fake"
os.environ["SEARCH_PROVIDERS"] = "mock"
