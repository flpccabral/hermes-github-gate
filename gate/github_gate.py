#!/usr/bin/env python3
"""
github_gate.py — Hermes GitHub Gate L1 (v3 - dedup determinístico + merge-base)

Bridge entre web AIs (Claude/ChatGPT via GitHub) e execução local.
Polla branches ai/*, valida por merge-base fixo, abre PRs, seta status.

Uso CLI:
    python github_gate.py poll --once
    python github_gate.py poll --watch
    python github_gate.py restore [--branch <name>]
    python github_gate.py pr-validate <branch>

Uso como plugin Hermes:
    from gate.github_gate import GitHubGate
    gate = GitHubGate()
    gate.poll_once()
"""
import argparse, datetime, hashlib, json, os, subprocess, sys, time, uuid
from typing import Optional
from pathlib import Path

REPO = "flpccabral/hermes-github-gate"
STATE_FILES = ["PROJECT_STATE.md", "DECISIONS.md", "CONVENTIONS.md", "FILEMAP.md"]
BRANCH_PREFIX = "ai/"
VALIDATOR_VERSION = "L1-v1"


class GitHubGate:
    """GitHub Gate: monitora branches ai/* com validação por SHA fixo."""

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
        if r.returncode != 0:
            return {}
        return json.loads(r.stdout) if r.stdout.strip() else {}

    def _get_branch_sha(self, branch: str) -> str:
        data = self._repo_api(f"branches/{branch}")
        return data.get("commit", {}).get("sha", "?")

    def _git(self, *args, timeout=60, **kwargs) -> subprocess.CompletedProcess:
        cmd = ["git"] + [str(a) for a in args]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kwargs)
        return r

    # ── Feedback Packet ──────────────────────────────────────

    def _make_marker(self, head_sha: str, base_sha: str) -> str:
        """Marcador determinístico: depende só de head+base, NÃO de run_id."""
        return f"<!-- hermes-gate:{VALIDATOR_VERSION}:{head_sha}:{base_sha}:end -->"

    def _semantic_key(self, result: dict) -> str:
        """Hash do RESULTADO SEMÂNTICO (ignora timestamps, run_id)."""
        payload = f"{result.get('success')}:{result.get('has_checkpoint')}:{result.get('errors', [])}:{result.get('warnings', [])}"
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def _feedback_packet(self, run_id: str, branch: str,
                         head_sha: str, base_sha: str, merge_base_sha: str,
                         result: dict) -> dict:
        infra_errors = [e for e in result["errors"]
                       if any(k in e.lower() for k in ("git ", "worktree", "fetch", "api", "timeout", "merge-base"))]
        if not result["success"]:
            overall = "infra_error" if infra_errors else "failed"
        elif result["warnings"]:
            overall = "passed_with_warnings"
        else:
            overall = "passed"

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

    # ── PR comment management (dedup determinístico) ─────────

    def _get_pr_number(self, branch: str) -> Optional[str]:
        r = self._gh("pr", "list", "--repo", self.repo,
                      "--head", branch, "--state", "open",
                      "--json", "number", "--jq", ".[0].number")
        return r.stdout.strip() if r.stdout.strip() else None

    def _find_existing_comment_id(self, pr_num: str, marker: str) -> Optional[int]:
        """Busca comment ID pelo marcador, com paginação."""
        page = 1
        while True:
            r = self._gh("api",
                f"repos/{self.repo}/issues/{pr_num}/comments?per_page=100&page={page}",
                "--jq", ".[] | {id, body}")
            if r.returncode != 0 or not r.stdout.strip():
                break
            for entry in r.stdout.strip().split("\n"):
                if not entry.strip():
                    continue
                try:
                    c = json.loads(entry)
                    if marker in c.get("body", ""):
                        return c["id"]
                except json.JSONDecodeError:
                    continue
            # Check if there's a next page
            if len(r.stdout.strip().split("\n")) < 100:
                break
            page += 1
        return None

    def _update_comment(self, comment_id: int, body: str):
        """Atualiza comentário existente em vez de criar novo."""
        self._gh("api", f"repos/{self.repo}/issues/comments/{comment_id}",
                 "-X", "PATCH",
                 "-f", f"body={body}")

    def _create_comment(self, pr_num: str, body: str):
        self._gh("pr", "comment", "--repo", self.repo, pr_num, "--body", body)

    def _post_or_update(self, branch: str, body: str, marker: str):
        """Posta ou atualiza comentário. 1 comentário canônico por par head/base."""
        pr_num = self._get_pr_number(branch)
        if not pr_num:
            return
        existing_id = self._find_existing_comment_id(pr_num, marker)
        if existing_id:
            self._update_comment(existing_id, body)
        else:
            self._create_comment(pr_num, body)
            # Pós-escrita: converge duplicatas (concorrência)
            ids = []
            page = 1
            while True:
                r = self._gh("api",
                    f"repos/{self.repo}/issues/{pr_num}/comments?per_page=100&page={page}",
                    "--jq", ".[] | {id, body}")
                if r.returncode != 0 or not r.stdout.strip():
                    break
                for entry in r.stdout.strip().split("\n"):
                    if not entry.strip(): continue
                    try:
                        c = json.loads(entry)
                        if marker in c.get("body", ""):
                            ids.append(c["id"])
                    except json.JSONDecodeError:
                        continue
                if len(r.stdout.strip().split("\n")) < 100:
                    break
                page += 1
            # Se mais de 1, mantém o mais antigo (menor id), remove os outros
            if len(ids) > 1:
                ids.sort()
                for dup_id in ids[1:]:
                    self._gh("api", f"repos/{self.repo}/issues/comments/{dup_id}",
                             "-X", "DELETE")

    # ── branch polling ────────────────────────────────────────

    def list_branches(self) -> list[dict]:
        r = self._gh("api", f"repos/{self.repo}/branches")
        if r.returncode != 0:
            self._log(f"Erro listing branches: {r.stderr.strip()}")
            return []
        branches = json.loads(r.stdout)
        ai_branches = []
        for b in branches:
            name = b.get("name", "")
            if not name.startswith(BRANCH_PREFIX) or name == "main":
                continue
            ci = b.get("commit", {}) or {}
            ai_branches.append({
                "name": name,
                "sha": ci.get("sha", "?"),
                "date": ci.get("commit", {}).get("author", {}).get("date", "?"),
            })
        return ai_branches

    def create_pr(self, branch: str) -> Optional[str]:
        if self._get_pr_number(branch):
            return None
        title = branch.replace("ai/claude/", "").replace("ai/", "").replace("-", " ").title()
        title = f"feat: {title}"
        r = self._gh("pr", "create", "--repo", self.repo,
                      "--head", branch, "--base", "main",
                      "--title", title,
                      "--body", f"🤖 PR automático do branch `{branch}`.\n\nAguardando validação do Hermes Gate.")
        return r.stdout.strip() if r.returncode == 0 else None

    # ── set_status (SHA fixo, nunca consulta branch) ─────────

    def set_status(self, head_sha: str, state: str, description: str):
        self._gh("api", f"repos/{self.repo}/statuses/{head_sha}",
                 "-f", f"state={state}",
                 "-f", f"context=hermes-gate/validate",
                 "-f", f"description={description}",
                 "-f", f"target_url=https://github.com/{self.repo}/pull?q=head+{head_sha[:12]}")

    # ── validation (merge-base fixo) ──────────────────────────

    def _fetch_and_verify(self, branch: str, head_sha: str, base_sha: str, result: dict) -> Optional[str]:
        """Fetch branch + base, calcula merge-base. Retorna merge_base_sha ou None."""
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
                result["errors"].append(f"git fetch {label} failed: {r.stderr.strip()}")
                return None

        # Verifica SHAs localmente
        for sha, label in [(head_sha, "head"), (base_sha, "base")]:
            r = self._git("cat-file", "-e", sha)
            if r.returncode != 0:
                result["success"] = False
                result["errors"].append(f"commit {label} ({sha[:12]}) não encontrado localmente")
                return None

        # Calcula merge-base
        try:
            r = self._git("merge-base", base_sha, head_sha, timeout=15)
        except subprocess.TimeoutExpired:
            result["success"] = False
            result["errors"].append("git merge-base timed out — infra_error")
            return None

        if r.returncode != 0:
            # Histórios não relacionados
            result["success"] = False
            result["errors"].append("UNRELATED_HISTORIES — branch e base sem ancestral comum")
            return None

        merge_base_sha = r.stdout.strip()
        if not merge_base_sha or len(merge_base_sha) < 10:
            result["success"] = False
            result["errors"].append("MERGE_BASE_HISTORY_INCOMPLETE — merge-base não encontrado")
            return None

        # Verifica se merge-base é ambíguo (múltiplos resultados)
        if "\n" in merge_base_sha:
            result["success"] = False
            result["errors"].append("AMBIGUOUS_MERGE_BASE — múltiplos merge-bases equivalentes (topologia não suportada no L1)")
            return None

        return merge_base_sha.strip()

    def validate_commit(self, branch: str, head_sha: str, base_sha: str,
                        merge_base_sha: str) -> dict:
        """Valida um commit específico usando merge-base fixo."""
        result = {"success": True, "errors": [], "warnings": [], "has_checkpoint": False}

        # Diff do checkpoint: merge_base → head (não base → head)
        r = self._git("diff", merge_base_sha, head_sha, "--", "PROJECT_STATE.md")
        if r.returncode != 0:
            result["success"] = False
            result["errors"].append(f"git diff checkpoint failed: {r.stderr.strip()}")
            return result
        if r.stdout.strip():
            result["has_checkpoint"] = True
        else:
            result["success"] = False
            result["errors"].append("PROJECT_STATE.md não foi alterado neste branch — checkpoint ausente")

        # Worktree no head_sha
        tmp_dir = f"/tmp/gate-validate-{uuid.uuid4().hex[:8]}"
        subprocess.run(["rm", "-rf", tmp_dir])
        r = self._git("worktree", "add", "--detach", tmp_dir, head_sha)
        if r.returncode != 0:
            result["success"] = False
            result["errors"].append(f"git worktree add failed: {r.stderr.strip()}")
            return result

        try:
            # .py alterados: merge_base → head
            r = self._git("diff", merge_base_sha, head_sha, "--name-only", "--", "*.py")
            if r.returncode != 0:
                result["success"] = False
                result["errors"].append(f"git diff py files failed: {r.stderr.strip()}")
                return result

            py_files = [f for f in r.stdout.strip().split('\n') if f.endswith('.py')]
            for pyf in py_files:
                full_path = Path(tmp_dir) / pyf
                if not full_path.exists():
                    continue
                sr = subprocess.run([sys.executable, "-m", "py_compile", str(full_path)],
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

            # Snapshot imutável: head_sha + base_sha
            head_sha = br["sha"]
            if head_sha == "?":
                self._log(f"  {name}: SHA inválido, ignorando")
                continue
            base_sha = self._get_branch_sha("main")
            if base_sha == "?":
                self._log(f"  {name}: não foi possível obter SHA da main")
                continue

            self._log(f"  → {name} head={head_sha[:12]} base={base_sha[:12]}")

            # Validação com merge-base
            ctx = {"success": True, "errors": [], "warnings": [], "has_checkpoint": False}
            merge_base_sha = self._fetch_and_verify(name, head_sha, base_sha, ctx)

            if merge_base_sha is None:
                # Erro no fetch/merge-base — usa ctx parcial p/ feedback
                fb = self._feedback_packet(run_id, name, head_sha, base_sha, "", ctx)
                status = "error"
                desc = "; ".join(ctx["errors"][:2])
            else:
                self._log(f"    merge-base={merge_base_sha[:12]}")
                result = self.validate_commit(name, head_sha, base_sha, merge_base_sha)
                fb = self._feedback_packet(run_id, name, head_sha, base_sha, merge_base_sha, result)

                if fb["overall_status"] == "passed":
                    status, desc = "success", "Validação OK + checkpoint presente"
                elif fb["overall_status"] == "passed_with_warnings":
                    status, desc = "success", "OK (com warnings)"
                elif fb["overall_status"] == "infra_error":
                    status, desc = "error", "; ".join(result["errors"][:2])
                else:
                    status, desc = "failure", "; ".join(result["errors"][:2])

            # Publica status no SHA validado (nunca consulta branch)
            self.set_status(head_sha, status, desc)

            # Cria PR se necessário
            if not self._get_pr_number(name):
                pr_url = self.create_pr(name)
                if pr_url:
                    self._log(f"    PR criado: {pr_url}")

            # Posta ou atualiza comentário (dedup determinístico)
            comment_body = self._format_comment(fb)
            marker = self._make_marker(head_sha, base_sha)
            self._post_or_update(name, comment_body, marker)

    def poll_loop(self, interval: int = 60):
        self._log(f"Iniciando watch (intervalo={interval}s)")
        while True:
            try:
                self.poll_once()
            except Exception as e:
                self._log(f"Erro no poll: {e}")
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
                # Busca último comentário DO GATE (marcado)
                marker_prefix = "<!-- hermes-gate:"
                page = 1
                last_gate = None
                while True:
                    r = self._gh("api",
                        f"repos/{self.repo}/issues/{pr_num}/comments?per_page=100&page={page}",
                        "--jq", ".[] | {id, body}")
                    if r.returncode != 0 or not r.stdout.strip():
                        break
                    for entry in r.stdout.strip().split("\n"):
                        if not entry.strip(): continue
                        try:
                            c = json.loads(entry)
                            if marker_prefix in c.get("body", ""):
                                last_gate = c["body"]
                        except json.JSONDecodeError:
                            continue
                    if len(r.stdout.strip().split("\n")) < 100:
                        break
                    page += 1
                if last_gate:
                    parts.append("=== ÚLTIMO FEEDBACK DO GATE ===\n" + last_gate)

        return (
            "Você está retomando um projeto em andamento. "
            f"Data de captura: {datetime.datetime.utcnow().isoformat()}Z\n\n"
            + "\n\n".join(parts)
        )


# ── CLI ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Hermes GitHub Gate L1")
    sub = parser.add_subparsers(dest="command")

    p_poll = sub.add_parser("poll", help="Poll branches ai/*")
    p_poll.add_argument("--watch", action="store_true")
    p_poll.add_argument("--once", action="store_true")
    p_poll.add_argument("--interval", type=int, default=60)

    p_validate = sub.add_parser("pr-validate", help="Validar branch específico")
    p_validate.add_argument("branch")

    p_restore = sub.add_parser("restore", help="Gerar prompt de retomada")
    p_restore.add_argument("--branch")

    args = parser.parse_args()
    gate = GitHubGate()

    if args.command == "poll":
        if args.watch:
            gate.poll_loop(args.interval)
        else:
            gate.poll_once()
    elif args.command == "pr-validate":
        head_sha = gate._get_branch_sha(args.branch)
        base_sha = gate._get_branch_sha("main")
        if head_sha == "?" or base_sha == "?":
            print("Erro: branch não encontrado")
            sys.exit(1)
        ctx = {"success": True, "errors": [], "warnings": [], "has_checkpoint": False}
        merge_base = gate._fetch_and_verify(args.branch, head_sha, base_sha, ctx)
        if not merge_base:
            fb = gate._feedback_packet("cli", args.branch, head_sha, base_sha, "", ctx)
        else:
            result = gate.validate_commit(args.branch, head_sha, base_sha, merge_base)
            fb = gate._feedback_packet("cli", args.branch, head_sha, base_sha, merge_base, result)
        print(json.dumps(fb, indent=2))
        sys.exit(0 if fb["overall_status"] in ("passed", "passed_with_warnings") else 1)
    elif args.command == "restore":
        print(gate.restore_prompt(args.branch if hasattr(args, 'branch') and args.branch else None))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
