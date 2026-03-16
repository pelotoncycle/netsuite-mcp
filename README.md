# netsuite-mcp

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server for querying NetSuite via SuiteQL and the REST Record API. Built with [FastMCP](https://github.com/jlowin/fastmcp).

## Tools

| Tool | Description |
|---|---|
| `suiteql_query` | Run a SuiteQL query — primary tool for all data retrieval |
| `get_record` | Fetch a specific record by type and internal ID |
| `list_record_types` | List all available REST record types |

A `netsuite://schema-guide` MCP resource is also exposed with table schemas, status codes, and query patterns for this instance.

## Setup

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure credentials**
   ```bash
   cp .env.example .env
   ```
   Fill in your NetSuite OAuth 1.0a credentials in `.env`:
   - `NETSUITE_ACCOUNT_ID` — your account ID (e.g. `3916530_SB4_RP`)
   - `NETSUITE_CONSUMER_KEY` / `NETSUITE_CONSUMER_SECRET` — integration credentials
   - `NETSUITE_TOKEN_ID` / `NETSUITE_TOKEN_SECRET` — access token credentials

3. **Register with Claude Code**

   Add to your project's `.mcp.json`:
   ```json
   {
     "mcpServers": {
       "netsuite": {
         "command": "python",
         "args": ["/path/to/netsuite-mcp/server.py"]
       }
     }
   }
   ```

## Authentication

Uses OAuth 1.0a with HMAC-SHA256 (Token-Based Authentication). Each user needs their own access token generated from the NetSuite UI under **Setup > Users/Roles > Access Tokens**.
