"""
Tests for connection pooling via requests.Session (PR 2).

Verifies that:
- NetSuiteClient creates a single Session on __init__
- All HTTP methods (suiteql, get_record, list_record_types) use that session
- OAuth auth is attached to the session (not per-request)
- Functional behaviour (success + error passthrough) is unchanged
"""
import json
import pytest
import requests

from netsuite_client import NetSuiteClient, NetSuiteAPIError


def _ok_response(body: dict) -> requests.Response:
    resp = requests.Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _error_response(status_code: int) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    resp._content = b"error"
    return resp


class TestSessionCreation:
    def test_client_has_session(self):
        client = NetSuiteClient()
        assert isinstance(client.session, requests.Session)

    def test_session_has_auth(self):
        client = NetSuiteClient()
        assert client.session.auth is not None

    def test_single_session_shared_across_calls(self):
        """Same session object is reused — not created per-request."""
        client = NetSuiteClient()
        session_id_1 = id(client.session)
        session_id_2 = id(client.session)
        assert session_id_1 == session_id_2

    def test_no_auth_attribute_on_client(self):
        """auth should be on the session, not as a top-level attribute."""
        client = NetSuiteClient()
        assert not hasattr(client, "auth"), (
            "client.auth should not exist; auth belongs on client.session"
        )


class TestSessionUsedForRequests:
    def setup_method(self):
        self.client = NetSuiteClient()

    def test_suiteql_uses_session_post(self, mocker):
        mock_post = mocker.patch.object(
            self.client.session, "post", return_value=_ok_response({"items": [], "hasMore": False})
        )
        self.client.suiteql("SELECT id FROM vendor")
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "suiteql" in call_url

    def test_get_record_uses_session_get(self, mocker):
        mock_get = mocker.patch.object(
            self.client.session, "get", return_value=_ok_response({"id": "123"})
        )
        self.client.get_record("vendor", "123")
        mock_get.assert_called_once()
        call_url = mock_get.call_args[0][0]
        assert "vendor/123" in call_url

    def test_list_record_types_uses_session_get(self, mocker):
        mock_get = mocker.patch.object(
            self.client.session, "get", return_value=_ok_response({"items": []})
        )
        self.client.list_record_types()
        mock_get.assert_called_once()
        call_url = mock_get.call_args[0][0]
        assert "metadata-catalog" in call_url

    def test_suiteql_passes_correct_headers(self, mocker):
        mock_post = mocker.patch.object(
            self.client.session, "post", return_value=_ok_response({"items": []})
        )
        self.client.suiteql("SELECT id FROM vendor")
        _, kwargs = mock_post.call_args
        assert kwargs["headers"]["Prefer"] == "transient"
        assert kwargs["headers"]["Content-Type"] == "application/json"

    def test_suiteql_passes_limit_and_offset(self, mocker):
        mock_post = mocker.patch.object(
            self.client.session, "post", return_value=_ok_response({"items": []})
        )
        self.client.suiteql("SELECT id FROM vendor", limit=50, offset=100)
        _, kwargs = mock_post.call_args
        assert kwargs["params"]["limit"] == 50
        assert kwargs["params"]["offset"] == 100

    def test_get_record_passes_fields(self, mocker):
        mock_get = mocker.patch.object(
            self.client.session, "get", return_value=_ok_response({"id": "1"})
        )
        self.client.get_record("vendor", "1", fields=["id", "companyname"])
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["fields"] == "id,companyname"

    def test_errors_still_propagate(self, mocker):
        mocker.patch.object(
            self.client.session, "post", return_value=_error_response(400)
        )
        with pytest.raises(NetSuiteAPIError):
            self.client.suiteql("BAD QUERY")
