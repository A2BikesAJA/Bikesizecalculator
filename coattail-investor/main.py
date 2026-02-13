#!/usr/bin/env python3
"""
Coattail Investor Research Tool -- CLI Entry Point.

Tracks the holdings and trading patterns of top institutional investors
using SEC 13F filings to identify high-conviction consensus picks.

Usage:
    python main.py fetch              # Fetch latest filings for all tracked investors
    python main.py analyze            # Run analysis and print consensus report
    python main.py run                # Fetch + analyze in one command
    python main.py investor NAME      # Check a specific investor
    python main.py stock TICKER       # Check a specific stock across all investors
    python main.py status             # Check filing status
    python main.py report             # Generate markdown report
    python main.py schedule           # View filing schedule and set up automation
    python main.py allocate 10000     # Build a $10,000 portfolio from consensus picks
"""

import json
import logging
import sys

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from config import DATA_DIR, TRACKED_INVESTORS, get_investor_by_name

logger = logging.getLogger(__name__)
console = Console()


def _load_cached_data() -> dict[str, list[dict]]:
    """Load all cached investor holdings data."""
    all_data = {}
    for investor in TRACKED_INVESTORS:
        cache_file = DATA_DIR / f"holdings_{investor['cik']}.json"
        if cache_file.exists():
            with open(cache_file) as f:
                all_data[investor["name"]] = json.load(f)
        else:
            all_data[investor["name"]] = []
    return all_data


@click.group()
@click.option("--debug", is_flag=True, help="Enable debug logging")
def cli(debug):
    """Coattail Investor -- Track top institutional investors via 13F filings."""
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)


@cli.command()
@click.option("--quarters", "-q", default=2, help="Number of quarters to fetch (default: 2)")
def fetch(quarters):
    """Fetch latest 13F filings for all tracked investors."""
    from data_fetcher import fetch_all_investors

    console.print("[bold cyan]Fetching 13F filings...[/bold cyan]")
    console.print(f"Tracking {len(TRACKED_INVESTORS)} investors, fetching {quarters} quarters each")
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching filings...", total=None)

        all_data = fetch_all_investors(num_quarters=quarters)

        progress.update(task, completed=True)

    # Summary
    console.print()
    success = sum(1 for v in all_data.values() if v)
    console.print(f"[green]Fetched data for {success}/{len(TRACKED_INVESTORS)} investors[/green]")

    for name, data in all_data.items():
        status = f"[green]{len(data)} quarters[/green]" if data else "[red]no data[/red]"
        console.print(f"  {name}: {status}")


@cli.command()
@click.option("--valuation/--no-valuation", default=True, help="Include valuation screening")
def analyze(valuation):
    """Run full analysis and generate consensus report."""
    from analyzer import build_consensus
    from reporter import print_report
    from valuation import enrich_consensus_with_valuation

    console.print("[bold cyan]Running consensus analysis...[/bold cyan]")

    all_data = _load_cached_data()
    if not any(v for v in all_data.values()):
        console.print("[red]No cached data found. Run 'fetch' first.[/red]")
        return

    consensus = build_consensus(all_data)

    if valuation:
        console.print("[dim]Screening watchlist for valuations...[/dim]")
        consensus = enrich_consensus_with_valuation(consensus)

    print_report(consensus)


@cli.command()
@click.option("--quarters", "-q", default=2, help="Number of quarters to fetch")
@click.option("--valuation/--no-valuation", default=True, help="Include valuation screening")
@click.option("--output", "-o", default=None, help="Save markdown report to file")
def run(quarters, valuation, output):
    """Fetch latest filings + run full analysis (one command)."""
    from analyzer import build_consensus
    from data_fetcher import fetch_all_investors
    from reporter import generate_markdown_report, print_report
    from valuation import enrich_consensus_with_valuation

    # Step 1: Fetch
    console.print("[bold cyan]Step 1: Fetching 13F filings...[/bold cyan]")
    console.print(f"Tracking {len(TRACKED_INVESTORS)} investors")
    console.print()

    all_data = fetch_all_investors(num_quarters=quarters)

    success = sum(1 for v in all_data.values() if v)
    console.print(f"\n[green]Fetched data for {success}/{len(TRACKED_INVESTORS)} investors[/green]")

    # Step 2: Analyze
    console.print("\n[bold cyan]Step 2: Running consensus analysis...[/bold cyan]")
    consensus = build_consensus(all_data)

    # Step 3: Valuation
    if valuation:
        console.print("\n[bold cyan]Step 3: Screening valuations...[/bold cyan]")
        consensus = enrich_consensus_with_valuation(consensus)

    # Step 4: Report
    console.print("\n[bold cyan]Step 4: Generating report...[/bold cyan]")
    print_report(consensus)

    if output:
        md = generate_markdown_report(consensus, output)
        console.print(f"\n[green]Markdown report saved to: {output}[/green]")
    else:
        md = generate_markdown_report(consensus)
        console.print(f"\n[dim]Markdown report saved to data/reports/[/dim]")


@cli.command()
@click.argument("name")
def investor(name):
    """Check a specific investor's holdings and changes."""
    from analyzer import analyze_investor
    from reporter import print_investor_report

    inv = get_investor_by_name(name)
    if not inv:
        console.print(f"[red]Investor '{name}' not found in tracking list.[/red]")
        console.print("Tracked investors:")
        for i in TRACKED_INVESTORS:
            console.print(f"  - {i['name']} ({i['entity']})")
        return

    cache_file = DATA_DIR / f"holdings_{inv['cik']}.json"
    if not cache_file.exists():
        console.print(f"[red]No cached data for {inv['name']}. Run 'fetch' first.[/red]")
        return

    with open(cache_file) as f:
        data = json.load(f)

    analysis = analyze_investor(data)
    print_investor_report(analysis)


