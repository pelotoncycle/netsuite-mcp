import json
import os
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from netsuite_client import NetSuiteClient, NetSuiteAPIError

load_dotenv()

mcp = FastMCP("NetSuite")
client = NetSuiteClient()

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
   group by entity ID, then resolve names separately
4. **No amount/amountremaining on vendorbill** — use `custbody_pel_usd_equivalent` for USD totals; `total` exists but is in the bill's local currency and must not be aggregated across vendors
5. **Date syntax** — prefer `TO_DATE('2025-01-01', 'YYYY-MM-DD')` for date comparisons
6. **Pagination** — max 1000 rows; check `hasMore` in results and increment `offset` by 1000

---

## Useful Query Patterns

### AP Aging (open bills only, USD amounts)
    SELECT
      CASE
        WHEN duedate >= TO_DATE('2026-03-13','YYYY-MM-DD') THEN 'Current'
        WHEN duedate >= TO_DATE('2026-02-11','YYYY-MM-DD') THEN '1-30 Days'
        WHEN duedate >= TO_DATE('2026-01-12','YYYY-MM-DD') THEN '31-60 Days'
        WHEN duedate >= TO_DATE('2025-12-13','YYYY-MM-DD') THEN '61-90 Days'
        ELSE '90+ Days'
      END AS aging_bucket,
      COUNT(*) AS bill_count,
      SUM(custbody_pel_usd_equivalent) AS total_usd
    FROM vendorbill
    WHERE status = 'A'
    GROUP BY CASE
        WHEN duedate >= TO_DATE('2026-03-13','YYYY-MM-DD') THEN 'Current'
        WHEN duedate >= TO_DATE('2026-02-11','YYYY-MM-DD') THEN '1-30 Days'
        WHEN duedate >= TO_DATE('2026-01-12','YYYY-MM-DD') THEN '31-60 Days'
        WHEN duedate >= TO_DATE('2025-12-13','YYYY-MM-DD') THEN '61-90 Days'
        ELSE '90+ Days'
    END

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
    -- Then resolve entity IDs: SELECT id, entityid, companyname FROM vendor WHERE id IN (...)

### Journal Entries
    SELECT id, trandate, tranid, memo
    FROM transaction
    WHERE type = 'Journal'
    AND trandate >= TO_DATE('2025-01-01','YYYY-MM-DD')
    ORDER BY trandate DESC
"""


@mcp.tool()
def suiteql_query(query: str, limit: int = 1000, offset: int = 0) -> str:
    """
    Run a SuiteQL query against NetSuite.

    SuiteQL is a SQL-like query language for NetSuite data. Use this as the
    primary tool for all data retrieval — it is faster and more flexible than
    get_record for anything beyond a single record lookup.

    ## Key Tables
    - vendorbill         — AP bills (vendor invoices). Use instead of transaction WHERE type='VendBill' (that does NOT work)
    - transaction        — all transaction types EXCEPT vendor bills; filter by type (e.g. 'Journal', 'CustInvc', 'VendPymt')
    - transactionline    — line-level detail for any transaction; join on transactionline.transaction = transaction.id
    - account            — chart of accounts
    - vendor             — vendor master; fields: id, entityid, companyname
    - customer           — customer master
    - entity             — base entity table (vendors, customers, employees share this); fields: id, entityid, altname
    - employee           — employee records
    - department         — department/cost center hierarchy
    - subsidiary         — legal entity / subsidiary
    - location           — warehouse and office locations
    - accountingperiod   — fiscal periods; fields: id, periodname, startdate, enddate

    ## Known Working Columns

    vendorbill:
    - id, tranid, trandate, duedate, entity, status, total, custbody_pel_usd_equivalent — all work
    - total is in the bill's local currency (TWD, GBP, EUR, etc.) — do NOT aggregate across vendors
    - custbody_pel_usd_equivalent is the USD equivalent — always use this for AP totals and aging
    - amount, amountremaining — do NOT exist
    - status codes: A = Open (unpaid), B = Paid In Full, D = Voided

    account:
    - Use accttype (not type) for account type — 'type' causes a query error

    ## Date Filtering
    Use TO_DATE with explicit format string:
        WHERE trandate >= TO_DATE('2025-01-01', 'YYYY-MM-DD')
    String comparison also works for simple cases:
        WHERE trandate >= '2025-01-01'

    ## JOIN Patterns
    Joining entity.altname in a GROUP BY clause causes errors. Instead:
    1. GROUP BY entity ID
    2. Resolve names in a second query against the vendor or entity table

    ## Pagination
    Max 1000 rows per request. Check hasMore in the result and use offset to paginate.
    Example for page 2: suiteql_query(query, offset=1000)

    ## Examples

    Open AP aging summary (use custbody_pel_usd_equivalent, not total):
        SELECT
          CASE
            WHEN duedate >= TO_DATE('2026-03-13','YYYY-MM-DD') THEN 'Current'
            WHEN duedate >= TO_DATE('2026-02-11','YYYY-MM-DD') THEN '1-30 Days'
            WHEN duedate >= TO_DATE('2026-01-12','YYYY-MM-DD') THEN '31-60 Days'
            ELSE '90+ Days'
          END AS aging_bucket,
          COUNT(*) AS bill_count,
          SUM(custbody_pel_usd_equivalent) AS total_usd
        FROM vendorbill
        WHERE status = 'A'
        GROUP BY CASE ... END

    Recent journal entries:
        SELECT id, trandate, tranid, memo FROM transaction
        WHERE type = 'Journal' AND trandate >= TO_DATE('2025-01-01','YYYY-MM-DD')
        ORDER BY trandate DESC

    GL detail for an account:
        SELECT t.trandate, t.tranid, t.memo, tl.debit, tl.credit, tl.account
        FROM transaction t
        JOIN transactionline tl ON tl.transaction = t.id
        WHERE tl.account = 1234
        ORDER BY t.trandate DESC

    Args:
        query: SuiteQL query string
        limit: Max rows to return (default 1000, max 1000)
        offset: Row offset for pagination (default 0)
    """
    try:
        result = client.suiteql(query, limit=limit, offset=offset)
        return json.dumps(result, indent=2)
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
