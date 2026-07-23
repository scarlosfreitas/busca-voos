# Metodologias de projeto
* Spec-Driven Development
* Test-Driven Development (TDD) Adaptado
* Domain-Driven Design - DDD
* Arquitetura de Microserviços/Módulos

# Conceitos

**Documentação Viva:** Manter arquivos `.md` atualizados sobre convenções de código, estrutura do banco de dados e padrões do projeto.

**PRD (Product Requirements Document):** É a bússola do projeto. Ele define estritamente **o quê** precisa ser construído e **por que**, descrevendo o problema, as funcionalidades esperadas e os critérios de aceite (ex: "O sistema deve processar 400 mil arquivos diários"). Ele nunca entra no mérito de **como** o código será feito ou qual banco de dados será usado.

**Single Source of Truth (Fonte Única da Verdade):** Nunca repita uma regra de negócio na instrução (_prompt_ de sistema) do agente e no PRD. O _prompt_ deve instruir comportamentos (ex: "Você é um engenheiro de dados focado em performance. Sempre valide as regras lendo `docs/domain/` antes de codificar").

**Isolamento de Escopo:** O PRD não deve ter comandos Docker. O documento de arquitetura não deve ter regras de negócio. Se a legislação ou a regra fiscal mudar, você edita apenas um arquivo markdown, e todos os agentes passam a seguir a nova regra na próxima execução.

**Princípio da Injeção de Contexto Sob Demanda:** Ensine o agente a não tentar carregar tudo de uma vez. Ele deve buscar o arquivo de status primeiro e, a partir dele, saber quais arquivos específicos do projeto ele precisa ler para a tarefa atual.

# Arquitetura de pastas e artefatos

| Caminho / Arquivo(s)                                      | Propósito / Função para o Agente                                                                                                                                                            |
| :-------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **`/STATUS.md`**                                          | **Ponto de partida obrigatório.** Informa ao agente o estado atual do projeto, o que acabou de ser feito e qual a próxima prioridade.                                                       |
| **`.claude/PRD.md`**                                      | **O "Quê" e o "Porquê".** A bússola do projeto contendo os requisitos de produto, regras de negócio alto nível e critérios de aceite inequívocos.                                           |
| **`.claude/plan/*`**                                      | **O "Como" (Execução da IA).** Documentos com o roadmap de tarefas, sessões paralelas e orquestração gerados pelos agentes.                                                                 |
| **`.claude/guidelines/`**                                 | **Comportamento da IA.** Regras sobre como criar subagentes, como estruturar atualizações no PRD e como/quando utilizar ferramentas nativas da IDE.                                         |
| **`docs/domain/regras_negocio.md`**                       | **Fonte única da verdade do negócio.** O agente consulta este arquivo para entender lógicas, cálculos (ex: regras fiscais, contábeis) e validações de domínio.                              |
| **`docs/standards/`**<br>`architecture.md`, `style.md`    | **Engenharia e Código.** Padrões de arquitetura, regras de linting e estilo para garantir que o código gerado obedeça às diretrizes do projeto.                                             |
| **`.devcontainer/`**<br>`devcontainer.json`, `Dockerfile` | **Ambiente.** Mantém as regras de ambiente e infraestrutura isoladas para agentes DevOps e garante execução reprodutível conteinerizada.                                                    |
| **`/data/lakehouse/`**<br>`bronze/`, `silver/`, `gold/`   | **Armazenamento de Dados.** Estrutura para ingestão e refinamento de dados locais (ex: bases DuckDB ou Apache Iceberg). O PRD usa isso para definir onde os dados processados devem pousar. |
| **`scripts/`**<br>`setup.sh`, `test.sh`                   | **Ação.** Scripts executáveis para automações de terminal, como rodar testes em loop (TDD) ou preparar infraestrutura.                                                                      |
| **`src/`**<br>`(domain/, utils/)`                         | **Código de Produção Principal.** Lógica central da aplicação, isolada de ferramentas externas e orquestradores.                                                                            |
| **`test/`**<br>`*.spec.ts`, `*.test.py`                   | **Controle de Qualidade (TDD).** O agente executa esses testes em loop contínuo até o terminal aprovar a lógica criada nos diretórios `src/`.                                               |
