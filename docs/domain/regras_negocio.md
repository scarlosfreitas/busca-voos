# Regras de negócio — fonte única da verdade

> **Single Source of Truth do domínio.** Os agentes consultam este arquivo para entender lógicas,
> cálculos e validações do negócio antes de codificar. Nunca duplique uma regra aqui e no _prompt_
> de sistema de um agente: o _prompt_ instrui **comportamento** ("valide as regras lendo
> `docs/domain/` antes de codificar"); este arquivo guarda **as regras**.

Se uma regra (fiscal, contábil, de validação, etc.) mudar, edite **apenas** este arquivo — todos os
agentes passam a seguir a nova regra na próxima execução.

## Glossário do domínio

| Termo | Definição |
| :--- | :--- |
| **Rota monitorada** | Par origem/destino + data de ida cadastrado para busca diária. No MVP, fixa: Macapá (MCP) → Brasília (BSB), ida em 01/09/2026. |
| **Execução (run)** | Uma rodada completa do job diário: acessa o site da Gol, busca a rota monitorada, intercepta o payload de rede, persiste os dados e (se aplicável) dispara alerta. |
| **Voo capturado** | Cada opção de voo retornada pela interceptação de rede (payload JSON da Gol) para a rota/data monitorada, com horário e preço pagante. |
| **Voo elegível** | Voo capturado que satisfaz a regra de elegibilidade vigente (ver [Regra de Elegibilidade](#regra-de-elegibilidade)) e portanto é candidato a alerta. |
| **Alerta** | Mensagem enviada ao Telegram informando um voo elegível recém-detectado ou com preço alterado. |
| **Notificação de falha** | Mensagem enviada ao Telegram quando a execução não consegue concluir a extração (bloqueio, CAPTCHA, timeout, erro inesperado). |
| **Camada Bronze** | Dado bruto (raw) do payload JSON interceptado, persistido no PostgreSQL sem transformação. |
| **Camada Prata** | Dado tratado: valores de preço e horário normalizados/tipados a partir do bronze. |
| **Camada Ouro** | Dado avaliado contra as regras de negócio (elegibilidade, deduplicação), pronto para virar alerta. |
| **Último preço alertado** | Para um dado voo (identificado por rota + data + número do voo), o valor de preço da última vez em que um alerta foi efetivamente enviado. Base para a regra de deduplicação. |
| **Identificador do voo** | Chave de deduplicação: rota + data + **número do voo** (ex: G3-1234), conforme retornado no payload da Gol. |
| **Parâmetros de busca** | Configuração fixa da simulação de busca: 1 adulto, classe econômica. Não varia no MVP. |

## Regras e cálculos

### Regra de Execução
- **Entrada:** nenhuma (job agendado).
- **Lógica:** o job roda **1x por dia**, em horário arbitrário (sem horário fixo definido no MVP). Não há re-execução automática no mesmo dia após uma execução bem-sucedida.
- **Saída esperada:** um registro de execução (bronze) por rota monitorada por dia.
- **Caso de borda:** se o job não rodar em um dia (ex: máquina desligada), não há mecanismo de compensação (catch-up) no MVP — a lacuna simplesmente não gera dado para aquele dia.

### Regra de Elegibilidade
- **Entrada:** lista de voos capturados na execução, para a rota monitorada.
- **Lógica:** no MVP, **todo voo capturado com sucesso é elegível** — não há limite de preço (teto) configurado. A regra existe como conceito extensível (limite fixo, queda percentual) para iterações futuras, mas hoje é uma função identidade: captura → elegível.
- **Saída esperada:** todos os voos capturados da execução seguem para a etapa de deduplicação.
- **Caso de borda:** nenhum voo capturado (ex: rota sem disponibilidade) → nenhum voo elegível, nenhuma mensagem é enviada (ver Regra de Notificação).

### Regra de Deduplicação
- **Entrada:** voo elegível da execução atual; último preço alertado para o mesmo voo (identificador do voo = rota + data + número do voo) no Postgres.
- **Lógica:** compara o preço atual (final, com taxas — o mesmo valor exibido no site) com o último preço alertado.
  - Se não existe alerta anterior para aquele voo → **notifica** (primeira ocorrência).
  - Se existe e o preço mudou, **por qualquer valor** (sem piso mínimo — R$ 0,01 já conta) → **notifica** e atualiza o "último preço alertado".
  - Se existe e o preço é exatamente igual → **não notifica**.
- **Saída esperada:** subconjunto de voos elegíveis que efetivamente geram alerta nesta execução.

### Regra de Notificação (Telegram)
- **Entrada:** lista de voos que passaram na deduplicação.
- **Lógica:**
  - Lista não vazia → compila e envia **uma mensagem** por execução, contendo Cia, Data, Trecho, horário(s), preço(s) e data da pesquisa.
  - Lista vazia (nenhum voo elegível novo/alterado) → **nenhuma mensagem é enviada**.
  - Falha na extração (bloqueio, CAPTCHA, timeout, exceção não tratada) → dispara **notificação de erro** separada, independente da notificação de voos.
- **Saída esperada:** 0 ou 1 mensagem de alerta de voos + 0 ou 1 mensagem de erro por execução (mutuamente exclusivas na prática, já que uma execução com falha não chega a produzir voos elegíveis).

### Regra de Persistência
- **Entrada:** dado bruto (bronze), dado tratado (prata), avaliação de elegibilidade/deduplicação (ouro).
- **Lógica:** todas as camadas são persistidas no PostgreSQL, sem expiração automática (retenção indefinida).
- **Saída esperada:** histórico completo e consultável de todas as execuções, mesmo as que não geraram alerta.

## Validações

- Todo voo capturado deve conter, no mínimo: companhia, número do voo, origem, destino, data do voo, horário de partida, preço final (valor numérico, com taxas incluídas, e moeda).
- A rota da execução deve corresponder exatamente à rota monitorada cadastrada (MCP → BSB, ida 01/09/2026 no MVP) — dados de outras rotas/datas não devem ser persistidos como resultado válido da execução.
- A busca deve sempre simular 1 adulto em classe econômica; qualquer preço capturado fora dessa configuração é inválido para os fins deste MVP.
- O preço capturado deve ser um valor numérico positivo; captura com preço nulo/zero/negativo é tratada como falha de extração daquele voo, não como voo elegível.
- O número do voo é obrigatório para persistência na camada ouro — sem ele não é possível aplicar a regra de deduplicação.
- Uma execução só é considerada "bem-sucedida" (para fins de não disparar notificação de erro) se a interceptação de rede retornar e for possível persistir ao menos a camada bronze — mesmo que zero voos sejam elegíveis.
