#!/usr/bin/env python3
"""
github_gate.py — Hermes GitHub Gate L1 (v4 - PATCH condicional + merge-base --all)

Bridge entre web AIs (Claude/ChatGPT via GitHub) e execução local.
Polla branches ai/*, valida por merge-base fixo, abre PRs, seta status.
"""
import argparse, datetime, hashlib, json, os, subprocess, sys, time, uuid
from typing import Optional
from pathlib import Path

REPO = "flpccabral/hermes-github-gate"
STATE_FILES = ["PROJECT_STATE.md", "DECISIONS.md", "CONVENTIONS.md", "FILEMAP.md"]
BRANCH_PREFIX = "ai/"
VALIDATOR_VERSION = "L1-v1"

# Códigos de erro conhecidos como infraestrutura (por code, não substring)
INFRA_CODES = {"HISTORY_INCOMPLETE", "UNSHALLOW_TIMEOUT", "REPOSITORY_TYPE_UNKNOWN",
               "AMBIGUOUS_MERGE_BASE", "COMMENT_LIST_PARSE_FAILED",
               "STATUS_PUBLISH_FAILED", "STATUS_PUBLISH_RETRIES_EXHAUSTED"}

def _make_error(code: str, message: str, category: str = None,
                retryable: bool = None) -> dict:
    """Cria erro estruturado com código semântico preservado.
    Se category/retryable nao fornecidos, consulta _ERROR_MAP."""
    if category is None or retryable is None:
        meta = GitHubGate._ERROR_MAP.get(code, ("code", False, "fix_code"))
        if category is None:
            category = meta[0]
        if retryable is None:
            retryable = meta[1]
    return {"code": code, "message": message,
            "category": category, "retryable": retryable}

# Campos ignorados na comparação semântica
_SEMANTIC_SKIP = {"run_id", "timestamps", "schema_version"}


