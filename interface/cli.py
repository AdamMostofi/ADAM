"""ADAM CLI — rich-based interactive interface."""
from __future__ import annotations

import sys
import subprocess
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from interface.core import ADAMCore


console = Console()


def main():
    core = ADAMCore()

    if len(sys.argv) > 1:
        if sys.argv[1] == "--web":
            console.print("[bold green]Starting ADAM web UI on http://localhost:7860[/bold green]")
            subprocess.run([sys.executable, "-m", "interface.web.app"])
            return
        message = " ".join(sys.argv[1:])
        result = core.chat(message)
        console.print(Panel(result["response"], title="ADAM", border_style="green"))
        return

    console.print(Panel.fit("[bold cyan]ADAM — First Of It's Kind[/bold cyan]\n[dim]Type 'quit' to exit, 'web' to launch UI[/dim]"))

    while True:
        try:
            user_input = Prompt.ask("\n[bold cyan]You[/bold cyan]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        if user_input.strip().lower() in ("quit", "exit", "q"):
            console.print("[dim]Goodbye.[/dim]")
            break
        if user_input.strip().lower() == "web":
            console.print("[bold green]Starting web UI...[/bold green]")
            subprocess.Popen([sys.executable, "-m", "interface.web.app"])
            continue
        if user_input.strip().lower() == "stats":
            _show_stats(core)
            continue

        result = core.chat(user_input)
        tone = result["state"]["emotional_tone"]
        border = "green" if tone == "positive" else "red" if tone == "negative" else "yellow"
        console.print(Panel(result["response"], title=f"ADAM [{tone}]", border_style=border))


def _show_stats(core: ADAMCore):
    stats = core.get_stats()
    table = Table(title="ADAM Stats")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Facts", str(stats["facts"]))
    table.add_row("Skills", str(stats["skills"]))
    table.add_row("Graph Nodes", str(stats["nodes"]))
    table.add_row("Graph Edges", str(stats["edges"]))
    table.add_row("EQ Baseline", f"{stats['baseline']:.2f}")
    table.add_row("Mood Shift", str(stats["mood_shift"]))
    console.print(table)


if __name__ == "__main__":
    main()
