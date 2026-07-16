# FILEMAP

- `.github/workflows/test.yml` — CI pytest (unit tests)
- `.gitignore` — Ignora __pycache__, .pytest_cache, etc.
- `CONVENTIONS.md` — Padroes do projeto (stack, tiers, IA-IA, regras)
- `DECISIONS.md` — ADRs append-only (001–008)
- `FILEMAP.md` — Este arquivo
- `LICENSE` — Licenca do projeto
- `PROJECT_STATE.md` — Estado vivo do projeto
- `README.md` — Introducao e instrucoes
- `checkpoint/checkpoint.py` — Checkpoint/restore stdlib
- `gate/github_gate.py` — L1 Gate (validacao, merge-base, erros, status)
- `tests/__init__.py` — Pacote de testes
- `tests/conftest.py` — Fixtures do pytest
- `tests/unit/__init__.py` — Pacote de testes unitarios
- `tests/unit/test_comment_convergence.py` — Convergencia de comentarios do Gate
- `tests/unit/test_comment_listing.py` — Listagem e parsing de comentarios
- `tests/unit/test_error_mapping.py` — Mapa de erros estruturados
- `tests/unit/test_feedback_packet.py` — Feedback Packet de revisao
- `tests/unit/test_merge_base_classifier.py` — Classificacao de merge-base
- `tests/unit/test_status_publish.py` — Publicacao de status check

> Arquivos de cache Python (`.pytest_cache/`, `gate/__pycache__/`) nao sao versionados.
