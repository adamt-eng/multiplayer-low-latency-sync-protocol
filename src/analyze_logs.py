import pandas as pd
import json
import numpy as np
import glob
import os
import matplotlib.pyplot as plt
from pathlib import Path

# --- Configuration ---
TEST_RESULTS_DIR = "test_results"
OUTPUT_CSV = "experiment_results_final.csv"
GRAPHS_DIR = "performance_graphs"

def calculate_state_error(server_json, client_json):
    """
    Calculates error as the number of mismatched cells between server and client.
    Because this is Grid Clash, 'Position Error' is effectively 'State Error'.
    """
    try:
        server_state = json.loads(server_json)
        client_state = json.loads(client_json)
        
        errors = 0
        all_keys = set(server_state.keys()) | set(client_state.keys())
        
        for key in all_keys:
            srv_val = server_state.get(key)
            cli_val = client_state.get(key)
            if srv_val != cli_val:
                errors += 1
        return errors
    except:
        return 0

def recalculate_jitter_from_latency(df_client):
    """
    Recalculate jitter as the variation in latency values.
    Jitter = |Latency_n - Latency_{n-1}|
    This is more robust than inter-arrival time variation.
    """
    df_client['jitter_ms'] = df_client['latency_ms'].diff().abs().fillna(0)
    return df_client

def parse_test_name(test_folder):
    """Extract test parameters from folder name."""
    name = test_folder.lower()
    
    params = {
        "test_name": test_folder,
        "loss_rate": 0,
        "delay_ms": 0,
        "jitter_ms": 0
    }
    
    if "baseline" in name:
        params["loss_rate"] = 0
        params["delay_ms"] = 0
    elif "loss" in name and "2" in name:
        params["loss_rate"] = 2
    elif "loss" in name and "5" in name:
        params["loss_rate"] = 5
    elif "delay" in name and "100" in name:
        if "jitter" in name or "10" in name:
            params["delay_ms"] = 100
            params["jitter_ms"] = 10
        else:
            params["delay_ms"] = 100
    
    return params

def process_test_folder(test_folder_path):
    """Process all logs in a single test folder."""
    server_log = os.path.join(test_folder_path, "server_log.csv")
    client_logs = glob.glob(os.path.join(test_folder_path, "client_log_*.csv"))
    
    if not os.path.exists(server_log) or not client_logs:
        return None
    
    df_server = pd.read_csv(server_log)
    all_results = []
    
    for c_file in client_logs:
        df_client = pd.read_csv(c_file)
        
        # Recalculate jitter based on latency variation
        df_client = recalculate_jitter_from_latency(df_client)
        
        # Merge on snapshot_id
        merged = pd.merge(df_client, df_server, on="snapshot_id", suffixes=('_cli', '_srv'))
        
        # Calculate Perceived Error
        merged['perceived_position_error'] = merged.apply(
            lambda row: calculate_state_error(row['authoritative_state'], row['perceived_state']), 
            axis=1
        )
        
        # Calculate Bandwidth (kbps)
        merged['bandwidth_per_client_kbps'] = (merged['bytes_sent_instant'] * 8) / (0.05 * 1000)
        
        all_results.append(merged)
    
    if all_results:
        return pd.concat(all_results, ignore_index=True)
    return None

