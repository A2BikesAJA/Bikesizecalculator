"""
Report Generation for Coattail Investor Tool.

Generates both terminal (rich) and markdown file reports.
"""

import logging
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from config import REPORTS_DIR

logger = logging.getLogger(__name__)
console = Console()


# ─── Signal Formatting ───────────────────────────────────────────────────────


def _signal_display(signal: str) -> str:
    """Convert signal to display string."""
    signals = {
        "GREEN": "[green]GREEN[/green]",
        "YELLOW": "[yellow]YELLOW[/yellow]",
        "RED": "[red]RED[/red]",
        "UNKNOWN": "[dim]?[/dim]",
    }
    return signals.get(signal, "[dim]?[/dim]")


def _signal_plain(signal: str) -> str:
    """Convert signal to plain text for markdown."""
    signals = {
        "GREEN": "GREEN",
        "YELLOW": "YELLOW",
        "RED": "RED",
        "UNKNOWN": "?",
    }
    return signals.get(signal, "?")


def _direction_display(direction: str) -> str:
    """Convert direction to display string with arrow."""
    directions = {
        "Adding": "[green]^ Adding[/green]",
        "Reducing": "[red]v Reducing[/red]",
        "Steady": "[dim]> Steady[/dim]",
    }
    return directions.get(direction, direction)


def _direction_plain(direction: str) -> str:
    """Convert direction to plain text."""
    directions = {
        "Adding": "^ Adding",
        "Reducing": "v Reducing",
        "Steady": "> Steady",
    }
    return directions.get(direction, direction)


# ─── Terminal Report (Rich) ──────────────────────────────────────────────────


def print_report(consensus: dict) -> None:
    """Print the full consensus report to the terminal using Rich."""
    quarter = consensus.get("quarter", "Unknown")
    total_inv = consensus.get("total_investors", 0)
    active_inv = consensus.get("investors_with_data", 0)
    report_date = datetime.now().strftime("%Y-%m-%d")

    # Header
    header_text = Text()
    header_text.append("COATTAIL INVESTOR", style="bold cyan")
    header_text.append(f" -- {quarter} REPORT\n", style="bold")
    header_text.append(f"Data as of: 13F filings through {quarter}\n", style="dim")
    header_text.append(f"Report generated: {report_date}\n", style="dim")
    header_text.append(
        f"FILING STATUS: {active_inv}/{total_inv} tracked investors have data",
        style="yellow",
    )

    console.print()
    console.print(Panel(header_text, border_style="cyan", expand=True))

    # ── Top Consensus Picks ──────────────────────────────────────────────
    _print_top_consensus(consensus)

    # ── New Positions to Watch ───────────────────────────────────────────
    _print_new_consensus(consensus)

    # ── High Conviction Overlap ──────────────────────────────────────────
    _print_high_conviction(consensus)

    # ── Smart Money Momentum ─────────────────────────────────────────────
    _print_smart_momentum(consensus)

    # ── Exit Warnings ────────────────────────────────────────────────────
    _print_exit_warnings(consensus)

    # ── Watchlist ────────────────────────────────────────────────────────
    _print_watchlist(consensus)

    console.print()


def _print_top_consensus(consensus: dict) -> None:
    """Print top consensus picks table."""
    picks = consensus.get("top_consensus", [])
    if not picks:
        console.print("\n[dim]No consensus picks found.[/dim]")
        return

    console.print()
    console.rule("[bold cyan]TOP CONSENSUS PICKS[/bold cyan]")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Rank", justify="center", width=4)
    table.add_column("Ticker", style="bold", width=8)
    table.add_column("Company", width=24)
    table.add_column("Holders", justify="center", width=9)
    table.add_column("Avg Wt", justify="right", width=8)
    table.add_column("Direction", width=12)
    table.add_column("Valuation", width=12)
    table.add_column("Score", justify="right", width=7)

    total_inv = consensus.get("total_investors", 0)

    for i, pick in enumerate(picks, 1):
        val = pick.get("valuation", {})
        val_signal = _signal_display(val.get("signal", "UNKNOWN") if val else "UNKNOWN")
        val_pct = val.get("price_change_pct", "") if val else ""
        val_str = f"{val_signal}"
        if val_pct != "" and val_pct is not None:
            val_str += f" {val_pct:+.0f}%"

        table.add_row(
            str(i),
            pick.get("ticker", "?"),
            _truncate(pick.get("name", "Unknown"), 22),
            f"{pick['num_holders']}/{total_inv}",
            f"{pick['avg_weight']:.1f}%",
            _direction_display(pick.get("direction", "Steady")),
            val_str,
            f"{pick['consensus_score']:.1f}",
        )

    console.print(table)


