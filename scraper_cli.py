#!/usr/bin/env python3
"""
Web Scraper CLI - A user-friendly interface for the LLM-assisted web scraper.

Usage:
    python scraper_cli.py run sites/books.json
    python scraper_cli.py run sites/books.json --site waterstones_the_truth
    python scraper_cli.py run sites/books.json --no-cache
    python scraper_cli.py clear-cache
    python scraper_cli.py list-sites sites/books.json
"""

import click
import json
import os
import glob
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

# Import existing modules
import html2text
from webdriver_extractor import WebdriverExtractor
from llm_client import LLMClient
from schema import Schema
from sites import Sites

console = Console()

def load_openai_key():
    """Load OpenAI API key from file"""
    try:
        with open('openai_key.txt', 'r') as file:
            return file.read().strip()
    except FileNotFoundError:
        console.print("[red]❌ Error: openai_key.txt not found. Please create this file with your OpenAI API key.[/red]")
        raise click.Abort()

def get_cache_files():
    """Get list of cached rule files"""
    return glob.glob('rules/*.json')

def clear_rule_cache(site_id=None):
    """Clear cached rules for a specific site or all sites"""
    if site_id:
        pattern = f'rules/*{site_id}*.json'
        files = glob.glob(pattern)
        if not files:
            console.print(f"[yellow]⚠️  No cache files found for site: {site_id}[/yellow]")
            return 0
    else:
        files = get_cache_files()
    
    if not files:
        console.print("[yellow]⚠️  No cache files to clear[/yellow]")
        return 0
    
    cleared_count = 0
    for file_path in files:
        try:
            os.remove(file_path)
            console.print(f"[green]✓[/green] Cleared: {os.path.basename(file_path)}")
            cleared_count += 1
        except OSError as e:
            console.print(f"[red]❌ Failed to clear {file_path}: {e}[/red]")
    
    return cleared_count

def determine_rules_with_progress(extractor, schema, site_name):
    """Determine rules with rich progress display"""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True
    ) as progress:
        
        # Step 1: Extract page content
        task = progress.add_task(f"[cyan]Analyzing page structure for {site_name}...", total=None)
        markdown_text = html2text.html2text(extractor.get_body_html())
        
        # Save markdown for debugging
        with open('example_markdown.md', 'w') as file:
            file.write(markdown_text)
        
        progress.update(task, description=f"[cyan]Calling LLM to extract data from {site_name}...")
        llm_client = LLMClient(api_key=load_openai_key())
        llm_summary = llm_client.extract_details(markdown_text, schema)
        
        progress.update(task, description=f"[cyan]Inferring selectors for {site_name}...")
        rules_with_matches = []
        rules = extractor.infer_rules(llm_summary['extracted_data'])
        
        if not rules:
            progress.remove_task(task)
            console.print(f"[red]❌ Could not determine rules for {site_name}[/red]")
            return None
        
        progress.update(task, description=f"[cyan]Testing selectors for {site_name}...")
        for rule in rules:
            matches = extractor.extract_using_rule(rule)
            rules_with_matches.append((rule, matches))
        
        progress.update(task, description=f"[cyan]Optimizing selector combination for {site_name}...")
        # Import here to avoid circular imports
        from find_selectors import minimal_rule_combo_for_total_cover
        final_rules = minimal_rule_combo_for_total_cover(rules_with_matches, llm_summary['extracted_data'])
        
        progress.remove_task(task)
        
    return final_rules

@click.group()
def cli():
    """🕷️  LLM-Assisted Web Scraper CLI
    
    A powerful web scraper that uses AI to automatically find and extract data from websites.
    """
    pass

