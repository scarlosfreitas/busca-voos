# CLAUDE.md

> Instruções persistentes para qualquer agente (Claude Code ou subagente) trabalhando neste
> repositório. Este arquivo define **comportamento e roteamento de contexto** — não duplica regra
> de negócio nem padrão técnico, que vivem em arquivos próprios (ver seção 2).

## 1. Fluxo de Trabalho e Consciência de Estado

Antes de iniciar qualquer nova tarefa ou alterar código, você **DEVE**:

1. Ler `/STATUS.md` para entender onde o projeto parou e qual é a prioridade atual.
2. Ler `/LESSONS_LEARNED.md`, se existir, para evitar repetir erros já conhecidos (bugs
   resolvidos, limitações de biblioteca, armadilhas de ambiente). Se o arquivo ainda não existe,
   não há lições registradas — siga em frente normalmente.
3. Se a tarefa envolver iniciar uma nova funcionalidade, **pergunte qual é o PRD da feature** e
   leia o arquivo correspondente em `docs/features/`. Nunca deduza o escopo de uma feature nova
   por conta própria. Essa pasta ainda não existe no repositório — ela é criada quando a primeira
   feature pós-MVP precisar de um PRD próprio; até lá, o escopo vigente é inteiramente o descrito
   em `.claude/PRD.md`.

Aplique **injeção de contexto sob demanda**: carregue apenas os arquivos que a tarefa atual exige,
em vez de ler o repositório inteiro a cada sessão.

## 2. Roteamento de Contexto (onde encontrar a verdade)

Não deduza lógica de negócio ou arquitetura — consulte sempre a fonte correta:

| Pergunta | Fonte |
| :--- | :--- |
| Qual o propósito do produto, o que está dentro/fora do escopo do MVP, critérios de aceite? | `.claude/PRD.md` |
| Qual a regra de negócio (elegibilidade, deduplicação, notificação, persistência)? | `docs/domain/regras_negocio.md` — fonte única da verdade do domínio |
| Qual o padrão técnico (estrutura de `src/`, schemas bronze/silver/gold no Postgres, ferramental Python, containerização, testes)? | `docs/standards/architecture.md` |
| Como estruturar comunicação/orquestração entre subagentes? | `.claude/guidelines/` (ainda não existe — criar quando a primeira regra concreta de orquestração de agentes surgir; até lá, siga as definições de `tools`/`model` em `.claude/agents/*.md`) |
| Qual o roadmap de tarefas em andamento? | `.claude/plans/` |

Se uma regra de negócio mudar, o único arquivo a editar é `docs/domain/regras_negocio.md`. Se um
padrão técnico mudar, o único arquivo é `docs/standards/architecture.md`. Nunca duplique essas
regras dentro deste CLAUDE.md ou dentro do prompt de um subagente.

## 3. Padrões de Código e Desenvolvimento

Além do ferramental já definido em `docs/standards/architecture.md` (uv, ruff, alembic,
estrutura de módulos `src/domain`, `extraction`, `persistence`, `notification`, `orchestration`,
`utils`):

*   **Idioma:** código (identificadores, comentários, docstrings) em **inglês**, seguindo a
    convenção usual do ecossistema Python/OSS. Documentação de negócio e de produto (PRD, regras
    de negócio, arquitetura, este CLAUDE.md) permanece em **português**.
*   **Commits:** [Conventional Commits](https://www.conventionalcommits.org/) —
    `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`. O histórico do repositório já segue
    esse padrão; mantenha a consistência.
*   **Branches:** trunk-based — trabalho comitado diretamente em `main`. Não é obrigatório abrir
    feature branch/PR para este projeto solo; se uma mudança for grande/arriscada o suficiente
    para justificar isolamento, decida pontualmente, mas o padrão é commit direto.
*   **Regra de negócio (`src/domain/`) é rastreável 1:1** com `docs/domain/regras_negocio.md` — ao
    implementar uma regra, referencie mentalmente a seção correspondente do arquivo, mas não copie
    o texto da regra como comentário no código (evite duplicação que pode divergir).

## 4. Ambiente e Execução

*   Não altere o ambiente local diretamente a menos que instruído. Toda regra de ambiente,
    dependência ou setup de conteinerização deve ser refletida nos arquivos dentro de
    `.devcontainer/` (`Dockerfile`, `docker-compose.yml`, `devcontainer.json`) — hoje a única
    infraestrutura do projeto, cobrindo aplicação + PostgreSQL local via `docker-compose`.
*   Não existe `/infra/` nem manifests de K3s/Proxmox no MVP. Essa camada é uma evolução futura de
    produção (mencionada no PRD como opção pós-MVP) — não crie esses arquivos a menos que
    explicitamente solicitado.
*   Se precisar preparar ou validar o ambiente, execute os scripts disponíveis em `scripts/`
    (ex: `scripts/clean.sh`, `scripts/plugins.sh`, ou os que vierem a existir como
    `scripts/setup.sh`/`scripts/test.sh`) e analise o output (STDOUT/STDERR) antes de propor
    correções.

## 5. Diretriz de Conclusão e Registro

Após finalizar uma tarefa com sucesso:

1. Atualize `/STATUS.md`: descreva o que foi feito, atualize "Feito recentemente" e defina a
   próxima prioridade (indicando qual trilha de agentes atende — `plan-dev`/`run-dev`/`test-ops`
   para código, `plan-ops`/`run-ops` para infra).
2. Se você resolveu um bug complexo ou descobriu uma limitação de biblioteca/ambiente (ex:
   conflito de dependência, comportamento inesperado do Playwright/stealth, peculiaridade do
   Postgres em container), registre uma entrada clara em `/LESSONS_LEARNED.md` (crie o arquivo se
   ainda não existir).
