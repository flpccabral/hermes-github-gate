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
                         result: dict) -> dict:
        infra = [e for e in result["errors"]
                if any(k in e.lower() for k in ("git ", "worktree", "fetch", "api",
                                                "timeout", "merge-base", "shallow"))]
        overall = "infra_error" if (not result["success"] and infra) else \
                  "failed" if not result["success"] else \
                  "passed_with_warnings" if result["warnings"] else "passed"

        return {
            "schema_version": "1.0", "run_id": run_id,
            "validator_version": VALIDATOR_VERSION,
            "branch": branch,
            "head_sha": head_sha, "base_sha": base_sha, "merge_base_sha": merge_base_sha,
            "overall_status": overall,
            "checkpoint_present": result.get("has_checkpoint", False),
            "errors": [{"code": f"ERR{i:02d}", "message": e}
                      for i, e in enumerate(result.get("errors", []))],
            "warnings": [{"code": f"WRN{i:02d}", "message": w}
                        for i, w in enumerate(result.get("warnings", []))],
            "next_action": {"passed": "merge", "passed_with_warnings": "review_warnings",
                           "failed": "fix_code", "infra_error": "retry"}.get(overall, "unknown"),
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
                    continue
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
            self._gh("api", f"repos/{self.repo}/issues/comments/{canonical['id']}",
                     "-X", "PATCH", "-f", f"body={body}")

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
        self._gh("api", f"repos/{self.repo}/issues/comments/{canonical['id']}",
                 "-X", "PATCH", "-f", f"body={body}")

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

    def set_status(self, head_sha: str, state: str, description: str):
        self._gh("api", f"repos/{self.repo}/statuses/{head_sha}",
                 "-f", f"state={state}",
                 "-f", f"context=hermes-gate/validate",
                 "-f", f"description={description}")

    # ── merge-base (Ponto 2 + Ponto 3 + Ponto 4) ──────────────

    def _classify_merge_base(self, all_mb: list[str], is_shallow: bool,
                             unshallow_attempted: bool) -> tuple:
        """Classificador ÚNICO de merge-base. Retorna (sha or None, error_code or None)."""
        if len(all_mb) == 0:
            if unshallow_attempted:
                return None, "HISTORY_INCOMPLETE"
            if is_shallow:
                return None, "HISTORY_INCOMPLETE"
            return None, "UNRELATED_HISTORIES"
        if len(all_mb) == 1:
            return all_mb[0], None
        # >1
        return None, "AMBIGUOUS_MERGE_BASE"

    def _resolve_merge_base(self, branch: str, head_sha: str, base_sha: str,
                            result: dict) -> Optional[str]:
        """Fetch, calcula merge-base com --all, classifica falhas. Retorna SHA ou None."""
        # Fetch
        for ref, label in [("main", "main"), (branch, "branch")]:
            try:
                r = self._git("fetch", "origin", ref, timeout=30)
            except subprocess.TimeoutExpired:
                result["success"] = False
                result["errors"].append(f"git fetch {label} timed out")
                return None
            if r.returncode != 0:
                result["success"] = False
                result["errors"].append(f"git fetch {label} failed")
                return None

        # Confirma SHAs localmente
        for sha, label in [(head_sha, "head"), (base_sha, "base")]:
            if self._git("cat-file", "-e", sha).returncode != 0:
                result["success"] = False
                result["errors"].append(f"commit {label} ({sha[:12]}) não encontrado localmente")
                return None

        # Função auxiliar: executa merge-base --all e classifica
        def _run_and_classify(already_unshallowed: bool = False) -> Optional[str]:
            try:
                r = self._git("merge-base", "--all", base_sha, head_sha, timeout=15)
            except subprocess.TimeoutExpired:
                result["success"] = False
                result["errors"].append("git merge-base timed out")
                return None

            if r.returncode != 0:
                # Correção 4: classificar falha — verificar shallow primeiro
                shallow_r = self._git("rev-parse", "--is-shallow-repository")
                if shallow_r.returncode != 0:
                    # Falha ao detectar shallow — não prova UNRELATED
                    result["success"] = False
                    result["errors"].append("REPOSITORY_TYPE_UNKNOWN — falha ao determinar tipo do repositório")
                    return None

                is_shallow = shallow_r.stdout.strip() == "true"

                if is_shallow and not already_unshallowed:
                    # Correção 3: capturar timeout do unshallow
                    try:
                        u = self._git("fetch", "--unshallow", timeout=60)
                    except subprocess.TimeoutExpired:
                        result["success"] = False
                        result["errors"].append("UNSHALLOW_TIMEOUT — unshallow excedeu 60s")
                        return None
                    if u.returncode == 0:
                        return _run_and_classify(already_unshallowed=True)
                    result["success"] = False
                    result["errors"].append("HISTORY_INCOMPLETE — unshallow falhou")
                    return None

                # Classificador único
                sha, err = self._classify_merge_base([], is_shallow, already_unshallowed)
                if err:
                    result["success"] = False
                    result["errors"].append(err)
                return sha

            # merge-base --all OK: normalizar e classificar
            all_mb_raw = [s.strip() for s in r.stdout.strip().split("\n") if s.strip()]
            all_mb = list(dict.fromkeys(all_mb_raw))  # dedup mantendo ordem

            # Determinar shallow state para classificação
            shallow_r = self._git("rev-parse", "--is-shallow-repository")
            is_shallow = (shallow_r.returncode == 0 and shallow_r.stdout.strip() == "true")

            sha, err = self._classify_merge_base(all_mb, is_shallow, already_unshallowed)
            if err:
                result["success"] = False
                result["errors"].append(err)
            return sha

        return _run_and_classify()

    # ── validation ────────────────────────────────────────────

    def validate_commit(self, branch: str, head_sha: str, base_sha: str,
                        merge_base_sha: str) -> dict:
        result = {"success": True, "errors": [], "warnings": [], "has_checkpoint": False}

        r = self._git("diff", merge_base_sha, head_sha, "--", "PROJECT_STATE.md")
        if r.returncode != 0:
            result["success"] = False
            result["errors"].append(f"git diff checkpoint failed: {r.stderr.strip()}")
            return result
        if r.stdout.strip():
            result["has_checkpoint"] = True
        else:
            result["success"] = False
            result["errors"].append("PROJECT_STATE.md não foi alterado — checkpoint ausente")

        tmp_dir = f"/tmp/gate-v4-{uuid.uuid4().hex[:8]}"
        subprocess.run(["rm", "-rf", tmp_dir])
        r = self._git("worktree", "add", "--detach", tmp_dir, head_sha)
        if r.returncode != 0:
            result["success"] = False
            result["errors"].append(f"git worktree add failed: {r.stderr.strip()}")
            return result

        try:
            r = self._git("diff", merge_base_sha, head_sha, "--name-only", "--", "*.py")
            if r.returncode != 0:
                result["success"] = False
                result["errors"].append(f"git diff py files failed: {r.stderr.strip()}")
                return result
            for pyf in [f for f in r.stdout.strip().split('\n') if f.endswith('.py')]:
                fp = Path(tmp_dir) / pyf
                if not fp.exists():
                    continue
                sr = subprocess.run([sys.executable, "-m", "py_compile", str(fp)],
                                   capture_output=True, text=True)
                if sr.returncode != 0:
                    result["success"] = False
                    result["errors"].append(f"Syntax error in {pyf}: {sr.stderr.strip()}")
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

            # Merge-base + fetch
            ctx = {"success": True, "errors": [], "warnings": [], "has_checkpoint": False}
            merge_base_sha = self._resolve_merge_base(name, head_sha, base_sha, ctx)

            if merge_base_sha is None:
                fb = self._feedback_packet(run_id, name, head_sha, base_sha, "", ctx)
                self.set_status(head_sha, "error", "; ".join(ctx["errors"][:2]))
            else:
                self._log(f"    merge-base={merge_base_sha[:12]}")
                result = self.validate_commit(name, head_sha, base_sha, merge_base_sha)
                fb = self._feedback_packet(run_id, name, head_sha, base_sha, merge_base_sha, result)

                if fb["overall_status"] in ("passed", "passed_with_warnings"):
                    self.set_status(head_sha, "success", f"{fb['overall_status']}")
                elif fb["overall_status"] == "infra_error":
                    self.set_status(head_sha, "error", "; ".join(result["errors"][:2]))
                else:
                    self.set_status(head_sha, "failure", "; ".join(result["errors"][:2]))

            if not self._get_pr_number(name):
                pr_url = self.create_pr(name)
                if pr_url:
                    self._log(f"    PR criado: {pr_url}")

            # Ponto 1 + Ponto 4: PATCH condicional + convergência
            comment_body = self._format_comment(fb)
            self._post_or_update(name, comment_body, fb)

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
