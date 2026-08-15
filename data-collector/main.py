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
}

_db_cache = {}

def clear_db_cache():
    """Clears the in-memory cache."""
    _db_cache.clear()
    print(f"[{datetime.now()}] Database cache cleared.")

def migrate_db(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(metrics)")
    columns = [column[1] for column in cursor.fetchall()]

    if "int_temp_min" not in columns:
        conn.execute("ALTER TABLE metrics ADD COLUMN int_temp_min REAL")
        print("Migration: Added 'int_temp_min' column to metrics table.")

    if "co2" not in columns:
        conn.execute("ALTER TABLE metrics ADD COLUMN co2 REAL")
        print("Migration: Added 'co2' column to metrics table.")

    if "cloud_cover" not in columns:
        conn.execute("ALTER TABLE metrics ADD COLUMN cloud_cover REAL")
        print("Migration: Added 'cloud_cover' column to metrics table.")

    if "direct_radiation" not in columns:
        conn.execute("ALTER TABLE metrics ADD COLUMN direct_radiation REAL")
        print("Migration: Added 'direct_radiation' column to metrics table.")

    cursor.execute("PRAGMA table_info(weather_forecasts)")
    forecast_columns = [column[1] for column in cursor.fetchall()]

    if "cloud_cover" not in forecast_columns:
        conn.execute("ALTER TABLE weather_forecasts ADD COLUMN cloud_cover REAL")
    if "direct_radiation" not in forecast_columns:
        conn.execute("ALTER TABLE weather_forecasts ADD COLUMN direct_radiation REAL")

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
            cloud_cover REAL,
            direct_radiation REAL,
            int_temp_min REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS weather_forecasts (
            timestamp TEXT PRIMARY KEY,
            meteo_temp REAL,
            meteo_hum REAL,
            wind_speed REAL,
            cloud_cover REAL,
            direct_radiation REAL
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
                    f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&hourly=temperature_2m,relative_humidity_2m,wind_speed_10m,cloud_cover,direct_radiation&past_days={days}&forecast_days=7",
                    timeout=10.0
                )
                print(f"[{datetime.now()}] Open-Meteo response status: {meteo_resp.status_code}")

                if meteo_resp.status_code == 200:
                    data = meteo_resp.json()["hourly"]
                    print(f"[{datetime.now()}] Successfully received {len(data.get('time', []))} hourly points.")
                    for t_str, temp, hum, wind, clouds, radiation in zip(
                        data["time"], data["temperature_2m"], data["relative_humidity_2m"],
                        data["wind_speed_10m"], data["cloud_cover"], data["direct_radiation"]
                    ):
                        dt = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)
                        point = [dt, float(temp), float(hum), float(wind or 0.0), float(clouds or 0.0), float(radiation or 0.0)]

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
async def run_collection(days: int = None):
    init_db()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    # Utilise le paramètre de l'URL s'il est fourni, sinon prend la valeur optimale (2 ou 10)
    days_to_fetch = days if days is not None else get_optimal_fetch_window(DB_PATH)

    try:
        print(f"[{datetime.now()}] Starting collection for the last {days_to_fetch} days...")
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
            df_meteo_past = pd.DataFrame(meteo_past_points, columns=["timestamp", "meteo_temp", "meteo_hum", "wind_speed", "cloud_cover", "direct_radiation"])
            df_meteo_past["timestamp"] = pd.to_datetime(df_meteo_past["timestamp"]).dt.tz_convert("UTC").dt.tz_localize(None)
            df_meteo_past = df_meteo_past.set_index("timestamp").resample("10min").mean().interpolate(method="linear").ffill().bfill()
            dfs_past.append(df_meteo_past)

        if dfs_past:
            # Concaténation globale et propagation propre de la dernière valeur pour chaque capteur (pas de croisement)
            final_past_df = pd.concat(dfs_past, axis=1)
            final_past_df = final_past_df.ffill().reset_index()

            # Always compute int_temp_min dynamically as the minimum between int_temp and cor_temp
            if "int_temp" in final_past_df.columns and "cor_temp" in final_past_df.columns:
                final_past_df["int_temp_min"] = final_past_df[["int_temp", "cor_temp"]].min(axis=1)

            numeric_cols_past = final_past_df.select_dtypes(include=["number"]).columns
            final_past_df[numeric_cols_past] = final_past_df[numeric_cols_past].round(2)

            final_past_df["timestamp"] = final_past_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

            conn = sqlite3.connect(DB_PATH)
            final_past_df.to_sql("metrics_temp", conn, if_exists="replace", index=False)
            conn.execute("""
                INSERT OR IGNORE INTO metrics (
                    timestamp, ext_temp, ext_hum, int_temp, int_hum,
                    cor_temp, cor_hum, co2, meteo_temp, meteo_hum, wind_speed, cloud_cover, direct_radiation, int_temp_min
                )
                SELECT
                    timestamp, ext_temp, ext_hum, int_temp, int_hum,
                    cor_temp, cor_hum, co2, meteo_temp, meteo_hum, wind_speed, cloud_cover, direct_radiation, int_temp_min
                FROM metrics_temp;
            """)

            # 2. On met à jour les lignes existantes en évitant d'écraser par du NULL
            conn.execute("""
                UPDATE metrics
                SET
                    ext_temp = COALESCE(metrics_temp.ext_temp, metrics.ext_temp),
                    ext_hum = COALESCE(metrics_temp.ext_hum, metrics.ext_hum),
                    int_temp = COALESCE(metrics_temp.int_temp, metrics.int_temp),
                    int_hum = COALESCE(metrics_temp.int_hum, metrics.int_hum),
                    cor_temp = COALESCE(metrics_temp.cor_temp, metrics.cor_temp),
                    cor_hum = COALESCE(metrics_temp.cor_hum, metrics.cor_hum),
                    co2 = COALESCE(metrics_temp.co2, metrics.co2),
                    meteo_temp = COALESCE(metrics_temp.meteo_temp, metrics.meteo_temp),
                    meteo_hum = COALESCE(metrics_temp.meteo_hum, metrics.meteo_hum),
                    wind_speed = COALESCE(metrics_temp.wind_speed, metrics.wind_speed),
                    cloud_cover = COALESCE(metrics_temp.cloud_cover, metrics.cloud_cover),
                    direct_radiation = COALESCE(metrics_temp.direct_radiation, metrics.direct_radiation),
                    int_temp_min = COALESCE(metrics_temp.int_temp_min, metrics.int_temp_min)
                FROM metrics_temp
                WHERE metrics.timestamp = metrics_temp.timestamp;
            """)

            conn.execute("DROP TABLE metrics_temp")
            conn.commit()
            conn.close()

        # 2. Process Future Weather Forecasts (Volatile Cache)
        # 2. Process Future Weather Forecasts (Volatile Cache)
        if meteo_future_points:
            df_meteo_future = pd.DataFrame(meteo_future_points, columns=["timestamp", "meteo_temp", "meteo_hum", "wind_speed", "cloud_cover", "direct_radiation"])
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

        clear_db_cache()

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

