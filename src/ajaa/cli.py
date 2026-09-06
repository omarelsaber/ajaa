"""
src/ajaa/cli.py

AJAA command-line interface.

Commands:
    ajaa init          Create data/config directories, store API key
    ajaa doctor        Probe the installation and report health
    ajaa serve         Start the web UI
    ajaa version       Print version

Usage:
    uv run ajaa init
    uv run ajaa doctor
    uv run ajaa serve
"""
from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="ajaa",
    help="Autonomous Job Application Agent — local-first, open-source.",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()
err_console = Console(stderr=True)


# ── ajaa version ──────────────────────────────────────────────────────────────

@app.command()
def version() -> None:
    """Print the AJAA version."""
    from importlib.metadata import version as pkg_version
    try:
        v = pkg_version("ajaa")
    except Exception:
        v = "dev"
    console.print(f"ajaa {v}")


# ── ajaa init ─────────────────────────────────────────────────────────────────

@app.command()
def init(
    set_api_key: bool = typer.Option(False, "--set-api-key", help="Store/update the API key in OS keychain"),
    data_dir: str | None = typer.Option(None, "--data-dir", help="Override data directory"),
    config_dir: str | None = typer.Option(None, "--config-dir", help="Override config directory"),
) -> None:
    """
    Initialize AJAA: create directories and verify the installation.

    Run this once after cloning. Safe to re-run — directories are created
    with exist_ok=True. No data is deleted.
    """
    from ajaa.bootstrap import init_directories
    from ajaa.config import _default_config_dir, _default_data_dir

    d_dir = Path(data_dir) if data_dir else _default_data_dir()
    c_dir = Path(config_dir) if config_dir else _default_config_dir()

    console.print(f"\n[bold]AJAA Init[/bold]")
    console.print(f"  data_dir:   [cyan]{d_dir}[/cyan]")
    console.print(f"  config_dir: [cyan]{c_dir}[/cyan]")
    console.print()

    result = init_directories(data_dir=d_dir, config_dir=c_dir)

    for check in result.checks:
        icon = "[green]OK[/green]" if check.passed else "[red]FAIL[/red]"
        console.print(f"  {icon}  {check.message}")
        if not check.passed and check.fix:
            console.print(f"       [dim]Fix: {check.fix}[/dim]")

    if set_api_key:
        _prompt_api_key()

    if result.ok:
        console.print(f"\n[green]Init complete.[/green] Run [cyan]ajaa doctor[/cyan] for a full health check.")
    else:
        console.print(f"\n[red]Init finished with errors.[/red] Fix the items above before running AJAA.")
        raise typer.Exit(code=1)


def _prompt_api_key() -> None:
    """Interactively store the API key in the OS keychain."""
    from ajaa.secrets.keychain import exists, store

    console.print()
    if exists("agent_router_api_key"):
        overwrite = typer.confirm("API key already stored. Overwrite?", default=False)
        if not overwrite:
            console.print("[dim]Keeping existing key.[/dim]")
            return

    key = typer.prompt("Paste API key", hide_input=True)
    store("agent_router_api_key", key)
    console.print("[green]API key stored in OS keychain.[/green]")


# ── ajaa doctor ───────────────────────────────────────────────────────────────

@app.command()
def doctor(
    probe_llm: bool = typer.Option(True, "--probe-llm/--no-probe-llm", help="Make a real LLM test call"),
) -> None:
    """
    Probe the installation and report health.

    Checks directories, API key, Python version, LLM connectivity,
    model IDs, structured output support, and pricing.
    """
    from ajaa.bootstrap import run_checks
    from ajaa.config import _default_config_dir, _default_data_dir

    console.print(f"\n[bold]AJAA Doctor[/bold]\n")

    # ── Bootstrap checks ──────────────────────────────────────
    result = run_checks()

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Details")

    for check in result.checks:
        status = "[green]OK[/green]" if check.passed else ("[red]FAIL[/red]" if check.critical else "[yellow]WARN[/yellow]")
        table.add_row(check.name, status, check.message)
        if not check.passed and check.fix:
            table.add_row("", "", f"[dim]Fix: {check.fix}[/dim]")

    console.print(table)

    # ── LLM probe ─────────────────────────────────────────────
    if probe_llm:
        console.print(f"\n[bold]LLM Connectivity[/bold]\n")
        _probe_llm()

    # ── Summary ────────────────────────────────────────────────
    console.print()
    if result.all_passed:
        console.print("[green]All checks passed. AJAA is ready.[/green]")
    elif result.ok:
        console.print("[yellow]Critical checks passed. Some warnings above.[/yellow]")
    else:
        console.print("[red]Critical checks FAILED. Fix errors before using AJAA.[/red]")
        raise typer.Exit(code=1)


def _probe_llm() -> None:
    """Make a real call to each tier and report results."""
    from ajaa.llm.gateway import LLMError, call_llm, get_session_cost
    from ajaa.types import LLMTask, Tier

    tiers = [
        (Tier.CHEAP,  "deepseek-v4-flash",  LLMTask.FIELD_CLASSIFICATION),
        (Tier.STRONG, "claude-opus-5",       LLMTask.CV_EXTRACTION),
    ]

    schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "model_name": {"type": "string"},
        },
        "required": ["status", "model_name"],
        "additionalProperties": False,
    }

    for tier, expected_model, task in tiers:
        try:
            result = call_llm(
                task=task,
                tier=tier,
                system_prompt="You are a health-check responder. Return the requested JSON only.",
                context_block='Respond with {"status": "ok", "model_name": "<your model name>"}',
                response_schema=schema,
                max_tokens=64,
            )
            model_reported = result.get("model_name", "unknown")
            console.print(f"  [green]OK[/green]  {tier.value:8s}  model={model_reported}")
        except LLMError as e:
            console.print(f"  [red]FAIL[/red] {tier.value:8s}  error={e}")
        except Exception as e:
            console.print(f"  [red]FAIL[/red] {tier.value:8s}  unexpected error: {e}")

    cost = get_session_cost()
    console.print(f"\n  Session cost so far: [cyan]${cost:.6f}[/cyan]")


# ── ajaa serve ────────────────────────────────────────────────────────────────

@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address"),
    port: int = typer.Option(8000, help="Port"),
    reload: bool = typer.Option(False, "--reload", help="Enable hot reload (dev mode)"),
) -> None:
    """Start the AJAA web UI."""
    import uvicorn
    console.print(f"[bold]AJAA[/bold] → http://{host}:{port}")
    uvicorn.run(
        "ajaa.web.app:app",
        host=host,
        port=port,
        reload=reload,
    )