class GitHubGate:
    def __init__(self, repo: str = REPO, gh_cmd: str = "gh"):
        self.repo = repo
        self.gh = gh_cmd
        self._check_gh()

    # ── helpers ──────────────────────────────────────────────

    def _check_gh(self):
        r = subprocess.run([self.gh, "auth", "status"], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("gh CLI not authenticated")

    def _gh(self, *args, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run([self.gh] + list(args),
                              capture_output=True, text=True, **kwargs)

    def _log(self, msg: str):
        print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}")

    def _repo_api(self, path: str) -> dict:
        r = self._gh("api", f"repos/{self.repo}/{path}")
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else {}

    def _get_branch_sha(self, branch: str) -> str:
        data = self._repo_api(f"branches/{branch}")
        return data.get("commit", {}).get("sha", "?")

    def _git(self, *args, timeout=60, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(["git"] + [str(a) for a in args],
                              capture_output=True, text=True, timeout=timeout, **kwargs)

    # ── marcador determinístico ─────────────────────────────

    def _make_marker(self, head_sha: str, base_sha: str) -> str:
        return f"<!-- hermes-gate:{VALIDATOR_VERSION}:{head_sha}:{base_sha}:end -->"

    # ── projeção semântica (Ponto 1) ─────────────────────────

    def _semantic_projection(self, fb: dict) -> str:
        """Projeção canônica: só campos que representam o resultado funcional.
        Ignora run_id, timestamps, etc. Saída determinística p/ comparação."""
        errors_norm = sorted(
            (e.get("code", ""), e.get("message", "")) for e in fb.get("errors", [])
        )
        warnings_norm = sorted(
            (w.get("code", ""), w.get("message", "")) for w in fb.get("warnings", [])
        )
        payload = json.dumps({
            "validator_version": fb.get("validator_version", ""),
            "branch": fb.get("branch", ""),
            "head_sha": fb.get("head_sha", ""),
            "base_sha": fb.get("base_sha", ""),
            "merge_base_sha": fb.get("merge_base_sha", ""),
            "overall_status": fb.get("overall_status", ""),
            "checkpoint_present": fb.get("checkpoint_present", False),
            "next_action": fb.get("next_action", ""),
            "errors": errors_norm,
            "warnings": warnings_norm,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[:32]

    def _extract_fb_from_body(self, body: str) -> Optional[dict]:
        """Extrai Feedback Packet do corpo do comentário."""
        for line in body.split("\n"):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        # Tenta extrair de bloco ```json
        if "```json" in body:
            block = body.split("```json")[1].split("```")[0].strip()
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                pass
        return None

    # ── Feedback Packet ──────────────────────────────────────

    def _feedback_packet(self, run_id: str, branch: str,
                         head_sha: str, base_sha: str, merge_base_sha: str,
                         result: dict, publication_status: str = "confirmed") -> dict:
        # Usa erros estruturados diretamente (códigos semânticos preservados)
        infra = any(e.get("code") in INFRA_CODES or e.get("category") == "infra"
                    for e in result.get("errors", []))

        overall = "infra_error" if (not result["success"] and infra) else \
                  "failed" if not result["success"] else \
                  "passed_with_warnings" if result["warnings"] else "passed"

        # Se publicação do status falhou, eleva para infra_error
        if publication_status == "failed":
            overall = "infra_error"

        # next_action do primeiro erro com mapeamento (ou genérico)
        first_err = None
        for e in result.get("errors", []):
            meta = self._ERROR_MAP.get(e.get("code", ""))
            if meta:
                first_err = meta[2]
                break
        if not first_err:
            first_err = {"passed": "merge", "passed_with_warnings": "review_warnings",
                        "failed": "fix_code", "infra_error": "retry"}.get(overall, "unknown")

        return {
            "schema_version": "1.0", "run_id": run_id,
            "validator_version": VALIDATOR_VERSION,
            "branch": branch,
            "head_sha": head_sha, "base_sha": base_sha, "merge_base_sha": merge_base_sha,
            "overall_status": overall,
            "checkpoint_present": result.get("has_checkpoint", False),
            "errors": result.get("errors", []),
            "warnings": result.get("warnings", []),
            "publication_status": publication_status,
            "next_action": first_err,
            "timestamps": {"poll_utc": datetime.datetime.utcnow().isoformat() + "Z"},
        }

    def _format_comment(self, fb: dict) -> str:
        marker = self._make_marker(fb["head_sha"], fb["base_sha"])
        body = "## 🔍 Validação do Gate\n"
        for e in fb.get("errors", []):
            body += f"### ❌ {e['code']}: {e['message']}\n"
        for w in fb.get("warnings", []):
            body += f"### ⚠️ {w['code']}: {w['message']}\n"
        if fb.get("checkpoint_present"):
            body += "✅ Checkpoint presente\n"
        body += f"\n**Status**: {fb['overall_status']} | **Ação**: {fb['next_action']}\n"
        body += f"\n{marker}\n"
        body += "\n```json\n" + json.dumps(fb, indent=2) + "\n```"
        return body

    # ── PR comment management ────────────────────────────────

    def _get_pr_number(self, branch: str) -> Optional[str]:
        r = self._gh("pr", "list", "--repo", self.repo,
                      "--head", branch, "--state", "open",
                      "--json", "number", "--jq", ".[0].number")
        return r.stdout.strip() if r.stdout.strip() else None

    def _get_all_comments(self, pr_num: str) -> dict:
        """Retorna {status, comments, error} com paginação completa.
        status: 'complete' | 'complete_empty' | 'failed'"""
        result = {"status": "failed", "comments": [], "error": None}
        comments = []
        page = 1
        while True:
            try:
                r = self._gh("api",
                    f"repos/{self.repo}/issues/{pr_num}/comments?per_page=100&page={page}",
                    "--jq", ".[] | {id, body, created_at, updated_at}")
            except Exception as e:
                result["error"] = f"API call failed at page {page}: {e}"
                return result
            if r.returncode != 0:
                if page == 1:
                    result["error"] = f"API error (HTTP {r.returncode}): {r.stderr.strip()[:200]}"
                    return result
                # Falha no meio da paginação → resultado parcial inválido
                result["error"] = f"Paginação incompleta na página {page}: {r.stderr.strip()[:200]}"
                return result
            if not r.stdout.strip():
                break
            for entry in r.stdout.strip().split("\n"):
                entry = entry.strip()
                if not entry:
                    continue
                try:
                    c = json.loads(entry)
                    if isinstance(c, dict) and "id" in c:
                        comments.append(c)
                except json.JSONDecodeError:
                    result["status"] = "failed"
                    result["error"] = f"COMMENT_LIST_PARSE_FAILED — entrada inválida na página {page}"
                    return result
            if len(r.stdout.strip().split("\n")) < 100:
                break
            page += 1
        result["comments"] = comments
        result["status"] = "complete_empty" if not comments else "complete"
        return result

    def _find_matching_comments(self, pr_num: str, marker: str) -> dict:
        """Busca comments pelo marcador. Retorna dict com {status, comments, error}."""
        res = self._get_all_comments(pr_num)
        if res["status"] != "failed":
            res["comments"] = [c for c in res["comments"] if marker in c.get("body", "")]
            if not res["comments"] and res["status"] == "complete":
                res["status"] = "complete_empty"
        return res

    def _post_or_update(self, branch: str, body: str, fb: dict):
        """Ponto 1 + Ponto 4: PATCH condicional + convergência concorrente.
        Correção 1a: verifica status da busca antes de criar/atualizar.
        Correção 1b: pós-criação relista e converge duplicatas."""
        pr_num = self._get_pr_number(branch)
        if not pr_num:
            return

        marker = self._make_marker(fb["head_sha"], fb["base_sha"])
        res = self._find_matching_comments(pr_num, marker)

        # Correção 1a: se busca falhou, abortar
        if res["status"] == "failed":
            self._log(f"  Erro buscando comentários PR #{pr_num}: {res.get('error', 'desconhecido')}")
            return

        matching = res["comments"]

        if not matching:
            # Correção 1b: criar + relistar + convergir
            self._log(f"  Criando comentário no PR #{pr_num}")
            create_r = self._gh("pr", "comment", "--repo", self.repo, pr_num, "--body", body)
            if create_r.returncode != 0:
                self._log(f"  Falha ao criar comentário: {create_r.stderr.strip()[:100]}")
                return

            # Pós-criação: relistar e convergir
            res2 = self._find_matching_comments(pr_num, marker)
            if res2["status"] == "failed":
                self._log(f"  Convergência pós-criação falhou (busca): {res2.get('error','?')}")
                return
            all_after = res2["comments"]
            if len(all_after) <= 1:
                return  # sem duplicatas

            # Convergir: escolher canônico (menor ID)
            all_after.sort(key=lambda c: c.get("id", 0))
            canonical = all_after[0]
            dups = all_after[1:]

            # Atualizar canônico com resultado atual
            patch_r = self._gh("api", f"repos/{self.repo}/issues/comments/{canonical['id']}",
                     "-X", "PATCH", "-f", f"body={body}")
            if patch_r.returncode != 0:
                self._log(f"  PATCH do canônico falhou — duplicatas mantidas p/ próximo poll")
                return

            # Remover duplicatas
            for dup in dups:
                self._gh("api", f"repos/{self.repo}/issues/comments/{dup['id']}",
                         "-X", "DELETE")
            self._log(f"  Convergido: {len(dups)} duplicatas removidas")
            return

        # Já existe comentário: PATCH condicional
        matching.sort(key=lambda c: c.get("id", 0))
        canonical = matching[0]
        duplicates = matching[1:]

        existing_fb = self._extract_fb_from_body(canonical.get("body", ""))
        if existing_fb:
            old_proj = self._semantic_projection(existing_fb)
            new_proj = self._semantic_projection(fb)
            if old_proj == new_proj:
                # Semanticamente igual → não faz PATCH, só remove duplicatas
                for dup in duplicates:
                    self._gh("api", f"repos/{self.repo}/issues/comments/{dup['id']}",
                             "-X", "DELETE")
                return

        # Semanticamente diferente → atualizar canônico
        patch_r = self._gh("api", f"repos/{self.repo}/issues/comments/{canonical['id']}",
                 "-X", "PATCH", "-f", f"body={body}")
        if patch_r.returncode != 0:
            self._log(f"  PATCH do canônico falhou — duplicatas mantidas p/ próximo poll")
            return

        for dup in duplicates:
            self._gh("api", f"repos/{self.repo}/issues/comments/{dup['id']}",
                     "-X", "DELETE")

    # ── branch polling ────────────────────────────────────────

    def list_branches(self) -> list[dict]:
        r = self._gh("api", f"repos/{self.repo}/branches")
        if r.returncode != 0:
            return []
        ai_branches = []
        for b in json.loads(r.stdout):
            name = b.get("name", "")
            if not name.startswith(BRANCH_PREFIX) or name == "main":
                continue
            ci = b.get("commit", {}) or {}
            ai_branches.append({"name": name, "sha": ci.get("sha", "?"),
                                "date": ci.get("commit", {}).get("author", {}).get("date", "?")})
        return ai_branches

    def create_pr(self, branch: str) -> Optional[str]:
        if self._get_pr_number(branch):
            return None
        title = branch.replace("ai/claude/", "").replace("ai/", "").replace("-", " ").title()
        title = f"feat: {title}"
        r = self._gh("pr", "create", "--repo", self.repo,
                      "--head", branch, "--base", "main",
                      "--title", title,
                      "--body", f"🤖 PR automático do branch `{branch}`.")
        return r.stdout.strip() if r.returncode == 0 else None

    def set_status(self, head_sha: str, state: str, description: str, max_retries: int = 3) -> bool:
        """Publica status no SHA validado. Com retry. Retorna True se confirmado."""
        import time as _time
        for attempt in range(max_retries):
            if attempt > 0:
                _time.sleep(1 * attempt)  # backoff simples
            r = self._gh("api", f"repos/{self.repo}/statuses/{head_sha}",
                     "-f", f"state={state}",
                     "-f", f"context=hermes-gate/validate",
                     "-f", f"description={description}")
            if r.returncode == 0:
                return True
        self._log(f"  Status publish FAILED after {max_retries} retries: {description}")
        return False

    # ── merge-base (Ponto 2 + Ponto 3 + Ponto 4) ──────────────

    def _classify_merge_base(self, all_mb: list[str], is_shallow: bool) -> tuple:
        """Classificador ÚNICO de merge-base.
        is_shallow: estado ATUAL do repositório (re-verificado após unshallow).
        Retorna (sha or None, error_code or None)."""
        if len(all_mb) == 0:
            if is_shallow:
                return None, "HISTORY_INCOMPLETE"
            return None, "UNRELATED_HISTORIES"
        if len(all_mb) == 1:
            return all_mb[0], None
        # >1
        return None, "AMBIGUOUS_MERGE_BASE"

    # Mapa: codigo_erro → (categoria, retryable, next_action)
    _ERROR_MAP = {
        "HISTORY_INCOMPLETE":         ("infra", True, "retry_history_fetch"),
        "UNSHALLOW_TIMEOUT":          ("infra", True, "retry_unshallow"),
        "REPOSITORY_TYPE_UNKNOWN":    ("infra", True, "inspect_repository"),
        "UNRELATED_HISTORIES":        ("policy", False, "recreate_branch"),
        "AMBIGUOUS_MERGE_BASE":       ("unsupported", False, "unsupported_topology"),
        "STATUS_PUBLISH_FAILED":      ("infra", True, "retry_status_publish"),
        "STATUS_PUBLISH_RETRIES_EXHAUSTED": ("infra", True, "retry_status_publish"),
        "COMMENT_LIST_PARSE_FAILED":  ("infra", True, "retry"),
        "FETCH_TIMEOUT":              ("infra", True, "retry"),
        "FETCH_FAILED":               ("infra", True, "retry"),
        "COMMIT_NOT_FOUND":           ("infra", True, "retry"),
        "MERGE_BASE_TIMEOUT":         ("infra", True, "retry"),
        "GIT_DIFF_FAILED":            ("infra", True, "retry"),
        "WORKTREE_FAILED":            ("infra", True, "retry"),
        "CHECKPOINT_MISSING":         ("code", False, "fix_checkpoint"),
        "SYNTAX_ERROR":               ("code", False, "fix_code"),
    }

    def _resolve_merge_base(self, branch: str, head_sha: str, base_sha: str,
                            result: dict) -> Optional[str]:
        """Fetch, calcula merge-base com --all, classifica falhas. Retorna SHA ou None."""
        # Fetch
        for ref, label in [("main", "main"), (branch, "branch")]:
            try:
                r = self._git("fetch", "origin", ref, timeout=30)
            except subprocess.TimeoutExpired:
                result["success"] = False
                result["errors"].append(_make_error("FETCH_TIMEOUT", f"git fetch {label} timed out", "infra", True))
                return None
            if r.returncode != 0:
                result["success"] = False
                result["errors"].append(_make_error("FETCH_FAILED", f"git fetch {label} failed", "infra", True))
                return None

        # Confirma SHAs localmente
        for sha, label in [(head_sha, "head"), (base_sha, "base")]:
            if self._git("cat-file", "-e", sha).returncode != 0:
                result["success"] = False
                result["errors"].append(_make_error("COMMIT_NOT_FOUND", f"commit {label} ({sha[:12]}) não encontrado localmente", "infra", True))
                return None

        # Função auxiliar: executa merge-base --all e classifica
        def _run_and_classify(already_unshallowed: bool = False) -> Optional[str]:
            try:
                r = self._git("merge-base", "--all", base_sha, head_sha, timeout=15)
            except subprocess.TimeoutExpired:
                result["success"] = False
                result["errors"].append(_make_error("MERGE_BASE_TIMEOUT", "git merge-base timed out", "infra", True))
                return None

            if r.returncode != 0:
                # Correção 4: classificar falha — verificar shallow primeiro
                shallow_r = self._git("rev-parse", "--is-shallow-repository")
                if shallow_r.returncode != 0:
                    # Falha ao detectar shallow — não prova UNRELATED
                    result["success"] = False
                    result["errors"].append(_make_error("REPOSITORY_TYPE_UNKNOWN", "REPOSITORY_TYPE_UNKNOWN — falha ao determinar tipo do repositório", "infra", True))
                    return None

                is_shallow = shallow_r.stdout.strip() == "true"

                if is_shallow and not already_unshallowed:
                    # Correção 3: capturar timeout do unshallow
                    try:
                        u = self._git("fetch", "--unshallow", timeout=60)
                    except subprocess.TimeoutExpired:
                        result["success"] = False
                        result["errors"].append(_make_error("UNSHALLOW_TIMEOUT", "UNSHALLOW_TIMEOUT — unshallow excedeu 60s", "infra", True))
                        return None
                    if u.returncode == 0:
                        return _run_and_classify(already_unshallowed=True)
                    result["success"] = False
                    result["errors"].append(_make_error("HISTORY_INCOMPLETE", "HISTORY_INCOMPLETE — unshallow falhou"))
                    return None

                # Classificador único (re-verifica shallow state atual)
                shallow_r2 = self._git("rev-parse", "--is-shallow-repository")
                is_shallow_now = shallow_r2.returncode == 0 and shallow_r2.stdout.strip() == "true"
                sha, err = self._classify_merge_base([], is_shallow_now)
                if err:
                    result["success"] = False
                    result["errors"].append(_make_error(err, err, "infra", True))
                return sha

            # merge-base --all OK: normalizar e classificar
            all_mb_raw = [s.strip() for s in r.stdout.strip().split("\n") if s.strip()]
            all_mb = list(dict.fromkeys(all_mb_raw))  # dedup mantendo ordem

            # Determinar shallow state para classificação
            shallow_r = self._git("rev-parse", "--is-shallow-repository")
            is_shallow = (shallow_r.returncode == 0 and shallow_r.stdout.strip() == "true")

            sha, err = self._classify_merge_base(all_mb, is_shallow)
            if err:
                result["success"] = False
                result["errors"].append(_make_error(err, err, "infra", True))
            return sha

        return _run_and_classify()

    # ── validation ────────────────────────────────────────────

    def validate_commit(self, branch: str, head_sha: str, base_sha: str,
                        merge_base_sha: str) -> dict:
        result = {"success": True, "errors": [], "warnings": [], "has_checkpoint": False}

        r = self._git("diff", merge_base_sha, head_sha, "--", "PROJECT_STATE.md")
        if r.returncode != 0:
            result["success"] = False
            result["errors"].append(_make_error("GIT_DIFF_FAILED", f"git diff checkpoint failed: {r.stderr.strip()}", "infra", True))
            return result
        if r.stdout.strip():
            result["has_checkpoint"] = True
        else:
            result["success"] = False
            result["errors"].append(_make_error("CHECKPOINT_MISSING", "PROJECT_STATE.md não foi alterado — checkpoint ausente", "code", False))

        tmp_dir = f"/tmp/gate-v4-{uuid.uuid4().hex[:8]}"
        subprocess.run(["rm", "-rf", tmp_dir])
        r = self._git("worktree", "add", "--detach", tmp_dir, head_sha)
        if r.returncode != 0:
            result["success"] = False
            result["errors"].append(_make_error("WORKTREE_FAILED", f"git worktree add failed: {r.stderr.strip()}", "infra", True))
            return result
        try:
            r = self._git("diff", merge_base_sha, head_sha, "--name-only", "--", "*.py")
            if r.returncode != 0:
                result["success"] = False
                result["errors"].append(_make_error("GIT_DIFF_FAILED", f"git diff py files failed: {r.stderr.strip()}", "infra", True))
                return result
            for pyf in [f for f in r.stdout.strip().split('\n') if f.endswith('.py')]:
                fp = Path(tmp_dir) / pyf
                if not fp.exists():
                    continue
                sr = subprocess.run([sys.executable, "-m", "py_compile", str(fp)],
                                   capture_output=True, text=True)
                if sr.returncode != 0:
                    result["success"] = False
                    result["errors"].append(_make_error("SYNTAX_ERROR", f"Syntax error in {pyf}: {sr.stderr.strip()}", "code", False))
        finally:
            self._git("worktree", "remove", "--force", tmp_dir)

        return result

    # ── polling ────────────────────────────────────────────────

    def poll_once(self):
        self._log("Polling branches...")
        branches = self.list_branches()
        if not branches:
            self._log("Nenhum branch ai/* encontrado")
            return

        for br in branches:
            name = br["name"]
            run_id = uuid.uuid4().hex[:12]
            head_sha = br["sha"]
            if head_sha == "?":
                continue
            base_sha = self._get_branch_sha("main")
            if base_sha == "?":
                continue

            self._log(f"  → {name} head={head_sha[:12]} base={base_sha[:12]}")

            # 1. Validar (merge-base + fetch)
            ctx = {"success": True, "errors": [], "warnings": [], "has_checkpoint": False}
            merge_base_sha = self._resolve_merge_base(name, head_sha, base_sha, ctx)

            if merge_base_sha is None:
                result = ctx
                merge_base_sha_val = ""
            else:
                self._log(f"    merge-base={merge_base_sha[:12]}")
                result = self.validate_commit(name, head_sha, base_sha, merge_base_sha)
                merge_base_sha_val = merge_base_sha

            # 2. Publicar status (com retry) — ANTES de comentário e PR
            if result["success"] and result.get("has_checkpoint"):
                status_ok = self.set_status(head_sha, "success", "Validação OK")
            elif not result["success"]:
                err_msg = result["errors"][0].get("message", str(result["errors"][0]))[:80] if result["errors"] else "unknown"
                is_infra = any(e.get("category") == "infra" for e in result.get("errors", []))
                status_ok = self.set_status(head_sha, "error" if is_infra else "failure", err_msg)
            else:
                status_ok = self.set_status(head_sha, "success", "OK (warnings)")

            # Se status falhou, adiciona erro estruturado
            if not status_ok:
                result.setdefault("errors", []).append(
                    _make_error("STATUS_PUBLISH_RETRIES_EXHAUSTED",
                                f"Status publish failed after retries for {head_sha[:12]}"))

            # 3. Gerar feedback packet (com publication_status)
            publication_status = "confirmed" if status_ok else "failed"
            fb = self._feedback_packet(run_id, name, head_sha, base_sha,
                                       merge_base_sha_val, result, publication_status)

            # 4. Sincronizar comentário (só se status confirmado ou já existe PR)
            existing_pr = self._get_pr_number(name)
            if existing_pr:
                comment_body = self._format_comment(fb)
                self._post_or_update(name, comment_body, fb)

            # 5. Criar PR apenas se status foi confirmado
            if status_ok and not existing_pr:
                pr_url = self.create_pr(name)
                if pr_url:
                    self._log(f"    PR criado: {pr_url}")

    def poll_loop(self, interval: int = 60):
        while True:
            try:
                self.poll_once()
            except Exception as e:
                self._log(f"Erro: {e}")
            time.sleep(interval)

    # ── restore ────────────────────────────────────────────────

    def restore_prompt(self, branch: Optional[str] = None) -> str:
        parts = []
        for fname in STATE_FILES:
            p = Path(fname)
            if p.exists():
                parts.append(f"=== {fname} ===\n{p.read_text(encoding='utf-8')}")

        if branch:
            pr_num = self._get_pr_number(branch)
            if pr_num:
                marker_prefix = "<!-- hermes-gate:"
                last_gate = None
                res = self._get_all_comments(pr_num)
                if res["status"] != "failed":
                    for c in res["comments"]:
                        if marker_prefix in c.get("body", ""):
                            last_gate = c["body"]
                if last_gate:
                    parts.append("=== ÚLTIMO FEEDBACK DO GATE ===\n" + last_gate)

        return ("Você está retomando um projeto em andamento. "
                f"Captura: {datetime.datetime.utcnow().isoformat()}Z\n\n"
                + "\n\n".join(parts))


# ── CLI ────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Hermes GitHub Gate L1 v4")
    sub = p.add_subparsers(dest="command")

    pp = sub.add_parser("poll")
    pp.add_argument("--watch", action="store_true")
    pp.add_argument("--once", action="store_true")
    pp.add_argument("--interval", type=int, default=60)

    pv = sub.add_parser("pr-validate")
    pv.add_argument("branch")

    sub.add_parser("restore").add_argument("--branch")

    args = p.parse_args()
    gate = GitHubGate()

    if args.command == "poll":
        if args.watch:
            gate.poll_loop(args.interval)
        else:
            gate.poll_once()
    elif args.command == "pr-validate":
        hs, bs = gate._get_branch_sha(args.branch), gate._get_branch_sha("main")
        if hs == "?" or bs == "?":
            print("Branch não encontrado", file=sys.stderr)
            sys.exit(1)
        ctx = {"success": True, "errors": [], "warnings": [], "has_checkpoint": False}
        mb = gate._resolve_merge_base(args.branch, hs, bs, ctx)
        if mb:
            result = gate.validate_commit(args.branch, hs, bs, mb)
            fb = gate._feedback_packet("cli", args.branch, hs, bs, mb, result)
        else:
            fb = gate._feedback_packet("cli", args.branch, hs, bs, "", ctx)
        print(json.dumps(fb, indent=2))
        sys.exit(0 if fb["overall_status"] in ("passed", "passed_with_warnings") else 1)
    elif args.command == "restore":
        print(gate.restore_prompt(args.branch if hasattr(args, 'branch') and args.branch else None))
    else:
        p.print_help()


if __name__ == "__main__":
    main()
