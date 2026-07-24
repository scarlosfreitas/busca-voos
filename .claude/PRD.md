# PRD: Sistema de Monitoramento e Alerta de Passagens e Milhas

## 1. Visão Geral do Produto
Uma aplicação assíncrona de extração de dados que monitora diariamente os preços de passagens aéreas pagantes e emissões por milhas nas companhias Gol (e Smiles), Latam (e Latam Pass) e Azul (e Azul Fidelidade). O sistema opera com baixíssima frequência (uma execução diária) para minimizar riscos de bloqueio e envia alertas curados via Telegram quando os preços atingem parâmetros pré-definidos.

## 2. Objetivos e Escopo
*   **O que faz:** Busca passagens em rotas específicas previamente cadastradas; intercepta as requisições de rede (arquivos JSON) nativas das companhias aéreas usando Playwright; compara os valores com o limite aceitável; notifica via Telegram.
*   **O que NÃO faz:** Não realiza a compra/emissão automática das passagens; não roda em alta frequência (scans a cada minuto/hora estão fora do escopo para preservar os IPs e a integridade da extração).

## 3. Arquitetura Técnica Recomendada
A stack tecnológica é desenhada para resiliência. Para o MVP, o deploy é **local via Docker** (máquina própria/Proxmox), com Cloud Run/Functions permanecendo como opção futura de produção.

*   **Linguagem & IDE:** Python desenvolvido nativamente no Antigravity IDE.
*   **Extração (Scraping):** Playwright para navegação *headless*, execução de JavaScript e interceptação de tráfego de rede (XHR/Fetch).
*   **Evasão Anti-Bot:** `playwright-stealth` para ofuscação inicial, complementado por proxies residenciais para mascaramento de rede (integração já prevista no MVP, configurável via `.env`; provedor a ser definido — roda sem proxy até a contratação).
*   **Orquestração:** Dagster para agendamento do *job* diário, gestão de *retries* e monitoramento dos *assets* de dados. No MVP não há horário fixo definido (execução 1x/dia em horário arbitrário).
*   **Armazenamento:** **PostgreSQL** (via `docker-compose`), substituindo o DuckDB da proposta original, para persistência das métricas e histórico de buscas. Retenção de dados indefinida (sem expiração automática).
*   **Mensageria:** Integração direta com a API de Bots do Telegram (bot a ser criado via @BotFather).
*   **Infraestrutura:** Docker/`docker-compose` para conteinerização da aplicação, banco Postgres e dependências do navegador.

## 4. Estratégia Anti-Bot e Evasão
Devido às severas proteções em sites de companhias aéreas, a estratégia divide-se em duas camadas:

*   **Fase 1: Evasão em Nível de Software (MVP)**
    *   Uso do `playwright-stealth` para mascarar variáveis (como `navigator.webdriver`).
    *   Injeção de *user-agents* orgânicos e comportamentos simulados (atrasos aleatórios, interações humanas não padronizadas).
*   **Fase 2: Evasão em Nível de Rede (Produção)**
    *   Implementação de serviços de Proxy Residencial Rotativo (ex: Bright Data, Oxylabs) para disfarçar o IP do datacenter, pulverizando as requisições em redes domésticas padrão e evitando firewalls de borda (como Cloudflare/Akamai).

## 6. Requisitos de Configuração e Deploy
*   **Dockerfile:** Baseado em imagens oficiais da Microsoft (`mcr.microsoft.com/playwright/python`) contendo todas as bibliotecas de sistema operacional (C++) necessárias para os *browsers* do Playwright.
*   **Gestão de Segredos:** Tokens de Telegram, strings de proxy e rotas parametrizadas armazenadas externamente (Secret Manager ou `.env`), sem *hardcode*.
*   **Timeouts:** Definição de limites de tempo altos (5+ minutos) para suportar lentidão de página ou *retries* decorrentes de desafios de rede.

## 7. Escopo Detalhado do MVP
*   **Companhia:** Somente Gol (sem Latam/Azul e sem busca por milhas nesta fase).
*   **Rota:** Somente Macapá (MCP) → Brasília (BSB), com data de ida em **1º de setembro de 2026**. A volta (10/09) **não** é buscada nem alertada no MVP — apenas o trecho de ida.
*   **Cadastro de rotas:** No MVP a rota é fixa; o cadastro dinâmico de novas rotas/regras fica para uma iteração futura.
*   **Regra de alerta:** Sem limite de preço configurado inicialmente — o sistema notifica assim que qualquer voo elegível for encontrado na extração. Regras mais elaboradas (limite fixo, queda percentual) ficam para iterações futuras.
*   **Deduplicação:** O sistema mantém o último preço alertado por voo/rota no Postgres e só notifica novamente se houver mudança de preço (ou na primeira ocorrência).
*   **Mensagens sem resultado:** Se nenhum voo elegível for encontrado no dia, nenhuma mensagem é enviada.
*   **Falhas de execução:** Erros de extração (bloqueio, CAPTCHA, timeout) disparam uma notificação de erro via Telegram, além do registro em log.
*   **Agendamento:** Execução 1x/dia; horário ainda não fixado (arbitrário) nesta fase.
*   **Proxy residencial:** Integração prevista e configurável via `.env`, mas sem provedor contratado — o MVP roda sem proxy até a definição.
*   **Telegram:** Bot ainda não criado; será provisionado via @BotFather como parte da configuração inicial do projeto.

## 8. Critérios de Aceite (MVP)
Para validar a viabilidade técnica e a resiliência contra os sistemas anti-bot, o Mínimo Produto Viável (MVP) será considerado homologado quando cumprir integralmente os seguintes requisitos:

*   **Acesso e Evasão (Sem Login):** O script em Playwright deve conseguir acessar a interface pública de buscas do site da Gol, mantendo o status de usuário anônimo (sem autenticação), sem ser bloqueado por telas de CAPTCHA ou recusas de conexão na primeira execução.
*   **Execução da Rota Alvo:** O sistema deve inserir corretamente os parâmetros de busca para a origem **Macapá (MCP)** e o destino **Brasília (BSB)**, definindo a data de ida estritamente para **1º de setembro de 2026**.
*   **Captura via Interceptação:** A extração dos voos, horários e preços (pagantes) deve ocorrer com sucesso através da interceptação da resposta de rede (payload JSON interno da Gol), comprovando que não há dependência de *parsing* de elementos visuais do HTML.
*   **Persistência:** Os dados brutos e processados devem ser gravados corretamente no PostgreSQL.
*   **Entrega da Mensagem (Telegram):** Ao concluir a extração, o script deve compilar os voos encontrados e disparar com sucesso uma notificação via API do Telegram quando houver voo elegível. A mensagem recebida no aplicativo deve ser clara, contendo os horários, valores encontrados e a data da pesquisa.
*   **Notificação de Falha:** Em caso de erro na extração, uma mensagem de falha deve ser enviada via Telegram.
