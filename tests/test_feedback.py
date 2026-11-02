"""The feedback form address: Tally form with hidden fields, or GitHub."""

from urllib.parse import parse_qs, urlparse

from convertcad import APP_VERSION
from convertcad.core import feedback


def test_tally_address_carries_version_os_and_language():
    url = feedback.form_url("fr", base="https://tally.so/r/abc123")
    u = urlparse(url)
    assert u.netloc == "tally.so" and u.path == "/r/abc123"
    q = parse_qs(u.query)
    assert q["version"] == [APP_VERSION]
    assert q["lang"] == ["fr"]
    assert q["os"][0]


def test_existing_query_is_kept():
    url = feedback.form_url("en", base="https://tally.so/r/abc?x=1")
    assert url.startswith("https://tally.so/r/abc?x=1&version=")


def test_without_form_github_issues_is_used():
    assert feedback.form_url("en", base="") == feedback.FALLBACK_URL
