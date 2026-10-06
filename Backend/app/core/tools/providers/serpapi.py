"""
SerpApiProvider — Google results through SerpAPI (https://serpapi.com).

Which SerpAPI option is used depends on the query's focus:
  RESEARCH → engine=google_scholar      (papers: title, link, snippet, publication)
  NEWS     → engine=google, tbm=nws     (news_results: title, link, source, date, snippet)
  anything else → engine=google         (organic_results: title, link, snippet, date, source)

include_domains becomes "(site:a OR site:b)" in the query; recency_days becomes
Google's tbs=qdr:d/w/m/y (or as_ylo, the start year, for Scholar).
Google doesn't always obey site: (the live test, 2026-10-06, got only other
sites back), so off-site results are also dropped here. If none are left the
search returns [] and the gateway asks the next provider.

Errors (SerpAPI docs, checked 2026-10-06):
  401, 403 → SearchAuthError
  429 "run out of searches" → SearchQuotaExhausted; any other 429 → SearchRateLimited
  400, 404, 410 → SearchBadRequest;   5xx → SearchServerError
  200 with "hasn't returned any results" → no results (not an error)

The API key travels as a query parameter (SerpAPI requires that), so request
URLs are never put into error messages or logs.
"""
from datetime import date

import httpx

from app.core.tools.providers.common import make_result, on_sites, parse_date, recency_bucket
from app.core.tools.search import (
    SearchAuthError,
    SearchBadRequest,
    SearchFocus,
    SearchProvider,
    SearchProviderError,
    SearchQuery,
    SearchQuotaExhausted,
    SearchRateLimited,
    SearchResult,
    SearchServerError,
    SearchTimeout,
)

DEFAULT_URL = "https://serpapi.com/search"
# Google ignores very long queries, so only the first few site filters are used.
MAX_SITE_FILTERS = 8
# Only "out of searches" means the plan is used up. The hourly-limit 429 can also
# mention the plan, and must stay a short rate-limit pause, not a long cooldown.
_QUOTA_WORDS = ("run out of searches", "out of searches")
_NO_RESULTS_WORDS = ("hasn't returned any results", "no results")
_QDR = {"day": "d", "week": "w", "month": "m", "year": "y"}


class SerpApiProvider(SearchProvider):
    name = "serpapi"

    def __init__(
        self,
        api_key: str,
        url: str = DEFAULT_URL,
        timeout_seconds: float = 20.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._url = url
        self._timeout = timeout_seconds
        self._client = http_client          # tests pass a client with a fake transport

    def keeps_to_sites(self, query: SearchQuery) -> bool:
        # Google Scholar only returns papers, which is what a research site list asks for.
        # Plain Google often ignores site: (live run, 2026-10-06).
        return query.focus == SearchFocus.RESEARCH

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        params = self._params(query)
        try:
            response = await self._get(params)
        except httpx.TimeoutException as error:
            raise SearchTimeout("SerpAPI did not answer in time.", provider=self.name) from error
        except httpx.TransportError as error:
            raise SearchServerError(f"Connection problem: {type(error).__name__}", provider=self.name) from error

        data = _json(response)
        message = str(data.get("error") or "")

        if response.status_code >= 400:
            raise self._http_error(response, message)
        if message:
            if any(word in message.lower() for word in _NO_RESULTS_WORDS):
                return []
            raise SearchServerError(f"SerpAPI error: {message[:200]}", provider=self.name)

        return self._results(query, data)[: query.max_results]

    # ── Request ───────────────────────────────────────────────────────────────

    def _params(self, query: SearchQuery) -> dict:
        text = query.text
        # Google Scholar only searches papers already, so site filters would only narrow it.
        if query.include_domains and query.focus != SearchFocus.RESEARCH:
            sites = " OR ".join(f"site:{d}" for d in query.include_domains[:MAX_SITE_FILTERS])
            text = f"{text} ({sites})"

        params = {"api_key": self._api_key, "q": text}
        bucket = recency_bucket(query.recency_days)

        if query.focus == SearchFocus.RESEARCH:
            params["engine"] = "google_scholar"
            if query.recency_days:
                # Scholar filters by year only: "from this year" or "from N years ago".
                params["as_ylo"] = str(date.today().year - query.recency_days // 365)
        else:
            params["engine"] = "google"
            if query.focus == SearchFocus.NEWS:
                params["tbm"] = "nws"
            if bucket:
                params["tbs"] = f"qdr:{_QDR[bucket]}"
        return params

    async def _get(self, params: dict) -> httpx.Response:
        if self._client is not None:
            return await self._client.get(self._url, params=params, timeout=self._timeout)
        async with httpx.AsyncClient() as client:
            return await client.get(self._url, params=params, timeout=self._timeout)

    # ── Response ──────────────────────────────────────────────────────────────

    def _http_error(self, response: httpx.Response, message: str) -> SearchProviderError:
        status = response.status_code
        text = f"HTTP {status}: {message[:200] or response.reason_phrase}"
        if status in (401, 403):
            return SearchAuthError(text, provider=self.name)
        if status == 429:
            if any(word in message.lower() for word in _QUOTA_WORDS):
                return SearchQuotaExhausted(text, provider=self.name)
            return SearchRateLimited(text, provider=self.name, retry_after=_retry_after(response))
        if status >= 500:
            return SearchServerError(text, provider=self.name)
        return SearchBadRequest(text, provider=self.name)

    def _results(self, query: SearchQuery, data: dict) -> list[SearchResult]:
        if query.focus == SearchFocus.NEWS:
            items = data.get("news_results") or []
            build = self._news_item
        elif query.focus == SearchFocus.RESEARCH:
            items = data.get("organic_results") or []
            build = self._scholar_item
        else:
            items = data.get("organic_results") or []
            build = self._web_item
        results = [build(item) for item in items if isinstance(item, dict)]
        results = [r for r in results if r is not None]
        if query.include_domains and query.focus != SearchFocus.RESEARCH:
            results = [r for r in results if on_sites(r.url, query.include_domains)]
        return results

    def _web_item(self, item: dict) -> SearchResult | None:
        return make_result(
            title=item.get("title"), url=item.get("link"), snippet=item.get("snippet"),
            publisher=item.get("source") or item.get("displayed_link"),
            published_date=parse_date(item.get("date")), provider=self.name,
        )

    def _news_item(self, item: dict) -> SearchResult | None:
        source = item.get("source")
        if isinstance(source, dict):                       # some layouts nest the name
            source = source.get("name")
        return make_result(
            title=item.get("title"), url=item.get("link"), snippet=item.get("snippet"),
            publisher=source,
            published_date=parse_date(item.get("published_at")) or parse_date(item.get("date")),
            provider=self.name,
        )

    def _scholar_item(self, item: dict) -> SearchResult | None:
        info = item.get("publication_info") or {}
        # e.g. "J Smith, A Lee - Journal of Maritime AI, 2023 - springer.com"
        summary = info.get("summary") if isinstance(info, dict) else None
        return make_result(
            title=item.get("title"), url=item.get("link"), snippet=item.get("snippet"),
            publisher=summary, published_date=None, provider=self.name,
        )


def _json(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _retry_after(response: httpx.Response) -> float | None:
    try:
        value = response.headers.get("retry-after")
        return float(value) if value is not None else None
    except ValueError:
        return None
