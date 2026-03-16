"""
Shared pytest configuration for netsuite-mcp tests.

Sets dummy environment variables so that NetSuiteClient (and server.py)
can be imported without real credentials.  Using setdefault ensures that
values already present in the environment (e.g. from a real .env file) are
never overwritten.
"""
import os

os.environ.setdefault("NETSUITE_ACCOUNT_ID", "test_account")
os.environ.setdefault("NETSUITE_CONSUMER_KEY", "ck")
os.environ.setdefault("NETSUITE_CONSUMER_SECRET", "cs")
os.environ.setdefault("NETSUITE_TOKEN_ID", "ti")
os.environ.setdefault("NETSUITE_TOKEN_SECRET", "ts")
