# Central de Afiliados — Next

Nova aplicação independente para organizar produtos afiliados, preparar conteúdo para Instagram e acompanhar resultados. Projeto mobile-first, pensado primeiro para execução local no Android/Termux.

## Estado atual

A base inicial inclui configuração do primeiro usuário, login, proteção CSRF, esquema SQLite e painel privado. Ainda não está pronta para uso público e não foi validada no aparelho Android. Os módulos de catálogo, imagens, calendário, conteúdo e resultados ainda precisam ser implementados.

## Arquivos principais

- `docs/PLANO.md`: escopo, regras, arquitetura e etapas do projeto.
- `app.py`: aplicação Flask, configuração inicial, login, proteção de formulários e criação do banco local.
- `templates/` e `static/`: telas responsivas com tema escuro e detalhes em laranja.
- `tests/test_app.py`: testes da configuração inicial, autenticação e proteção CSRF.
- `.github/workflows/tests.yml`: execução automatizada dos testes no GitHub Actions.
- `.gitignore`: exclui ambientes, bancos locais, uploads e segredos.

## Requisitos e execução local

Python 3.11+ recomendado. Instale as dependências com:

```bash
python -m pip install -r requirements.txt
```

Defina uma chave secreta forte na variável de ambiente `CENTRAL_SECRET_KEY` antes de executar `python app.py`. Não use uma chave de exemplo em uma instalação real. O servidor de desenvolvimento fica limitado a `127.0.0.1`; não o exponha diretamente à internet.

Na primeira abertura, acesse `/configurar` e crie um nome de usuário e uma senha com pelo menos 12 caracteres. A configuração inicial fica bloqueada depois que o primeiro usuário é criado. Não existe senha padrão. Guarde suas credenciais: não há recuperação de senha implementada nesta fase.

## Segurança e limitações atuais

- Senhas são armazenadas como hash; formulários POST exigem token CSRF.
- O banco SQLite é criado no diretório local `instance` por padrão.
- Esta versão não tem catálogo funcional nem upload de fotos ainda.
- A configuração do cookie seguro deve ser revisada para uma implantação HTTPS.
- Testes foram escritos, mas só devem ser considerados aprovados depois de uma execução confirmada no CI e/ou no ambiente local.
- Não há integração validada com API da Shopee nem publicação automática no Instagram.

## Princípios

- Não importar dados da versão antiga.
- Não inventar preços, descontos, tendências ou métricas.
- Não versionar segredos ou chaves de API.
- Testar e fazer backup antes de atualizações relevantes.
- Não ativar publicação automática no Instagram sem integração oficial verificada.