def _print_new_consensus(consensus: dict) -> None:
    """Print new consensus positions."""
    picks = consensus.get("new_consensus_picks", [])
    if not picks:
        return

    console.print()
    console.rule("[bold green]NEW POSITIONS TO WATCH[/bold green]")
    console.print("[dim](Stocks initiated by 3+ tracked managers this quarter)[/dim]")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Ticker", style="bold", width=8)
    table.add_column("Company", width=24)
    table.add_column("Initiated By", width=40)
    table.add_column("# Initiators", justify="center", width=12)

    for pick in picks:
        table.add_row(
            pick.get("ticker", "?"),
            _truncate(pick.get("name", "Unknown"), 22),
            ", ".join(pick.get("initiated_by", [])),
            str(pick.get("num_initiators", 0)),
        )

    console.print(table)


def _print_high_conviction(consensus: dict) -> None:
    """Print high conviction overlap."""
    picks = consensus.get("high_conviction_overlap", [])
    if not picks:
        return

    console.print()
    console.rule("[bold magenta]HIGH CONVICTION OVERLAP[/bold magenta]")
    console.print("[dim](Stocks in 3+ investors' top 10 holdings)[/dim]")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Ticker", style="bold", width=8)
    table.add_column("Company", width=24)
    table.add_column("In Top 10 Of", width=40)
    table.add_column("Avg Wt", justify="right", width=8)

    for pick in picks:
        table.add_row(
            pick.get("ticker", "?"),
            _truncate(pick.get("name", "Unknown"), 22),
            ", ".join(pick.get("in_top10_of", [])),
            f"{pick.get('avg_weight_in_top10', 0):.1f}%",
        )

    console.print(table)


def _print_smart_momentum(consensus: dict) -> None:
    """Print smart money momentum."""
    picks = consensus.get("smart_money_momentum", [])
    if not picks:
        return

    console.print()
    console.rule("[bold blue]SMART MONEY MOMENTUM[/bold blue]")
    console.print("[dim](Stocks where 3+ investors increased positions)[/dim]")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Ticker", style="bold", width=8)
    table.add_column("Company", width=24)
    table.add_column("Increased By", width=40)
    table.add_column("# Adding", justify="center", width=8)

    for pick in picks:
        table.add_row(
            pick.get("ticker", "?"),
            _truncate(pick.get("name", "Unknown"), 22),
            ", ".join(pick.get("increased_by", [])),
            str(pick.get("num_increasing", 0)),
        )

    console.print(table)


def _print_exit_warnings(consensus: dict) -> None:
    """Print exit warnings."""
    warnings = consensus.get("exit_warnings", [])
    if not warnings:
        return

    console.print()
    console.rule("[bold red]EXIT WARNINGS[/bold red]")
    console.print("[dim](Stocks exited or significantly reduced by 3+ managers)[/dim]")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Ticker", style="bold", width=8)
    table.add_column("Company", width=24)
    table.add_column("Reduced By", width=40)
    table.add_column("Avg Reduction", justify="right", width=12)

    for w in warnings:
        table.add_row(
            w.get("ticker", "?"),
            _truncate(w.get("name", "Unknown"), 22),
            ", ".join(w.get("reduced_by", [])),
            f"{w.get('avg_reduction_pct', 0):.0f}%",
        )

    console.print(table)


def _print_watchlist(consensus: dict) -> None:
    """Print the final actionable watchlist."""
    watchlist = consensus.get("watchlist", [])
    if not watchlist:
        return

    console.print()
    console.rule("[bold yellow]ACTIONABLE WATCHLIST[/bold yellow]")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("#", justify="center", width=3)
    table.add_column("Ticker", style="bold", width=8)
    table.add_column("Company", width=20)
    table.add_column("Score", justify="right", width=6)
    table.add_column("Holders", width=30)
    table.add_column("Dir", width=10)
    table.add_column("Val", width=10)

    for item in watchlist:
        val = item.get("valuation", {})
        val_signal = "UNKNOWN"
        val_pct = ""
        if val:
            val_signal = val.get("signal", "UNKNOWN")
            pct = val.get("price_change_pct")
            if pct is not None:
                val_pct = f" {pct:+.0f}%"

        table.add_row(
            str(item.get("rank", "")),
            item.get("ticker", "?"),
            _truncate(item.get("name", "Unknown"), 18),
            f"{item.get('consensus_score', 0):.1f}",
            _truncate(item.get("holders_display", ""), 28),
            _direction_display(item.get("direction", "Steady")),
            f"{_signal_display(val_signal)}{val_pct}",
        )

    console.print(table)


