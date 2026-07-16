# CONVENTIONS

> Este arquivo define os padrões do projeto. Deve ser escrito no dia zero e raramente muda.

## Stack
- Python 3.11+
- Stdlib preferencialmente (sem frameworks pesados)
- GitHub CLI (`gh`) para interações com API

## Estrutura de diretórios
```
hermes-github-gate/
├── gate/               # Plugin Hermes (watch + execução)
├── checkpoint/         # Scripts de checkpoint/restore
├── PROJECT_STATE.md    # Estado vivo do projeto
├── DECISIONS.md        # ADRs
├── CONVENTIONS.md      # Este arquivo
└── FILEMAP.md          # Mapa do código
```

## Naming
- Branches: `task/<task_id>-<descricao>` (ex: `task/TASK-0042-refresh-tokens`)
- Commits: `checkpoint(<tier>): <descricao>`
- Python: snake_case para funções/variáveis, PascalCase para classes

## IA-IA Communication Protocol (REGRIA FIXA)
- Toda comunicação entre modelos de IA DEVE usar formato IA-IA
- Seções nomeadas em MAIÚSCULAS: STATUS / PROBLEMA / FIX / DECISAO
- Bullet points, chaves tipo B1/B2, sem parágrafos longos
- Proibido: saudações, agradecimentos, linguagem prolixa
- Solicitar resposta no mesmo formato: "Responda: STATUS / DECISAO / PROXIMOS_PASSOS"
- Aplicável a: ChatGPT, Claude, delegate_task, cronjobs, qualquer sub-agente

## Tiers
- **TIER_0** — Felipe: autoridade final, decisões de produto, aceitação de risco, merge HIGH_RISK
- **TIER_1** — ChatGPT / Claude F5: design e revisão apenas. ZERO código.
- **TIER_2** — Hermes Agent (deepseek-v4-pro): orquestrador local. Interpreta design, gerencia git/gh/PR, executa testes.
- **TIER_3** — Sub-agente (kimi-k2.7-code:cloud): única entidade que escreve código. Tool calling via Ollama local proxy.

## Planos Transversais
- **CONTROL PLANE**
  - Operador: Tier 2 / Hermes
  - Enforcement: Gate, CI e GitHub branch protection
  - Responsabilidades: políticas, permissões, state machine, risk classification, allowlists
- **AUDIT PLANE**: eventos estruturados, logs imutáveis, proveniência, métricas, dados de recuperação

## Regras de Aprovação
BASELINE — TODOS OS NIVEIS:
  - Testes requeridos passando
  - CI verde
  - Gate verde
  - Zero blockers
LOW_RISK: baseline + 1 aprovacao Tier 1
MEDIUM_RISK: baseline + 2 revisoes Tier 1
HIGH_RISK: baseline + 2 aprovacoes Tier 1 + revisao de seguranca + autorizacao explicita TIER_0

## Bridge
- **Repositório**: flpccabral/hermes-github-gate (fonte de verdade)
- **Arquivos de estado**: PROJECT_STATE.md, DECISIONS.md, CONVENTIONS.md, FILEMAP.md
- **Gate**: gate/github_gate.py (validação SHA-pinned, merge-base, erros estruturados, status retry)
- **Testes**: tests/unit/ (28 testes, pytest)
