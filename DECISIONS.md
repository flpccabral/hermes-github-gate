# DECISIONS

Formato: `YYYY-MM-DD | # | Decisão | Motivo | Alternativa rejeitada`

Nenhuma decisão registrada ainda.

2026-07-16 | 001 | GitHub Gate como arquitetura de bridge | Repo como fonte de verdade, Hermes como gate de execução, web AIs escrevem em branches ai/* | Multi-tier cascade com fallbacks de API

2026-07-16 | 002 | Responsabilidades por tier | Claude projeta apenas. Hermes orquestra e delega. Sub-agent codifica. Nenhum tier escreve código que não é de sua responsabilidade. | Tiers sobrepostos causavam retrabalho e código sem dono.
2026-07-16 | 003 | Formato IA-IA em TODA comunicação entre agentes de IA | REGRA FIXA E IMPRETERÍVEL: toda comunicação entre modelos de IA (Hermes ↔ ChatGPT, Claude, sub-agentes, delegate_task, cronjobs) DEVE usar exclusivamente o formato IA-IA: seções nomeadas em MAIÚSCULAS (STATUS, PROBLEMA, CAUSA, FIX, DECISAO), bullet points, chaves tipo BLOCKER-1/B1, respostas no MESMO formato. Proibido terminantemente: saudações ("olá", "bom dia"), agradecimentos ("obrigado", "valeu"), linguagem humana prolixa, perguntas retóricas. Ao final de cada request, incluir "Responda no formato IA-IA: STATUS / DECISAO / PROXIMOS_PASSOS". | Formato humano verboso desperdiça tokens, adiciona ruído e ambiguidade a cada iteração. Formato IA-IA reduziu ~40% tokens e eliminou ciclos de revisão por interpretação errada.