def print_investor_report(analysis: dict) -> None:
    """Print a single investor's analysis to the terminal."""
    name = analysis.get("investor_name", "Unknown")
    quarter = analysis.get("quarter", "Unknown")
    concentration = analysis.get("concentration", {})

    console.print()
    console.print(Panel(
        f"[bold]{name}[/bold] -- {quarter}\n"
        f"Total positions: {concentration.get('total_positions', 0)} | "
        f"Portfolio: ${concentration.get('total_value_millions', 0):,.0f}M\n"
        f"Top 5: {concentration.get('top_5_pct', 0):.1f}% | "
        f"Top 10: {concentration.get('top_10_pct', 0):.1f}% | "
        f"Turnover: {analysis.get('turnover_rate', 0):.1f}%",
        border_style="cyan",
    ))

    # Top 10
    if analysis.get("top_10"):
        table = Table(title="Top 10 Holdings", show_header=True, header_style="bold")
        table.add_column("#", justify="center", width=3)
        table.add_column("Ticker", style="bold", width=8)
        table.add_column("Company", width=24)
        table.add_column("Value ($K)", justify="right", width=12)
        table.add_column("Weight", justify="right", width=8)

        for i, h in enumerate(analysis["top_10"], 1):
            table.add_row(
                str(i),
                h.get("ticker", "?"),
                _truncate(h.get("name", ""), 22),
                f"{h.get('value_thousands', 0):,}",
                f"{h.get('weight_pct', 0):.1f}%",
            )
        console.print(table)

    # New positions
    if analysis.get("new_positions"):
        console.print(f"\n[green]New Positions ({len(analysis['new_positions'])}):[/green]")
        for h in analysis["new_positions"][:10]:
            console.print(f"  + {h.get('ticker', '?'):6s} {h.get('name', '')}")

    # Exited positions
    if analysis.get("exited_positions"):
        console.print(f"\n[red]Exited Positions ({len(analysis['exited_positions'])}):[/red]")
        for h in analysis["exited_positions"][:10]:
            console.print(f"  - {h.get('ticker', '?'):6s} {h.get('name', '')}")


def print_stock_report(stock_info: dict) -> None:
    """Print a stock lookup report."""
    name = stock_info.get("stock_name", "Unknown")
    ticker = stock_info.get("stock_ticker", "?")
    holders = stock_info.get("holders", [])
    total = stock_info.get("total_tracked", 0)

    console.print()
    console.print(Panel(
        f"[bold]{ticker}[/bold] -- {name}\n"
        f"Held by {len(holders)}/{total} tracked investors",
        border_style="cyan",
    ))

    if holders:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Investor", width=28)
        table.add_column("Shares", justify="right", width=14)
        table.add_column("Value ($K)", justify="right", width=12)
        table.add_column("Weight", justify="right", width=8)
        table.add_column("Quarter", width=10)

        for h in holders:
            table.add_row(
                h.get("investor", ""),
                f"{h.get('shares', 0):,}",
                f"{h.get('value_thousands', 0):,}",
                f"{h.get('weight_pct', 0):.1f}%",
                h.get("quarter", ""),
            )
        console.print(table)
    else:
        console.print("[dim]Not held by any tracked investors.[/dim]")


def print_filing_status(statuses: list[dict]) -> None:
    """Print filing status for all tracked investors."""
    if not statuses:
        console.print("[dim]No filing status data.[/dim]")
        return

    expected = statuses[0].get("expected_quarter", "Unknown")
    filed = sum(1 for s in statuses if s["has_filed"])
    total = len(statuses)

    console.print()
    console.print(Panel(
        f"[bold]13F Filing Status[/bold] -- Expected: {expected}\n"
        f"Filed: {filed}/{total} tracked investors",
        border_style="cyan",
    ))

    table = Table(show_header=True, header_style="bold")
    table.add_column("Status", justify="center", width=6)
    table.add_column("Investor", width=28)
    table.add_column("Latest Quarter", width=14)
    table.add_column("Filing Date", width=12)

    for s in statuses:
        status_icon = "[green]OK[/green]" if s["has_filed"] else "[yellow]WAIT[/yellow]"
        table.add_row(
            status_icon,
            s["name"],
            s.get("latest_quarter", "N/A"),
            s.get("filing_date", "N/A"),
        )

    console.print(table)


# ─── Markdown Report Generation ─────────────────────────────────────────────


