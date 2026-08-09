from datetime import datetime, timedelta, timezone
import math
import os
import sqlite3
from dotenv import load_dotenv
import httpx
from fastapi import FastAPI
import pandas as pd
from astral import LocationInfo
from astral.sun import elevation, azimuth

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
    "cor_hum": "sensor.temtop_c1plus_temtop_humidity"
}

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    # Historical validated metrics (past only)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS metrics (
            timestamp TEXT PRIMARY KEY,
            ext_temp REAL,
            ext_hum REAL,
            int_temp REAL,
            int_hum REAL,
            cor_temp REAL,
            cor_hum REAL,
            meteo_temp REAL,
            meteo_hum REAL,
            wind_speed REAL,
            sun_elevation REAL,
            sun_azimuth REAL
        )
    """)
    # Future weather forecasts (volatile, separate table)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS weather_forecasts (
            timestamp TEXT PRIMARY KEY,
            meteo_temp REAL,
            meteo_hum REAL,
            wind_speed REAL,
            sun_elevation REAL,
            sun_azimuth REAL
        )
    """)
    # Collection logs
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
    conn.commit()
    conn.close()

def calculate_solar_position(dt: datetime, lat: float, lon: float):
    loc = LocationInfo(latitude=lat, longitude=lon)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    elev = elevation(loc.observer, dt)
    azim = azimuth(loc.observer, dt)
    return round(float(elev), 2), round(float(azim), 2)

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
        end_time = now_utc + timedelta(days=2)

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

        # Fetch continuous block including past and future in a single request
        meteo_past_points = []
        meteo_future_points = []
        try:
            meteo_resp = await client.get(f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&hourly=temperature_2m,relative_humidity_2m,wind_speed_10m&past_days={days}&forecast_days=2", timeout=10.0)
            if meteo_resp.status_code == 200:
                data = meteo_resp.json()["hourly"]
                for t_str, temp, hum, wind in zip(data["time"], data["temperature_2m"], data["relative_humidity_2m"], data["wind_speed_10m"]):
                    dt = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)
                    point = [dt, float(temp), float(hum), float(wind or 0.0)]

                    if dt <= now_utc:
                        meteo_past_points.append(point)
                    else:
                        meteo_future_points.append(point)
        except Exception as e: print(f"Meteo Error: {e}")

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
                dfs_past.append(df.set_index("timestamp").resample("10min").mean().interpolate(method="linear").ffill().bfill())

        if meteo_past_points:
            df_meteo_past = pd.DataFrame(meteo_past_points, columns=["timestamp", "meteo_temp", "meteo_hum", "wind_speed"])
            df_meteo_past["timestamp"] = pd.to_datetime(df_meteo_past["timestamp"]).dt.tz_convert("UTC").dt.tz_localize(None)
            df_meteo_past = df_meteo_past.set_index("timestamp").resample("10min").mean().interpolate(method="linear").ffill().bfill()
            solar = [calculate_solar_position(ts, LAT, LON) for ts in df_meteo_past.index]
            df_meteo_past["sun_elevation"], df_meteo_past["sun_azimuth"] = [s[0] for s in solar], [s[1] for s in solar]
            dfs_past.append(df_meteo_past)

        if dfs_past:
            final_past_df = pd.concat(dfs_past, axis=1).reset_index()
            numeric_cols_past = final_past_df.select_dtypes(include=["number"]).columns
            final_past_df[numeric_cols_past] = final_past_df[numeric_cols_past].round(2)

            final_past_df["timestamp"] = final_past_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

            conn = sqlite3.connect(DB_PATH)
            final_past_df.to_sql("metrics_temp", conn, if_exists="replace", index=False)
            conn.execute("""
                INSERT INTO metrics (
                    timestamp, ext_temp, ext_hum, int_temp, int_hum,
                    cor_temp, cor_hum, meteo_temp, meteo_hum,
                    wind_speed, sun_elevation, sun_azimuth
                )
                SELECT
                    timestamp, ext_temp, ext_hum, int_temp, int_hum,
                    cor_temp, cor_hum, meteo_temp, meteo_hum,
                    wind_speed, sun_elevation, sun_azimuth
                FROM metrics_temp
                WHERE true
                ON CONFLICT(timestamp) DO UPDATE SET
                    ext_temp = COALESCE(metrics.ext_temp, excluded.ext_temp),
                    ext_hum = COALESCE(metrics.ext_hum, excluded.ext_hum),
                    int_temp = COALESCE(metrics.int_temp, excluded.int_temp),
                    int_hum = COALESCE(metrics.int_hum, excluded.int_hum),
                    cor_temp = COALESCE(metrics.cor_temp, excluded.cor_temp),
                    cor_hum = COALESCE(metrics.cor_hum, excluded.cor_hum),
                    meteo_temp = COALESCE(metrics.meteo_temp, excluded.meteo_temp),
                    meteo_hum = COALESCE(metrics.meteo_hum, excluded.meteo_hum),
                    wind_speed = COALESCE(metrics.wind_speed, excluded.wind_speed),
                    sun_elevation = COALESCE(metrics.sun_elevation, excluded.sun_elevation),
                    sun_azimuth = COALESCE(metrics.sun_azimuth, excluded.sun_azimuth);
            """)
            conn.execute("DROP TABLE metrics_temp")
            conn.commit()
            conn.close()

        # 2. Process Future Weather Forecasts (Volatile Cache)
        if meteo_future_points:
            df_meteo_future = pd.DataFrame(meteo_future_points, columns=["timestamp", "meteo_temp", "meteo_hum", "wind_speed"])
            df_meteo_future["timestamp"] = pd.to_datetime(df_meteo_future["timestamp"]).dt.tz_convert("UTC").dt.tz_localize(None)
            df_meteo_future = df_meteo_future.set_index("timestamp").resample("10min").mean().interpolate(method="linear").ffill().bfill()
            solar_fut = [calculate_solar_position(ts, LAT, LON) for ts in df_meteo_future.index]
            df_meteo_future["sun_elevation"], df_meteo_future["sun_azimuth"] = [s[0] for s in solar_fut], [s[1] for s in solar_fut]

            final_future_df = df_meteo_future.reset_index()
            numeric_cols_fut = final_future_df.select_dtypes(include=["number"]).columns
            final_future_df[numeric_cols_fut] = final_future_df[numeric_cols_fut].round(2)

            final_future_df["timestamp"] = final_future_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

            conn = sqlite3.connect(DB_PATH)
            final_future_df.to_sql("weather_forecasts", conn, if_exists="replace", index=False)
            conn.commit()
            conn.close()

        # Record success log
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

@app.get("/api/data")
async def get_stored_data():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM metrics", conn)
    conn.close()
    return df.to_dict(orient="records")

@app.delete("/api/clean")
async def clean_database():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DROP TABLE IF EXISTS metrics")
        conn.execute("DROP TABLE IF EXISTS weather_forecasts")
        conn.execute("DROP TABLE IF EXISTS collection_logs")
        conn.commit(); conn.close()
        init_db()
        return {"status": "success", "message": "Database cleaned."}
    except Exception as e: return {"status": "error", "message": str(e)}