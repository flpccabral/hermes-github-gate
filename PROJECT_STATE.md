# PROJECT STATE — atualizado 2026-07-16T19:05Z por tier3/hermes
## Objetivo
GitHub Gate L1 — validação SHA-fixo, fail-closed completo, Feedback Packet v2.

## Tarefa atual
Correções baseadas no veredito do ChatGPT (2º juiz).

## Correções aplicadas
1. TOCTOU eliminado: head_sha e base_sha fixados ANTES da validação
2. set_status() usa head_sha recebido (nunca consulta branch de novo)
3. git fetch com verificação de returncode
4. git diff com verificação de returncode
5. cat-file -e confirma que commits existem localmente
6. Dedup por marcador estruturado: <!-- hermes-gate:feedback:run_id:head_sha:base_sha:status:end -->
7. Feedback Packet v2: schema_version, overall_status (passed/failed/infra_error), run_id
8. pytest removido (volta em PR futuro com sandbox)
9. Warnings não silenciam erros de infraestrutura
10. restore() busca só comentários DO GATE (marcados)

## Próximas ações
1. Smoke test do L1 corrigido
2. Reportar para ChatGPT+Claude revisarem
3. Merge se aprovado

## Bloqueadores anteriores (resolvidos)
- R1 (spam): ✅ Dedup por marcador estruturado, não por body
- R2 (fail-closed): ✅ git fetch + git diff verificam returncode
- R3 (checkpoint): ✅ PROJECT_STATE.md atualizado
- TOCTOU: ✅ SHA fixado antes da validação
