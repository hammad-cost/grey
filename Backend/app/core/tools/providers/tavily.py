"""
TavilySearchProvider — web search built for AI apps (https://tavily.com).

Request (Tavily docs, checked 2026-10-06):
  POST https://api.tavily.com/search, header "Authorization: Bearer <key>"
  body: query, topic ("news" for NEWS focus, else "general"), search_depth "basic"
        (1 credit), max_results, include_domains, time_range (day/week/month/year)
Response: results[] with title, url, content, score, published_date (if known).

Errors:
  401, 403 → SearchAuthError
  429 → SearchRateLimited (with Retry-After)
  432 (key/plan limit), 433 (pay-as-you-go limit) → SearchQuotaExhausted
  400, 422 → SearchBadRequest;   5xx → SearchServerError

The key is only sent in the Authorization header — never in messages or logs.
"""
import httpx

from app.core.tools.providers.common import make_result, parse_date, recency_bucket
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

DEFAULT_URL = "https://api.tavily.com/search"


class TavilySearchProvider(SearchProvider):
    name = "tavily"

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

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        body: dict = {
            "query": query.text,
            "topic": "news" if query.focus == SearchFocus.NEWS else "general",
            "search_depth": "basic",
            "max_results": query.max_results,
            "include_answer": False,
            "include_raw_content": False,
        }
        if query.include_domains:
            body["include_domains"] = query.include_domains
        bucket = recency_bucket(query.recency_days)
        if bucket:
            body["time_range"] = bucket

        try:
            response = await self._post(body)
        except httpx.TimeoutException as error:
            raise SearchTimeout("Tavily did not answer in time.", provider=self.name) from error
        except httpx.TransportError as error:
            raise SearchServerError(f"Connection problem: {type(error).__name__}", provider=self.name) from error

        if response.status_code >= 400:
            raise self._http_error(response)

        try:
            data = response.json()
            items = data.get("results") or []
        except (ValueError, AttributeError) as error:
            raise SearchServerError("Tavily sent an unreadable response.", provider=self.name) from error

        results = [
            make_result(
                title=item.get("title"), url=item.get("url"), snippet=item.get("content"),
                publisher=None, published_date=parse_date(item.get("published_date")),
                provider=self.name,
            )
            for item in items
            if isinstance(item, dict)
        ]
        return [r for r in results if r is not None][: query.max_results]

    async def _post(self, body: dict) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if self._client is not None:
            return await self._client.post(self._url, json=body, headers=headers, timeout=self._timeout)
        async with httpx.AsyncClient() as client:
            return await client.post(self._url, json=body, headers=headers, timeout=self._timeout)

    def _http_error(self, response: httpx.Response) -> SearchProviderError:
        status = response.status_code
        message = _error_message(response)
        text = f"HTTP {status}: {message}"
        if status in (401, 403):
            return SearchAuthError(text, provider=self.name)
        if status == 429:
            return SearchRateLimited(text, provider=self.name, retry_after=_retry_after(response))
        if status in (432, 433):
            return SearchQuotaExhausted(text, provider=self.name)
        if status >= 500:
            return SearchServerError(text, provider=self.name)
        return SearchBadRequest(text, provider=self.name)


def _error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
        detail = data.get("detail") or data.get("error") or ""
        if isinstance(detail, dict):
            detail = detail.get("error") or detail.get("message") or ""
        return str(detail)[:200] or response.reason_phrase
    except (ValueError, AttributeError):
        return response.reason_phrase or "error"


def _retry_after(response: httpx.Response) -> float | None:
    try:
        value = response.headers.get("retry-after")
        return float(value) if value is not None else None
    except ValueError:
        return None
