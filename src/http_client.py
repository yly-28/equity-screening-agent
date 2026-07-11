"""Shared HTTP configuration for public data-source adapters."""

from __future__ import annotations

from typing import Mapping, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def build_session(
    user_agent: str,
    extra_headers: Optional[Mapping[str, str]] = None,
) -> requests.Session:
    """Create a retrying session with an explicit, source-appropriate user agent."""

    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": user_agent})
    if extra_headers:
        session.headers.update(dict(extra_headers))
    return session
