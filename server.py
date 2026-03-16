import json
import logging
import os
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from netsuite_client import NetSuiteClient, NetSuiteAPIError

load_dotenv()
logging.basicConfig(level=logging.WARNING)

mcp = FastMCP("NetSuite")
client = NetSuiteClient()

# ---------------------------------------------------------------------------
# Schema guide — single source of truth shared by the resource and prompt.
# Dates are intentionally omitted from examples; use today's date at query
# time rather than stale hardcoded values.
# ---------------------------------------------------------------------------

_SCHEMA_GUIDE_CONTENT = """
# NetSuite SuiteQL Schema Guide
Peloton sandbox — 3916530_SB4_RP (Release Preview)
Last updated: March 2026

---

## Table Reference

### vendorbill
AP vendor bills. Query this directly — do NOT use `transaction WHERE type = 'VendBill'` (errors out).

| Column     | Notes |
|------------|-------|
| id         | Internal ID |
| tranid     | Bill number (e.g. "INV-1234") |
| trandate   | Bill date |
| duedate    | Payment due date |
| entity     | Vendor internal ID (join to vendor.id) |
| status     | A = Open, B = Paid In Full, D = Voided |
| total      | Bill amount in transaction currency (TWD, GBP, EUR, etc.) — do NOT aggregate across vendors |
| custbody_pel_usd_equivalent | USD equivalent amount — always use this for AP totals and aging |

Columns that do NOT exist: `amount`, `amountremaining`

### transaction
All transaction types except vendor bills. Filter by `type`.

Common type values: Journal, CustInvc, CashRfnd, VendPymt, CustDep, SalesOrd, ItemShip

| Column   | Notes |
|----------|-------|
| id       | Internal ID |
| tranid   | Transaction number |
| trandate | Transaction date |
| type     | Transaction type code |
| memo     | Memo/description |
| entity   | Related entity ID |

### transactionline
Line-level GL detail. Always join to transaction.

    JOIN transactionline tl ON tl.transaction = t.id

| Column      | Notes |
|-------------|-------|
| transaction | Parent transaction ID |
| account     | Account internal ID |
| debit       | Debit amount |
| credit      | Credit amount |
| department  | Department ID |
| location    | Location ID |
| memo        | Line memo |

### account
Chart of accounts.

| Column    | Notes |
|-----------|-------|
| id        | Internal ID |
| acctnumber| Account number |
| fullname  | Full account name |
| accttype  | Account type — use this, NOT `type` (causes error) |

Common accttype values: Bank, AcctRec, AcctPay, Income, COGS, Expense, OthCurrAsset, FixedAsset

### vendor
| Column      | Notes |
|-------------|-------|
| id          | Internal ID |
| entityid    | Vendor code (e.g. "V001310") |
| companyname | Full vendor name |

### accountingperiod
| Column     | Notes |
|------------|-------|
| id         | Internal ID |
| periodname | e.g. "Jan 2025" |
| startdate  | Period start |
| enddate    | Period end |

---

## Status Code Reference

### vendorbill.status
| Code | Meaning |
|------|---------|
| A    | Open (approved, unpaid) |
| B    | Paid In Full |
| D    | Voided |

---

## Common Gotchas

1. **vendorbill vs transaction** — always use the `vendorbill` table for AP bills
2. **account.accttype not account.type** — `type` is a reserved word and breaks queries
3. **entity JOIN in GROUP BY** — joining entity.altname in a GROUP BY errors out;
   group by entity ID, then resolve names separately (use the `resolve_ids` tool)
4. **No amount/amountremaining on vendorbill** — use `custbody_pel_usd_equivalent` for USD totals; `total` exists but is in the bill's local currency and must not be aggregated across vendors
5. **Date syntax** — prefer `TO_DATE('YYYY-MM-DD', 'YYYY-MM-DD')` for date comparisons; always use today's actual date, never hardcode stale dates
6. **Pagination** — max 1000 rows; check `has_more` in results and pass `next_offset` as the offset for the next page

---

## Useful Query Patterns

### AP Aging (open bills only, USD amounts)
Use today's date to compute bucket boundaries (current date minus 30/60/90 days).

    SELECT
      CASE
        WHEN duedate >= TO_DATE('<today>','YYYY-MM-DD') THEN 'Current'
        WHEN duedate >= TO_DATE('<today-30>','YYYY-MM-DD') THEN '1-30 Days'
        WHEN duedate >= TO_DATE('<today-60>','YYYY-MM-DD') THEN '31-60 Days'
        WHEN duedate >= TO_DATE('<today-90>','YYYY-MM-DD') THEN '61-90 Days'
        ELSE '90+ Days'
      END AS aging_bucket,
      COUNT(*) AS bill_count,
      SUM(custbody_pel_usd_equivalent) AS total_usd
    FROM vendorbill
    WHERE status = 'A'
    GROUP BY <same CASE expression>

### GL Detail for an Account
    SELECT t.trandate, t.tranid, t.memo, tl.debit, tl.credit
    FROM transaction t
    JOIN transactionline tl ON tl.transaction = t.id
    WHERE tl.account = <account_id>
    ORDER BY t.trandate DESC

### Bills by Vendor (top vendors by open balance, USD)
    SELECT entity, COUNT(*) AS bill_count, SUM(custbody_pel_usd_equivalent) AS total_usd
    FROM vendorbill
    WHERE status = 'A'
    GROUP BY entity
    ORDER BY SUM(custbody_pel_usd_equivalent) DESC
    -- Then resolve entity IDs with the resolve_ids tool: record_type='vendor', ids=[...]

### Journal Entries
    SELECT id, trandate, tranid, memo
    FROM transaction
    WHERE type = 'Journal'
    AND trandate >= TO_DATE('<start_date>','YYYY-MM-DD')
    ORDER BY trandate DESC
"""