def main():
    # Create output directory for graphs
    os.makedirs(GRAPHS_DIR, exist_ok=True)
    
    # Find all test folders
    test_folders = []
    for item in os.listdir(TEST_RESULTS_DIR):
        item_path = os.path.join(TEST_RESULTS_DIR, item)
        if os.path.isdir(item_path):
            test_folders.append((item, item_path))
    
    if not test_folders:
        print(f"No test folders found in {TEST_RESULTS_DIR}")
        return
    
    # Process all tests
    all_test_results = {}
    
    for test_name, test_path in sorted(test_folders):
        print(f"Processing {test_name}...")
        df = process_test_folder(test_path)
        
        if df is not None:
            params = parse_test_name(test_name)
            all_test_results[test_name] = {
                "data": df,
                "params": params
            }
            
            print(f"  ✓ Loaded {len(df)} records")
    
    if not all_test_results:
        print("No valid test data found.")
        return
    
    # --- Print Statistics ---
    print("\n" + "="*70)
    print("PERFORMANCE METRICS SUMMARY (per test scenario)")
    print("="*70)
    
    for test_name in sorted(all_test_results.keys()):
        test_info = all_test_results[test_name]
        df = test_info["data"]
        params = test_info["params"]
        
        print(f"\nTest: {test_name}")
        if params["loss_rate"] > 0:
            print(f"  Loss Rate: {params['loss_rate']}%")
        if params["delay_ms"] > 0:
            print(f"  Delay: {params['delay_ms']}ms", end="")
            if params["jitter_ms"] > 0:
                print(f" ± {params['jitter_ms']}ms jitter")
            else:
                print()
        
        print(f"\n  Latency (ms)")
        print(f"    Mean: {df['latency_ms'].mean():.2f}, Median: {df['latency_ms'].median():.2f}, 95th %ile: {df['latency_ms'].quantile(0.95):.2f}")
        
        print(f"  Jitter (ms) - Latency Variation")
        print(f"    Mean: {df['jitter_ms'].mean():.2f}, Median: {df['jitter_ms'].median():.2f}, 95th %ile: {df['jitter_ms'].quantile(0.95):.2f}")
        
        print(f"  Perceived State Error (mismatched cells)")
        print(f"    Mean: {df['perceived_position_error'].mean():.2f}, Median: {df['perceived_position_error'].median():.2f}, 95th %ile: {df['perceived_position_error'].quantile(0.95):.2f}")
        
        print(f"  Bandwidth (Kbps)")
        print(f"    Mean: {df['bandwidth_per_client_kbps'].mean():.2f}, Median: {df['bandwidth_per_client_kbps'].median():.2f}")
        
        cpu_numeric = pd.to_numeric(df['cpu_percent'], errors='coerce')
        if not cpu_numeric.isna().all():
            print(f"  CPU Usage (%)")
            print(f"    Mean: {cpu_numeric.mean():.2f}%, Median: {cpu_numeric.median():.2f}%")
    
    # --- Create Graphs ---
    print("\n" + "="*70)
    print("GENERATING PERFORMANCE GRAPHS")
    print("="*70)
    
    # Prepare data for comparison graphs
    test_names_sorted = sorted(all_test_results.keys())
    latency_means = []
    jitter_means = []
    error_means = []
    bandwidth_means = []
    
    for test_name in test_names_sorted:
        test_info = all_test_results[test_name]
        df = test_info["data"]
        
        latency_means.append(df['latency_ms'].mean())
        jitter_means.append(df['jitter_ms'].mean())
        error_means.append(df['perceived_position_error'].mean())
        bandwidth_means.append(df['bandwidth_per_client_kbps'].mean())
    
    # Graph 1: Latency vs Test Scenario
    fig, ax = plt.subplots(figsize=(12, 6))
    x_pos = np.arange(len(test_names_sorted))
    bars = ax.bar(x_pos, latency_means, color='steelblue', alpha=0.8, edgecolor='black')
    ax.set_xlabel("Test Scenario", fontsize=12, fontweight='bold')
    ax.set_ylabel("Latency (ms)", fontsize=12, fontweight='bold')
    ax.set_title("Average Latency by Test Scenario", fontsize=14, fontweight='bold')
    ax.set_xticks(x_pos)
    ax.set_xticklabels(test_names_sorted, rotation=45, ha='right')
    ax.grid(axis='y', alpha=0.3)
    
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.2f}ms', ha='center', va='bottom', fontsize=10)
    
    plt.tight_layout()
    plt.savefig(os.path.join(GRAPHS_DIR, "01_latency_by_scenario.png"), dpi=150)
    print(f"✓ Saved: 01_latency_by_scenario.png")
    plt.close()
    
    # Graph 2: Jitter vs Test Scenario
    fig, ax = plt.subplots(figsize=(12, 6))
    bars = ax.bar(x_pos, jitter_means, color='coral', alpha=0.8, edgecolor='black')
    ax.set_xlabel("Test Scenario", fontsize=12, fontweight='bold')
    ax.set_ylabel("Jitter (ms)", fontsize=12, fontweight='bold')
    ax.set_title("Average Jitter by Test Scenario (Latency Variation)", fontsize=14, fontweight='bold')
    ax.set_xticks(x_pos)
    ax.set_xticklabels(test_names_sorted, rotation=45, ha='right')
    ax.grid(axis='y', alpha=0.3)
    
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.2f}ms', ha='center', va='bottom', fontsize=10)
    
    plt.tight_layout()
    plt.savefig(os.path.join(GRAPHS_DIR, "02_jitter_by_scenario.png"), dpi=150)
    print(f"✓ Saved: 02_jitter_by_scenario.png")
    plt.close()
    
    # Graph 3: Perceived State Error vs Test Scenario
    fig, ax = plt.subplots(figsize=(12, 6))
    bars = ax.bar(x_pos, error_means, color='lightcoral', alpha=0.8, edgecolor='black')
    ax.set_xlabel("Test Scenario", fontsize=12, fontweight='bold')
    ax.set_ylabel("Perceived State Error (# of mismatched cells)", fontsize=12, fontweight='bold')
    ax.set_title("Average Grid State Synchronization Error by Test Scenario", fontsize=14, fontweight='bold')
    ax.set_xticks(x_pos)
    ax.set_xticklabels(test_names_sorted, rotation=45, ha='right')
    ax.grid(axis='y', alpha=0.3)
    
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.2f}', ha='center', va='bottom', fontsize=10)
    
    plt.tight_layout()
    plt.savefig(os.path.join(GRAPHS_DIR, "03_state_error_by_scenario.png"), dpi=150)
    print(f"✓ Saved: 03_state_error_by_scenario.png")
    plt.close()
    
    # Graph 4: Bandwidth Comparison
    fig, ax = plt.subplots(figsize=(12, 6))
    bars = ax.bar(x_pos, bandwidth_means, color='lightgreen', alpha=0.8, edgecolor='black')
    ax.set_xlabel("Test Scenario", fontsize=12, fontweight='bold')
    ax.set_ylabel("Bandwidth per Client (Kbps)", fontsize=12, fontweight='bold')
    ax.set_title("Network Bandwidth Usage by Test Scenario", fontsize=14, fontweight='bold')
    ax.set_xticks(x_pos)
    ax.set_xticklabels(test_names_sorted, rotation=45, ha='right')
    ax.grid(axis='y', alpha=0.3)
    
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.2f}', ha='center', va='bottom', fontsize=10)
    
    plt.tight_layout()
    plt.savefig(os.path.join(GRAPHS_DIR, "04_bandwidth_by_scenario.png"), dpi=150)
    print(f"✓ Saved: 04_bandwidth_by_scenario.png")
    plt.close()
    
    # Graph 5: Latency Distribution (box plot)
    fig, ax = plt.subplots(figsize=(14, 7))
    latency_data = [all_test_results[name]["data"]['latency_ms'].values for name in test_names_sorted]
    bp = ax.boxplot(latency_data, labels=test_names_sorted, patch_artist=True)
    
    for patch in bp['boxes']:
        patch.set_facecolor('lightblue')
        patch.set_alpha(0.7)
    
    ax.set_xlabel("Test Scenario", fontsize=12, fontweight='bold')
    ax.set_ylabel("Latency (ms)", fontsize=12, fontweight='bold')
    ax.set_title("Latency Distribution Across Test Scenarios", fontsize=14, fontweight='bold')
    ax.grid(axis='y', alpha=0.3)
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    plt.savefig(os.path.join(GRAPHS_DIR, "05_latency_distribution.png"), dpi=150)
    print(f"✓ Saved: 05_latency_distribution.png")
    plt.close()
    
    # Graph 6: Combined metric comparison (normalized)
    fig, ax = plt.subplots(figsize=(12, 6))
    
    latency_norm = np.array(latency_means) / max(latency_means) * 100 if max(latency_means) > 0 else np.zeros_like(latency_means)
    jitter_norm = np.array(jitter_means) / max(jitter_means) * 100 if max(jitter_means) > 0 else np.zeros_like(jitter_means)
    error_norm = np.array(error_means) / max(error_means) * 100 if max(error_means) > 0 else np.zeros_like(error_means)
    
    width = 0.25
    x_pos_metrics = np.arange(len(test_names_sorted))
    
    ax.bar(x_pos_metrics - width, latency_norm, width, label='Latency', color='steelblue', alpha=0.8)
    ax.bar(x_pos_metrics, jitter_norm, width, label='Jitter', color='coral', alpha=0.8)
    ax.bar(x_pos_metrics + width, error_norm, width, label='State Error', color='lightcoral', alpha=0.8)
    
    ax.set_xlabel("Test Scenario", fontsize=12, fontweight='bold')
    ax.set_ylabel("Normalized Score (0-100)", fontsize=12, fontweight='bold')
    ax.set_title("Normalized Performance Metrics Comparison", fontsize=14, fontweight='bold')
    ax.set_xticks(x_pos_metrics)
    ax.set_xticklabels(test_names_sorted, rotation=45, ha='right')
    ax.legend(fontsize=11)
    ax.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(os.path.join(GRAPHS_DIR, "06_normalized_metrics.png"), dpi=150)
    print(f"✓ Saved: 06_normalized_metrics.png")
    plt.close()
    
    # --- Graph 7: CDF (Cumulative Distribution Function) for Latency ---
    fig, axes = plt.subplots(1, len(test_names_sorted), figsize=(16, 5))
    if len(test_names_sorted) == 1:
        axes = [axes]
    
    for idx, test_name in enumerate(test_names_sorted):
        df = all_test_results[test_name]["data"]
        latencies = np.sort(df['latency_ms'].values)
        cumulative_pct = np.arange(1, len(latencies) + 1) / len(latencies) * 100
        
        ax = axes[idx]
        ax.plot(latencies, cumulative_pct, linewidth=2.5, color='darkblue', marker='o', markersize=3, alpha=0.6)
        ax.set_xlabel("Latency (ms)", fontsize=11, fontweight='bold')
        ax.set_ylabel("Cumulative Percentage (%)", fontsize=11, fontweight='bold')
        ax.set_title(f"{test_name}\nCDF", fontsize=12, fontweight='bold')
        ax.grid(alpha=0.3)
        ax.set_ylim([0, 100])
        
        # Add percentile markers
        p50 = np.percentile(df['latency_ms'], 50)
        p95 = np.percentile(df['latency_ms'], 95)
        p99 = np.percentile(df['latency_ms'], 99)
        
        ax.axvline(p50, color='green', linestyle='--', alpha=0.7, label=f'p50: {p50:.1f}ms')
        ax.axvline(p95, color='orange', linestyle='--', alpha=0.7, label=f'p95: {p95:.1f}ms')
        ax.axvline(p99, color='red', linestyle='--', alpha=0.7, label=f'p99: {p99:.1f}ms')
        ax.legend(fontsize=9)
    
    plt.tight_layout()
    plt.savefig(os.path.join(GRAPHS_DIR, "07_cdf_latency.png"), dpi=150)
    print(f"✓ Saved: 07_cdf_latency.png")
    plt.close()
    
    # --- Graph 8: Time-Series Scatter Plot (Latency vs Time) ---
    fig, axes = plt.subplots(1, len(test_names_sorted), figsize=(16, 5))
    if len(test_names_sorted) == 1:
        axes = [axes]
    
    for idx, test_name in enumerate(test_names_sorted):
        df = all_test_results[test_name]["data"]
        
        # Convert snapshot_id to time (assuming 50ms between snapshots)
        # First snapshot is at t=0, second at t=50ms, etc.
        time_seconds = df['snapshot_id'].values * 0.05
        
        ax = axes[idx]
        ax.scatter(time_seconds, df['latency_ms'].values, alpha=0.5, s=20, color='steelblue')
        
        # Add rolling average line for trend
        if len(df) > 10:
            rolling_avg = pd.Series(df['latency_ms'].values).rolling(window=10, center=True).mean()
            ax.plot(time_seconds, rolling_avg, color='red', linewidth=2, label='10-packet MA', alpha=0.8)
        
        ax.set_xlabel("Time (seconds)", fontsize=11, fontweight='bold')
        ax.set_ylabel("Latency (ms)", fontsize=11, fontweight='bold')
        ax.set_title(f"{test_name}\nLatency Over Time", fontsize=12, fontweight='bold')
        ax.grid(alpha=0.3)
        if len(df) > 10:
            ax.legend(fontsize=9)
        ax.set_xlim([0, max(time_seconds) * 1.05])
    
    plt.tight_layout()
    plt.savefig(os.path.join(GRAPHS_DIR, "08_latency_timeseries.png"), dpi=150)
    print(f"✓ Saved: 08_latency_timeseries.png")
    plt.close()
    
    # --- Graph 9: Stacked Area Chart for Bandwidth (Header vs Payload) ---
    fig, ax = plt.subplots(figsize=(14, 7))
    
    HEADER_SIZE = 28  # bytes (protocol overhead)
    
    test_names_sorted = sorted(all_test_results.keys())
    header_overhead = []
    payload_data = []
    
    for test_name in test_names_sorted:
        df = all_test_results[test_name]["data"]
        
        # Calculate average bytes sent and decompose into header and payload
        avg_bytes_sent = df['bytes_sent_instant'].mean()
        avg_payload = max(0, avg_bytes_sent - HEADER_SIZE)
        avg_header = min(HEADER_SIZE, avg_bytes_sent)
        
        # Convert to bandwidth (kbps)
        header_kbps = (avg_header * 8) / (0.05 * 1000)  # 50ms broadcast interval
        payload_kbps = (avg_payload * 8) / (0.05 * 1000)
        
        header_overhead.append(header_kbps)
        payload_data.append(payload_kbps)
    
    x_pos = np.arange(len(test_names_sorted))
    
    # Stacked area chart
    ax.bar(x_pos, header_overhead, label='Header Overhead (28 bytes)', color='#FF6B6B', alpha=0.85, edgecolor='black')
    ax.bar(x_pos, payload_data, bottom=header_overhead, label='Payload Data (Delta Encoded)', color='#4ECDC4', alpha=0.85, edgecolor='black')
    
    # Add total bandwidth labels on bars
    for i, (h, p) in enumerate(zip(header_overhead, payload_data)):
        total = h + p
        ax.text(i, total + 0.5, f'{total:.2f} Kbps', ha='center', va='bottom', fontsize=10, fontweight='bold')
        ax.text(i, h/2, f'{h:.2f}', ha='center', va='center', fontsize=9, color='white', fontweight='bold')
        ax.text(i, h + p/2, f'{p:.2f}', ha='center', va='center', fontsize=9, color='white', fontweight='bold')
    
    ax.set_xlabel("Test Scenario", fontsize=12, fontweight='bold')
    ax.set_ylabel("Bandwidth (Kbps)", fontsize=12, fontweight='bold')
    ax.set_title("Bandwidth Composition: Header Overhead vs Payload\n(Delta Encoding Efficiency)", fontsize=14, fontweight='bold')
    ax.set_xticks(x_pos)
    ax.set_xticklabels(test_names_sorted, rotation=45, ha='right')
    ax.legend(fontsize=11, loc='upper left')
    ax.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(os.path.join(GRAPHS_DIR, "09_bandwidth_stacked.png"), dpi=150)
    print(f"✓ Saved: 09_bandwidth_stacked.png")
    plt.close()
    
    print("\n" + "="*70)
    print("✅ Analysis complete! All graphs saved to:", GRAPHS_DIR)
    print("="*70)

if __name__ == "__main__":
    main()