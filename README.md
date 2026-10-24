# Central de Afiliados — Next

Nova aplicação independente para organizar produtos afiliados, preparar conteúdo para Instagram e acompanhar resultados. Projeto mobile-first, com foco inicial em execução local no Android/Termux.

## Estado atual

A fundação inicial está sendo organizada. A aplicação ainda não está pronta para uso público e não foi validada no aparelho.

## Primeiros arquivos

- `docs/PLANO.md`: escopo, regras, arquitetura e etapas do projeto.
- `app.py`: fábrica Flask, rota inicial e verificação de saúde.
- `templates/` e `static/`: interface inicial responsiva, tema escuro e laranja.
- `tests/test_app.py`: testes básicos da rota de saúde e do painel.
- `.gitignore`: exclui ambientes, bancos locais, uploads e segredos.

## Requisitos

Python 3.11+ recomendado. Instale dependências com `pip install -r requirements.txt`.

Defina `CENTRAL_SECRET_KEY` por variável de ambiente antes de iniciar. Para executar localmente, use `python app.py`. O servidor de desenvolvimento é apenas para testes locais, não para produção.

## Princípios

- Não importar dados da versão antiga.
- Não inventar preços, descontos, tendências ou métricas.
- Não versionar segredos ou chaves de API.
- Testar e fazer backup antes de atualizações relevantes.
- Não ativar publicação automática no Instagram sem integração oficial verificada.
