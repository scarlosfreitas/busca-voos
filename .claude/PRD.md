# PRD: Sistema de Monitoramento e Alerta de Passagens e Milhas

## 1. Visão Geral do Produto
Uma aplicação assíncrona de extração de dados que monitora diariamente os preços de passagens aéreas pagantes e emissões por milhas nas companhias Gol (e Smiles), Latam (e Latam Pass) e Azul (e Azul Fidelidade). O sistema opera com baixíssima frequência (uma execução diária) para minimizar riscos de bloqueio e envia alertas curados via Telegram quando os preços atingem parâmetros pré-definidos.

## 2. Objetivos e Escopo
*   **O que faz:** Busca passagens em rotas específicas previamente cadastradas; intercepta as requisições de rede (arquivos JSON) nativas das companhias aéreas usando Playwright; compara os valores com o limite aceitável; notifica via Telegram.
*   **O que NÃO faz:** Não realiza a compra/emissão automática das passagens; não roda em alta frequência (scans a cada minuto/hora estão fora do escopo para preservar os IPs e a integridade da extração).

## 3. Arquitetura Técnica Recomendada
A stack tecnológica é desenhada para resiliência, permitindo o desenvolvimento otimizado e facilitando o deploy via Cloud Code (ex: Cloud Run/Functions) ou infraestrutura local (Proxmox).

*   **Linguagem & IDE:** Python desenvolvido nativamente no Antigravity IDE.
*   **Extração (Scraping):** Playwright para navegação *headless*, execução de JavaScript e interceptação de tráfego de rede (XHR/Fetch).
*   **Evasão Anti-Bot:** `playwright-stealth` para ofuscação inicial, complementado por proxies residenciais para mascaramento de rede.
*   **Orquestração:** Dagster para agendamento do *job* diário, gestão de *retries* e monitoramento dos *assets* de dados.
*   **Armazenamento (Data Lakehouse):** DuckDB para armazenamento analítico rápido e local das métricas e históricos.
*   **Mensageria:** Integração direta com a API de Bots do Telegram.
*   **Infraestrutura:** Docker para conteinerização de toda a aplicação e dependências do navegador.

## 4. Estratégia Anti-Bot e Evasão
Devido às severas proteções em sites de companhias aéreas, a estratégia divide-se em duas camadas:

*   **Fase 1: Evasão em Nível de Software (MVP)**
    *   Uso do `playwright-stealth` para mascarar variáveis (como `navigator.webdriver`).
    *   Injeção de *user-agents* orgânicos e comportamentos simulados (atrasos aleatórios, interações humanas não padronizadas).
*   **Fase 2: Evasão em Nível de Rede (Produção)**
    *   Implementação de serviços de Proxy Residencial Rotativo (ex: Bright Data, Oxylabs) para disfarçar o IP do datacenter, pulverizando as requisições em redes domésticas padrão e evitando firewalls de borda (como Cloudflare/Akamai).

## 5. Fluxo de Execução (Pipeline de Dados)
A rotina diária será orquestrada adotando a arquitetura Medallion:

1.  **Ingestão (Camada Bronze):**
    *   Dagster aciona o script Python.
    *   Playwright acessa a interface de busca, intercepta a resposta JSON nativa da API da companhia e salva o dado bruto (raw) no DuckDB.
2.  **Processamento (Camada Prata/Ouro):**
    *   Tratamento dos JSONs, isolando valores limpos (Reais e Pontos/Milhas).
    *   Cruzamento dos dados com as regras de negócio de limite de valor.
3.  **Distribuição (Alerta):**
    *   Verificação na Camada Ouro: Se a passagem atingir o preço/milhagem alvo, os dados são compilados.
    *   Disparo via Telegram com detalhes (Cia, Data, Trecho, Preço/Milhas, Link) e encerramento do *job*.

## 6. Requisitos de Configuração e Deploy
*   **Dockerfile:** Baseado em imagens oficiais da Microsoft (`mcr.microsoft.com/playwright/python`) contendo todas as bibliotecas de sistema operacional (C++) necessárias para os *browsers* do Playwright.
*   **Gestão de Segredos:** Tokens de Telegram, strings de proxy e rotas parametrizadas armazenadas externamente (Secret Manager ou `.env`), sem *hardcode*.
*   **Timeouts:** Definição de limites de tempo altos (5+ minutos) para suportar lentidão de página ou *retries* decorrentes de desafios de rede.

## 7. Critérios de Aceite (MVP)
Para validar a viabilidade técnica e a resiliência contra os sistemas anti-bot, o Mínimo Produto Viável (MVP) será considerado homologado quando cumprir integralmente os seguintes requisitos:

*   **Acesso e Evasão (Sem Login):** O script em Playwright deve conseguir acessar a interface pública de buscas do site da Gol, mantendo o status de usuário anônimo (sem autenticação), sem ser bloqueado por telas de CAPTCHA ou recusas de conexão na primeira execução.
*   **Execução da Rota Alvo:** O sistema deve inserir corretamente os parâmetros de busca para a origem **Brasília (BSB)** e um destino padrão definido no código, definindo a data de ida estritamente para **1º de setembro de 2026**.
*   **Captura via Interceptação:** A extração dos voos, horários e preços (pagantes) deve ocorrer com sucesso através da interceptação da resposta de rede (payload JSON interno da Gol), comprovando que não há dependência de *parsing* de elementos visuais do HTML.
*   **Entrega da Mensagem (Telegram):** Ao concluir a extração, o script deve compilar os voos encontrados e disparar com sucesso uma notificação via API do Telegram. A mensagem recebida no aplicativo deve ser clara, contendo os horários, valores encontrados e a data da pesquisa.