@cli.command()
@click.argument('config_file', type=click.Path(exists=True))
@click.option('--site', help='Run only specific site by ID')
@click.option('--no-cache', is_flag=True, help='Force re-inference of rules (ignore cached selectors)')
@click.option('--output-dir', default='results', help='Output directory for results (default: results)')
@click.option('--format', 'output_format', default='json', type=click.Choice(['json', 'table']), help='Output format')
def run(config_file, site, no_cache, output_dir, output_format):
    """🚀 Run the scraper on sites from a configuration file.
    
    CONFIG_FILE: Path to the sites configuration JSON file (e.g., sites/books.json)
    """
    
    # Ensure output directory exists
    Path(output_dir).mkdir(exist_ok=True)
    
    try:
        # Load configuration
        with console.status(f"[cyan]Loading configuration from {config_file}..."):
            sites = Sites.from_file(config_file)
        
        console.print(f"[green]✓[/green] Loaded configuration: [bold]{sites.id}[/bold]")
        console.print(f"[dim]Schema: {sites.schema.attributes}[/dim]")
        
        # Filter sites if specific site requested
        sites_to_process = sites.sites
        if site:
            sites_to_process = [s for s in sites.sites if s['id'] == site]
            if not sites_to_process:
                console.print(f"[red]❌ Site '{site}' not found in configuration[/red]")
                return
        
        # Initialize extractor
        field_names = sites.schema.attributes
        extractor = WebdriverExtractor(field_names)
        
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
            
            # Determine rules file path
            rules_file = f'rules/{sites.id}_{site_id}.json'
            
            # Load or determine rules
            rules = None
            if not no_cache:
                try:
                    with open(rules_file, 'r') as file:
                        rules = json.load(file)
                    console.print(f"[green]✓[/green] Using cached rules from {rules_file}")
                except FileNotFoundError:
                    console.print(f"[yellow]⚠️[/yellow]  No cached rules found, will infer new ones")
            else:
                console.print(f"[yellow]🔄[/yellow] Ignoring cached rules (--no-cache flag)")
            
            if not rules:
                console.print("[cyan]🧠 Determining extraction rules...[/cyan]")
                rules = determine_rules_with_progress(extractor, sites.schema, site_name)
                
                if rules:
                    # Save rules for future use
                    os.makedirs('rules', exist_ok=True)
                    with open(rules_file, 'w') as f:
                        json.dump(rules, f, indent=2)
                    console.print(f"[green]✓[/green] Rules saved to {rules_file}")
                else:
                    console.print(f"[red]❌ Failed to determine rules for {site_name}[/red]")
                    continue
            
            # Extract data
            with console.status(f"[cyan]Extracting data from {site_name}..."):
                extraction = extractor.extract_using_rules(rules)
            
            # Save results
            results_file = f'{output_dir}/{sites.id}_{site_id}.json'
            with open(results_file, 'w') as f:
                json.dump(extraction, f, indent=4)
            
            # Display results summary
            if extraction:
                console.print(f"[green]✅ Success![/green] Extracted {len(extraction)} record(s)")
                
                if output_format == 'table' and extraction:
                    # Display as table
                    table = Table(title=f"Extracted Data - {site_name}", box=box.ROUNDED)
                    
                    # Add columns
                    if extraction:
                        for field in extraction[0].keys():
                            table.add_column(field.title(), style="cyan")
                        
                        # Add rows
                        for record in extraction:
                            table.add_row(*[str(record.get(field, '')) for field in extraction[0].keys()])
                    
                    console.print(table)
                
                results_summary.append({
                    'site': site_name,
                    'records': len(extraction),
                    'file': results_file
                })
            else:
                console.print(f"[red]❌ No data extracted from {site_name}[/red]")
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
            records_style = "green" if result['records'] > 0 else "red"
            summary_table.add_row(
                result['site'],
                f"[{records_style}]{result['records']}[/{records_style}]",
                result['file']
            )
        
        console.print(summary_table)
        
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        if console.quiet:
            raise
        import traceback
        traceback.print_exc()
    finally:
        # Close browser
        if 'extractor' in locals():
            try:
                extractor.driver.quit()
            except:
                pass

@cli.command('clear-cache')
@click.option('--site', help='Clear cache for specific site ID only')
@click.option('--confirm', is_flag=True, help='Skip confirmation prompt')
def clear_cache_cmd(site, confirm):
    """🗑️  Clear cached extraction rules.
    
    This will force the scraper to re-analyze websites and create new rules.
    """
    
    if site:
        cache_files = glob.glob(f'rules/*{site}*.json')
        message = f"Clear cache for site '{site}'"
    else:
        cache_files = get_cache_files()
        message = "Clear ALL cached rules"
    
    if not cache_files:
        console.print("[yellow]⚠️  No cache files found to clear[/yellow]")
        return
    
    # Show what will be cleared
    console.print(f"[yellow]Found {len(cache_files)} cache file(s):[/yellow]")
    for file_path in cache_files:
        console.print(f"  • {os.path.basename(file_path)}")
    
    if not confirm:
        if not click.confirm(f"\n{message}?"):
            console.print("[blue]ℹ️  Cache clearing cancelled[/blue]")
            return
    
    cleared_count = clear_rule_cache(site)
    if cleared_count > 0:
        console.print(f"\n[green]✅ Cleared {cleared_count} cache file(s)[/green]")
    else:
        console.print("\n[yellow]⚠️  No files were cleared[/yellow]")

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
        table.add_column("Cached Rules", justify="center")
        
        for site in sites.sites:
            # Check if rules exist
            rules_file = f'rules/{sites.id}_{site["id"]}.json'
            has_cache = "✅" if os.path.exists(rules_file) else "❌"
            
            table.add_row(
                site['id'],
                site['name'],
                site['url'][:60] + "..." if len(site['url']) > 60 else site['url'],
                has_cache
            )
        
        console.print(table)
        console.print(f"\n[dim]Total: {len(sites.sites)} site(s)[/dim]")
        
    except Exception as e:
        console.print(f"[red]❌ Error loading config: {e}[/red]")

@cli.command('cache-status')
def cache_status():
    """📊 Show cache status and statistics."""
    
    cache_files = get_cache_files()
    
    if not cache_files:
        console.print("[yellow]📭 No cached rules found[/yellow]")
        return
    
    console.print(f"[green]📁 Found {len(cache_files)} cached rule file(s):[/green]\n")
    
    table = Table(box=box.ROUNDED)
    table.add_column("File", style="cyan")
    table.add_column("Size", justify="right", style="green")
    table.add_column("Modified", style="dim")
    
    for file_path in sorted(cache_files):
        stat = os.stat(file_path)
        size = f"{stat.st_size:,} bytes"
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        
        table.add_row(
            os.path.basename(file_path),
            size,
            modified
        )
    
    console.print(table)

if __name__ == '__main__':
    cli()