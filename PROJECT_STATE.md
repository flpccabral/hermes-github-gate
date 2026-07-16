# PROJECT STATE — atualizado 2026-07-16T19:30Z por tier3/hermes
## Objetivo
GitHub Gate L1 — validação SHA-pinned, merge-base determinístico, erros estruturados.

## Entregue
- gate/github_gate.py: poll branches ai/*, validação SHA fixa, merge-base --all, checkpoint diff-based, PRs, status check com retry, comments idempotentes (PATCH condicional), Feedback Packet, erros estruturados (_ERROR_MAP, códigos semânticos)
- checkpoint/checkpoint.py: save/restore stdlib
- .github/ISSUE_TEMPLATE/task.md: template de issues (pendente poll_issues em PR futuro)

## Marcador de comentário (atual)
<!-- hermes-gate:L1-v1:HEAD_SHA:BASE_SHA:end -->
(Determinístico: versão + head_sha + base_sha. NÃO contém run_id.)

## Erros estruturados
- _make_error(code, msg) → {code, message, category, retryable}
- _ERROR_MAP: 19 códigos com (categoria, retryable, next_action)
- category ∈ {code, infra, policy, unsupported}
- INFRA_CODES usado apenas para compatibilidade

## PR #3
- Head: 9e52e2f
- Título: "feat: L1 - validacao SHA-pinned, merge-base deterministico, erros estruturados"
- Status: aguardando revisão final

## Decisões registradas
- 001: GitHub Gate como arquitetura de bridge
- 002: Responsabilidades por tier (Claude projeta, Hermes orquestra, sub-agent codifica)
- 003: Formato IA-IA em toda comunicação entre agentes
