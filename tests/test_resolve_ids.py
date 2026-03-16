"""
Tests for the resolve_ids feature.

Covers:
- NetSuiteClient.resolve_ids() — correct SuiteQL query generation, result mapping,
  empty-id short-circuit, and unsupported-type error.
- server.resolve_ids() MCP tool — happy path and both error paths.
"""
import json
import pytest

from netsuite_client import NetSuiteClient, NetSuiteAPIError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _suiteql_response(*rows: dict) -> dict:
    """Build a fake suiteql() response dict."""
    return {"items": list(rows), "count": len(rows), "hasMore": False}


# ---------------------------------------------------------------------------
# NetSuiteClient.resolve_ids
# ---------------------------------------------------------------------------

class TestResolveIdsClient:
    def setup_method(self):
        self.client = NetSuiteClient()

    def test_vendor_returns_id_to_name_map(self, mocker):
        mocker.patch.object(
            self.client,
            "suiteql",
            return_value=_suiteql_response(
                {"id": 1234, "name": "Acme Corp"},
                {"id": 5678, "name": "Global Supplies Ltd"},
            ),
        )
        result = self.client.resolve_ids("vendor", [1234, 5678])
        assert result == {"1234": "Acme Corp", "5678": "Global Supplies Ltd"}

    def test_customer_returns_id_to_name_map(self, mocker):
        mocker.patch.object(
            self.client,
            "suiteql",
            return_value=_suiteql_response({"id": 99, "name": "Big Customer"}),
        )
        result = self.client.resolve_ids("customer", [99])
        assert result == {"99": "Big Customer"}

    def test_employee_returns_full_name(self, mocker):
        mocker.patch.object(
            self.client,
            "suiteql",
            return_value=_suiteql_response({"id": 7, "name": "Jane Doe"}),
        )
        result = self.client.resolve_ids("employee", [7])
        assert result == {"7": "Jane Doe"}

    def test_account_department_location_subsidiary(self, mocker):
        for rtype in ("account", "department", "location", "subsidiary"):
            mock = mocker.patch.object(
                self.client,
                "suiteql",
                return_value=_suiteql_response({"id": 1, "name": f"{rtype} name"}),
            )
            result = self.client.resolve_ids(rtype, [1])
            assert result == {"1": f"{rtype} name"}
            mock.stop()

    def test_empty_ids_returns_empty_dict_without_calling_suiteql(self, mocker):
        spy = mocker.patch.object(self.client, "suiteql")
        result = self.client.resolve_ids("vendor", [])
        assert result == {}
        spy.assert_not_called()

    def test_unsupported_type_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported record_type 'invoice'"):
            self.client.resolve_ids("invoice", [1])

    def test_suiteql_called_with_correct_limit(self, mocker):
        mock = mocker.patch.object(
            self.client,
            "suiteql",
            return_value=_suiteql_response(),
        )
        self.client.resolve_ids("vendor", [10, 20, 30])
        _, kwargs = mock.call_args
        assert kwargs.get("limit") == 3

    def test_query_contains_all_ids(self, mocker):
        mock = mocker.patch.object(
            self.client,
            "suiteql",
            return_value=_suiteql_response(),
        )
        self.client.resolve_ids("department", [11, 22])
        query = mock.call_args[0][0]
        assert "11" in query
        assert "22" in query
        assert "department" in query.lower()

    def test_missing_name_returns_none(self, mocker):
        """Rows missing the name key should produce None values, not KeyErrors."""
        mocker.patch.object(
            self.client,
            "suiteql",
            return_value=_suiteql_response({"id": 5}),
        )
        result = self.client.resolve_ids("vendor", [5])
        assert result == {"5": None}


# ---------------------------------------------------------------------------
# server.resolve_ids MCP tool
# ---------------------------------------------------------------------------

class TestResolveIdsServer:
    def setup_method(self):
        import server
        self.server = server

    def test_returns_id_to_name_json(self, mocker):
        mocker.patch.object(
            self.server.client,
            "resolve_ids",
            return_value={"1234": "Acme Corp", "5678": "Global Supplies Ltd"},
        )
        result = self.server.resolve_ids("vendor", [1234, 5678])
        parsed = json.loads(result)
        assert parsed["1234"] == "Acme Corp"
        assert parsed["5678"] == "Global Supplies Ltd"

    def test_unsupported_type_returns_error_string(self, mocker):
        mocker.patch.object(
            self.server.client,
            "resolve_ids",
            side_effect=ValueError("Unsupported record_type 'invoice'"),
        )
        result = self.server.resolve_ids("invoice", [1])
        assert "Error" in result
        assert "invoice" in result

    def test_api_error_returns_structured_error(self, mocker):
        mocker.patch.object(
            self.server.client,
            "resolve_ids",
            side_effect=NetSuiteAPIError(500, "Internal Server Error"),
        )
        result = self.server.resolve_ids("vendor", [99])
        assert "500" in result
        assert "Internal Server Error" in result

    def test_empty_ids_returns_empty_json_object(self, mocker):
        mocker.patch.object(
            self.server.client,
            "resolve_ids",
            return_value={},
        )
        result = self.server.resolve_ids("vendor", [])
        assert json.loads(result) == {}
