from unittest.mock import MagicMock, patch

import pytest
from urllib.error import HTTPError

from kitsune_pgx.fetch.ena import _http_get


def test_http_get_retries_500() -> None:
    ok = MagicMock()
    ok.read.return_value = b"ok"
    ok.__enter__ = lambda s: s
    ok.__exit__ = MagicMock(return_value=False)

    err = HTTPError("url", 500, "Internal Server Error", None, None)

    with patch("kitsune_pgx.fetch.ena.urlopen", side_effect=[err, err, ok]) as op:
        with patch("kitsune_pgx.fetch.ena.time.sleep"):
            assert _http_get("https://example.test", retries=5) == b"ok"
    assert op.call_count == 3


def test_http_get_no_retry_on_404() -> None:
    err = HTTPError("url", 404, "Not Found", None, None)
    with patch("kitsune_pgx.fetch.ena.urlopen", side_effect=err):
        with pytest.raises(HTTPError):
            _http_get("https://example.test", retries=5)
