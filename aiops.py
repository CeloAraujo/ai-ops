"""Generic, dependency-free health checks for HTTP services and commands."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class CheckResult:
    name: str
    kind: str
    status: str
    duration_ms: int
    details: str


def check_http(item: dict[str, Any], timeout: float) -> CheckResult:
    name = str(item.get("name") or item.get("url") or "HTTP check")
    started = time.monotonic()
    request = urllib.request.Request(str(item["url"]), headers={"User-Agent": "AI-Ops/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            code = response.status
            expected = item.get("expected_status", [200, 299])
            if isinstance(expected, int):
                ok = code == expected
            else:
                ok = int(expected[0]) <= code <= int(expected[1])
            status, details = ("ok", f"HTTP {code}") if ok else ("failed", f"HTTP {code}; esperado {expected}")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        status, details = "failed", str(exc)
    return CheckResult(name, "http", status, round((time.monotonic() - started) * 1000), details)


def check_command(item: dict[str, Any], timeout: float) -> CheckResult:
    name = str(item.get("name") or "Command check")
    command = item.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(arg, str) for arg in command):
        raise ValueError(f"'{name}': command deve ser uma lista de argumentos, sem shell")
    started = time.monotonic()
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        output = (completed.stdout or completed.stderr).strip().splitlines()
        details = f"exit code {completed.returncode}" + (f" — {output[-1][:240]}" if output else "")
        status = "ok" if completed.returncode == int(item.get("expected_exit_code", 0)) else "failed"
    except (OSError, subprocess.TimeoutExpired) as exc:
        status, details = "failed", str(exc)
    return CheckResult(name, "command", status, round((time.monotonic() - started) * 1000), details)


def load_config(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Não foi possível ler {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("checks"), list):
        raise ValueError("Configuração inválida: informe um objeto JSON com uma lista 'checks'.")
    return data


def run(config: dict[str, Any], timeout: float) -> list[CheckResult]:
    results = []
    for item in config["checks"]:
        if not isinstance(item, dict):
            raise ValueError("Cada verificação deve ser um objeto JSON.")
        kind = item.get("type")
        if kind == "http" and item.get("url"):
            results.append(check_http(item, timeout))
        elif kind == "command":
            results.append(check_command(item, timeout))
        else:
            raise ValueError(f"Verificação inválida ({item.get('name', 'sem nome')}): type deve ser http ou command.")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Verificador AIOps genérico para serviços HTTP e comandos de saúde.")
    parser.add_argument("config", nargs="?", type=Path, default=Path("aiops.config.json"), help="Arquivo de configuração JSON")
    parser.add_argument("--timeout", type=float, default=5.0, help="Timeout em segundos por verificação (padrão: 5)")
    parser.add_argument("--json", action="store_true", help="Imprime o resultado como JSON")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout deve ser maior que zero")
    try:
        results = run(load_config(args.config), args.timeout)
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"service": "AI-Ops", "status": "ok" if all(x.status == "ok" for x in results) else "degraded", "checks": [asdict(x) for x in results]}, ensure_ascii=False, indent=2))
    else:
        print("AI-Ops — resultado das verificações")
        for result in results:
            marker = "OK" if result.status == "ok" else "FALHA"
            print(f"[{marker}] {result.name} ({result.duration_ms} ms): {result.details}")
        print(f"\n{sum(x.status == 'ok' for x in results)}/{len(results)} verificações aprovadas")
    return 0 if all(x.status == "ok" for x in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
