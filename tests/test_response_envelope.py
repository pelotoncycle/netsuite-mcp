"""
Tests for clean suiteql_query response envelope (PR 6).

Verifies that:
- Response has keys: rows, row_count, has_more, next_offset
- Raw NetSuite envelope keys (items, hasMore, count, totalResults) are NOT exposed
- next_offset is pre-computed correctly when has_more is True
- next_offset is null when has_more is False
- row_count matches the number of rows returned
- Empty result set is handled correctly
- Error path is unchanged
"""
import json
import pytest

import server


def _mock_suiteql(mocker, items, has_more, offset=0, limit=1000):
    payload = {
        "items": items,
        "hasMore": has_more,
        "count": len(items),
        "offset": offset,
        "totalResults": len(items),
    }
    mocker.patch.object(server.client, "suiteql", return_value=payload)
    return payload


class TestResponseShape:
    def test_response_has_rows_key(self, mocker):
        _mock_suiteql(mocker, [{"id": "1"}], has_more=False)
        result = json.loads(server.suiteql_query("SELECT id FROM vendor"))
        assert "rows" in result

    def test_response_has_row_count_key(self, mocker):
        _mock_suiteql(mocker, [{"id": "1"}], has_more=False)
        result = json.loads(server.suiteql_query("SELECT id FROM vendor"))
        assert "row_count" in result

    def test_response_has_has_more_key(self, mocker):
        _mock_suiteql(mocker, [], has_more=False)
        result = json.loads(server.suiteql_query("SELECT id FROM vendor"))
        assert "has_more" in result

    def test_response_has_next_offset_key(self, mocker):
        _mock_suiteql(mocker, [], has_more=False)
        result = json.loads(server.suiteql_query("SELECT id FROM vendor"))
        assert "next_offset" in result

    def test_raw_items_key_not_exposed(self, mocker):
        _mock_suiteql(mocker, [{"id": "1"}], has_more=False)
        result = json.loads(server.suiteql_query("SELECT id FROM vendor"))
        assert "items" not in result

    def test_raw_hasMore_not_exposed(self, mocker):
        _mock_suiteql(mocker, [], has_more=True)
        result = json.loads(server.suiteql_query("SELECT id FROM vendor"))
        assert "hasMore" not in result

    def test_raw_totalResults_not_exposed(self, mocker):
        _mock_suiteql(mocker, [], has_more=False)
        result = json.loads(server.suiteql_query("SELECT id FROM vendor"))
        assert "totalResults" not in result


class TestRowsContent:
    def test_rows_contains_items(self, mocker):
        _mock_suiteql(mocker, [{"id": "1"}, {"id": "2"}], has_more=False)
        result = json.loads(server.suiteql_query("SELECT id FROM vendor"))
        assert result["rows"] == [{"id": "1"}, {"id": "2"}]

    def test_row_count_matches_rows_length(self, mocker):
        _mock_suiteql(mocker, [{"id": "1"}, {"id": "2"}, {"id": "3"}], has_more=False)
        result = json.loads(server.suiteql_query("SELECT id FROM vendor"))
        assert result["row_count"] == 3
        assert len(result["rows"]) == 3

    def test_empty_result_set(self, mocker):
        _mock_suiteql(mocker, [], has_more=False)
        result = json.loads(server.suiteql_query("SELECT id FROM vendor WHERE 1=0"))
        assert result["rows"] == []
        assert result["row_count"] == 0
        assert result["has_more"] is False
        assert result["next_offset"] is None


class TestPagination:
    def test_next_offset_is_null_when_no_more_pages(self, mocker):
        _mock_suiteql(mocker, [{"id": "1"}], has_more=False)
        result = json.loads(server.suiteql_query("SELECT id FROM vendor"))
        assert result["next_offset"] is None

    def test_next_offset_computed_when_has_more(self, mocker):
        _mock_suiteql(mocker, [{"id": str(i)} for i in range(1000)], has_more=True)
        result = json.loads(server.suiteql_query("SELECT id FROM vendor", limit=1000, offset=0))
        assert result["has_more"] is True
        assert result["next_offset"] == 1000

    def test_next_offset_increments_correctly_from_offset(self, mocker):
        _mock_suiteql(mocker, [{"id": str(i)} for i in range(1000)], has_more=True)
        result = json.loads(server.suiteql_query("SELECT id FROM vendor", limit=1000, offset=1000))
        assert result["next_offset"] == 2000

    def test_next_offset_uses_limit_as_increment(self, mocker):
        _mock_suiteql(mocker, [{"id": str(i)} for i in range(100)], has_more=True)
        result = json.loads(server.suiteql_query("SELECT id FROM vendor", limit=100, offset=0))
        assert result["next_offset"] == 100


class TestErrorPathUnchanged:
    def test_error_still_returns_string_message(self, mocker):
        mocker.patch.object(server.client, "suiteql", side_effect=Exception("connection failed"))
        result = server.suiteql_query("SELECT id FROM vendor")
        assert isinstance(result, str)
        assert "Error" in result
        assert "connection failed" in result
