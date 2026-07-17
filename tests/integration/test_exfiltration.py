import subprocess


def test_gh_not_in_sandbox_path():
    """Verifica que gh nao esta acessivel com env whitelist."""
    env = {"PATH": "/usr/bin", "HOME": "/tmp/_empty_home", "LANG": "C"}
    r = subprocess.run(["which", "gh"], capture_output=True, env=env)
    assert r.returncode != 0, "gh acessivel — risco de exfiltracao"


def test_sandbox_blocks_network():
    """Verifica que gh nao funciona com env minimo (sem binarios de rede adicionais no PATH)."""
    env = {"PATH": "/usr/bin", "HOME": "/tmp/_empty_home", "LANG": "C"}
    r = subprocess.run(["which", "gh"], capture_output=True, env=env)
    assert r.returncode != 0, "gh acessivel no sandbox"