def generate_markdown_report(consensus: dict, output_path: str | None = None) -> str:
    """
    Generate a markdown report from consensus analysis.

    Args:
        consensus: Full consensus analysis dict.
        output_path: Optional file path to save the report.

    Returns:
        The markdown string.
    """
    quarter = consensus.get("quarter", "Unknown")
    total_inv = consensus.get("total_investors", 0)
    active_inv = consensus.get("investors_with_data", 0)
    report_date = datetime.now().strftime("%Y-%m-%d")

    lines = []

    lines.append(f"# Coattail Investor Report -- {quarter}")
    lines.append("")
    lines.append(f"**Report generated:** {report_date}")
    lines.append(f"**Filing status:** {active_inv}/{total_inv} tracked investors have data")
    lines.append(f"**Total stocks tracked:** {consensus.get('total_stocks_tracked', 0)}")
    lines.append("")

    # ── Top Consensus Picks ──
    lines.append("## Top Consensus Picks")
    lines.append("")

    picks = consensus.get("top_consensus", [])
    if picks:
        lines.append("| Rank | Ticker | Company | Holders | Avg Weight | Direction | Valuation | Score |")
        lines.append("|------|--------|---------|---------|------------|-----------|-----------|-------|")

        for i, pick in enumerate(picks, 1):
            val = pick.get("valuation", {})
            val_signal = _signal_plain(val.get("signal", "UNKNOWN") if val else "UNKNOWN")
            val_pct = val.get("price_change_pct", "") if val else ""
            val_str = val_signal
            if val_pct != "" and val_pct is not None:
                val_str += f" {val_pct:+.0f}%"

            lines.append(
                f"| {i} | {pick.get('ticker', '?')} | "
                f"{_truncate(pick.get('name', 'Unknown'), 20)} | "
                f"{pick['num_holders']}/{total_inv} | "
                f"{pick['avg_weight']:.1f}% | "
                f"{_direction_plain(pick.get('direction', 'Steady'))} | "
                f"{val_str} | "
                f"{pick['consensus_score']:.1f} |"
            )
        lines.append("")

    # ── New Positions ──
    new_picks = consensus.get("new_consensus_picks", [])
    if new_picks:
        lines.append("## New Positions to Watch")
        lines.append("*Stocks initiated by 3+ tracked managers this quarter*")
        lines.append("")
        lines.append("| Ticker | Company | Initiated By | # Initiators |")
        lines.append("|--------|---------|--------------|--------------|")

        for pick in new_picks:
            lines.append(
                f"| {pick.get('ticker', '?')} | "
                f"{_truncate(pick.get('name', 'Unknown'), 20)} | "
                f"{', '.join(pick.get('initiated_by', []))} | "
                f"{pick.get('num_initiators', 0)} |"
            )
        lines.append("")

    # ── Exit Warnings ──
    warnings = consensus.get("exit_warnings", [])
    if warnings:
        lines.append("## Exit Warnings")
        lines.append("*Stocks exited or significantly reduced by 3+ managers*")
        lines.append("")
        lines.append("| Ticker | Company | Reduced By | Avg Reduction |")
        lines.append("|--------|---------|------------|---------------|")

        for w in warnings:
            lines.append(
                f"| {w.get('ticker', '?')} | "
                f"{_truncate(w.get('name', 'Unknown'), 20)} | "
                f"{', '.join(w.get('reduced_by', []))} | "
                f"{w.get('avg_reduction_pct', 0):.0f}% |"
            )
        lines.append("")

    # ── Watchlist ──
    watchlist = consensus.get("watchlist", [])
    if watchlist:
        lines.append("## Actionable Watchlist")
        lines.append("")
        lines.append("| # | Ticker | Company | Score | Holders | Direction | Valuation | Rationale |")
        lines.append("|---|--------|---------|-------|---------|-----------|-----------|-----------|")

        for item in watchlist:
            val = item.get("valuation", {})
            val_signal = _signal_plain(val.get("signal", "UNKNOWN") if val else "UNKNOWN")
            pct = val.get("price_change_pct") if val else None
            val_str = val_signal
            if pct is not None:
                val_str += f" {pct:+.0f}%"

            lines.append(
                f"| {item.get('rank', '')} | "
                f"{item.get('ticker', '?')} | "
                f"{_truncate(item.get('name', ''), 18)} | "
                f"{item.get('consensus_score', 0):.1f} | "
                f"{_truncate(item.get('holders_display', ''), 25)} | "
                f"{_direction_plain(item.get('direction', 'Steady'))} | "
                f"{val_str} | "
                f"{_truncate(item.get('rationale', ''), 40)} |"
            )
        lines.append("")

    # ── Investor Profiles ──
    investor_analyses = consensus.get("investor_analyses", {})
    if investor_analyses:
        lines.append("## Investor Profiles")
        lines.append("")

        for inv_name, analysis in investor_analyses.items():
            lines.append(f"### {inv_name}")
            conc = analysis.get("concentration", {})
            lines.append(
                f"- **Quarter:** {analysis.get('quarter', 'N/A')} | "
                f"**Positions:** {conc.get('total_positions', 0)} | "
                f"**Value:** ${conc.get('total_value_millions', 0):,.0f}M"
            )
            lines.append(
                f"- **Concentration:** Top 5 = {conc.get('top_5_pct', 0):.1f}%, "
                f"Top 10 = {conc.get('top_10_pct', 0):.1f}%"
            )
            lines.append(f"- **Turnover:** {analysis.get('turnover_rate', 0):.1f}%")
            lines.append("")

            # Top 5 holdings
            top = analysis.get("top_10", [])[:5]
            if top:
                lines.append("| # | Ticker | Company | Weight |")
                lines.append("|---|--------|---------|--------|")
                for i, h in enumerate(top, 1):
                    lines.append(
                        f"| {i} | {h.get('ticker', '?')} | "
                        f"{_truncate(h.get('name', ''), 20)} | "
                        f"{h.get('weight_pct', 0):.1f}% |"
                    )
                lines.append("")

    md_text = "\n".join(lines)

    # Save to file
    if output_path is None:
        output_path = str(REPORTS_DIR / f"report_{quarter}_{report_date}.md")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(md_text)

    logger.info(f"Report saved to {output_path}")
    return md_text


