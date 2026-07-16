# PROJECT STATE — atualizado 2026-07-16T14:45Z por tier3/hermes
## Objetivo
GitHub Gate — Hermes Agent plugin que monitores branches ai/*, valida código, abre PRs e seta status checks.

## Tarefa atual
Corrigir itens críticos apontados pela revisão do Claude Fable 5 no PR #1.

## Estado incompleto
- validate_branch corrigido: agora é diff-based (não existencia-based) ✅
- post_pr_comment: precisa de dedup real (não postar mesmo body repetido)
- PROJECT_STATE.md agora atualizado neste PR

## Próximas 3 ações
1. Commitar correções e fazer push para o branch do PR
2. Claude Fable 5 revisar as correções
3. Merge do PR e configurar branch protection na main

## Bugs conhecidos / armadilhas
- py_compile não detecta erros de runtime, só de sintaxe
- Gate depende de gh CLI autenticado