@app.get("/api/data/history/{version}")
async def get_history_data(version: str):
    """
    Fetch historical metrics from the database with in-memory caching.
    version: '24h' or '7d'
    """
    cache_key = f"history_{version}"

    # Return cached data if available
    if cache_key in _db_cache:
        return _db_cache[cache_key]

    hours_back = 24 if version == '24h' else (7 * 24)
    start_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    start_str_db = start_time.strftime("%Y-%m-%d %H:%M:%S")

    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql(
            "SELECT timestamp, ext_temp, int_temp_min, cor_temp, int_temp "
            "FROM metrics "
            "WHERE timestamp >= ? "
            "ORDER BY timestamp ASC",
            conn,
            params=(start_str_db,)
        )
        conn.close()

        if df.empty:
            result = {"status": "success", "data": []}
        else:
            result = {"status": "success", "data": df.to_dict(orient="records")}

        # Store the result in cache before returning
        _db_cache[cache_key] = result
        return result

    except Exception as e:
        print(f"Database read error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/data/current")
async def get_current_metrics():
    """
    Fetch the most recent metrics row with caching.
    """
    cache_key = "current_metrics"

    if cache_key in _db_cache:
        return _db_cache[cache_key]

    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql(
            "SELECT ext_temp, int_temp_min, cor_temp, int_temp "
            "FROM metrics "
            "ORDER BY timestamp DESC LIMIT 1",
            conn
        )
        conn.close()

        if df.empty:
            result = {"status": "success", "data": {}}
        else:
            result = {"status": "success", "data": df.iloc[0].to_dict()}

        _db_cache[cache_key] = result
        return result

    except Exception as e:
        print(f"Database read error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/data/openmeteo")
async def get_open_meteo():
    """
    Fetch raw Open-Meteo temperatures (past and future) for the baseline chart curve.
    """
    cache_key = "open_meteo_series"
    if cache_key in _db_cache:
        return _db_cache[cache_key]

    try:
        conn = sqlite3.connect(DB_PATH)
        # Fetch past and future meteo temps, combining them
        df_m = pd.read_sql("SELECT timestamp, meteo_temp FROM metrics WHERE meteo_temp IS NOT NULL", conn)
        df_f = pd.read_sql("SELECT timestamp, meteo_temp FROM weather_forecasts WHERE meteo_temp IS NOT NULL", conn)
        conn.close()

        # Merge and drop duplicates
        df = pd.concat([df_m, df_f]).drop_duplicates(subset=["timestamp"]).sort_values("timestamp")

        if df.empty:
            result = {"status": "success", "data": []}
        else:
            result = {"status": "success", "data": df.to_dict(orient="records")}

        _db_cache[cache_key] = result
        return result

    except Exception as e:
        print(f"Database read error for Open-Meteo: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/status/last-collection")
def get_last_collection():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT timestamp FROM metrics ORDER BY timestamp DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()

        last_ts = row[0] if row else None
        return {"status": "success", "last_collection": last_ts}
    except Exception as e:
        return {"status": "error", "message": str(e)}