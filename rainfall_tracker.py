import os
import time
import requests
import urllib3
import pandas as pd
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DISTRICT_ID = -1
BASE_CONFIG_URL = "https://infobanjirjps.selangor.gov.my/data/config.json"
DATA_DIR = "data"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*"
}

def get_target_csv_filename():
    os.makedirs(DATA_DIR, exist_ok=True)
    now = datetime.now()
    day = now.day

    if day <= 10:
        period = "part1"
    elif day <= 20:
        period = "part2"
    else:
        period = "part3"

    filename = f"selangor_rainfall_{now.strftime('%Y_%m')}_{period}.csv"
    return os.path.join(DATA_DIR, filename)

def fetch_with_retry(url, retries=3, backoff=5):
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30, verify=False)
            resp.raise_for_status()
            return resp.json()
        except Exception as err:
            print(f"[Attempt {attempt}/{retries}] Request failed: {err}")
            if attempt < retries:
                time.sleep(backoff)
            else:
                return None

def fetch_rainfall_data():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] Fetching data from InfoBanjir Rainfall API...")

    cfg_data = fetch_with_retry(BASE_CONFIG_URL)
    api_base = cfg_data.get("apiURL", "https://infobanjirjps.selangor.gov.my/InfoBanjir.WebAPI/api/") if cfg_data else "https://infobanjirjps.selangor.gov.my/InfoBanjir.WebAPI/api/"

    if not api_base.endswith("/"):
        api_base += "/"

    data_url = (
        f"{api_base}StationRainfalls/GetRFStationData/-1"
        if DISTRICT_ID == -1
        else f"{api_base}StationRainfalls/GetRFAllStationData/{DISTRICT_ID}"
    )

    payload = fetch_with_retry(data_url)
    if not payload:
        print("Rainfall server did not respond after 3 attempts.")
        return None

    stations = payload.get("stations", [])
    if not stations:
        print("No rainfall stations returned.")
        return None

    records = []
    for s in stations:
        if s.get("stationStatus") != 1:
            continue

        hourly_rf = s.get("hourlyRainfall")
        today_rf = s.get("todayRainfall")

        if (hourly_rf is not None and hourly_rf <= -900) or (today_rf is not None and today_rf <= -900):
            continue

        records.append({
            "Station_ID": str(s.get("stationId", "")).strip(),
            "Station_Name": s.get("stationName", "").strip(),
            "District": s.get("districtName", "").strip(),
            "Last_Updated": s.get("lastUpdate", ""),
            "Total_1Hour_mm": hourly_rf,
            "Rain_From_Midnight_mm": today_rf,
            "Latitude": s.get("latitude"),
            "Longitude": s.get("longitude"),
            "Scraped_At": now_str
        })

    return pd.DataFrame(records)

def save_and_deduplicate(new_df):
    if new_df is None or new_df.empty:
        print("No valid active rainfall records to append.")
        return

    csv_file = get_target_csv_filename()
    print(f"Target file: {csv_file}")

    existing_df = pd.DataFrame()
    if os.path.exists(csv_file):
        try:
            existing_df = pd.read_csv(csv_file)
            if "Total_1Hour_mm" in existing_df.columns:
                existing_df = existing_df[existing_df["Total_1Hour_mm"] > -900]
        except pd.errors.EmptyDataError:
            existing_df = pd.DataFrame()

    if not existing_df.empty:
        combined = pd.concat([existing_df, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["Station_ID", "Last_Updated"], keep="last")
        added = len(combined) - len(existing_df)
        combined.to_csv(csv_file, index=False)
        print(f"Appended {added} new rainfall record(s) to {csv_file}. Total: {len(combined)}")
    else:
        new_df.to_csv(csv_file, index=False)
        print(f"Initialized {csv_file} with {len(new_df)} initial records.")

if __name__ == "__main__":
    data = fetch_rainfall_data()
    save_and_deduplicate(data)
