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
- Branches: `ai/<tier>/<descricao>` (ex: `ai/claude/refresh-tokens`)
- Commits: `checkpoint(<tier>): <descricao>`
- Python: snake_case para funções/variáveis, PascalCase para classes

## IA-IA Communication Protocol (REGRIA FIXA)
- Toda comunicação entre modelos de IA DEVE usar formato IA-IA
- Seções nomeadas em MAIÚSCULAS: STATUS / PROBLEMA / FIX / DECISAO
- Bullet points, chaves tipo B1/B2, sem parágrafos longos
- Proibido: saudações, agradecimentos, linguagem prolixa
- Solicitar resposta no mesmo formato: "Responda: STATUS / DECISAO / PROXIMOS_PASSOS"
- Aplicável a: ChatGPT, Claude, delegate_task, cronjobs, qualquer sub-agente
