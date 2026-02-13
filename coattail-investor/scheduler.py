"""
Filing Schedule Tracker and Automation.

Tracks SEC 13F filing deadlines and checks for new filings.
Supports setting up cron-based automated checks.
"""

import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta

from rich.console import Console
from rich.table import Table

from config import QUARTER_DEADLINES, TRACKED_INVESTORS
from data_fetcher import get_filing_status

logger = logging.getLogger(__name__)
console = Console()


def get_current_filing_period() -> dict:
    """
    Determine the current filing period and deadlines.

    Returns:
        Dict with current quarter info, deadline dates, and status.
    """
    now = datetime.now()
    year = now.year

    # Determine which quarter's filings we're waiting for
    # 13Fs are due 45 days after quarter-end
    periods = [
        {
            "quarter": f"{year - 1}-Q4",
            "quarter_end": datetime(year - 1, 12, 31),
            "filing_deadline": datetime(year, 2, 14),
            "label": "Q4",
        },
        {
            "quarter": f"{year}-Q1",
            "quarter_end": datetime(year, 3, 31),
            "filing_deadline": datetime(year, 5, 15),
            "label": "Q1",
        },
        {
            "quarter": f"{year}-Q2",
            "quarter_end": datetime(year, 6, 30),
            "filing_deadline": datetime(year, 8, 14),
            "label": "Q2",
        },
        {
            "quarter": f"{year}-Q3",
            "quarter_end": datetime(year, 9, 30),
            "filing_deadline": datetime(year, 11, 14),
            "label": "Q3",
        },
    ]

    # Find the most relevant period (closest deadline that hasn't passed by much)
    for period in periods:
        deadline = period["filing_deadline"]
        # Consider a period relevant until 30 days after its deadline
        if now <= deadline + timedelta(days=30):
            days_until = (deadline - now).days
            period["days_until_deadline"] = days_until
            period["deadline_passed"] = days_until < 0
            period["status"] = (
                "OVERDUE" if days_until < 0
                else "DUE SOON" if days_until <= 7
                else "UPCOMING" if days_until <= 30
                else "FUTURE"
            )
            return period

    # Default to next year's Q4
    return {
        "quarter": f"{year}-Q4",
        "quarter_end": datetime(year, 12, 31),
        "filing_deadline": datetime(year + 1, 2, 14),
        "label": "Q4",
        "days_until_deadline": (datetime(year + 1, 2, 14) - now).days,
        "deadline_passed": False,
        "status": "FUTURE",
    }


def check_new_filings() -> dict:
    """
    Check which tracked investors have filed new 13Fs.

    Returns:
        Dict with period info and per-investor filing status.
    """
    period = get_current_filing_period()
    statuses = get_filing_status()

    filed = [s for s in statuses if s["has_filed"]]
    pending = [s for s in statuses if not s["has_filed"]]

    period["filed_count"] = len(filed)
    period["pending_count"] = len(pending)
    period["total_investors"] = len(statuses)
    period["filed_investors"] = filed
    period["pending_investors"] = pending
    period["all_statuses"] = statuses

    return period


def print_schedule() -> None:
    """Print the filing schedule and current status."""
    period = check_new_filings()

    console.print()
    console.print(f"[bold cyan]13F Filing Schedule[/bold cyan]")
    console.print()

    # Current period info
    quarter = period.get("quarter", "Unknown")
    deadline = period.get("filing_deadline")
    deadline_str = deadline.strftime("%Y-%m-%d") if deadline else "Unknown"
    days = period.get("days_until_deadline", 0)
    status = period.get("status", "UNKNOWN")

    status_style = {
        "OVERDUE": "red",
        "DUE SOON": "yellow",
        "UPCOMING": "green",
        "FUTURE": "dim",
    }.get(status, "white")

    console.print(f"  Quarter: [bold]{quarter}[/bold]")
    console.print(f"  Filing deadline: {deadline_str}")
    console.print(f"  Status: [{status_style}]{status}[/{status_style}] ({days} days)")
    console.print(
        f"  Filed: {period.get('filed_count', 0)}/{period.get('total_investors', 0)}"
    )
    console.print()

    # All filing deadlines for the year
    console.print("[bold]Upcoming 13F Deadlines:[/bold]")

    year = datetime.now().year
    table = Table(show_header=True, header_style="bold")
    table.add_column("Quarter", width=10)
    table.add_column("Quarter End", width=12)
    table.add_column("Filing Deadline", width=14)
    table.add_column("Status", width=10)

    now = datetime.now()
    schedule = [
        (f"{year - 1}-Q4", f"{year - 1}-12-31", f"{year}-02-14"),
        (f"{year}-Q1", f"{year}-03-31", f"{year}-05-15"),
        (f"{year}-Q2", f"{year}-06-30", f"{year}-08-14"),
        (f"{year}-Q3", f"{year}-09-30", f"{year}-11-14"),
        (f"{year}-Q4", f"{year}-12-31", f"{year + 1}-02-14"),
    ]

    for q, qend, deadline in schedule:
        dl = datetime.strptime(deadline, "%Y-%m-%d")
        if dl < now - timedelta(days=30):
            s = "[dim]Past[/dim]"
        elif dl < now:
            s = "[yellow]Active[/yellow]"
        elif (dl - now).days <= 45:
            s = "[green]Next[/green]"
        else:
            s = "[dim]Future[/dim]"

        table.add_row(q, qend, deadline, s)

    console.print(table)

    # Per-investor status
    console.print()
    statuses = period.get("all_statuses", [])
    if statuses:
        console.print("[bold]Investor Filing Status:[/bold]")

        inv_table = Table(show_header=True, header_style="bold")
        inv_table.add_column("Status", justify="center", width=6)
        inv_table.add_column("Investor", width=30)
        inv_table.add_column("Latest Quarter", width=14)
        inv_table.add_column("Filing Date", width=12)

        for s in statuses:
            icon = "[green]OK[/green]" if s["has_filed"] else "[yellow]WAIT[/yellow]"
            inv_table.add_row(
                icon,
                s["name"],
                s.get("latest_quarter", "N/A"),
                s.get("filing_date", "N/A"),
            )

        console.print(inv_table)


def setup_cron(schedule: str = "daily") -> None:
    """
    Set up a cron job for automated filing checks.

    Args:
        schedule: "daily", "weekly", or a custom cron expression.
    """
    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "main.py"))
    python_path = sys.executable

    cron_schedules = {
        "daily": "0 8 * * *",       # 8 AM daily
        "weekly": "0 8 * * 1",      # 8 AM Monday
        "quarterly": "0 8 15 2,5,8,11 *",  # 15th of filing months
    }

    cron_expr = cron_schedules.get(schedule, schedule)
    cron_line = f'{cron_expr} cd {os.path.dirname(script_path)} && {python_path} {script_path} status >> /tmp/coattail_investor.log 2>&1'

    console.print(f"\n[bold]Cron Job Setup[/bold]")
    console.print(f"\nTo add automated filing checks, add this line to your crontab:")
    console.print(f"\n[dim]  {cron_line}[/dim]")
    console.print(f"\nRun [bold]crontab -e[/bold] and paste the line above.")
    console.print(f"Schedule: {schedule} ({cron_expr})")
