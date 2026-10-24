# Central de Afiliados — plano oficial

## Objetivo
Construir uma aplicação independente para organizar produtos afiliados, preparar conteúdo para Instagram, planejar publicações e acompanhar resultados. O desenvolvimento será mobile-first e pensado para uso no Android/Termux, com possibilidade de hospedagem futura.

## Regras do projeto
- Não importar produtos, fotos, banco de dados ou configurações da aplicação antiga.
- Não inventar preços, descontos, comissões, tendências ou resultados.
- Diferenciar estimativas de valores confirmados.
- Não publicar automaticamente no Instagram sem integração oficial validada e autorização explícita.
- Não guardar senhas em texto puro nem incluir chaves de API no Git.
- Fazer backup antes de atualizações de banco ou aplicação.
- Testar cada etapa antes de declarar que está pronta.
- Priorizar soluções gratuitas e informar custos de serviços externos antes de ativá-los.

## Módulos planejados
1. Painel: produtos cadastrados, conteúdos preparados, publicações e métricas disponíveis.
2. Catálogo: nome, categoria, preço, link de afiliado em campo próprio, comissão estimada, notas e até 10 fotos originais.
3. Biblioteca criativa: imagens geradas separadas das fotos originais, com histórico e associação ao produto.
4. Preparação de conteúdo: Story 9:16, Feed com formatos configuráveis, legenda, hashtags e chamada para ação.
5. Calendário: planejamento semanal, tipo de conteúdo e estados Ideia, Em andamento, Pronto, Publicado e Pausado.
6. Compartilhamento assistido: preparar material para compartilhar no Android; a revisão final, adesivo de link, música e publicação ficam sob controle do usuário.
7. Métricas: cliques, pedidos, vendas e comissões, com origem e estado identificados.
8. Análise de oportunidades: priorização com base em dados reais disponíveis e data da fonte; sem fingir acesso a rankings privados da Shopee.
9. Configurações: preferências, modelos de prompt, formatos, integrações, exportação e backups.
10. Atualização segura: versão, testes, backup e possibilidade de reversão.

## Arquitetura inicial
- Python + Flask para a aplicação web.
- SQLite para começar no aparelho, com caminho de dados fora dos arquivos de código.
- Templates e CSS separados da lógica.
- Configurações sensíveis por variáveis de ambiente, nunca versionadas.
- Testes automatizados para rotas e funções críticas.

## Etapas
1. Especificação e estrutura limpa.
2. Fundação Flask, configuração, banco e testes.
3. Autenticação segura e configuração inicial.
4. Catálogo e fotos.
5. Calendário e biblioteca de conteúdo.
6. Integração configurável com provedor de imagens, com custos e limites explícitos.
7. Compartilhamento assistido no Instagram.
8. Métricas e análise.
9. Backups, atualizador, testes de segurança e validação no Android.

## Estado
Planejamento registrado. Nenhuma integração externa, publicação, implantação pública ou teste em aparelho foi concluído ainda.
