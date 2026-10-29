# Integração com a Shopee Affiliate Open API

## Estado desta etapa

Esta branch adiciona apenas a camada de comunicação GraphQL assinada e testes unitários. Ainda não conecta a API às telas de Produtos e não altera o banco de dados.

## Credenciais

Configure as variáveis de ambiente no ambiente em que a Central será executada:

- `SHOPEE_APP_ID`: AppID mostrado na página Open API da Shopee.
- `SHOPEE_APP_SECRET`: senha/secret da API gerada pela Shopee — não é a senha de login da conta.

Não coloque os valores em arquivos versionados, templates, banco SQLite, mensagens, prints ou commits. Se as credenciais já foram expostas, redefina-as no painel da Shopee antes de conectar.

## Endpoint e assinatura

O cliente envia uma requisição HTTP POST para:

`https://open-api.affiliate.shopee.com.br/graphql`

O corpo JSON é serializado uma vez e a mesma string é usada na assinatura SHA-256:

`SHA256(AppID + timestamp Unix em segundos + corpo JSON exato + secret)`

O cabeçalho segue o formato:

`Authorization: SHA256 Credential=..., Timestamp=..., Signature=...`

O cliente não registra credenciais e substitui erros de transporte por mensagens genéricas. As operações GraphQL devem ser confirmadas no explorador/documentação da própria Shopee, pois a conta pode ter permissões específicas.

## Próximos passos

1. Executar os testes unitários sem chamar a API real.
2. Configurar as duas variáveis de ambiente localmente, sem as enviar no chat.
3. Fazer um teste controlado com uma consulta simples confirmada no explorador oficial.
4. Adicionar uma página privada de configuração/status e uma ação de teste na Central.
5. Implementar busca de ofertas e geração de links curtos apenas após confirmar os campos GraphQL aceitos pela API brasileira.

## Testes

Execute:

```bash
python -m pytest -q
```

Os testes da camada Shopee simulam a resposta HTTP e não precisam de credenciais reais.
