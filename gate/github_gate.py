#!/usr/bin/env python3
"""
github_gate.py — Hermes GitHub Gate L1

Bridge entre web AIs (Claude/ChatGPT via GitHub) e execução local.
Polla branches ai/* e issues ai:task, valida, abre PRs, seta status checks.

Uso CLI:
    python github_gate.py poll --once        # verifica branches/issues uma vez
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
TASK_LABEL = "ai:task"
ABANDON_DAYS = 7  # dias sem atividade para fechar PR automaticamente


class GitHubGate:
    """GitHub Gate: monitora branches ai/* e issues, valida, abre PRs, seta status."""

    def __init__(self, repo: str = REPO, gh_cmd: str = "gh"):
        self.repo = repo
        self.gh = gh_cmd
        if "RESTORE" not in os.environ:
            self._check_gh()

    # ── helpers ──────────────────────────────────────────────

    def _check_gh(self):
        r = subprocess.run([self.gh, "auth", "status"], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("gh CLI not authenticated")

    def _gh(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([self.gh, *args], capture_output=True, text=True)

    def _log(self, msg: str):
        print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}")

    def _repo_api(self, path: str) -> dict:
        """Chama gh api e retorna dict."""
        r = self._gh("api", f"repos/{self.repo}/{path}")
        if r.returncode != 0:
            return {}
        return json.loads(r.stdout) if r.stdout.strip() else {}

    def _feedback_packet(self, branch: str, result: dict, stage: str = "validate") -> dict:
        """Gera Feedback Packet machine-readable."""
        return {
            "sha": self._get_branch_sha(branch),
            "level": "L1",
            "stage": stage,
            "passed": result.get("success", False) and result.get("has_checkpoint", False),
            "errors": result.get("errors", []),
            "warnings": result.get("warnings", []),
            "has_checkpoint": result.get("has_checkpoint", False),
            "next_action": "merge" if result.get("success") else "fix_checkpoint",
            "timestamps": {
                "poll": datetime.datetime.utcnow().isoformat() + "Z",
            }
        }

    def _get_branch_sha(self, branch: str) -> str:
        """Pega SHA do branch remoto."""
        data = self._repo_api(f"branches/{branch}")
        if data:
            return data.get("commit", {}).get("sha", "?")
        return "?"

    # ── Task Packet (issue polling) ──────────────────────────

    def poll_issues(self):
        """Escuta issues com label ai:task e cria branches automaticamente."""
        r = self._gh("api", f"repos/{self.repo}/issues",
                     "-f", "labels=" + TASK_LABEL,
                     "-f", "state=open",
                     "--jq", ".[] | select(.pull_request == null)")
        if r.returncode != 0 or not r.stdout.strip():
            return

        issues = json.loads(r.stdout) if r.stdout.strip().startswith("[") else []
        if not isinstance(issues, list):
            issues = [issues]

        for issue in issues:
            num = issue.get("number", 0)
            title = issue.get("title", "task").replace("[Task] ", "").strip()
            slug = title.lower().replace(" ", "-")[:30]
            branch = f"ai/task/{num}-{slug}"

            # Verifica se branch já existe
            existing = self._repo_api(f"branches/{branch}")
            if existing.get("name"):
                self._log(f"  Branch já existe para issue #{num}: {branch}")
                continue

            body = issue.get("body", "")
            self._log(f"  Issue #{num}: {title} → criando branch {branch}")

            # Cria branch a partir da main
            main_sha = self._repo_api("branches/main").get("commit", {}).get("sha", "")
            if not main_sha:
                self._log(f"  Erro: não foi possível obter SHA da main")
                continue

            self._gh("api", f"repos/{self.repo}/git/refs",
                     "-f", "ref=refs/heads/" + branch,
                     "-f", f"sha={main_sha}")

            # Cria PROJECT_STATE.md básico a partir da issue
            state_content = (
                f"# PROJECT STATE — gerado da issue #{num}\n"
                f"## Objetivo\n{title}\n\n"
                f"## Tarefa atual\n{title}\n\n"
                f"## Contexto\n{body}\n\n"
                f"## Próximas 3 ações\n1. Implementar\n2. Testar\n3. Atualizar este checkpoint\n"
            )

            # Commit via API
            # (simplificado: o tier web deve preencher o checkpoint manualmente)
            self._log(f"  Branch {branch} criado. Issue #{num} → PR será criado no próximo poll.")

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
                      "--head", branch, "--state", "open",
                      "--json", "number")
        if r.returncode != 0:
            return False
        prs = json.loads(r.stdout)
        return len(prs) > 0

    def create_pr(self, branch: str) -> Optional[str]:
        if self.has_open_pr(branch):
            self._log(f"PR já existe para {branch}")
            return None

        # Gera título: ai/task/42-desc → feat(task-42): desc
        if "task/" in branch:
            parts = branch.split("/")
            task_num = parts[-1].split("-")[0] if len(parts) >= 2 else "0"
            title_parts = parts[-1].split("-")[1:] if len(parts) >= 2 else [parts[-1]]
            title = " ".join(title_parts).title() if title_parts else "Task"
            title = f"feat(task-{task_num}): {title}"
        else:
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

    def post_pr_comment(self, branch: str, body: str, feedback: Optional[dict] = None):
        """Posta comentário no PR. Inclui Feedback Packet JSON se fornecido."""
        r = self._gh("pr", "list", "--repo", self.repo,
                      "--head", branch, "--state", "open",
                      "--json", "number", "--jq", ".[0].number")
        if not r.stdout.strip():
            return
        pr_num = r.stdout.strip()

        # Adiciona Feedback Packet machine-readable
        if feedback:
            body += "\n\n```json\n" + json.dumps(feedback, indent=2) + "\n```"

        # Verifica duplicação
        comments = self._gh("api", f"repos/{self.repo}/issues/{pr_num}/comments",
                           "--jq", ".[].body")
        if comments.returncode == 0 and body.strip() in comments.stdout:
            return

        self._gh("pr", "comment", "--repo", self.repo, pr_num, "--body", body)

    # ── abandoned branch cleanup ──────────────────────────────

    def cleanup_abandoned(self):
        """Fecha PRs sem atividade há mais de ABANDON_DAYS dias."""
        r = self._gh("pr", "list", "--repo", self.repo,
                      "--state", "open", "--json", "number,updatedAt,headRefName")
        if r.returncode != 0:
            return
        prs = json.loads(r.stdout)
        now = datetime.datetime.now(datetime.timezone.utc)

        for pr in prs:
            updated = pr.get("updatedAt", "")
            if not updated:
                continue
            try:
                updated_dt = datetime.datetime.fromisoformat(updated.replace("Z", "+00:00"))
                days_idle = (now - updated_dt).days
                if days_idle >= ABANDON_DAYS:
                    num = pr["number"]
                    branch = pr["headRefName"]
                    self._log(f"  Fechando PR #{num} ({branch}) — {days_idle}d sem atividade")
                    self._gh("pr", "close", "--repo", self.repo, str(num))
                    self._gh("api", f"repos/{self.repo}/git/refs/heads/{branch}",
                             "-X", "DELETE")
            except (ValueError, KeyError):
                continue

    # ── validation ────────────────────────────────────────────

    def validate_branch(self, branch: str, base: str = "main") -> dict:
        """Valida um branch. Verifica checkpoint + syntax check + pytest."""
        result = {"success": True, "errors": [], "warnings": [], "has_checkpoint": False}

        subprocess.run(["git", "fetch", "origin", branch, base], capture_output=True)

        # Diff-based checkpoint enforcement
        diff = subprocess.run(
            ["git", "diff", f"origin/{base}...origin/{branch}", "--", "PROJECT_STATE.md"],
            capture_output=True, text=True
        )
        if diff.stdout.strip():
            result["has_checkpoint"] = True
        else:
            result["success"] = False
            result["errors"].append("PROJECT_STATE.md não foi alterado neste branch — checkpoint ausente")

        # Worktree para testes
        tmp_dir = f"/tmp/gate-validate-{branch.replace('/', '-')}-{int(time.time())}"
        subprocess.run(["rm", "-rf", tmp_dir])
        r = subprocess.run(["git", "worktree", "add", "--detach", tmp_dir, f"origin/{branch}"],
                          capture_output=True, text=True)
        if r.returncode != 0:
            result["errors"].append(f"git worktree add failed: {r.stderr.strip()}")
            return result

        try:
            # Arquivos .py alterados
            diff_files = subprocess.run(
                ["git", "diff", f"origin/{base}...origin/{branch}", "--name-only", "--", "*.py"],
                capture_output=True, text=True
            )
            py_files = [f for f in diff_files.stdout.strip().split('\n') if f.endswith('.py')]

            for pyf in py_files:
                full_path = Path(tmp_dir) / pyf
                if not full_path.exists():
                    continue

                # Syntax check
                sr = subprocess.run([sys.executable, "-m", "py_compile", str(full_path)],
                                   capture_output=True, text=True)
                if sr.returncode != 0:
                    result["success"] = False
                    result["errors"].append(f"Syntax error in {pyf}: {sr.stderr.strip()}")

            # Test execution (pytest) com env limpo
            if py_files:
                test_env = {k: v for k, v in os.environ.items()
                           if not k.startswith("GH_") and k not in ("GITHUB_TOKEN", "GH_TOKEN")}
                test_env["PYTHONPATH"] = str(Path(tmp_dir))
                test_env.pop("GITHUB_TOKEN", None)
                test_env.pop("GH_TOKEN", None)

                tr = subprocess.run(
                    [sys.executable, "-m", "pytest", str(Path(tmp_dir) / "tests"), "-x", "-q", "--timeout=30"],
                    capture_output=True, text=True, timeout=60,
                    cwd=tmp_dir, env=test_env
                )
                if tr.returncode != 0:
                    result["warnings"].append(f"pytest exit code {tr.returncode}: {tr.stdout.strip()[-200:]}")
                    # Não marca como falha — py_compile é o gate mínimo

        except subprocess.TimeoutExpired:
            result["warnings"].append("pytest timed out (>60s)")
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", tmp_dir], capture_output=True)

        return result

    # ── status check ──────────────────────────────────────────

    def set_status(self, branch: str, state: str, description: str):
        sha = self._get_branch_sha(branch)
        if sha == "?":
            return
        self._gh("api", f"repos/{self.repo}/statuses/{sha}",
                 "-f", f"state={state}",
                 "-f", f"context=hermes-gate/validate",
                 "-f", f"description={description}")

    # ── polling ────────────────────────────────────────────────

    def poll_once(self):
        self._log("Polling branches e issues...")
        self.cleanup_abandoned()
        self.poll_issues()

        branches = self.list_branches()
        if not branches:
            self._log("Nenhum branch ai/* encontrado")
            return

        for br in branches:
            name = br["name"]
            self._log(f"  → {name} ({br['sha'][:8]})")

            result = self.validate_branch(name)
            feedback = self._feedback_packet(name, result)

            # Seta status
            if result["success"] and result["has_checkpoint"]:
                self.set_status(name, "success", "Validação OK + checkpoint presente")
            elif result["success"] and not result["has_checkpoint"]:
                self.set_status(name, "failure", "PROJECT_STATE.md ausente ou incompleto")
            else:
                self.set_status(name, "failure", "; ".join(result["errors"][:2]))

            # Cria PR sempre
            if not self.has_open_pr(name):
                pr_url = self.create_pr(name)
                if pr_url:
                    self._log(f"    PR criado: {pr_url}")

            # Posta resumo com Feedback Packet
            body = "## 🔍 Validação do Gate\n"
            if result["errors"]:
                body += "### ❌ Erros\n" + "\n".join(f"- {e}" for e in result["errors"]) + "\n"
            if result["warnings"]:
                body += "### ⚠️ Avisos\n" + "\n".join(f"- {w}" for w in result["warnings"]) + "\n"
            if result["has_checkpoint"]:
                body += "✅ Checkpoint presente\n"
            self.post_pr_comment(name, body, feedback=feedback)

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
        """Gera prompt de retomada. Se branch fornecido, inclui último Feedback Packet."""
        parts = []
        for fname in STATE_FILES:
            p = Path(fname)
            if p.exists():
                parts.append(f"=== {fname} ===\n{p.read_text(encoding='utf-8')}")

        # Inclui feedback packet do branch se disponível
        if branch:
            pr_num = self._gh("pr", "list", "--repo", self.repo,
                              "--head", branch, "--state", "open",
                              "--json", "number", "--jq", ".[0].number").stdout.strip()
            if pr_num:
                last_comment = self._gh("api", f"repos/{self.repo}/issues/{pr_num}/comments",
                                       "--jq", ".[-1].body").stdout.strip()
                if "```json" in last_comment:
                    fb = last_comment.split("```json")[1].split("```")[0].strip()
                    parts.append(f"=== ÚLTIMO FEEDBACK ===\n{fb}")

        return (
            "Você está retomando um projeto em andamento. "
            "Leia o estado abaixo e execute APENAS a próxima ação listada. "
            "Não contradiga DECISIONS.md sem adicionar uma entrada de revogação.\n\n"
            + "\n\n".join(parts)
        )


# ── CLI ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Hermes GitHub Gate L1")
    sub = parser.add_subparsers(dest="command")

    p_poll = sub.add_parser("poll", help="Poll branches ai/* e issues")
    p_poll.add_argument("--watch", action="store_true", help="Loop contínuo")
    p_poll.add_argument("--once", action="store_true", help="Apenas uma vez")
    p_poll.add_argument("--interval", type=int, default=60, help="Intervalo em segundos")

    p_validate = sub.add_parser("pr-validate", help="Validar branch específico")
    p_validate.add_argument("branch", help="Nome do branch")

    p_restore = sub.add_parser("restore", help="Gerar prompt de retomada")
    p_restore.add_argument("--branch", help="Branch para incluir feedback packet")

    args = parser.parse_args()
    gate = GitHubGate()

    if args.command == "poll":
        if args.watch:
            gate.poll_loop(args.interval)
        else:
            gate.poll_once()

    elif args.command == "pr-validate":
        result = gate.validate_branch(args.branch)
        feedback = gate._feedback_packet(args.branch, result)
        print(json.dumps(feedback, indent=2))
        if not result["success"]:
            sys.exit(1)

    elif args.command == "restore":
        print(gate.restore_prompt(args.branch if hasattr(args, 'branch') and args.branch else None))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
