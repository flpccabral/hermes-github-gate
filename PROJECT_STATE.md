# PROJECT STATE — atualizado 2026-07-16T14:45Z por tier3/hermes
## Objetivo
GitHub Gate — Hermes Agent plugin que monitora branches ai/*, valida código, abre PRs e seta status checks.

## Tarefa atual
Formalizar regra de responsabilidades entre tiers.

## Estado incompleto
- MVP do Gate implementado e testado (reprovação ✅ + aprovação ✅)
- Falta registrar no DECISIONS.md a regra de responsabilidades

## Próximas 3 ações
1. Registrar regra no DECISIONS.md: Claude projeta, Hermes orquestra, sub-agent codifica
2. Comunicar regra ao Claude no chat
3. Fechar PR #2 do smoke test e limpar branches

## Bugs conhecidos / armadilhas
- Nenhum

## Regra de responsabilidades (decisão 002)
- Claude Fable 5 (Tier 1): ONLY design, architecture, review, decisions. ZERO código.
- Hermes (Tier 2): interpreta design de Claude, delega para sub-agentes.
- Sub-agente (Tier 3): única entidade que escreve código no repositório.
