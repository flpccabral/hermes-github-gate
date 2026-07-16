#!/usr/bin/env python3
"""
github_gate.py — Hermes GitHub Gate MVP

Bridge entre web AIs (Claude/ChatGPT via GitHub) e execução local.
Polla branches ai/*, valida, abre PRs, seta status checks.

Uso CLI:
    python github_gate.py poll --once        # verifica branches uma vez
    python github_gate.py poll --watch        # loop contínuo
    python github_gate.py restore             # gera prompt de retomada
    python github_gate.py pr-validate <branch> # valida um branch específico

Uso como plugin Hermes:
    from gate.github_gate import GitHubGate
    gate = GitHubGate()
    gate.poll_once()
"""
import argparse, datetime, json, os, subprocess, sys, time
from typing import Optional, List
from pathlib import Path

REPO = "flpccabral/hermes-github-gate"
STATE_FILES = ["PROJECT_STATE.md", "DECISIONS.md", "CONVENTIONS.md", "FILEMAP.md"]
BRANCH_PREFIX = "ai/"


class GitHubGate:
    """GitHub Gate: monitora branches ai/*, valida, abre PRs, seta status."""

    def __init__(self, repo: str = REPO, gh_cmd: str = "gh"):
        self.repo = repo
        self.gh = gh_cmd
        self._check_gh()

    # ── helpers ──────────────────────────────────────────────

    def _check_gh(self):
        """Verifica se gh CLI está autenticado."""
        r = subprocess.run([self.gh, "auth", "status"], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("gh CLI not authenticated")

    def _gh(self, *args: str) -> subprocess.CompletedProcess:
        """Executa comando gh."""
        return subprocess.run([self.gh, *args], capture_output=True, text=True)

    def _log(self, msg: str):
        print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}")

    # ── branch polling ────────────────────────────────────────

    def list_branches(self) -> list[dict]:
        """Lista branches ai/* com último commit SHA."""
        r = self._gh("api", f"repos/{self.repo}/branches")
        if r.returncode != 0:
            self._log(f"Erro listing branches: {r.stderr.strip()}")
            return []
        branches = json.loads(r.stdout)
        ai_branches = []
        for b in branches:
            name = b["name"]
            if name.startswith(BRANCH_PREFIX) and name != "main":
                ai_branches.append({
                    "name": name,
                    "sha": b["commit"]["sha"],
                    "date": b["commit"]["commit"]["author"]["date"],
                })
        return ai_branches

    def get_branch_diff(self, branch: str, base: str = "main") -> list[dict]:
        """Retorna arquivos modificados no branch vs base."""
        r = self._gh("api", f"repos/{self.repo}/compare/{base}...{branch}")
        if r.returncode != 0:
            return []
        data = json.loads(r.stdout)
        return [f for f in data.get("files", [])]

    # ── PR management ─────────────────────────────────────────

    def has_open_pr(self, branch: str) -> bool:
        """Verifica se já existe PR aberto para o branch."""
        r = self._gh("pr", "list", "--repo", self.repo,
                      "--head", branch, "--state", "open",
                      "--json", "number")
        if r.returncode != 0:
            return False
        prs = json.loads(r.stdout)
        return len(prs) > 0

    def create_pr(self, branch: str) -> Optional[str]:
        """Cria PR para o branch. Retorna URL ou None."""
        if self.has_open_pr(branch):
            self._log(f"PR já existe para {branch}")
            return None

        # Gera título da branch: ai/claude/descricao → descricao
        title = branch.replace("ai/claude/", "").replace("ai/", "").replace("-", " ").title()
        title = f"feat: {title}"

        r = self._gh("pr", "create", "--repo", self.repo,
                      "--head", branch, "--base", "main",
                      "--title", title,
                      "--body", f"🤖 PR automático do branch `{branch}`.\n\nAguardando validação do Hermes Gate.")
        if r.returncode != 0:
            self._log(f"Erro criando PR: {r.stderr.strip()}")
            return None
        return r.stdout.strip()

    def post_pr_comment(self, branch: str, body: str):
        """Posta comentário no PR associado ao branch.
        Só posta se ainda não postou o mesmo body (evita spam a cada poll)."""
        r = self._gh("pr", "list", "--repo", self.repo,
                      "--head", branch, "--state", "open",
                      "--json", "number", "--jq", ".[0].number")
        if not r.stdout.strip():
            return
        pr_num = r.stdout.strip()
        
        # Verifica comentários existentes para evitar duplicação
        comments = self._gh("api", f"repos/{self.repo}/issues/{pr_num}/comments",
                           "--jq", ".[].body")
        if comments.returncode == 0 and body.strip() in comments.stdout:
            return  # Já postou este conteúdo
        
        self._gh("pr", "comment", "--repo", self.repo, pr_num, "--body", body)

    # ── validation ────────────────────────────────────────────

    def validate_branch(self, branch: str, base: str = "main") -> dict:
        """Valida um branch. Verifica diff-based se PROJECT_STATE.md foi alterado."""
        result = {"success": True, "errors": [], "warnings": [], "has_checkpoint": False}

        # Fetch branch
        subprocess.run(["git", "fetch", "origin", branch, base], capture_output=True)

        # Diff: verifica se PROJECT_STATE.md foi modificado no branch vs base
        diff = subprocess.run(
            ["git", "diff", f"origin/{base}...origin/{branch}", "--", "PROJECT_STATE.md"],
            capture_output=True, text=True
        )
        if diff.stdout.strip():
            result["has_checkpoint"] = True
        else:
            result["success"] = False
            result["errors"].append("PROJECT_STATE.md não foi alterado neste branch — checkpoint ausente")

        # Checkout em worktree temporário para syntax check
        tmp_dir = f"/tmp/gate-validate-{branch.replace('/', '-')}-{int(time.time())}"
        subprocess.run(["rm", "-rf", tmp_dir])
        r = subprocess.run(["git", "worktree", "add", "--detach", tmp_dir, f"origin/{branch}"],
                          capture_output=True, text=True)
        if r.returncode != 0:
            result["errors"].append(f"git worktree add failed: {r.stderr.strip()}")
            return result

        try:
            # Syntax check nos .py alterados (diff-based, não rglob)
            diff_files = subprocess.run(
                ["git", "diff", f"origin/{base}...origin/{branch}", "--name-only", "--", "*.py"],
                capture_output=True, text=True
            )
            py_files = [f for f in diff_files.stdout.strip().split('\n') if f.endswith('.py')]
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
            subprocess.run(["git", "worktree", "remove", "--force", tmp_dir], capture_output=True)

        return result

    # ── status check ──────────────────────────────────────────

    def set_status(self, branch: str, state: str, description: str):
        """Seta status check no commit mais recente do branch.
        state: 'success', 'failure', 'pending', 'error'
        """
        # Pega SHA do branch remoto
        r = self._gh("api", f"repos/{self.repo}/branches/{branch}")
        if r.returncode != 0:
            return
        data = json.loads(r.stdout)
        sha = data["commit"]["sha"]

        context = "hermes-gate/validate"
        self._gh("api", f"repos/{self.repo}/statuses/{sha}",
                 "-f", f"state={state}",
                 "-f", f"context={context}",
                 "-f", f"description={description}")

    # ── polling ────────────────────────────────────────────────

    def poll_once(self):
        """Poll único: verifica branches ai/*, valida, cria PRs, seta status."""
        self._log("Polling branches...")
        branches = self.list_branches()
        if not branches:
            self._log("Nenhum branch ai/* encontrado")
            return

        for br in branches:
            name = br["name"]
            self._log(f"  → {name} ({br['sha'][:8]})")

            # Valida
            result = self.validate_branch(name)

            # Seta status
            if result["success"] and result["has_checkpoint"]:
                self.set_status(name, "success", "Validação OK + checkpoint presente")
            elif result["success"] and not result["has_checkpoint"]:
                self.set_status(name, "failure", "PROJECT_STATE.md ausente ou incompleto")
            else:
                self.set_status(name, "failure", "; ".join(result["errors"][:2]))

            # Cria PR se passou na validação
            if result["success"] and not self.has_open_pr(name):
                pr_url = self.create_pr(name)
                if pr_url:
                    self._log(f"    PR criado: {pr_url}")

            # Posta resumo
            if result["errors"] or result["warnings"]:
                body = "## 🔍 Validação do Gate\n"
                if result["errors"]:
                    body += "### ❌ Erros\n" + "\n".join(f"- {e}" for e in result["errors"]) + "\n"
                if result["warnings"]:
                    body += "### ⚠️ Avisos\n" + "\n".join(f"- {w}" for w in result["warnings"]) + "\n"
                if result["has_checkpoint"]:
                    body += "✅ Checkpoint presente\n"
                self.post_pr_comment(name, body)

    def poll_loop(self, interval: int = 60):
        """Loop contínuo de polling."""
        self._log(f"Iniciando watch (intervalo={interval}s)")
        while True:
            try:
                self.poll_once()
            except Exception as e:
                self._log(f"Erro no poll: {e}")
            time.sleep(interval)

    # ── restore ────────────────────────────────────────────────

    def restore_prompt(self) -> str:
        """Gera prompt de retomada para qualquer modelo."""
        parts = []
        for fname in STATE_FILES:
            p = Path(fname)
            if p.exists():
                parts.append(f"=== {fname} ===\n{p.read_text(encoding='utf-8')}")
        return (
            "Você está retomando um projeto em andamento. "
            "Leia o estado abaixo e execute APENAS a próxima ação listada. "
            "Não contradiga DECISIONS.md sem adicionar uma entrada de revogação.\n\n"
            + "\n\n".join(parts)
        )


# ── CLI ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Hermes GitHub Gate")
    sub = parser.add_subparsers(dest="command")

    p_poll = sub.add_parser("poll", help="Poll branches ai/*")
    p_poll.add_argument("--watch", action="store_true", help="Loop contínuo")
    p_poll.add_argument("--once", action="store_true", help="Apenas uma vez")
    p_poll.add_argument("--interval", type=int, default=60, help="Intervalo em segundos")

    p_validate = sub.add_parser("pr-validate", help="Validar branch específico")
    p_validate.add_argument("branch", help="Nome do branch")

    sub.add_parser("restore", help="Gerar prompt de retomada")

    args = parser.parse_args()
    gate = GitHubGate()

    if args.command == "poll":
        if args.watch:
            gate.poll_loop(args.interval)
        else:
            gate.poll_once()

    elif args.command == "pr-validate":
        result = gate.validate_branch(args.branch)
        print(json.dumps(result, indent=2))
        if not result["success"]:
            sys.exit(1)

    elif args.command == "restore":
        print(gate.restore_prompt())

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
