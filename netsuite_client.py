import os
from requests_oauthlib import OAuth1
import requests


class NetSuiteAPIError(Exception):
    """Raised when the NetSuite API returns an HTTP error response."""

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"NetSuite API error {status_code}: {body}")


class NetSuiteClient:
    def __init__(self):
        self.account_id = os.environ["NETSUITE_ACCOUNT_ID"]
        self.base_url = f"https://{self.account_id.replace('_', '-').lower()}.suitetalk.api.netsuite.com/services/rest"
        self.auth = OAuth1(
            client_key=os.environ["NETSUITE_CONSUMER_KEY"].strip(),
            client_secret=os.environ["NETSUITE_CONSUMER_SECRET"].strip(),
            resource_owner_key=os.environ["NETSUITE_TOKEN_ID"].strip(),
            resource_owner_secret=os.environ["NETSUITE_TOKEN_SECRET"].strip(),
            signature_method="HMAC-SHA256",
            realm=self.account_id.upper().replace("-", "_"),
        )

    def _raise_for_status(self, response: requests.Response) -> None:
        """Raise NetSuiteAPIError with the full response body on HTTP errors."""
        try:
            response.raise_for_status()
        except requests.HTTPError:
            raise NetSuiteAPIError(response.status_code, response.text)

    def suiteql(self, query: str, limit: int = 1000, offset: int = 0) -> dict:
        url = f"{self.base_url}/query/v1/suiteql"
        headers = {"Content-Type": "application/json", "Prefer": "transient"}
        payload = {"q": query}
        params = {"limit": limit, "offset": offset}
        response = requests.post(url, json=payload, params=params, headers=headers, auth=self.auth)
        self._raise_for_status(response)
        return response.json()

    def get_record(self, record_type: str, record_id: str, fields: list[str] | None = None) -> dict:
        url = f"{self.base_url}/record/v1/{record_type}/{record_id}"
        params = {}
        if fields:
            params["fields"] = ",".join(fields)
        response = requests.get(url, params=params, auth=self.auth)
        self._raise_for_status(response)
        return response.json()

    def list_record_types(self) -> dict:
        url = f"{self.base_url}/record/v1/metadata-catalog"
        response = requests.get(url, auth=self.auth, headers={"Accept": "application/json"})
        self._raise_for_status(response)
        return response.json()
