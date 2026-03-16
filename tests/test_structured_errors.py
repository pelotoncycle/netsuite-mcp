"""
Tests for structured error responses (PR 1).

Verifies that:
- NetSuiteAPIError is raised with status code + body when the API returns an HTTP error
- server.py tool handlers return the structured error message to the LLM
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

from netsuite_client import NetSuiteClient, NetSuiteAPIError


def _make_error_response(status_code: int, body: str) -> requests.Response:
    """Build a fake requests.Response that raise_for_status() will reject."""
    resp = requests.Response()
    resp.status_code = status_code
    resp._content = body.encode()
    return resp


class TestNetSuiteAPIError:
    def test_error_carries_status_code_and_body(self):
        err = NetSuiteAPIError(400, '{"error": "invalid column"}')
        assert err.status_code == 400
        assert err.body == '{"error": "invalid column"}'

    def test_error_str_includes_status_and_body(self):
        err = NetSuiteAPIError(404, "Not Found")
        assert "404" in str(err)
        assert "Not Found" in str(err)

    def test_error_is_exception(self):
        err = NetSuiteAPIError(500, "Server Error")
        assert isinstance(err, Exception)


class TestRaiseForStatus:
    def setup_method(self):
        self.client = NetSuiteClient()

    def test_raises_netsuite_api_error_on_400(self):
        resp = _make_error_response(400, '{"o:errorDetails": [{"detail": "invalid column name"}]}')
        with pytest.raises(NetSuiteAPIError) as exc_info:
            self.client._raise_for_status(resp)
        assert exc_info.value.status_code == 400
        assert "invalid column name" in exc_info.value.body

    def test_raises_netsuite_api_error_on_404(self):
        resp = _make_error_response(404, "Record not found")
        with pytest.raises(NetSuiteAPIError) as exc_info:
            self.client._raise_for_status(resp)
        assert exc_info.value.status_code == 404

    def test_raises_netsuite_api_error_on_429(self):
        resp = _make_error_response(429, "Too Many Requests")
        with pytest.raises(NetSuiteAPIError) as exc_info:
            self.client._raise_for_status(resp)
        assert exc_info.value.status_code == 429

    def test_raises_netsuite_api_error_on_500(self):
        resp = _make_error_response(500, "Internal Server Error")
        with pytest.raises(NetSuiteAPIError) as exc_info:
            self.client._raise_for_status(resp)
        assert exc_info.value.status_code == 500

    def test_does_not_raise_on_200(self):
        resp = _make_error_response(200, '{"items": []}')
        # Should not raise
        self.client._raise_for_status(resp)

    def test_does_not_raise_on_201(self):
        resp = _make_error_response(201, '{"id": "123"}')
        self.client._raise_for_status(resp)


class TestServerToolErrorHandling:
    """Verify that server tools surface NetSuiteAPIError cleanly to the LLM."""

    def setup_method(self):
        # Patch client on the already-imported server module
        import server
        self.server = server

    def test_suiteql_query_returns_structured_error(self, mocker):
        mocker.patch.object(
            self.server.client,
            "suiteql",
            side_effect=NetSuiteAPIError(400, '{"o:errorDetails":[{"detail":"column FOO does not exist"}]}'),
        )
        result = self.server.suiteql_query("SELECT FOO FROM vendorbill")
        assert "400" in result
        assert "FOO does not exist" in result

    def test_get_record_returns_structured_error(self, mocker):
        mocker.patch.object(
            self.server.client,
            "get_record",
            side_effect=NetSuiteAPIError(404, "Record not found"),
        )
        result = self.server.get_record("vendor", "99999")
        assert "404" in result
        assert "Record not found" in result

    def test_list_record_types_returns_structured_error(self, mocker):
        mocker.patch.object(
            self.server.client,
            "list_record_types",
            side_effect=NetSuiteAPIError(503, "Service Unavailable"),
        )
        result = self.server.list_record_types()
        assert "503" in result
        assert "Service Unavailable" in result

    def test_suiteql_query_success_still_works(self, mocker):
        payload = {"items": [{"id": "1"}], "hasMore": False, "count": 1, "offset": 0, "totalResults": 1}
        mocker.patch.object(self.server.client, "suiteql", return_value=payload)
        result = self.server.suiteql_query("SELECT id FROM vendor")
        parsed = json.loads(result)
        assert parsed["items"][0]["id"] == "1"
