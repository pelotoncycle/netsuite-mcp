"""
Tests for schema guide exposed as MCP prompt (PR 5).

Verifies that:
- _SCHEMA_GUIDE_CONTENT is a non-empty string
- The schema guide resource still returns the same content (backward compat)
- The schema guide prompt returns the same content as the resource
- The prompt is registered on the FastMCP instance
- Key schema sections are present in the content
"""
import os

os.environ.setdefault("NETSUITE_ACCOUNT_ID", "test_account")
os.environ.setdefault("NETSUITE_CONSUMER_KEY", "ck")
os.environ.setdefault("NETSUITE_CONSUMER_SECRET", "cs")
os.environ.setdefault("NETSUITE_TOKEN_ID", "ti")
os.environ.setdefault("NETSUITE_TOKEN_SECRET", "ts")

import server


class TestSchemaGuideContent:
    def test_schema_content_is_non_empty(self):
        assert len(server._SCHEMA_GUIDE_CONTENT.strip()) > 0

    def test_schema_content_contains_vendorbill(self):
        assert "vendorbill" in server._SCHEMA_GUIDE_CONTENT

    def test_schema_content_contains_transaction(self):
        assert "transaction" in server._SCHEMA_GUIDE_CONTENT

    def test_schema_content_contains_gotchas(self):
        assert "Gotchas" in server._SCHEMA_GUIDE_CONTENT

    def test_schema_content_contains_status_codes(self):
        assert "Status Code" in server._SCHEMA_GUIDE_CONTENT

    def test_schema_content_contains_accttype_warning(self):
        assert "accttype" in server._SCHEMA_GUIDE_CONTENT

    def test_schema_content_contains_usd_equivalent_warning(self):
        assert "custbody_pel_usd_equivalent" in server._SCHEMA_GUIDE_CONTENT


class TestSchemaGuideResource:
    def test_resource_returns_schema_content(self):
        result = server.schema_guide()
        assert result == server._SCHEMA_GUIDE_CONTENT

    def test_resource_content_is_string(self):
        result = server.schema_guide()
        assert isinstance(result, str)


class TestSchemaGuidePrompt:
    def test_prompt_returns_schema_content(self):
        result = server.netsuite_schema_guide()
        assert result == server._SCHEMA_GUIDE_CONTENT

    def test_prompt_and_resource_return_same_content(self):
        assert server.netsuite_schema_guide() == server.schema_guide()

    def test_prompt_content_is_string(self):
        assert isinstance(server.netsuite_schema_guide(), str)


class TestPromptRegistration:
    def test_prompt_registered_on_mcp(self):
        """The netsuite_schema_guide prompt must be discoverable via the FastMCP instance."""
        prompt_names = [p.name for p in server.mcp._prompt_manager._prompts.values()]
        assert "netsuite_schema_guide" in prompt_names

    def test_resource_still_registered_on_mcp(self):
        """Existing resource must remain for backward compatibility."""
        resource_names = list(server.mcp._resource_manager._resources.keys())
        assert any("schema-guide" in str(name) for name in resource_names)
