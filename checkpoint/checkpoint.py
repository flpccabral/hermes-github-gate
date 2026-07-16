#!/usr/bin/env python3
"""checkpoint.py — stdlib-only checkpoint/restore para o GitHub Gate."""
import subprocess, sys, datetime, pathlib

STATE = pathlib.Path("PROJECT_STATE.md")

def checkpoint(tier: str, msg: str, state_body: str) -> str:
    """Salva estado, commita e retorna SHA."""
    header = (f"# PROJECT STATE — atualizado "
              f"{datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='minutes')} "
              f"por {tier}\n\n")
    STATE.write_text(header + state_body, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "commit", "-m", f"checkpoint({tier}): {msg}"], check=True)
    subprocess.run(["git", "push", "origin", "HEAD"], check=True)
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True, check=True).stdout.strip()
    return sha

def restore() -> str:
    """Monta prompt de retomada para qualquer modelo."""
    parts = []
    for f in ["PROJECT_STATE.md", "DECISIONS.md", "CONVENTIONS.md", "FILEMAP.md"]:
        p = pathlib.Path(f)
        if p.exists():
            parts.append(f"=== {f} ===\n{p.read_text(encoding='utf-8')}")
    return ("Você está retomando um projeto em andamento. "
            "Leia o estado abaixo e execute APENAS a próxima ação listada. "
            "Não contradiga DECISIONS.md sem adicionar uma entrada de revogação.\n\n"
            + "\n\n".join(parts))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python checkpoint.py [save|restore] [tier] [msg]")
        sys.exit(1)
    
    action = sys.argv[1]
    if action == "restore":
        print(restore())
    elif action == "save":
        if len(sys.argv) < 4:
            print("Uso: python checkpoint.py save <tier> <msg>")
            sys.exit(1)
        tier = sys.argv[2]
        msg = sys.argv[3]
        state_body = sys.stdin.read()
        sha = checkpoint(tier, msg, state_body)
        print(f"✅ checkpoint({tier}): {msg} — {sha}")
    else:
        print(f"Ação desconhecida: {action}")
        sys.exit(1)
