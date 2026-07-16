#!/usr/bin/env python3
"""
github_gate.py — Hermes GitHub Gate L1 (correções pós-2º juiz)

Bridge entre web AIs (Claude/ChatGPT via GitHub) e execução local.
Polla branches ai/*, valida SHA fixo, abre PRs, seta status checks.

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
import argparse, datetime, json, os, subprocess, sys, time, uuid
from typing import Optional
from pathlib import Path

REPO = "flpccabral/hermes-github-gate"
STATE_FILES = ["PROJECT_STATE.md", "DECISIONS.md", "CONVENTIONS.md", "FILEMAP.md"]
BRANCH_PREFIX = "ai/"
FB_MARKER_START = "<!-- hermes-gate:feedback:"
FB_MARKER_END = ":end -->"


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

    def _git(self, *args, **kwargs) -> subprocess.CompletedProcess:
        """git wrapper que já loga erros."""
        cmd = ["git"] + [str(a) for a in args]
        r = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
        return r

    # ── Feedback Packet ──────────────────────────────────────

    def _feedback_packet(self, run_id: str, branch: str,
                         head_sha: str, base_sha: str,
                         result: dict) -> dict:
        """Gera Feedback Packet estruturado com schema version."""
        # overall_status: 'passed' | 'failed' | 'infra_error'
        if not result["success"]:
            # Erros de infra vs código
            infra_errors = [e for e in result["errors"]
                          if any(k in e.lower() for k in ("git ", "worktree", "fetch", "api", "timeout"))]
            overall = "infra_error" if infra_errors else "failed"
        elif result["warnings"]:
            overall = "passed_with_warnings"
        else:
            overall = "passed"

        return {
            "schema_version": "1.0",
            "run_id": run_id,
            "branch": branch,
            "head_sha": head_sha,
            "base_sha": base_sha,
            "level": "L1",
            "overall_status": overall,
            "checkpoint_present": result.get("has_checkpoint", False),
            "errors": [{"code": f"ERR{i:02d}", "message": e}
                      for i, e in enumerate(result.get("errors", []))],
            "warnings": [{"code": f"WRN{i:02d}", "message": w}
                        for i, w in enumerate(result.get("warnings", []))],
            "next_action": {
                "passed": "merge",
                "passed_with_warnings": "review_warnings",
                "failed": "fix_code",
                "infra_error": "retry",
            }.get(overall, "unknown"),
            "timestamps": {
                "poll_utc": datetime.datetime.utcnow().isoformat() + "Z",
            }
        }

    def _format_feedback_comment(self, fb: dict) -> str:
        """Formata comentário do PR com marcador estruturado."""
        body = "## 🔍 Validação do Gate\n"
        for e in fb.get("errors", []):
            body += f"### ❌ {e['code']}: {e['message']}\n"
        for w in fb.get("warnings", []):
            body += f"### ⚠️ {w['code']}: {w['message']}\n"
        if fb.get("checkpoint_present"):
            body += "✅ Checkpoint presente\n"
        body += f"\n**Status**: {fb['overall_status']} | **Próxima ação**: {fb['next_action']}\n"

        # Marcador estruturado para dedup machine-readable
        marker = (f"{FB_MARKER_START}{fb['run_id']}:{fb['head_sha']}:{fb['base_sha']}:{fb['overall_status']}"
                  f"{FB_MARKER_END}")
        body += f"\n{marker}\n"
        body += "\n```json\n" + json.dumps(fb, indent=2) + "\n```"
        return body

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
            commit_info = b.get("commit", {}) or {}
            ai_branches.append({
                "name": name,
                "sha": commit_info.get("sha", "?"),
                "date": commit_info.get("commit", {}).get("author", {}).get("date", "?"),
            })
        return ai_branches

    # ── PR management ─────────────────────────────────────────

    def has_open_pr(self, branch: str) -> bool:
        r = self._gh("pr", "list", "--repo", self.repo,
                      "--head", branch, "--state", "open", "--json", "number")
        return r.returncode == 0 and len(json.loads(r.stdout)) > 0

    def create_pr(self, branch: str) -> Optional[str]:
        if self.has_open_pr(branch):
            return None
        title = branch.replace("ai/claude/", "").replace("ai/", "").replace("-", " ").title()
        title = f"feat: {title}"
        r = self._gh("pr", "create", "--repo", self.repo,
                      "--head", branch, "--base", "main",
                      "--title", title,
                      "--body", f"🤖 PR automático do branch `{branch}`.\n\nAguardando validação do Hermes Gate.")
        return r.stdout.strip() if r.returncode == 0 else None

    def has_processed_run(self, pr_num: str, marker: str) -> bool:
        """Verifica se marcador já existe nos comentários (dedup estruturado)."""
        r = self._gh("api", f"repos/{self.repo}/issues/{pr_num}/comments",
                     "--jq", ".[].body")
        return r.returncode == 0 and marker in r.stdout

    def post_pr_comment(self, branch: str, body: str):
        """Posta comentário no PR. Dedup via marcador estruturado."""
        r = self._gh("pr", "list", "--repo", self.repo,
                      "--head", branch, "--state", "open",
                      "--json", "number", "--jq", ".[0].number")
        if not r.stdout.strip():
            return
        pr_num = r.stdout.strip()

        # Extrai marcador para dedup
        marker = ""
        for line in body.split("\n"):
            if line.startswith(FB_MARKER_START) and FB_MARKER_END in line:
                marker = line.strip()
                break

        if marker and self.has_processed_run(pr_num, marker):
            return

        self._gh("pr", "comment", "--repo", self.repo, pr_num, "--body", body)

    # ── validation (SHA-fixo) ─────────────────────────────────

    def validate_commit(self, branch: str, head_sha: str, base_sha: str) -> dict:
        """Valida um commit específico (head_sha) vs base (base_sha).
        Usa SHAs fixos — nunca origin/branch (evita TOCTOU)."""
        result = {"success": True, "errors": [], "warnings": [], "has_checkpoint": False}

        # Fetch base (main) e branch (por nome, não SHA — SHA não é fetchável diretamente)
        for remote_ref, label in [(f"main", "main"), (f"{branch}", "branch")]:
            r = self._git("fetch", "origin", remote_ref, timeout=30)
            if r.returncode != 0:
                result["success"] = False
                result["errors"].append(f"git fetch {label} failed: {r.stderr.strip()}")
                return result

        # Verifica se os SHAs existem localmente após fetch
        for sha, label in [(head_sha, "head"), (base_sha, "base")]:
            r = self._git("cat-file", "-e", sha)
            if r.returncode != 0:
                result["success"] = False
                result["errors"].append(f"commit {label} ({sha[:12]}) não encontrado localmente após fetch")
                return result

        # Diff-based checkpoint enforcement (SHA fixo)
        r = self._git("diff", base_sha, head_sha, "--", "PROJECT_STATE.md")
        if r.returncode != 0:
            result["success"] = False
            result["errors"].append(f"git diff checkpoint failed: {r.stderr.strip()}")
            return result
        if r.stdout.strip():
            result["has_checkpoint"] = True
        else:
            result["success"] = False
            result["errors"].append("PROJECT_STATE.md não foi alterado neste branch — checkpoint ausente")

        # Worktree no SHA fixo
        tmp_dir = f"/tmp/gate-validate-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        subprocess.run(["rm", "-rf", tmp_dir])
        r = self._git("worktree", "add", "--detach", tmp_dir, head_sha)
        if r.returncode != 0:
            result["success"] = False  # fail-closed
            result["errors"].append(f"git worktree add failed: {r.stderr.strip()}")
            return result

        try:
            # Arquivos .py alterados (diff SHA-fixo)
            r = self._git("diff", base_sha, head_sha, "--name-only", "--", "*.py")
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

    # ── status check (SHA fixo) ───────────────────────────────

    def set_status(self, head_sha: str, state: str, description: str):
        """Publica status no SHA exato que foi validado.
        CRÍTICO: usa head_sha recebido, não consulta branch (evita TOCTOU)."""
        self._gh("api", f"repos/{self.repo}/statuses/{head_sha}",
                 "-f", f"state={state}",
                 "-f", f"context=hermes-gate/validate",
                 "-f", f"description={description}")

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

            # PASSO CRÍTICO: snapshot dos SHAs ANTES da validação
            head_sha = br["sha"]
            if head_sha == "?":
                self._log(f"  {name}: SHA inválido, ignorando")
                continue
            base_sha = self._get_branch_sha("main")
            if base_sha == "?":
                self._log(f"  {name}: não foi possível obter SHA da main")
                continue

            self._log(f"  → {name} head={head_sha[:12]} base={base_sha[:12]} ({run_id})")

            # Valida usando SHAs fixos
            result = self.validate_commit(name, head_sha, base_sha)
            fb = self._feedback_packet(run_id, name, head_sha, base_sha, result)

            # Publica status no SHA validado (nunca consulta branch de novo)
            if fb["overall_status"] == "passed":
                self.set_status(head_sha, "success", "Validação OK + checkpoint presente")
            elif fb["overall_status"] == "passed_with_warnings":
                self.set_status(head_sha, "success", "OK (com warnings)")
            elif fb["overall_status"] == "infra_error":
                self.set_status(head_sha, "error", "; ".join(result["errors"][:2]))
            else:
                self.set_status(head_sha, "failure", "; ".join(result["errors"][:2]))

            # Cria PR se necessário
            if not self.has_open_pr(name):
                pr_url = self.create_pr(name)
                if pr_url:
                    self._log(f"    PR criado: {pr_url}")

            # Posta feedback com dedup por marcador estruturado
            comment = self._format_feedback_comment(fb)
            self.post_pr_comment(name, comment)

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
        """Gera prompt de retomada. Se branch, busca último feedback do Gate."""
        parts = []
        for fname in STATE_FILES:
            p = Path(fname)
            if p.exists():
                parts.append(f"=== {fname} ===\n{p.read_text(encoding='utf-8')}")

        if branch:
            pr_num = self._gh("pr", "list", "--repo", self.repo,
                              "--head", branch, "--state", "open",
                              "--json", "number", "--jq", ".[0].number").stdout.strip()
            if pr_num:
                # Busca último comentário DO GATE (marcado)
                r = self._gh("api", f"repos/{self.repo}/issues/{pr_num}/comments",
                            "--jq", f".[] | select(.body | contains(\"{FB_MARKER_START}\")) | .body")
                if r.stdout.strip():
                    last_gate = r.stdout.strip().split("\n\n")[-1]  # último bloco
                    parts.append(f"=== ÚLTIMO FEEDBACK DO GATE ===\n{last_gate}")

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
    p_restore.add_argument("--branch", help="Branch p/ incluir feedback")

    args = parser.parse_args()
    gate = GitHubGate()

    if args.command == "poll":
        if args.watch:
            gate.poll_loop(args.interval)
        else:
            gate.poll_once()
    elif args.command == "pr-validate":
        base_sha = gate._get_branch_sha("main")
        head_sha = gate._get_branch_sha(args.branch)
        if head_sha == "?":
            print(f"Erro: branch {args.branch} não encontrado")
            sys.exit(1)
        result = gate.validate_commit(args.branch, head_sha, base_sha)
        fb = gate._feedback_packet("cli", args.branch, head_sha, base_sha, result)
        print(json.dumps(fb, indent=2))
        sys.exit(0 if result["success"] else 1)
    elif args.command == "restore":
        print(gate.restore_prompt(args.branch if hasattr(args, 'branch') and args.branch else None))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