@cli.command()
@click.argument("ticker")
def stock(ticker):
    """Check a specific stock's holdings across all tracked investors."""
    from analyzer import find_stock_across_investors
    from reporter import print_stock_report

    all_data = _load_cached_data()
    if not any(v for v in all_data.values()):
        console.print("[red]No cached data found. Run 'fetch' first.[/red]")
        return

    stock_info = find_stock_across_investors(ticker, all_data)
    print_stock_report(stock_info)


@cli.command()
def status():
    """Check 13F filing status for all tracked investors."""
    from data_fetcher import get_filing_status
    from reporter import print_filing_status

    console.print("[bold cyan]Checking filing status...[/bold cyan]")

    statuses = get_filing_status()
    print_filing_status(statuses)


@cli.command()
@click.option("--output", "-o", default=None, help="Output file path")
@click.option("--valuation/--no-valuation", default=True, help="Include valuation screening")
def report(output, valuation):
    """Generate a markdown report from cached data."""
    from analyzer import build_consensus
    from reporter import generate_markdown_report, print_report
    from valuation import enrich_consensus_with_valuation

    all_data = _load_cached_data()
    if not any(v for v in all_data.values()):
        console.print("[red]No cached data found. Run 'fetch' first.[/red]")
        return

    consensus = build_consensus(all_data)

    if valuation:
        console.print("[dim]Screening valuations...[/dim]")
        consensus = enrich_consensus_with_valuation(consensus)

    # Print to terminal
    print_report(consensus)

    # Save markdown
    md = generate_markdown_report(consensus, output)
    save_path = output or "data/reports/"
    console.print(f"\n[green]Markdown report saved to: {save_path}[/green]")


@cli.command()
@click.option("--setup-cron", type=click.Choice(["daily", "weekly", "quarterly"]),
              default=None, help="Set up automated checks")
def schedule(setup_cron):
    """View filing schedule and set up automation."""
    from scheduler import print_schedule, setup_cron as do_setup_cron

    print_schedule()

    if setup_cron:
        do_setup_cron(setup_cron)


@cli.command()
@click.argument("dollars", type=float)
@click.option(
    "--strategy", "-s",
    type=click.Choice(["conviction", "score", "equal", "holders"]),
    default="conviction",
    help="Weighting strategy (default: conviction)",
)
@click.option("--max-positions", "-n", type=int, default=None,
              help="Maximum number of positions")
@click.option("--max-weight", "-w", type=float, default=None,
              help="Max single-position weight %% (default: 15)")
@click.option("--min-position", type=float, default=None,
              help="Minimum dollars per position (default: $100)")
@click.option("--fractional/--whole-shares", default=False,
              help="Allow fractional shares (default: whole shares only)")
@click.option("--exclude-red", is_flag=True, default=False,
              help="Exclude stocks with RED valuation signal")
@click.option("--output", "-o", default=None, help="Save allocation report to markdown file")
def allocate(dollars, strategy, max_positions, max_weight, min_position,
             fractional, exclude_red, output):
    """Build a portfolio allocation from consensus picks.

    Takes your investment DOLLARS and distributes them proportionally across
    the top consensus picks based on the chosen weighting strategy.

    \b
    Strategies:
      conviction  Score * direction boost * valuation discount (default)
      score       Pure consensus score weighting
      equal       Equal weight across all positions
      holders     Weight by number of institutional holders

    \b
    Examples:
      python main.py allocate 10000
      python main.py allocate 50000 --strategy equal --max-positions 10
      python main.py allocate 25000 --fractional --exclude-red
      python main.py allocate 100000 -s score -n 15 -w 10 -o portfolio.md
    """
    from allocator import allocate_portfolio
    from analyzer import build_consensus
    from reporter import generate_allocation_markdown, print_allocation
    from valuation import enrich_consensus_with_valuation

    if dollars <= 0:
        console.print("[red]Investment amount must be positive.[/red]")
        return

    # Load cached data
    all_data = _load_cached_data()
    if not any(v for v in all_data.values()):
        console.print("[red]No cached data found. Run 'fetch' first.[/red]")
        return

    # Build consensus
    console.print("[bold cyan]Building consensus analysis...[/bold cyan]")
    consensus = build_consensus(all_data)

    # Enrich with valuation data (needed for prices + signals)
    console.print("[dim]Fetching current prices and valuations...[/dim]")
    consensus = enrich_consensus_with_valuation(consensus)

    watchlist = consensus.get("watchlist", [])
    if not watchlist:
        console.print("[red]No consensus watchlist available. Run 'analyze' first.[/red]")
        return

    # Run allocation
    console.print(
        f"\n[bold cyan]Allocating ${dollars:,.2f} across consensus picks "
        f"(strategy: {strategy})...[/bold cyan]"
    )

    allocation = allocate_portfolio(
        watchlist=watchlist,
        total_dollars=dollars,
        strategy=strategy,
        max_positions=max_positions,
        max_single_pct=max_weight,
        min_position_dollars=min_position,
        fractional_shares=fractional,
        exclude_red=exclude_red,
    )

    # Display results
    print_allocation(allocation)

    # Save markdown if requested
    if output:
        generate_allocation_markdown(allocation, output)
        console.print(f"\n[green]Allocation report saved to: {output}[/green]")


if __name__ == "__main__":
    cli()
