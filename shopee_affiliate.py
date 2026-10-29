"""Cliente mínimo e seguro para a Shopee Affiliate Open API (GraphQL).

As credenciais são lidas somente de variáveis de ambiente; nunca são gravadas
no banco, exibidas em páginas ou incluídas nas mensagens de erro.
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request


SHOPEE_AFFILIATE_ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"


class ShopeeAPIError(RuntimeError):
    """Erro de configuração, transporte ou resposta da API Shopee."""


def build_authorization(app_id, secret, payload, timestamp=None):
    """Gera o cabeçalho SHA256 assinado com o corpo JSON exato da requisição."""
    app_id = str(app_id or "").strip()
    secret = str(secret or "")
    if not app_id or not secret:
        raise ShopeeAPIError("Configure SHOPEE_APP_ID e SHOPEE_APP_SECRET no ambiente.")
    timestamp = int(time.time()) if timestamp is None else int(timestamp)
    signature_base = f"{app_id}{timestamp}{payload}{secret}".encode("utf-8")
    signature = hashlib.sha256(signature_base).hexdigest()
    return (
        f"SHA256 Credential={app_id}, Timestamp={timestamp}, "
        f"Signature={signature}"
    )


class ShopeeAffiliateClient:
    """Cliente GraphQL sem persistência de credenciais nem logs de segredos."""

    def __init__(self, app_id=None, secret=None, endpoint=None, timeout=20):
        self.app_id = (app_id if app_id is not None else os.environ.get("SHOPEE_APP_ID", "")).strip()
        self.secret = secret if secret is not None else os.environ.get("SHOPEE_APP_SECRET", "")
        self.endpoint = endpoint or SHOPEE_AFFILIATE_ENDPOINT
        self.timeout = timeout

    def request(self, query, variables=None, operation_name=None):
        if not self.app_id or not self.secret:
            raise ShopeeAPIError(
                "A API da Shopee ainda não está configurada. "
                "Defina SHOPEE_APP_ID e SHOPEE_APP_SECRET no ambiente."
            )
        if not isinstance(query, str) or not query.strip():
            raise ShopeeAPIError("A consulta GraphQL está vazia.")

        body = {"query": query}
        if variables is not None:
            body["variables"] = variables
        if operation_name:
            body["operationName"] = operation_name
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        timestamp = int(time.time())
        authorization = build_authorization(
            self.app_id, self.secret, payload, timestamp=timestamp
        )
        req = urllib.request.Request(
            self.endpoint,
            data=payload.encode("utf-8"),
            headers={
                "Authorization": authorization,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Não registrar o cabeçalho, payload nem credenciais.
            raise ShopeeAPIError(
                f"A Shopee respondeu com HTTP {exc.code}. Confira o acesso à API e tente novamente."
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ShopeeAPIError(
                "Não foi possível conectar à API da Shopee. Verifique a conexão e tente novamente."
            ) from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ShopeeAPIError("A resposta da API da Shopee não veio em JSON válido.") from None

        if not isinstance(result, dict):
            raise ShopeeAPIError("A resposta da API da Shopee tem um formato inesperado.")
        if result.get("errors"):
            # A mensagem da API é resumida e nunca inclui os cabeçalhos enviados.
            first_error = result["errors"][0] if result["errors"] else {}
            extensions = first_error.get("extensions") or {}
            code = extensions.get("code")
            suffix = f" (código {code})" if code is not None else ""
            raise ShopeeAPIError(
                "A Shopee recusou a consulta GraphQL" + suffix +
                ". Confira a operação e as permissões no explorador oficial da API."
            )
        if "data" not in result:
            raise ShopeeAPIError("A resposta da API da Shopee não contém dados.")
        return result["data"]



PRODUCT_OFFER_QUERY = """
query ProductOfferV2($keyword: String, $sortType: Int, $page: Int, $limit: Int) {
  productOfferV2(
    keyword: $keyword,
    sortType: $sortType,
    page: $page,
    limit: $limit
  ) {
    nodes {
      itemId
      commissionRate
      appExistRate
      appNewRate
      webExistRate
      webNewRate
      commission
      price
      sales
      imageUrl
      productName
      shopName
      productLink
      offerLink
      periodEndTime
      periodStartTime
      priceMin
      priceMax
      productCatIds
      ratingStar
      priceDiscountRate
      shopId
      shopType
      sellerCommissionRate
      shopeeCommissionRate
    }
    pageInfo {
      page
      limit
      hasNextPage
      scrollId
    }
  }
}
"""


def search_product_offers(client, keyword, page=1, limit=20, sort_type=5):
    """Pesquisa ofertas de produtos; não salva nada no banco automaticamente."""
    keyword = str(keyword or "").strip()
    if not keyword:
        raise ShopeeAPIError("Informe uma palavra-chave para pesquisar produtos.")
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise ShopeeAPIError("A página deve ser um número inteiro maior que zero.")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
        raise ShopeeAPIError("O limite deve ser um número inteiro entre 1 e 50.")
    if sort_type not in (1, 2, 3, 4, 5):
        raise ShopeeAPIError("A ordenação deve estar entre 1 e 5.")

    data = client.request(
        PRODUCT_OFFER_QUERY,
        variables={
            "keyword": keyword,
            "sortType": sort_type,
            "page": page,
            "limit": limit,
        },
        operation_name="ProductOfferV2",
    )
    offers = data.get("productOfferV2") if isinstance(data, dict) else None
    if not isinstance(offers, dict):
        raise ShopeeAPIError("A resposta não contém a lista de ofertas de produtos.")
    return offers
