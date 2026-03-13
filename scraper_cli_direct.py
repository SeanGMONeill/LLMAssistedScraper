#!/usr/bin/env python3
"""
Direct LLM Web Scraper CLI - Simplified alternative using Claude for direct extraction.

This version:
- Uses Claude Haiku for direct extraction (no selector inference)
- No caching (LLM called on every run)
- Simpler codebase (~100 lines vs ~400 lines)
- More resilient to HTML structure changes

Usage:
    python scraper_cli_direct.py run sites/books.json
    python scraper_cli_direct.py run sites/books.json --site waterstones_the_truth
    python scraper_cli_direct.py list-sites sites/books.json
"""

import click
import json
import os
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich import box

# Import modules
from direct_extractor import DirectExtractor
from anthropic_client import AnthropicClient
from schema import Schema
from sites import Sites

console = Console()


def load_anthropic_key():
    """Load Anthropic API key from file."""
    try:
        with open('anthropic_key.txt', 'r') as file:
            return file.read().strip()
    except FileNotFoundError:
        console.print("[red]❌ Error: anthropic_key.txt not found.[/red]")
        console.print("[yellow]Please create this file with your Anthropic API key.[/yellow]")
        console.print("[dim]Get your key from: https://console.anthropic.com/[/dim]")
        raise click.Abort()


@click.group()
def cli():
    """🕷️  Direct LLM Web Scraper CLI

    A simplified web scraper using Claude for direct extraction.
    No selector inference, no caching - just pure LLM extraction.
    """
    pass


@cli.command()
@click.argument('config_file', type=click.Path(exists=True))
@click.option('--site', help='Run only specific site by ID')
@click.option('--output-dir', default='results_direct', help='Output directory (default: results_direct)')
@click.option('--format', 'output_format', default='json', type=click.Choice(['json', 'table']), help='Output format')
@click.option('--model', default='claude-haiku-4-5-20251001', help='Claude model to use')
def run(config_file, site, output_dir, output_format, model):
    """🚀 Run the direct LLM scraper on sites from a configuration file.

    CONFIG_FILE: Path to the sites configuration JSON file (e.g., sites/books.json)
    """

    # Ensure output directory exists
    Path(output_dir).mkdir(exist_ok=True)

    extractor = None

    try:
        # Load configuration
        with console.status(f"[cyan]Loading configuration from {config_file}..."):
            sites = Sites.from_file(config_file)

        console.print(f"[green]✓[/green] Loaded configuration: [bold]{sites.id}[/bold]")
        console.print(f"[dim]Schema: {sites.schema.attributes}[/dim]")
        console.print(f"[dim]Model: {model}[/dim]")

        # Filter sites if specific site requested
        sites_to_process = sites.sites
        if site:
            sites_to_process = [s for s in sites.sites if s['id'] == site]
            if not sites_to_process:
                console.print(f"[red]❌ Site '{site}' not found in configuration[/red]")
                return

        # Initialize clients
        api_key = load_anthropic_key()
        llm_client = AnthropicClient(api_key=api_key, model=model)
        extractor = DirectExtractor()

        # Process each site
        results_summary = []

        for site_config in sites_to_process:
            site_name = site_config['name']
            site_id = site_config['id']
            url = site_config['url']

            console.print(f"\n[bold blue]🔍 Processing: {site_name}[/bold blue]")
            console.print(f"[dim]URL: {url}[/dim]")

            # Navigate to the site
            with console.status(f"[cyan]Loading {url}..."):
                extractor.navigate(url)

            console.print("[green]✓[/green] Page loaded successfully")

            # Extract with progress indicator
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
                transient=True
            ) as progress:

                # Convert to markdown
                task = progress.add_task(f"[cyan]Converting page to markdown...", total=None)
                markdown = extractor.get_page_markdown()

                # Save markdown for debugging (optional)
                debug_file = f'{output_dir}/{sites.id}_{site_id}_markdown.md'
                with open(debug_file, 'w') as f:
                    f.write(markdown)

                # Extract using Claude
                progress.update(task, description=f"[cyan]Extracting data with Claude...")
                extracted_data = llm_client.extract_data(markdown, sites.schema)

                progress.remove_task(task)

            # Save results
            results_file = f'{output_dir}/{sites.id}_{site_id}.json'
            with open(results_file, 'w') as f:
                json.dump(extracted_data, f, indent=4)

            # Display results
            if extracted_data:
                console.print(f"[green]✅ Success![/green] Extracted {len(extracted_data)} record(s)")

                if output_format == 'table' and extracted_data:
                    # Display as table
                    table = Table(title=f"Extracted Data - {site_name}", box=box.ROUNDED)

                    # Add columns
                    for field in extracted_data[0].keys():
                        table.add_column(field.title(), style="cyan")

                    # Add rows (limit to first 10 for readability)
                    for record in extracted_data[:10]:
                        table.add_row(*[str(record.get(field, '')) for field in extracted_data[0].keys()])

                    if len(extracted_data) > 10:
                        console.print(f"[dim]Showing first 10 of {len(extracted_data)} records[/dim]")

                    console.print(table)

                results_summary.append({
                    'site': site_name,
                    'records': len(extracted_data),
                    'file': results_file
                })
            else:
                console.print(f"[yellow]⚠️  No data extracted from {site_name}[/yellow]")
                results_summary.append({
                    'site': site_name,
                    'records': 0,
                    'file': results_file
                })

        # Final summary
        console.print(f"\n[bold green]🎉 Processing Complete![/bold green]")

        summary_table = Table(title="Results Summary", box=box.ROUNDED)
        summary_table.add_column("Site", style="cyan")
        summary_table.add_column("Records", justify="right", style="green")
        summary_table.add_column("Output File", style="dim")

        for result in results_summary:
            records_style = "green" if result['records'] > 0 else "yellow"
            summary_table.add_row(
                result['site'],
                f"[{records_style}]{result['records']}[/{records_style}]",
                result['file']
            )

        console.print(summary_table)

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        if not console.quiet:
            import traceback
            traceback.print_exc()
    finally:
        # Close browser
        if extractor:
            extractor.close()


