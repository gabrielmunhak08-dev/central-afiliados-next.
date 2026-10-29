import hashlib
import json
from unittest.mock import patch

import pytest

from shopee_affiliate import (
    SHOPEE_AFFILIATE_ENDPOINT,
    ShopeeAPIError,
    ShopeeAffiliateClient,
    build_authorization,
)


def test_build_authorization_matches_documented_signature():
    payload = '{"query":"{ test }"}'
    timestamp = 1_700_000_000
    expected_signature = hashlib.sha256(
        f"123{timestamp}{payload}secret".encode("utf-8")
    ).hexdigest()
    header = build_authorization("123", "secret", payload, timestamp=timestamp)
    assert header == (
        f"SHA256 Credential=123, Timestamp={timestamp}, "
        f"Signature={expected_signature}"
    )


def test_missing_credentials_fail_without_network_call():
    client = ShopeeAffiliateClient(app_id="", secret="")
    with pytest.raises(ShopeeAPIError, match="SHOPEE_APP_ID"):
        client.request("{ test }")


def test_request_sends_signed_json_and_returns_data():
    response = type("Response", (), {
        "__enter__": lambda self: self,
        "__exit__": lambda self, *args: False,
        "read": lambda self: b'{"data":{"ok":true}}',
    })()
    with patch("shopee_affiliate.urllib.request.urlopen", return_value=response) as mocked:
        client = ShopeeAffiliateClient(
            app_id="123", secret="secret", endpoint=SHOPEE_AFFILIATE_ENDPOINT
        )
        result = client.request("{ test }", variables={"limit": 1}, operation_name="Test")
    assert result == {"ok": True}
    request = mocked.call_args.args[0]
    assert request.full_url == SHOPEE_AFFILIATE_ENDPOINT
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("Authorization").startswith("SHA256 Credential=123, Timestamp=")
    sent = json.loads(request.data.decode("utf-8"))
    assert sent == {
        "query": "{ test }",
        "variables": {"limit": 1},
        "operationName": "Test",
    }


def test_graphql_errors_are_reported_without_echoing_secret():
    response = type("Response", (), {
        "__enter__": lambda self: self,
        "__exit__": lambda self, *args: False,
        "read": lambda self: b'{"errors":[{"message":"bad signature","extensions":{"code":10020}}]}',
    })()
    with patch("shopee_affiliate.urllib.request.urlopen", return_value=response):
        client = ShopeeAffiliateClient(app_id="123", secret="secret-that-must-not-leak")
        with pytest.raises(ShopeeAPIError) as exc:
            client.request("{ test }")
    assert "10020" in str(exc.value)
    assert "secret-that-must-not-leak" not in str(exc.value)
