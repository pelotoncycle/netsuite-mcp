import logging
import os
from requests_oauthlib import OAuth1
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import requests

logger = logging.getLogger(__name__)

# (connect_timeout, read_timeout) in seconds.
# connect_timeout: time to establish the TCP connection.
# read_timeout: time to wait for the server to send a response.
# SuiteQL queries can be slow on a loaded instance; 120s read timeout is
# generous but still prevents infinite hangs from tying up the connection.
DEFAULT_TIMEOUT = (10, 120)

# Retry on transient server-side and rate-limit errors.
# backoff_factor=2 means waits of 2s, 4s, 8s between attempts,
# giving NetSuite time to recover rather than immediately hammering it again.
DEFAULT_RETRY = Retry(
    total=3,
    backoff_factor=2,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"],
    raise_on_status=False,
)

# Tables that support ID-to-name resolution and their name column.
_RESOLVABLE_TYPES: dict[str, tuple[str, str]] = {
    "vendor":      ("vendor",          "companyname"),
    "customer":    ("customer",        "companyname"),
    "employee":    ("employee",        "firstname || ' ' || lastname"),
    "account":     ("account",         "fullname"),
    "department":  ("department",      "name"),
    "location":    ("location",        "name"),
    "subsidiary":  ("subsidiary",      "name"),
}


class NetSuiteAPIError(Exception):
    """Raised when the NetSuite API returns an HTTP error response."""

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"NetSuite API error {status_code}: {body}")


class NetSuiteClient:
    def __init__(self, timeout: tuple[int, int] = DEFAULT_TIMEOUT, retry: Retry = DEFAULT_RETRY):
        self.account_id = os.environ["NETSUITE_ACCOUNT_ID"]
        self.base_url = f"https://{self.account_id.replace('_', '-').lower()}.suitetalk.api.netsuite.com/services/rest"
        self.timeout = timeout
        auth = OAuth1(
            client_key=os.environ["NETSUITE_CONSUMER_KEY"].strip(),
            client_secret=os.environ["NETSUITE_CONSUMER_SECRET"].strip(),
            resource_owner_key=os.environ["NETSUITE_TOKEN_ID"].strip(),
            resource_owner_secret=os.environ["NETSUITE_TOKEN_SECRET"].strip(),
            signature_method="HMAC-SHA256",
            realm=self.account_id.upper().replace("-", "_"),
        )
        self.session = requests.Session()
        self.session.auth = auth
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        logger.debug("NetSuiteClient initialised (account=%s)", self.account_id)

    def _raise_for_status(self, response: requests.Response) -> None:
        """Raise NetSuiteAPIError with the full response body on HTTP errors."""
        try:
            response.raise_for_status()
        except requests.HTTPError:
            logger.error(
                "NetSuite API error: status=%s url=%s body=%s",
                response.status_code,
                response.url,
                response.text[:500],
            )
            raise NetSuiteAPIError(response.status_code, response.text)

    def suiteql(self, query: str, limit: int = 100, offset: int = 0) -> dict:
        url = f"{self.base_url}/query/v1/suiteql"
        headers = {"Content-Type": "application/json", "Prefer": "transient"}
        payload = {"q": query}
        params = {"limit": limit, "offset": offset}
        logger.debug("SuiteQL query limit=%s offset=%s: %.200s", limit, offset, query)
        response = self.session.post(url, json=payload, params=params, headers=headers, timeout=self.timeout)
        self._raise_for_status(response)
        result = response.json()
        logger.debug("SuiteQL returned count=%s hasMore=%s", result.get("count"), result.get("hasMore"))
        return result

    def get_record(self, record_type: str, record_id: str, fields: list[str] | None = None) -> dict:
        url = f"{self.base_url}/record/v1/{record_type}/{record_id}"
        params = {}
        if fields:
            params["fields"] = ",".join(fields)
        logger.debug("get_record type=%s id=%s fields=%s", record_type, record_id, fields)
        response = self.session.get(url, params=params, timeout=self.timeout)
        self._raise_for_status(response)
        return response.json()

    def list_record_types(self) -> dict:
        url = f"{self.base_url}/record/v1/metadata-catalog"
        logger.debug("list_record_types")
        response = self.session.get(url, headers={"Accept": "application/json"}, timeout=self.timeout)
        self._raise_for_status(response)
        return response.json()

    def resolve_ids(self, record_type: str, ids: list[int]) -> dict:
        """
        Resolve a list of internal IDs to human-readable names for a given record type.

        Returns a dict mapping str(id) -> name.
        Raises ValueError for unsupported record types.
        """
        if record_type not in _RESOLVABLE_TYPES:
            supported = sorted(_RESOLVABLE_TYPES.keys())
            raise ValueError(
                f"Unsupported record_type '{record_type}'. "
                f"Supported types: {supported}"
            )
        if not ids:
            return {}

        table, name_expr = _RESOLVABLE_TYPES[record_type]
        id_list = ", ".join(str(i) for i in ids)
        query = f"SELECT id, {name_expr} AS name FROM {table} WHERE id IN ({id_list})"
        logger.debug("resolve_ids type=%s ids=%s", record_type, ids)
        result = self.suiteql(query, limit=len(ids))
        return {str(row["id"]): row.get("name") for row in result.get("items", [])}