# ─── Portfolio Allocation Report ─────────────────────────────────────────────


def print_allocation(allocation) -> None:
    """Print a portfolio allocation to the terminal using Rich."""
    from allocator import PortfolioAllocation

    console.print()
    console.print(Panel(
        f"[bold cyan]PORTFOLIO ALLOCATION[/bold cyan]\n"
        f"Strategy: [bold]{allocation.strategy}[/bold] | "
        f"Positions: [bold]{allocation.num_positions}[/bold]\n"
        f"Total to invest: [bold green]${allocation.total_investment:,.2f}[/bold green] | "
        f"Cash deployed: [bold]${allocation.cash_invested:,.2f}[/bold] | "
        f"Cash remaining: [yellow]${allocation.cash_remaining:,.2f}[/yellow]\n"
        f"Largest position: {allocation.largest_position_pct:.1f}% | "
        f"Smallest: {allocation.smallest_position_pct:.1f}% | "
        f"Effective positions: {allocation.effective_positions:.1f}",
        border_style="green",
        expand=True,
    ))

    if not allocation.positions:
        console.print("[dim]No positions to allocate.[/dim]")
        return

    # ── Main allocation table ────────────────────────────────────────────
    console.print()
    console.rule("[bold green]POSITION DETAILS[/bold green]")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("#", justify="center", width=3)
    table.add_column("Ticker", style="bold", width=7)
    table.add_column("Company", width=20)
    table.add_column("Weight", justify="right", width=7)
    table.add_column("Dollars", justify="right", width=11)
    table.add_column("Price", justify="right", width=9)
    table.add_column("Shares", justify="right", width=8)
    table.add_column("Score", justify="right", width=6)
    table.add_column("Holders", justify="center", width=7)
    table.add_column("Dir", width=10)
    table.add_column("Val", width=8)

    for i, pos in enumerate(allocation.positions, 1):
        price_str = f"${pos.share_price:,.2f}" if pos.share_price else "N/A"

        if pos.fractional_ok and pos.shares_fractional > 0:
            shares_str = f"{pos.shares_fractional:,.2f}"
        elif pos.shares_whole > 0:
            shares_str = f"{pos.shares_whole:,}"
        else:
            shares_str = "N/A"

        table.add_row(
            str(i),
            pos.ticker,
            _truncate(pos.name, 18),
            f"{pos.final_weight_pct:.1f}%",
            f"${pos.dollar_allocation:,.2f}",
            price_str,
            shares_str,
            f"{pos.consensus_score:.1f}",
            str(pos.num_holders),
            _direction_display(pos.direction),
            _signal_display(pos.valuation_signal),
        )

    console.print(table)

    # ── Summary bar ──────────────────────────────────────────────────────
    console.print()
    total = allocation.total_investment
    invested = allocation.cash_invested
    remaining = allocation.cash_remaining
    pct_deployed = (invested / total * 100) if total > 0 else 0

    bar_width = 40
    filled = int(bar_width * pct_deployed / 100)
    bar = "[green]" + "#" * filled + "[/green]" + "[dim]" + "-" * (bar_width - filled) + "[/dim]"

    console.print(f"  Deployed: {bar} {pct_deployed:.1f}%")
    console.print(
        f"  [green]${invested:,.2f} invested[/green]  |  "
        f"[yellow]${remaining:,.2f} remaining cash[/yellow]"
    )
    console.print()


def print_trades(trades: list[dict]) -> None:
    """Print a rebalancing trade list."""
    if not trades:
        console.print("[dim]No trades required.[/dim]")
        return

    console.print()
    console.rule("[bold yellow]REBALANCING TRADES[/bold yellow]")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Action", justify="center", width=6)
    table.add_column("Ticker", style="bold", width=7)
    table.add_column("Company", width=20)
    table.add_column("Current $", justify="right", width=11)
    table.add_column("Target $", justify="right", width=11)
    table.add_column("Delta $", justify="right", width=11)
    table.add_column("Shares +/-", justify="right", width=10)

    for t in trades:
        if t["action"] == "HOLD":
            action_style = "[dim]HOLD[/dim]"
        elif t["action"] == "BUY":
            action_style = "[green]BUY[/green]"
        else:
            action_style = "[red]SELL[/red]"

        delta_str = f"${t['dollar_delta']:+,.2f}"
        if t["dollar_delta"] > 0:
            delta_str = f"[green]{delta_str}[/green]"
        elif t["dollar_delta"] < 0:
            delta_str = f"[red]{delta_str}[/red]"

        table.add_row(
            action_style,
            t["ticker"],
            _truncate(t.get("name", ""), 18),
            f"${t['current_dollars']:,.2f}",
            f"${t['target_dollars']:,.2f}",
            delta_str,
            f"{t['share_delta']:+,}" if isinstance(t['share_delta'], int) else f"{t['share_delta']:+,.2f}",
        )

    console.print(table)


