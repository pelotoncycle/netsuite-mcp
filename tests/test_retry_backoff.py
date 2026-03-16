"""
Tests for retry with exponential backoff (PR 4).

Verifies that:
- DEFAULT_RETRY is configured with the right status codes and backoff
- The session mounts an HTTPAdapter with the retry policy
- A custom Retry can be injected at construction time
- POST is included in allowed_methods (SuiteQL uses POST)
- raise_on_status is False so we can call _raise_for_status() ourselves
"""
import json
import os
import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

os.environ.setdefault("NETSUITE_ACCOUNT_ID", "test_account")
os.environ.setdefault("NETSUITE_CONSUMER_KEY", "ck")
os.environ.setdefault("NETSUITE_CONSUMER_SECRET", "cs")
os.environ.setdefault("NETSUITE_TOKEN_ID", "ti")
os.environ.setdefault("NETSUITE_TOKEN_SECRET", "ts")

from netsuite_client import NetSuiteClient, NetSuiteAPIError, DEFAULT_RETRY


class TestDefaultRetryConfig:
    def test_default_retry_is_retry_instance(self):
        assert isinstance(DEFAULT_RETRY, Retry)

    def test_default_retry_total(self):
        assert DEFAULT_RETRY.total == 3

    def test_default_retry_backoff_factor(self):
        assert DEFAULT_RETRY.backoff_factor == 2

    def test_default_retry_includes_429(self):
        assert 429 in DEFAULT_RETRY.status_forcelist

    def test_default_retry_includes_500(self):
        assert 500 in DEFAULT_RETRY.status_forcelist

    def test_default_retry_includes_503(self):
        assert 503 in DEFAULT_RETRY.status_forcelist

    def test_default_retry_includes_post(self):
        # POST must be retried — SuiteQL queries use POST
        assert "POST" in DEFAULT_RETRY.allowed_methods

    def test_default_retry_includes_get(self):
        assert "GET" in DEFAULT_RETRY.allowed_methods

    def test_default_retry_raise_on_status_false(self):
        # We call _raise_for_status() ourselves; urllib3 must not raise first
        assert DEFAULT_RETRY.raise_on_status is False


class TestSessionAdapterMounting:
    def test_session_has_https_adapter_with_retry(self):
        client = NetSuiteClient()
        adapter = client.session.get_adapter("https://example.com")
        assert isinstance(adapter, HTTPAdapter)

    def test_session_adapter_has_retry_policy(self):
        client = NetSuiteClient()
        adapter = client.session.get_adapter("https://example.com")
        assert adapter.max_retries is not None
        assert adapter.max_retries.total == DEFAULT_RETRY.total

    def test_custom_retry_is_used(self):
        custom_retry = Retry(total=1, backoff_factor=0.5, status_forcelist=[503])
        client = NetSuiteClient(retry=custom_retry)
        adapter = client.session.get_adapter("https://example.com")
        assert adapter.max_retries.total == 1

    def test_http_adapter_also_mounted(self):
        """http:// mount ensures retry works even for non-TLS (e.g. local testing)."""
        client = NetSuiteClient()
        adapter = client.session.get_adapter("http://example.com")
        assert isinstance(adapter, HTTPAdapter)


class TestRetryDoesNotAffectSuccessPath:
    def test_suiteql_success_still_returns_data(self, mocker):
        client = NetSuiteClient()
        payload = {"items": [{"id": "1"}], "hasMore": False}
        resp = requests.Response()
        resp.status_code = 200
        resp._content = json.dumps(payload).encode()
        mocker.patch.object(client.session, "post", return_value=resp)
        result = client.suiteql("SELECT id FROM vendor")
        assert result["items"][0]["id"] == "1"

    def test_non_retryable_error_propagates_immediately(self, mocker):
        """400 Bad Request is not in status_forcelist and must not be retried."""
        client = NetSuiteClient()
        resp = requests.Response()
        resp.status_code = 400
        resp._content = b'{"error": "bad query"}'
        mocker.patch.object(client.session, "post", return_value=resp)
        with pytest.raises(NetSuiteAPIError) as exc_info:
            client.suiteql("BAD QUERY")
        assert exc_info.value.status_code == 400
