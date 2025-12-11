import pandas as pd
import json
import numpy as np
import glob
import os

# --- Configuration ---
SERVER_LOG = "server_log.csv"
CLIENT_LOG_PATTERN = "client_log_*.csv"
OUTPUT_CSV = "experiment_results_final.csv"

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
            # For Grid Clash, 'state' is the owner ID. 
            # If owners match, no error.
            srv_val = server_state.get(key)
            cli_val = client_state.get(key)
            if srv_val != cli_val:
                errors += 1
        return errors
    except:
        return 0

def main():
    if not os.path.exists(SERVER_LOG):
        print(f"Error: {SERVER_LOG} not found.")
        return

    client_files = glob.glob(CLIENT_LOG_PATTERN)
    if not client_files:
        print("Error: No client logs found.")
        return

    print(f"Loading {SERVER_LOG}...")
    df_server = pd.read_csv(SERVER_LOG)
    
    all_results = []

    for c_file in client_files:
        print(f"Processing {c_file}...")
        df_client = pd.read_csv(c_file)
        
        # Merge Client and Server logs on 'snapshot_id'
        # We use inner join to only analyze snapshots received by client
        merged = pd.merge(df_client, df_server, on="snapshot_id", suffixes=('_cli', '_srv'))
        
        # Calculate Perceived Error
        merged['perceived_position_error'] = merged.apply(
            lambda row: calculate_state_error(row['authoritative_state'], row['perceived_state']), axis=1
        )
        
        # Calculate Bandwidth (kbps) for this client
        # Logic: bytes_sent_instant is total for ALL clients. 
        # Approx per client = (bytes / num_clients) ... 
        # But simply: Bandwidth = (bytes * 8) / (0.05s broadcast interval) / 1000
        # We will use the logged 'bytes_sent_instant' which is the packet size
        # Assuming 1 client for simplicity in calculation, or divide by known count.
        # For the final CSV, let's just report the rate based on that packet size.
        # bit_rate_kbps = (Bytes * 8) / (Broadcast_Interval_sec * 1000)
        # Broadcast interval is 0.05s (20Hz)
        merged['bandwidth_per_client_kbps'] = (merged['bytes_sent_instant'] * 8) / (0.05 * 1000)

        # Select columns for final output
        final_df = merged[[
            "client_id", 
            "snapshot_id", 
            "seq_num", 
            "server_timestamp_ms", 
            "recv_time_ms", 
            "latency_ms", 
            "jitter_ms", 
            "perceived_position_error", 
            "cpu_percent", 
            "bandwidth_per_client_kbps"
        ]]
        
        all_results.append(final_df)

    if not all_results:
        print("No matching snapshots found.")
        return

    # Combine all clients
    full_report = pd.concat(all_results)
    
    # Save to CSV
    full_report.to_csv(OUTPUT_CSV, index=False)
    print(f"\n✅ Final combined log saved to: {OUTPUT_CSV}")

    # --- Print Statistics (Mean, Median, 95th Percentile) ---
    print("\n" + "="*40)
    print("       EXPERIMENT RESULTS SUMMARY       ")
    print("="*40)
    
    metrics = ["latency_ms", "jitter_ms", "perceived_position_error", "cpu_percent"]
    
    for metric in metrics:
        data = full_report[metric]
        
        # Skip CPU percent if it's all "N/A"
        if metric == "cpu_percent":
            # Try to convert to numeric, skip if all are N/A
            data_numeric = pd.to_numeric(data, errors='coerce')
            if data_numeric.isna().all():
                print(f"\nMetric: {metric}")
                print(f"  Status: Not collected (all values are N/A)")
                continue
            else:
                data = data_numeric.dropna()
        
        mean_val = data.mean()
        median_val = data.median()
        p95_val = data.quantile(0.95)
        
        print(f"\nMetric: {metric}")
        print(f"  Mean:            {mean_val:.2f}")
        print(f"  Median:          {median_val:.2f}")
        print(f"  95th Percentile: {p95_val:.2f}")

    print("="*40)

if __name__ == "__main__":
    main()