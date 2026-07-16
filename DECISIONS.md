# DECISIONS

Formato: `YYYY-MM-DD | # | Decisão | Motivo | Alternativa rejeitada`

Nenhuma decisão registrada ainda.

2026-07-16 | 001 | GitHub Gate como arquitetura de bridge | Repo como fonte de verdade, Hermes como gate de execução, web AIs escrevem em branches ai/* | Multi-tier cascade com fallbacks de API

2026-07-16 | 002 | Responsabilidades por tier | Claude projeta apenas. Hermes orquestra e delega. Sub-agent codifica. Nenhum tier escreve código que não é de sua responsabilidade. | Tiers sobrepostos causavam retrabalho e código sem dono.
2026-07-16 | 003 | Formato IA-IA em toda comunicação entre agentes | Toda comunicação entre modelos de IA (Hermes ↔ ChatGPT, Claude, sub-agentes) deve usar formato IA-IA: seções nomeadas, bullet points, chaves tipo PROBLEMA/CAUSA/FIX, respostas no mesmo formato. Solicitar explicitamente "responda no mesmo formato". Proibido: saudacoes, agradecimentos, linguagem prolixa. | Formato humano verboso desperdica tokens e adiciona ruido a cada iteracao. Formato IA-IA reduziu ~40% tokens e eliminou ambiguidade nas req/review.
