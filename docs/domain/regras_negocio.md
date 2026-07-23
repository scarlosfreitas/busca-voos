# Regras de negócio — fonte única da verdade

> **Single Source of Truth do domínio.** Os agentes consultam este arquivo para entender lógicas,
> cálculos e validações do negócio antes de codificar. Nunca duplique uma regra aqui e no _prompt_
> de sistema de um agente: o _prompt_ instrui **comportamento** ("valide as regras lendo
> `docs/domain/` antes de codificar"); este arquivo guarda **as regras**.

Se uma regra (fiscal, contábil, de validação, etc.) mudar, edite **apenas** este arquivo — todos os
agentes passam a seguir a nova regra na próxima execução.

## Glossário do domínio

_(Termos e entidades do negócio, com definição inequívoca.)_

## Regras e cálculos

_(Uma seção por regra: entrada, lógica/cálculo, saída esperada, casos de borda. Detalhada o
suficiente para virar teste.)_

## Validações

_(Invariantes que os dados/entidades precisam sempre satisfazer.)_