@mcp.tool()
def suiteql_query(query: str, limit: int = 100, offset: int = 0) -> str:
    """
    Run a SuiteQL query against NetSuite.

    SuiteQL is SQL-like. Use this as the primary tool for all data retrieval.
    For schema details, table names, known columns, and gotchas, load the
    `netsuite_schema_guide` prompt first.

    ## Pagination
    Default limit is 100 rows (max 1000). If has_more is true, call again
    with the returned next_offset to fetch the next page.

    ## Response shape
    {
      "rows":        [...],   -- the result rows
      "row_count":   N,       -- number of rows in this page
      "has_more":    bool,    -- true if more pages exist
      "next_offset": N|null   -- pass as offset to fetch the next page; null when has_more is false
    }

    Args:
        query: SuiteQL query string
        limit: Max rows to return (default 100, max 1000)
        offset: Row offset for pagination (default 0)
    """
    try:
        result = client.suiteql(query, limit=limit, offset=offset)
        has_more = result.get("hasMore", False)
        return json.dumps(
            {
                "rows": result.get("items", []),
                "row_count": result.get("count", 0),
                "has_more": has_more,
                "next_offset": offset + limit if has_more else None,
            },
            indent=2,
        )
    except NetSuiteAPIError as e:
        return f"NetSuite API error {e.status_code}: {e.body}"
    except Exception as e:
        return f"Error executing SuiteQL query: {str(e)}"


@mcp.tool()
def get_record(record_type: str, record_id: str, fields: str = "") -> str:
    """
    Fetch a specific NetSuite record by type and ID.

    Args:
        record_type: The NetSuite record type (e.g., 'invoice', 'journalentry',
                     'vendor', 'customer', 'account')
        record_id: The internal ID of the record
        fields: Optional comma-separated list of fields to return.
                Leave empty to return all fields.
    """
    try:
        field_list = [f.strip() for f in fields.split(",") if f.strip()] if fields else None
        result = client.get_record(record_type, record_id, fields=field_list)
        return json.dumps(result, indent=2)
    except NetSuiteAPIError as e:
        return f"NetSuite API error {e.status_code}: {e.body}"
    except Exception as e:
        return f"Error fetching record: {str(e)}"


@mcp.tool()
def list_record_types() -> str:
    """
    List all available NetSuite record types accessible via the REST API.
    Useful for discovering what data is available to query.
    """
    try:
        result = client.list_record_types()
        # Extract just the names and links for readability
        if "items" in result:
            types = [{"name": item.get("name"), "id": item.get("id")} for item in result["items"]]
            return json.dumps(types, indent=2)
        return json.dumps(result, indent=2)
    except NetSuiteAPIError as e:
        return f"NetSuite API error {e.status_code}: {e.body}"
    except Exception as e:
        return f"Error listing record types: {str(e)}"


@mcp.tool()
def resolve_ids(record_type: str, ids: list[int]) -> str:
    """
    Resolve a list of NetSuite internal IDs to human-readable names.

    Use this after a SuiteQL query returns numeric IDs (entity, account,
    department, etc.) to label them without writing a manual JOIN or a
    separate SELECT ... WHERE id IN (...) query.

    Supported record_type values:
      vendor, customer, employee, account, department, location, subsidiary

    Returns a JSON object mapping each ID (as a string) to its name.

    Example:
        resolve_ids("vendor", [1234, 5678])
        -> {"1234": "Acme Corp", "5678": "Global Supplies Ltd"}

    Args:
        record_type: One of the supported types listed above
        ids: List of internal integer IDs to resolve
    """
    try:
        result = client.resolve_ids(record_type, ids)
        return json.dumps(result, indent=2)
    except ValueError as e:
        return f"Error: {str(e)}"
    except NetSuiteAPIError as e:
        return f"NetSuite API error {e.status_code}: {e.body}"
    except Exception as e:
        return f"Error resolving IDs: {str(e)}"


@mcp.resource("netsuite://schema-guide")
def schema_guide() -> str:
    """
    Reference guide for querying this NetSuite instance via SuiteQL.
    Covers table schemas, status codes, known gotchas, and query patterns
    discovered through live testing against the Peloton sandbox (3916530_SB4_RP).
    """
    return _SCHEMA_GUIDE_CONTENT


@mcp.prompt()
def netsuite_schema_guide() -> str:
    """
    Load the NetSuite SuiteQL schema guide into context.

    Use this prompt before writing any SuiteQL queries to ensure you have
    accurate table schemas, known working columns, status codes, gotchas,
    and query patterns for this Peloton NetSuite instance.
    """
    return _SCHEMA_GUIDE_CONTENT


if __name__ == "__main__":
    mcp.run(transport="stdio")