def generate_allocation_markdown(allocation, output_path: str | None = None) -> str:
    """Generate a markdown report for the portfolio allocation."""
    report_date = datetime.now().strftime("%Y-%m-%d")

    lines = [
        f"# Portfolio Allocation Report",
        "",
        f"**Generated:** {report_date}",
        f"**Strategy:** {allocation.strategy}",
        f"**Total investment:** ${allocation.total_investment:,.2f}",
        f"**Cash deployed:** ${allocation.cash_invested:,.2f}",
        f"**Cash remaining:** ${allocation.cash_remaining:,.2f}",
        f"**Positions:** {allocation.num_positions}",
        f"**Effective positions (1/HHI):** {allocation.effective_positions:.1f}",
        "",
        "## Positions",
        "",
        "| # | Ticker | Company | Weight | Dollars | Price | Shares | Score | Holders | Direction | Valuation |",
        "|---|--------|---------|--------|---------|-------|--------|-------|---------|-----------|-----------|",
    ]

    for i, pos in enumerate(allocation.positions, 1):
        price_str = f"${pos.share_price:,.2f}" if pos.share_price else "N/A"

        if pos.fractional_ok and pos.shares_fractional > 0:
            shares_str = f"{pos.shares_fractional:,.2f}"
        elif pos.shares_whole > 0:
            shares_str = f"{pos.shares_whole:,}"
        else:
            shares_str = "N/A"

        lines.append(
            f"| {i} | {pos.ticker} | "
            f"{_truncate(pos.name, 18)} | "
            f"{pos.final_weight_pct:.1f}% | "
            f"${pos.dollar_allocation:,.2f} | "
            f"{price_str} | "
            f"{shares_str} | "
            f"{pos.consensus_score:.1f} | "
            f"{pos.num_holders} | "
            f"{_direction_plain(pos.direction)} | "
            f"{_signal_plain(pos.valuation_signal)} |"
        )

    lines.append("")
    lines.append(f"**Deployment:** {allocation.cash_invested / allocation.total_investment * 100:.1f}% of capital deployed")
    lines.append("")

    md_text = "\n".join(lines)

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            f.write(md_text)
        logger.info(f"Allocation report saved to {output_path}")

    return md_text


# ─── Simulation Report ───────────────────────────────────────────────────────


