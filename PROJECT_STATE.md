# PROJECT STATE — atualizado 2026-07-16T15:30Z por tier3/hermes
## Objetivo
GitHub Gate L1 — validação diff-based, pytest, Feedback Packet, fail-closed.

## Tarefa atual
Corrigir regressões apontadas na revisão do Claude F5: R1 (dedup por SHA), R2 (fail-closed worktree), R3 (checkpoint ausente no PR).

## Próximas 3 ações
1. Merge do PR #3 após correções aprovadas
2. poll_issues + cleanup_abandoned em PR separado (fora do L1)
3. Smoke test do L1

## Bugs conhecidos / armadilhas
- restore offline ainda depende de gh CLI (pendente p/ PR futuro)
- restore usa CWD, não repo_path (pendente p/ PR futuro)
