import time
from typing import Any, Callable, Dict, Iterable, List, Optional

import requests


DEFAULT_BACKOFF_SECONDS = (10, 20, 40, 80)


def check_urls_with_retries(
    urls: Iterable[str],
    timeout_seconds: int,
    backoff_seconds: Iterable[int] = DEFAULT_BACKOFF_SECONDS,
    request_get: Optional[Callable[..., Any]] = None,
    sleep_func: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> Dict[str, Any]:
    urls = [url for url in urls if url]
    if not urls:
        return _result("skipped", None, None, None, 0, "Health check skipped because no public endpoint is available.")

    request_get = request_get or requests.get
    attempts = 0
    started = monotonic()
    last_status_code = None
    last_response_time_ms = None
    last_error = None

    delays: List[int] = list(backoff_seconds) or [0]
    for index, delay in enumerate(delays):
        if monotonic() - started > timeout_seconds:
            break

        for url in urls:
            attempts += 1
            request_started = monotonic()
            try:
                response = request_get(url, timeout=5)
                last_response_time_ms = round((monotonic() - request_started) * 1000, 2)
                last_status_code = response.status_code
                if response.status_code >= 400:
                    last_error = f"{url} returned HTTP {response.status_code}."
                    break
            except requests.RequestException as exc:
                last_error = str(exc)
                break
        else:
            return _result("passed", urls[0], last_status_code, last_response_time_ms, attempts, "All public endpoints responded successfully.")

        if index < len(delays) - 1 and monotonic() - started + delay <= timeout_seconds:
            sleep_func(delay)

    return _result("failed", urls[0], last_status_code, last_response_time_ms, attempts, last_error or "Timed out waiting for public endpoints to respond.")


def _result(result: str, url: Optional[str], status_code: Optional[int], response_time_ms: Optional[float], attempts: int, message: str) -> Dict[str, Any]:
    return {
        "result": result,
        "status": result,
        "passed": True if result == "passed" else False if result == "failed" else None,
        "url": url,
        "status_code": status_code,
        "response_time_ms": response_time_ms,
        "attempts": attempts,
        "message": message,
    }
