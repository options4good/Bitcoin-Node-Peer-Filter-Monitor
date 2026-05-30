import subprocess
import json
import time
import sys
import os
from datetime import datetime
from rich.console import Console, Group
from rich.table import Table
from rich.panel import Panel
from rich.align import Align
from rich.live import Live

# --- USER CONFIGURATION ---
CONFIG = {
    "node_name": "BCH Node",                
    "cli_path": "bitcoin-cli",  
    "datadir": "/home/bch2/.bitcoin",        
    "refresh_interval": 60, 
    "max_inbound_display": 25,
    "version": "V3.3.4" 
}

console = Console()

def get_rpc_data(command):
    try:
        args = [CONFIG["cli_path"], f"-datadir={CONFIG['datadir']}", command]
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except Exception:
        return None

def format_duration(seconds_ago):
    if seconds_ago < 0: seconds_ago = 0
    if seconds_ago < 60:
        return f"{seconds_ago}s"
    minutes, seconds = divmod(seconds_ago, 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"

def format_bytes(size_bytes):
    if size_bytes == 0: return "0 B"
    units = ("B", "KB", "MB", "GB", "TB")
    i = 0
    while size_bytes >= 1024 and i < len(units) - 1:
        size_bytes /= 1024
        i += 1
    return f"{size_bytes:.2f} {units[i]}"

def format_diff(val):
    if val >= 1e12: return f"{val/1e12:.2f} T"
    if val >= 1e9: return f"{val/1e9:.2f} G"
    return f"{val/1e7:.2f} Gh/s"

def clean_version(subver):
    if not subver: return "N/A"
    scrub_list = ["Indelible", "Bridge", "Bitcoin Cash Node:", "Bitcoin Cash Node", "Bitcoin:", "Bitcoin", "Satoshi:", "Linux", "x86_64", "EB32", ";", "(", ")"]
    clean = subver
    for phrase in scrub_list:
        clean = clean.replace(phrase, "")
    return clean.strip("/: ")

def make_dashboard(cached_data, reference_ts, current_live_ts):
    blockchain_info, peers, network_info = cached_data
    
    # Render fallback group if node data hasn't dropped or failed to load yet
    if not blockchain_info or peers is None or not network_info:
        return Group(Panel(Text("Error: Unable to connect to node.", style="bold red"), border_style="dim"))

    current_height = blockchain_info.get('blocks', 0)
    node_subver = clean_version(network_info.get('subversion', 'N/A'))
    raw_difficulty = blockchain_info.get('difficulty', 0)
    difficulty_str = format_diff(raw_difficulty)
    
    verification_progress = blockchain_info.get('verificationprogress', 0)
    sync_perc = verification_progress * 100

    # Dynamic Live System Clock for the Header Panel
    now_str = datetime.fromtimestamp(current_live_ts).strftime("%Y-%m-%d %H:%M:%S")
    
    title_text = f"[bold white]{CONFIG['node_name']} ({node_subver}) - Complete Peer List[/bold white]"
    metadata = f"[dim]{now_str}  |  {CONFIG['version']}[/dim]"
    header_panel = Panel(Group(Align.center(title_text), Align.center(metadata)), border_style="dim")

    # Sorting relative to the live timestamp or the cache snapshot
    peers.sort(key=lambda x: x.get('pingtime', 999))
    peers.sort(key=lambda x: x['inbound'])
    
    outbound_peers = [p for p in peers if not p['inbound']]
    inbound_peers = [p for p in peers if p['inbound']][:CONFIG["max_inbound_display"]]

    summary = (f"[white]Total Peers:[/white] {len(peers)}  |  "
              f"[deep_sky_blue1]Outbound:[/deep_sky_blue1] {len(outbound_peers)}  |  "
              f"[magenta]Inbound (Disp):[/magenta] {len(inbound_peers)}  |  "
              f"[white]Height:[/white] [navajo_white3]{current_height} (Synced: {sync_perc:.2f}%)[/navajo_white3]  |  "
              f"[white]Difficulty:[/white] [navajo_white3]{difficulty_str}[/navajo_white3]")
    
    table = Table(show_header=True, header_style="bold", border_style="dim", expand=True, title=summary, title_style="none")
    table.add_column("[dim]# [/dim]", justify="right", style="dim")
    table.add_column("[spring_green3]ID #[/spring_green3]", justify="right", style="spring_green3")
    table.add_column("[deep_sky_blue1]Out[/deep_sky_blue1][dim]/[/dim][magenta]In[/magenta]", justify="center")
    table.add_column("[grey50]IP Address[/grey50]", justify="left", style="grey50")
    table.add_column("[light_green]La[/light_green][yellow1]ten[/yellow1][red1]cy[/red1]", justify="right")
    table.add_column("[khaki1]Version[/khaki1]", justify="left", style="khaki1")
    table.add_column("[cyan]Uptime[/cyan]", justify="right", style="cyan")
    table.add_column("[orange1]Last Recv[/orange1][dim]/[/dim][tan]Sent[/tan]", justify="right")
    table.add_column("[white]Data[/white]", justify="right")
    table.add_column("[navajo_white3]Sync Height[/navajo_white3]", justify="right", style="navajo_white3")
    table.add_column("[medium_purple1]Addnode[/medium_purple1]", justify="center")
    table.add_column("[green]Status[/green]", justify="center")

    def add_peer_rows(peer_list, dir_label, dir_color):
        for i, p in enumerate(peer_list, 1):
            ping_ms = int(p.get('pingtime', 0) * 1000)
            ping_str = f"[light_green]{ping_ms}ms[/light_green]" if ping_ms <= 50 else f"[yellow1]{ping_ms}ms[/yellow1]" if ping_ms <= 99 else f"[red1]{ping_ms}ms[/red1]"
            
            uptime = format_duration(reference_ts - p.get('conntime', reference_ts))
            last_recv = format_duration(reference_ts - p.get('lastrecv', reference_ts))
            last_send = format_duration(reference_ts - p.get('lastsend', reference_ts))
            combined_rs = f"[orange1]{last_recv}[/orange1][dim]/[/dim][tan]{last_send}[/tan]"
            
            data_recv_formatted = format_bytes(p.get('bytesrecv', 0))
            
            is_manual = p["addnode"] if "addnode" in p else (p.get("connection_type", "") == "manual")
            is_addnode_str = "[green]Yes[/green]" if is_manual else "[red]No[/red]"

            peer_height = p.get('synced_blocks', -1)
            if peer_height == -1: peer_height = p.get('startingheight', 0)
            diff_height = current_height - peer_height
            status = f"[red1]BEHIND (-{diff_height})[/red1]" if (not p['inbound'] and diff_height >= 3) else "[green]Healthy[/green]"

            table.add_row(
                str(i), str(p.get('id', 'N/A')), f"[{dir_color}]{dir_label}[/{dir_color}]", 
                p['addr'], ping_str, clean_version(p.get('subver', 'N/A')), uptime, 
                combined_rs, data_recv_formatted, str(peer_height), is_addnode_str, status
            )

    add_peer_rows(outbound_peers, "OUT", "deep_sky_blue1")
    table.add_section()
    add_peer_rows(inbound_peers, "IN", "magenta")

    # Generate custom live timestamp footer view
    refresh_time_str = datetime.fromtimestamp(reference_ts).strftime("%H:%M:%S")
    footer_text = f"Refresh Set To: {CONFIG['refresh_interval']}s  |  Last Refreshed: {refresh_time_str}  |  Press Ctrl+C to Exit"
    footer_align = Align.center(footer_text)

    return Group(header_panel, table, footer_align)

# --- Main Execution ---
def main():
    last_rpc_fetch = 0.0
    b_info, p_info, n_info = None, None, None
    frozen_ts = 0

    # Initialize basic container UI group to pass to Live layout configuration
    render_group = Group()

    with Live(render_group, refresh_per_second=4, screen=True) as live:
        while True:
            current_time = time.time()
            current_second = int(current_time)

            # 1. Check if it's time to fetch fresh RPC data
            if current_time - last_rpc_fetch >= CONFIG["refresh_interval"]:
                b_info = get_rpc_data('getblockchaininfo')
                p_info = get_rpc_data('getpeerinfo')
                n_info = get_rpc_data('getnetworkinfo')
                frozen_ts = current_second
                last_rpc_fetch = current_time

            # 2. Build layout updates context safely over screen resize changes
            live.update(make_dashboard((b_info, p_info, n_info), frozen_ts, current_second))
            
            # High-frequency sleep interval allows responsive real-time top clock updates 
            time.sleep(0.25)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        os.system('clear')
        print("Exiting Monitor. Happy Mining!")