def print_simulation(report) -> None:
    """Print the full simulation report to the terminal."""
    from simulator import SimulationReport

    initial = report.initial_investment
    years = report.years

    console.print()
    console.print(Panel(
        f"[bold cyan]COATTAIL INVESTMENT SCENARIO ANALYSIS[/bold cyan]\n"
        f"Initial investment: [bold green]${initial:,.2f}[/bold green] | "
        f"Horizon: [bold]{years} years[/bold]\n"
        f"Monte Carlo simulations: [bold]{report.monte_carlo.num_simulations:,}[/bold]",
        border_style="cyan",
        expand=True,
    ))

    # ── Scenario comparison table ────────────────────────────────────────
    console.print()
    console.rule("[bold cyan]SCENARIO PROJECTIONS[/bold cyan]")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Scenario", width=14)
    table.add_column("Annual Return", justify="right", width=13)
    table.add_column("Volatility", justify="right", width=10)
    table.add_column(f"Value (Yr {years})", justify="right", width=14)
    table.add_column("Total Return", justify="right", width=12)
    table.add_column("Profit", justify="right", width=12)
    table.add_column("CAGR", justify="right", width=7)

    for s in report.scenarios:
        # Color code by scenario type
        if s.name == "bull":
            style = "green"
        elif s.name == "base":
            style = "cyan"
        elif s.name == "bear":
            style = "yellow"
        else:
            style = "red"

        profit_str = f"${s.total_profit:+,.0f}"
        if s.total_profit >= 0:
            profit_style = f"[green]{profit_str}[/green]"
        else:
            profit_style = f"[red]{profit_str}[/red]"

        table.add_row(
            f"[{style}]{s.label}[/{style}]",
            f"{s.annual_return * 100:.1f}%",
            f"{s.annual_volatility * 100:.0f}%",
            f"[{style}]${s.final_value:,.0f}[/{style}]",
            f"{s.total_return_pct:+.1f}%",
            profit_style,
            f"{s.cagr:.1f}%",
        )

    console.print(table)

    # ── Year-by-year breakdown ───────────────────────────────────────────
    console.print()
    console.rule("[bold cyan]YEAR-BY-YEAR GROWTH[/bold cyan]")
    console.print()

    yr_table = Table(show_header=True, header_style="bold")
    yr_table.add_column("Year", justify="center", width=5)
    for s in report.scenarios:
        yr_table.add_column(s.label, justify="right", width=14)

    # Start row
    yr_table.add_row("0", *[f"${initial:,.0f}" for _ in report.scenarios])

    for yr in range(years):
        row = [str(yr + 1)]
        for s in report.scenarios:
            val = s.yearly[yr].ending_value
            ret = s.yearly[yr].annual_return_pct
            row.append(f"${val:,.0f} ({ret:+.1f}%)")
        yr_table.add_row(*row)

    console.print(yr_table)

    # ── Monte Carlo results ──────────────────────────────────────────────
    mc = report.monte_carlo

    console.print()
    console.rule("[bold magenta]MONTE CARLO SIMULATION[/bold magenta]")
    console.print(f"[dim]  {mc.num_simulations:,} simulated paths | "
                  f"Base: {mc.annual_return * 100:.0f}% return, "
                  f"{mc.annual_volatility * 100:.0f}% volatility[/dim]")
    console.print()

    # Outcome distribution
    dist_table = Table(show_header=True, header_style="bold", title="Outcome Distribution")
    dist_table.add_column("Percentile", justify="center", width=12)
    dist_table.add_column(f"Portfolio Value (Yr {years})", justify="right", width=20)
    dist_table.add_column("Total Return", justify="right", width=12)
    dist_table.add_column("Profit/Loss", justify="right", width=14)

    percentiles = [
        ("5th (worst)", mc.p5),
        ("10th", mc.p10),
        ("25th", mc.p25),
        ("50th (median)", mc.p50),
        ("75th", mc.p75),
        ("90th", mc.p90),
        ("95th (best)", mc.p95),
        ("Mean", mc.mean),
    ]

    for label, val in percentiles:
        ret = (val - initial) / initial * 100
        profit = val - initial
        profit_str = f"${profit:+,.0f}"
        if profit >= 0:
            profit_style = f"[green]{profit_str}[/green]"
        else:
            profit_style = f"[red]{profit_str}[/red]"

        dist_table.add_row(
            label,
            f"${val:,.0f}",
            f"{ret:+.1f}%",
            profit_style,
        )

    console.print(dist_table)

    # Probability metrics
    console.print()
    console.print("[bold]Probability Analysis:[/bold]")
    console.print(f"  [green]Chance of profit:        {mc.prob_profit:.1f}%[/green]")
    console.print(f"  [green]Chance of doubling:      {mc.prob_double:.1f}%[/green]")
    console.print(f"  [yellow]Chance of 10%+ loss:     {mc.prob_loss_10pct:.1f}%[/yellow]")
    console.print(f"  [red]Chance of 25%+ loss:     {mc.prob_loss_25pct:.1f}%[/red]")

    # ASCII median-path chart
    console.print()
    _print_growth_chart(mc, initial, years)

    # Bottom line
    console.print()
    console.print(Panel(
        f"[bold]BOTTOM LINE[/bold] for [green]${initial:,.0f}[/green] over {years} years:\n"
        f"  Most likely outcome (median): [bold]${mc.p50:,.0f}[/bold] "
        f"([green]{(mc.p50 - initial) / initial * 100:+.1f}%[/green])\n"
        f"  Expected value (mean):        [bold]${mc.mean:,.0f}[/bold] "
        f"([green]{(mc.mean - initial) / initial * 100:+.1f}%[/green])\n"
        f"  Realistic range (10th-90th):  "
        f"${mc.p10:,.0f} to ${mc.p90:,.0f}",
        border_style="green",
    ))
    console.print()


def _print_growth_chart(mc, initial: float, years: int) -> None:
    """Print an ASCII chart of the median growth path with p25/p75 bands."""
    console.rule("[bold]PROJECTED GROWTH PATH[/bold]")
    console.print("[dim]  Shaded area = 25th-75th percentile range[/dim]")
    console.print()

    chart_height = 15
    chart_width = min(years * 10, 60)

    # Collect all values for scaling
    all_vals = mc.p25_path + mc.p75_path + mc.median_path
    min_val = min(all_vals) * 0.95
    max_val = max(all_vals) * 1.05
    val_range = max_val - min_val
    if val_range == 0:
        val_range = 1

    # Build chart rows (top = high value, bottom = low value)
    rows = []
    for row in range(chart_height):
        threshold = max_val - (row / (chart_height - 1)) * val_range
        line = ""

        for yr in range(years + 1):
            # Map year to x position
            col_width = chart_width // years if years > 0 else chart_width
            median_v = mc.median_path[yr]
            p25_v = mc.p25_path[yr]
            p75_v = mc.p75_path[yr]

            if abs(median_v - threshold) <= val_range / chart_height:
                line += "[bold cyan]*[/bold cyan]"
            elif p25_v <= threshold <= p75_v:
                line += "[dim]:[/dim]"
            else:
                line += " "

            # Fill between years
            if yr < years:
                for _ in range(col_width - 1):
                    # Interpolate between this year and next
                    frac = (_ + 1) / col_width
                    interp_med = median_v + (mc.median_path[yr + 1] - median_v) * frac
                    interp_25 = p25_v + (mc.p25_path[yr + 1] - p25_v) * frac
                    interp_75 = p75_v + (mc.p75_path[yr + 1] - p75_v) * frac

                    if abs(interp_med - threshold) <= val_range / chart_height:
                        line += "[bold cyan]*[/bold cyan]"
                    elif interp_25 <= threshold <= interp_75:
                        line += "[dim]:[/dim]"
                    else:
                        line += " "

        # Y-axis label
        label = f"${threshold:>8,.0f}"
        rows.append(f"  {label} |{line}|")

    for row in rows:
        console.print(row)

    # X-axis
    x_axis = "  " + " " * 9 + "+"
    x_labels = "  " + " " * 9 + " "
    col_width = chart_width // years if years > 0 else chart_width
    for yr in range(years + 1):
        if yr < years:
            x_axis += "-" * col_width
        x_labels += f"Yr{yr}" + " " * max(0, col_width - len(f"Yr{yr}"))
    x_axis += "+"
    console.print(x_axis)
    console.print(x_labels)


