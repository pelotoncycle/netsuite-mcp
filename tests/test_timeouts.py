"""
Tests for request timeouts (PR 3).

Verifies that:
- DEFAULT_TIMEOUT constant is a (connect, read) tuple
- All client methods pass the timeout to their session calls
- timeout is configurable at construction time
- Timeout errors surface as requests.Timeout (not silently swallowed)
"""
import json
import os
import pytest
import requests

os.environ.setdefault("NETSUITE_ACCOUNT_ID", "test_account")
os.environ.setdefault("NETSUITE_CONSUMER_KEY", "ck")
os.environ.setdefault("NETSUITE_CONSUMER_SECRET", "cs")
os.environ.setdefault("NETSUITE_TOKEN_ID", "ti")
os.environ.setdefault("NETSUITE_TOKEN_SECRET", "ts")

from netsuite_client import NetSuiteClient, DEFAULT_TIMEOUT


def _ok_response(body: dict) -> requests.Response:
    resp = requests.Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


class TestDefaultTimeout:
    def test_default_timeout_is_tuple(self):
        assert isinstance(DEFAULT_TIMEOUT, tuple)
        assert len(DEFAULT_TIMEOUT) == 2

    def test_default_timeout_connect_is_positive(self):
        connect_timeout, _ = DEFAULT_TIMEOUT
        assert connect_timeout > 0

    def test_default_timeout_read_is_positive(self):
        _, read_timeout = DEFAULT_TIMEOUT
        assert read_timeout > 0

    def test_client_uses_default_timeout(self):
        client = NetSuiteClient()
        assert client.timeout == DEFAULT_TIMEOUT

    def test_client_accepts_custom_timeout(self):
        client = NetSuiteClient(timeout=(5, 30))
        assert client.timeout == (5, 30)


class TestTimeoutPassedToRequests:
    def setup_method(self):
        self.client = NetSuiteClient(timeout=(5, 60))

    def test_suiteql_passes_timeout(self, mocker):
        mock_post = mocker.patch.object(
            self.client.session, "post",
            return_value=_ok_response({"items": [], "hasMore": False}),
        )
        self.client.suiteql("SELECT id FROM vendor")
        _, kwargs = mock_post.call_args
        assert kwargs["timeout"] == (5, 60)

    def test_get_record_passes_timeout(self, mocker):
        mock_get = mocker.patch.object(
            self.client.session, "get",
            return_value=_ok_response({"id": "1"}),
        )
        self.client.get_record("vendor", "1")
        _, kwargs = mock_get.call_args
        assert kwargs["timeout"] == (5, 60)

    def test_list_record_types_passes_timeout(self, mocker):
        mock_get = mocker.patch.object(
            self.client.session, "get",
            return_value=_ok_response({"items": []}),
        )
        self.client.list_record_types()
        _, kwargs = mock_get.call_args
        assert kwargs["timeout"] == (5, 60)


class TestTimeoutErrors:
    def setup_method(self):
        self.client = NetSuiteClient()

    def test_suiteql_raises_on_connect_timeout(self, mocker):
        mocker.patch.object(self.client.session, "post", side_effect=requests.ConnectTimeout())
        with pytest.raises(requests.ConnectTimeout):
            self.client.suiteql("SELECT id FROM vendor")

    def test_suiteql_raises_on_read_timeout(self, mocker):
        mocker.patch.object(self.client.session, "post", side_effect=requests.ReadTimeout())
        with pytest.raises(requests.ReadTimeout):
            self.client.suiteql("SELECT id FROM vendor")

    def test_get_record_raises_on_timeout(self, mocker):
        mocker.patch.object(self.client.session, "get", side_effect=requests.Timeout())
        with pytest.raises(requests.Timeout):
            self.client.get_record("vendor", "1")

    def test_list_record_types_raises_on_timeout(self, mocker):
        mocker.patch.object(self.client.session, "get", side_effect=requests.Timeout())
        with pytest.raises(requests.Timeout):
            self.client.list_record_types()