@cli.command('list-sites')
@click.argument('config_file', type=click.Path(exists=True))
def list_sites(config_file):
    """📋 List all sites in a configuration file.

    CONFIG_FILE: Path to the sites configuration JSON file
    """

    try:
        sites = Sites.from_file(config_file)

        console.print(f"\n[bold cyan]Sites in {config_file}[/bold cyan]")
        console.print(f"[dim]Schema: {sites.schema.attributes}[/dim]\n")

        table = Table(box=box.ROUNDED)
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("URL", style="blue")

        for site in sites.sites:
            table.add_row(
                site['id'],
                site['name'],
                site['url'][:60] + "..." if len(site['url']) > 60 else site['url']
            )

        console.print(table)
        console.print(f"\n[dim]Total: {len(sites.sites)} site(s)[/dim]")

    except Exception as e:
        console.print(f"[red]❌ Error loading config: {e}[/red]")


@cli.command('compare')
@click.argument('original_results', type=click.Path(exists=True))
@click.argument('direct_results', type=click.Path(exists=True))
def compare(original_results, direct_results):
    """📊 Compare results from both extraction methods.

    ORIGINAL_RESULTS: JSON file from original scraper
    DIRECT_RESULTS: JSON file from direct scraper
    """

    try:
        with open(original_results, 'r') as f:
            original = json.load(f)

        with open(direct_results, 'r') as f:
            direct = json.load(f)

        console.print(f"\n[bold cyan]Comparison: Original vs Direct[/bold cyan]\n")

        table = Table(box=box.ROUNDED)
        table.add_column("Metric", style="cyan")
        table.add_column("Original (Selector)", justify="right", style="green")
        table.add_column("Direct (LLM)", justify="right", style="blue")

        table.add_row(
            "Records Extracted",
            str(len(original)),
            str(len(direct))
        )

        # Calculate field coverage
        if original and direct:
            original_fields = set(original[0].keys())
            direct_fields = set(direct[0].keys())

            table.add_row(
                "Fields Extracted",
                str(len(original_fields)),
                str(len(direct_fields))
            )

            # Show sample comparison
            console.print(table)
            console.print("\n[bold]Sample Record Comparison:[/bold]\n")

            # Show first record from each
            orig_table = Table(title="Original Scraper", box=box.ROUNDED)
            orig_table.add_column("Field", style="cyan")
            orig_table.add_column("Value", style="green")

            for key, value in original[0].items():
                orig_table.add_row(key, str(value)[:60])

            direct_table = Table(title="Direct Scraper", box=box.ROUNDED)
            direct_table.add_column("Field", style="cyan")
            direct_table.add_column("Value", style="blue")

            for key, value in direct[0].items():
                direct_table.add_row(key, str(value)[:60])

            from rich.columns import Columns
            console.print(Columns([orig_table, direct_table]))
        else:
            console.print(table)

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")


if __name__ == '__main__':
    cli()
