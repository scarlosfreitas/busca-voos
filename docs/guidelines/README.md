# `docs/guidelines/` — diretrizes de trabalho

Regras sobre **como** os agentes trabalham (não sobre o produto — isso é o `.claude/PRD.md`, nem
sobre regra de negócio — isso é `docs/domain/`). Ponto de extensão para diretrizes como:

- como e quando criar/orquestrar subagentes;
- como estruturar atualizações no `.claude/PRD.md` e no `STATUS.md`;
- como/quando usar ferramentas nativas da IDE;
- padrões de commit, de PR e de registro de planos em `.claude/plans/`.

**Isolamento de escopo:** estes arquivos descrevem comportamento do agente. Não coloque aqui regra
de negócio (`docs/domain/`) nem padrão de código/arquitetura (`docs/standards/`). Assim, mudar uma
diretriz de trabalho não obriga a mexer no PRD nem nas regras de domínio.

Preencha com um arquivo por diretriz (ex.: `subagentes.md`, `commits.md`) conforme o projeto pedir.

## `prd-good-pratices.md`

Referência de metodologia e arquitetura de pastas, **consultada ao gerar/escrever um novo
`.claude/PRD.md`**. É a base das convenções deste kit; mantida no projeto gerado como guia para
quem for preencher o PRD.
