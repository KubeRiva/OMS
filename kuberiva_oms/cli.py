from __future__ import annotations

import shutil
import subprocess
import sys
import time
import webbrowser
from importlib.resources import files
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

from kuberiva_oms import __version__

app = typer.Typer(
    name="kuberiva",
    help="KubeRiva OMS — AI-native order management system",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
console = Console()

# Where kuberiva stores its working files on the user's machine
HOME_DIR = Path.home() / ".kuberiva"
COMPOSE_FILE = HOME_DIR / "docker-compose.yml"
ENV_FILE = HOME_DIR / ".env"

API_HEALTH = "http://localhost:8001/health"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_docker() -> None:
    if shutil.which("docker") is None:
        console.print(Panel(
            "[red]Docker not found.[/red]\n\n"
            "Install Docker Desktop from https://docs.docker.com/get-docker/ then try again.",
            title="Missing dependency",
        ))
        raise typer.Exit(1)
    result = subprocess.run(["docker", "info"], capture_output=True)
    if result.returncode != 0:
        console.print(Panel(
            "[red]Docker daemon is not running.[/red]\n\n"
            "Start Docker Desktop and try again.",
            title="Docker not running",
        ))
        raise typer.Exit(1)


def _ensure_home() -> None:
    HOME_DIR.mkdir(parents=True, exist_ok=True)


def _ensure_compose_file() -> None:
    _ensure_home()
    if not COMPOSE_FILE.exists():
        _copy_bundled_asset("docker-compose.yml", COMPOSE_FILE)


def _ensure_env_file() -> None:
    _ensure_home()
    if not ENV_FILE.exists():
        _copy_bundled_asset(".env.example", ENV_FILE)
        console.print(
            f"\n[yellow]Config file created at:[/yellow] {ENV_FILE}\n"
            "[dim]Edit it to set your secrets before starting in production.[/dim]\n"
        )


def _copy_bundled_asset(name: str, dest: Path) -> None:
    asset = files("kuberiva_oms.assets").joinpath(name)
    dest.write_bytes(asset.read_bytes())


def _compose(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "--env-file", str(ENV_FILE), "-f", str(COMPOSE_FILE), *args],
        check=check,
    )


def _api_ready(timeout: int = 120) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(API_HEALTH, timeout=3)
            if r.status_code == 200:
                return True
        except httpx.RequestError:
            pass
        time.sleep(3)
    return False


def _print_urls() -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="cyan bold")
    table.add_column()
    table.add_row("Frontend dashboard", "http://localhost:3001")
    table.add_row("API docs (Swagger)", "http://localhost:8001/docs")
    table.add_row("Celery Flower",      "http://localhost:5556")
    table.add_row("Default login",      "admin@example.com  /  admin123")
    console.print(Panel(table, title="[green]KubeRiva OMS[/green]", border_style="green"))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command()
def start(
    seed: bool = typer.Option(False, "--seed", "-s", help="Load demo data after services start"),
    open_browser: bool = typer.Option(False, "--open", "-o", help="Open the dashboard in a browser"),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for the API to be healthy before returning"),
) -> None:
    """Start all KubeRiva OMS services."""
    _check_docker()
    _ensure_compose_file()
    _ensure_env_file()

    console.print("[bold]Starting KubeRiva OMS...[/bold]")
    _compose("up", "-d", "--pull", "always")

    if wait:
        console.print("[dim]Waiting for API to be ready...[/dim]", end="")
        if _api_ready():
            console.print(" [green]ready[/green]")
        else:
            console.print(" [yellow]timed out — services may still be starting[/yellow]")

    if seed:
        _run_seed()

    _print_urls()

    if open_browser:
        webbrowser.open("http://localhost:3001")


@app.command()
def stop() -> None:
    """Stop all KubeRiva OMS services."""
    _ensure_compose_file()
    console.print("[yellow]Stopping KubeRiva OMS...[/yellow]")
    _compose("down")
    console.print("[green]Stopped.[/green]")


@app.command()
def restart(
    service: str = typer.Argument(None, help="Restart a single service (default: all)"),
) -> None:
    """Restart all services or a single named service."""
    _check_docker()
    _ensure_compose_file()
    args = ["restart"] + ([service] if service else [])
    _compose(*args)
    console.print("[green]Restarted.[/green]")


@app.command()
def status() -> None:
    """Show running services and their URLs."""
    _ensure_compose_file()
    _compose("ps", check=False)
    console.print()
    _print_urls()


@app.command()
def logs(
    service: str = typer.Argument(None, help="Service name (api, frontend, celery_worker, …)"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Stream logs"),
    tail: int = typer.Option(50, "--tail", "-n", help="Number of lines to show"),
) -> None:
    """View logs from services."""
    _ensure_compose_file()
    args = ["logs", f"--tail={tail}"]
    if follow:
        args.append("--follow")
    if service:
        args.append(service)
    _compose(*args, check=False)


@app.command()
def seed() -> None:
    """Load demo data — nodes, rules, orders, and inventory."""
    _ensure_compose_file()
    _run_seed()


def _run_seed() -> None:
    console.print("[cyan]Loading demo data...[/cyan]")
    _compose("exec", "api", "python", "scripts/seed.py")
    console.print("[green]Demo data loaded.[/green]")


@app.command()
def update() -> None:
    """Pull the latest Docker images and restart services."""
    _check_docker()
    _ensure_compose_file()
    console.print("[cyan]Pulling latest images...[/cyan]")
    _compose("pull")
    _compose("up", "-d")
    console.print("[green]Updated and restarted.[/green]")
    _print_urls()


@app.command()
def open_ui() -> None:
    """Open the KubeRiva OMS dashboard in your default browser."""
    webbrowser.open("http://localhost:3001")


@app.callback(invoke_without_command=True)
def version_flag(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", is_eager=True, help="Show version and exit"),
) -> None:
    if version:
        rprint(f"[cyan]kuberiva-oms[/cyan] [bold]{__version__}[/bold]")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())


if __name__ == "__main__":
    app()
