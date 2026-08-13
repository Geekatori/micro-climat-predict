from datetime import datetime, timedelta, timezone
import math
import os
import sqlite3
from dotenv import load_dotenv
import httpx
from fastapi import FastAPI
import pandas as pd
import asyncio

load_dotenv()

app = FastAPI()

HA_URL = os.getenv("HA_URL", "http://homeassistant.local:8123")
HA_TOKEN = os.getenv("HA_TOKEN")
LAT = float(os.getenv("LAT", 45.7797))
LON = float(os.getenv("LON", 3.0863))

DB_PATH = "/app/data/metrics.db"

ENTITIES = {
    "ext_temp": "sensor.exterieur_temperature",
    "ext_hum": "sensor.exterieur_humidity",
    "int_temp": "sensor.0x8c73dafffeda02b5_temperature",
    "int_hum": "sensor.0x8c73dafffeda02b5_humidity",
    "cor_temp": "sensor.temtop_c1plus_temtop_temperature",
    "cor_hum": "sensor.temtop_c1plus_temtop_humidity",
    "co2": "sensor.temtop_c1plus_temtop_co2",
    "int_temp_min": "sensor.temperature_interieure_min"
}

def migrate_db(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(metrics)")
    columns = [column[1] for column in cursor.fetchall()]

    # Add int_temp_min column if it does not exist
    if "int_temp_min" not in columns:
        conn.execute("ALTER TABLE metrics ADD COLUMN int_temp_min REAL")
        print("Migration: Added 'int_temp_min' column to metrics table.")

    # Add co2 column if it does not exist
    if "co2" not in columns:
        conn.execute("ALTER TABLE metrics ADD COLUMN co2 REAL")
        print("Migration: Added 'co2' column to metrics table.")


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS metrics (
            timestamp TEXT PRIMARY KEY,
            ext_temp REAL,
            ext_hum REAL,
            int_temp REAL,
            int_hum REAL,
            cor_temp REAL,
            cor_hum REAL,
            co2 REAL,
            meteo_temp REAL,
            meteo_hum REAL,
            wind_speed REAL,
            int_temp_min REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS weather_forecasts (
            timestamp TEXT PRIMARY KEY,
            meteo_temp REAL,
            meteo_hum REAL,
            wind_speed REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS collection_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            days_fetched INTEGER,
            rows_processed INTEGER,
            status TEXT,
            message TEXT
        )
    """)

    migrate_db(conn)

    conn.commit()
    conn.close()

def get_optimal_fetch_window(db_path: str) -> int:
    if not os.path.exists(db_path): return 10
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM metrics")
        count = cursor.fetchone()[0]
        conn.close()
        return 2 if count > 0 else 10
    except: return 10

@app.on_event("startup")
async def startup_event():
    init_db()

async def fetch_weather_data_days(days: int):
    async with httpx.AsyncClient() as client:
        now_utc = datetime.now(timezone.utc)
        start_time = now_utc - timedelta(days=days)
        end_time = now_utc + timedelta(days=7)

        ha_headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
        start_str = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")

        ha_data_dict = {key: [] for key in ENTITIES.keys()}
        entities_filter = ",".join(ENTITIES.values())

        try:
            ha_resp = await client.get(f"{HA_URL}/api/history/period/{start_str}?filter_entity_id={entities_filter}&end_time={end_str}", headers=ha_headers, timeout=20.0)
            if ha_resp.status_code == 200:
                for entity_history in ha_resp.json():
                    if not entity_history: continue
                    key = next((k for k, v in ENTITIES.items() if v == entity_history[0].get("entity_id")), None)
                    if key:
                        for state in entity_history:
                            try:
                                dt = datetime.fromisoformat(state["last_updated"])
                                val = float(state["state"])
                                if not math.isnan(val) and not math.isinf(val): ha_data_dict[key].append([dt, val])
                            except: continue
        except Exception as e: print(f"HA Error: {e}")

        meteo_past_points = []
        meteo_future_points = []
        max_retries = 3
        retry_delay = 2.0

        for attempt in range(max_retries):
            try:
                print(f"[{datetime.now()}] Fetching Open-Meteo data (Attempt {attempt + 1}/{max_retries})...")
                meteo_resp = await client.get(
                    f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&hourly=temperature_2m,relative_humidity_2m,wind_speed_10m&past_days={days}&forecast_days=7",
                    timeout=10.0
                )
                print(f"[{datetime.now()}] Open-Meteo response status: {meteo_resp.status_code}")

                if meteo_resp.status_code == 200:
                    data = meteo_resp.json()["hourly"]
                    print(f"[{datetime.now()}] Successfully received {len(data.get('time', []))} hourly points.")
                    for t_str, temp, hum, wind in zip(data["time"], data["temperature_2m"], data["relative_humidity_2m"], data["wind_speed_10m"]):
                        dt = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)
                        point = [dt, float(temp), float(hum), float(wind or 0.0)]

                        if dt <= now_utc:
                            meteo_past_points.append(point)
                        else:
                            meteo_future_points.append(point)
                    break  # Exit retry loop on success
                else:
                    print(f"[{datetime.now()}] Open-Meteo error HTTP {meteo_resp.status_code}: {meteo_resp.text}")
            except Exception as e:
                print(f"[{datetime.now()}] Open-Meteo exception on attempt {attempt + 1}: {e}")

            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)

        print(f"[{datetime.now()}] Final summary -> meteo_past_points: {len(meteo_past_points)} | meteo_future_points: {len(meteo_future_points)}")

        return ha_data_dict, meteo_past_points, meteo_future_points

@app.get("/api/collect")
async def run_collection():
    init_db()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    days_to_fetch = get_optimal_fetch_window(DB_PATH)

    try:
        ha_data, meteo_past_points, meteo_future_points = await fetch_weather_data_days(days=days_to_fetch)

        # 1. Process Past Data (Metrics)
        dfs_past = []
        for key, data in ha_data.items():
            if data:
                df = pd.DataFrame(data, columns=["timestamp", key])
                df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_convert("UTC").dt.tz_localize(None)
                # Resample individuel par capteur avec interpolation et ffill/bfill
                dfs_past.append(df.set_index("timestamp").resample("10min").mean().interpolate(method="linear").ffill().bfill())

        if meteo_past_points:
            df_meteo_past = pd.DataFrame(meteo_past_points, columns=["timestamp", "meteo_temp", "meteo_hum", "wind_speed"])
            df_meteo_past["timestamp"] = pd.to_datetime(df_meteo_past["timestamp"]).dt.tz_convert("UTC").dt.tz_localize(None)
            df_meteo_past = df_meteo_past.set_index("timestamp").resample("10min").mean().interpolate(method="linear").ffill().bfill()
            dfs_past.append(df_meteo_past)

        if dfs_past:
            # Concaténation globale et propagation propre de la dernière valeur pour chaque capteur (pas de croisement)
            final_past_df = pd.concat(dfs_past, axis=1)
            final_past_df = final_past_df.ffill().bfill().reset_index()

            numeric_cols_past = final_past_df.select_dtypes(include=["number"]).columns
            final_past_df[numeric_cols_past] = final_past_df[numeric_cols_past].round(2)

            final_past_df["timestamp"] = final_past_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

            conn = sqlite3.connect(DB_PATH)
            final_past_df.to_sql("metrics_temp", conn, if_exists="replace", index=False)
            conn.execute("""
                INSERT INTO metrics (
                    timestamp, ext_temp, ext_hum, int_temp, int_hum,
                    cor_temp, cor_hum, co2, meteo_temp, meteo_hum, wind_speed, int_temp_min
                )
                SELECT
                    timestamp, ext_temp, ext_hum, int_temp, int_hum,
                    cor_temp, cor_hum, co2, meteo_temp, meteo_hum, wind_speed, int_temp_min
                FROM metrics_temp
                ON CONFLICT(timestamp) DO UPDATE SET
                    ext_temp = COALESCE(excluded.ext_temp, metrics.ext_temp),
                    ext_hum = COALESCE(excluded.ext_hum, metrics.ext_hum),
                    int_temp = COALESCE(excluded.int_temp, metrics.int_temp),
                    int_hum = COALESCE(excluded.int_hum, metrics.int_hum),
                    cor_temp = COALESCE(excluded.cor_temp, metrics.cor_temp),
                    cor_hum = COALESCE(excluded.cor_hum, metrics.cor_hum),
                    co2 = COALESCE(excluded.co2, metrics.co2),
                    meteo_temp = COALESCE(excluded.meteo_temp, metrics.meteo_temp),
                    meteo_hum = COALESCE(excluded.meteo_hum, metrics.meteo_hum),
                    wind_speed = COALESCE(excluded.wind_speed, metrics.wind_speed),
                    int_temp_min = COALESCE(excluded.int_temp_min, metrics.int_temp_min);
            """)
            conn.execute("DROP TABLE metrics_temp")
            conn.commit()
            conn.close()

        # 2. Process Future Weather Forecasts (Volatile Cache)
        if meteo_future_points:
            df_meteo_future = pd.DataFrame(meteo_future_points, columns=["timestamp", "meteo_temp", "meteo_hum", "wind_speed"])
            df_meteo_future["timestamp"] = pd.to_datetime(df_meteo_future["timestamp"]).dt.tz_convert("UTC").dt.tz_localize(None)
            df_meteo_future = df_meteo_future.set_index("timestamp").resample("10min").mean().interpolate(method="linear").ffill().bfill()

            final_future_df = df_meteo_future.reset_index()
            numeric_cols_fut = final_future_df.select_dtypes(include=["number"]).columns
            final_future_df[numeric_cols_fut] = final_future_df[numeric_cols_fut].round(2)

            final_future_df["timestamp"] = final_future_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

            conn = sqlite3.connect(DB_PATH)
            final_future_df.to_sql("weather_forecasts", conn, if_exists="replace", index=False)
            conn.commit()
            conn.close()

        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            INSERT INTO collection_logs (timestamp, days_fetched, rows_processed, status, message)
            VALUES (?, ?, ?, ?, ?)
        """, (now_str, days_to_fetch, len(dfs_past[0]) if dfs_past else 0, "success", "Collection completed successfully"))
        conn.commit()
        conn.close()

        return {"status": "success", "rows_processed": len(dfs_past[0]) if dfs_past else 0}

    except Exception as e:
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("""
                INSERT INTO collection_logs (timestamp, days_fetched, rows_processed, status, message)
                VALUES (?, ?, ?, ?, ?)
            """, (now_str, days_to_fetch, 0, "error", str(e)))
            conn.commit()
            conn.close()
        except:
            pass
        raise e