def generate_simulation_markdown(report, output_path: str | None = None) -> str:
    """Generate a markdown report for the simulation results."""
    initial = report.initial_investment
    years = report.years
    mc = report.monte_carlo
    report_date = datetime.now().strftime("%Y-%m-%d")

    lines = [
        "# Coattail Investment Scenario Analysis",
        "",
        f"**Generated:** {report_date}",
        f"**Initial investment:** ${initial:,.2f}",
        f"**Horizon:** {years} years",
        f"**Monte Carlo simulations:** {mc.num_simulations:,}",
        "",
        "## Scenario Projections",
        "",
        f"| Scenario | Annual Return | Volatility | Value (Yr {years}) | Total Return | Profit | CAGR |",
        "|----------|---------------|------------|-------------|--------------|--------|------|",
    ]

    for s in report.scenarios:
        lines.append(
            f"| {s.label} | {s.annual_return * 100:.1f}% | "
            f"{s.annual_volatility * 100:.0f}% | "
            f"${s.final_value:,.0f} | {s.total_return_pct:+.1f}% | "
            f"${s.total_profit:+,.0f} | {s.cagr:.1f}% |"
        )

    lines.append("")
    lines.append("## Year-by-Year Growth")
    lines.append("")
    header = "| Year |"
    sep = "|------|"
    for s in report.scenarios:
        header += f" {s.label} |"
        sep += "------------|"
    lines.append(header)
    lines.append(sep)

    row = "| 0 |"
    for _ in report.scenarios:
        row += f" ${initial:,.0f} |"
    lines.append(row)

    for yr in range(years):
        row = f"| {yr + 1} |"
        for s in report.scenarios:
            val = s.yearly[yr].ending_value
            ret = s.yearly[yr].annual_return_pct
            row += f" ${val:,.0f} ({ret:+.1f}%) |"
        lines.append(row)

    lines.append("")
    lines.append("## Monte Carlo Simulation")
    lines.append("")
    lines.append(f"*{mc.num_simulations:,} simulated paths, "
                 f"{mc.annual_return * 100:.0f}% base return, "
                 f"{mc.annual_volatility * 100:.0f}% volatility*")
    lines.append("")
    lines.append("### Outcome Distribution")
    lines.append("")
    lines.append("| Percentile | Portfolio Value | Total Return | Profit/Loss |")
    lines.append("|------------|----------------|--------------|-------------|")

    for label, val in [
        ("5th (worst)", mc.p5), ("10th", mc.p10), ("25th", mc.p25),
        ("50th (median)", mc.p50), ("75th", mc.p75), ("90th", mc.p90),
        ("95th (best)", mc.p95), ("Mean", mc.mean),
    ]:
        ret = (val - initial) / initial * 100
        profit = val - initial
        lines.append(
            f"| {label} | ${val:,.0f} | {ret:+.1f}% | ${profit:+,.0f} |"
        )

    lines.append("")
    lines.append("### Probability Analysis")
    lines.append("")
    lines.append(f"- Chance of profit: **{mc.prob_profit:.1f}%**")
    lines.append(f"- Chance of doubling: **{mc.prob_double:.1f}%**")
    lines.append(f"- Chance of 10%+ loss: **{mc.prob_loss_10pct:.1f}%**")
    lines.append(f"- Chance of 25%+ loss: **{mc.prob_loss_25pct:.1f}%**")
    lines.append("")
    lines.append("### Bottom Line")
    lines.append("")
    lines.append(f"For a **${initial:,.0f}** investment over **{years} years**:")
    lines.append(f"- Most likely outcome (median): **${mc.p50:,.0f}** "
                 f"({(mc.p50 - initial) / initial * 100:+.1f}%)")
    lines.append(f"- Expected value (mean): **${mc.mean:,.0f}** "
                 f"({(mc.mean - initial) / initial * 100:+.1f}%)")
    lines.append(f"- Realistic range (10th-90th): **${mc.p10:,.0f}** to **${mc.p90:,.0f}**")
    lines.append("")

    md_text = "\n".join(lines)

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            f.write(md_text)
        logger.info(f"Simulation report saved to {output_path}")

    return md_text


# ─── Utilities ───────────────────────────────────────────────────────────────


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if too long."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 2] + ".."
