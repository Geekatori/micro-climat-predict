from datetime import datetime, timezone
import os
import sqlite3
import joblib
import math
from fastapi import FastAPI, HTTPException, Query
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import train_test_split
from astral import LocationInfo
from astral.sun import elevation, azimuth

app = FastAPI()

DB_PATH = "/app/data/metrics.db"
MODEL_EXT_PATH = "/app/data/model_ext.joblib"
MODEL_INT_PATH = "/app/data/model_int.joblib"

LAT = float(os.getenv("LAT", 45.7797))
LON = float(os.getenv("LON", 3.0863))

# Multiscale features applied to weather and solar data
FEATURES_EXT = [
    "meteo_temp", "meteo_hum", "wind_speed", "sun_elevation", "sun_azimuth",
    "meteo_temp_lag1", "meteo_temp_lag6", "meteo_temp_lag12", "meteo_temp_lag72", "meteo_temp_lag144",
    "sun_elevation_lag1", "sun_elevation_lag6", "sun_elevation_lag12"
]

# Added thermal_mode and window_open_flag for interior physical behavior
FEATURES_INT = [
    "meteo_temp", "meteo_hum", "wind_speed", "sun_elevation", "sun_azimuth",
    "meteo_temp_lag1", "meteo_temp_lag6", "meteo_temp_lag12", "meteo_temp_lag72", "meteo_temp_lag144",
    "sun_elevation_lag1", "sun_elevation_lag6", "sun_elevation_lag12",
]

def clean_for_json(data):
    """Recursively traverse dictionaries and lists to replace NaN/Inf with None."""
    if isinstance(data, list):
        return [clean_for_json(item) for item in data]
    elif isinstance(data, dict):
        return {key: clean_for_json(value) for key, value in data.items()}
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return None
    return data

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS training_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            rows_ext INTEGER,
            rows_int INTEGER,
            rmse_ext REAL,
            rmse_int REAL,
            status TEXT,
            message TEXT
        )
    """)
    conn.commit()
    conn.close()

def add_solar_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add sun_elevation and sun_azimuth columns based on timestamps."""
    elevs, azims = [], []
    loc = LocationInfo(latitude=LAT, longitude=LON)
    for ts in pd.to_datetime(df["timestamp"]):
        dt = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
        elevs.append(elevation(loc.observer, dt))
        azims.append(azimuth(loc.observer, dt))
    df["sun_elevation"] = elevs
    df["sun_azimuth"] = azims
    return df

def add_multiscale_features(df: pd.DataFrame) -> pd.DataFrame:
    """Apply multiscale rolling lags to meteo_temp and sun_elevation."""
    lags = [1, 6, 12, 72, 144]
    for lag in lags:
        df[f"meteo_temp_lag{lag}"] = df["meteo_temp"].shift(lag)

    solar_lags = [1, 6, 12]
    for lag in solar_lags:
        df[f"sun_elevation_lag{lag}"] = df["sun_elevation"].shift(lag)

    return df

def add_behavioral_features(df: pd.DataFrame) -> pd.DataFrame:
    """State machine: opens on precise criteria, closes on CO2 rise or thermal inversion."""
    df["window_open_flag"] = 0
    df["is_fit_ready"] = 0
    df["thermal_mode"] = 4

    if "co2" in df.columns and "ext_temp" in df.columns and "int_temp_min" in df.columns:
        co2_drop = df["co2"].diff(6)
        is_co2_dropping = (co2_drop < -70).fillna(False)
        ext_cooler_than_int = (df["ext_temp"] < (df["int_temp_min"] - 0.5)).fillna(False)
        int_hot = (df["int_temp_min"] > 23.0).fillna(False)

        is_opening_co2 = is_co2_dropping & ext_cooler_than_int & int_hot

        int_warmer_than_ext = (df["int_temp_min"] > df["ext_temp"]).fillna(False)
        int_smoothed = df["int_temp_min"].rolling(window=6, min_periods=1).mean()
        int_smoothed_drop = int_smoothed.diff(3) < 0
        is_int_smoothed_dropping = int_smoothed_drop.fillna(False)

        co2_very_low = (df["co2"] < 700).fillna(False)

        is_opening_cooling = int_warmer_than_ext & is_int_smoothed_dropping & co2_very_low
        is_opening = is_opening_co2 | is_opening_cooling

        co2_rising = (df["co2"].diff(6) > 70).fillna(False)
        ext_exceeds_int = (df["ext_temp"] > df["int_temp_min"] + 0.5).fillna(False)
        is_closing = co2_rising | ext_exceeds_int

        state = pd.Series(0, index=df.index)
        current_state = 0

        for i in range(len(df)):
            if is_opening.iloc[i]:
                current_state = 1
            elif is_closing.iloc[i]:
                current_state = 0
            state.iloc[i] = current_state

        df["window_open_flag"] = state

        co2_high = (df["co2"] > 900).fillna(False)
        df["is_fit_ready"] = ((df["window_open_flag"] == 0) & co2_high).astype(int)

    df.loc[df["is_fit_ready"] == 1, "thermal_mode"] = 1
    df.loc[df["window_open_flag"] == 1, "thermal_mode"] = 3

    return df

@app.on_event("startup")
async def startup_event():
    init_db()

@app.post("/api/train")
async def train_models():
    """Train models using multiscale weather, solar, and behavioral features triggered by cron."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=404, detail="Database not found.")

    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql("SELECT * FROM metrics ORDER BY timestamp ASC", conn)
        conn.close()

        if df.empty:
            raise HTTPException(status_code=400, detail="Database is empty.")

        df = add_solar_features(df)
        df = add_behavioral_features(df)
        df = add_multiscale_features(df)
        df = df.dropna()

        if df.empty:
            raise HTTPException(status_code=400, detail="Not enough valid data after lag dropna.")

        # --- 1. Train Exterior Model ---
        X_ext = df[FEATURES_EXT]
        y_ext = df["ext_temp"]
        X_tr, X_te, y_tr, y_te = train_test_split(X_ext, y_ext, test_size=0.2, random_state=42)
        model_ext = RandomForestRegressor(n_estimators=100, random_state=42)
        model_ext.fit(X_tr, y_tr)
        rmse_ext = float(np.sqrt(mean_squared_error(y_te, model_ext.predict(X_te))))
        joblib.dump(model_ext, MODEL_EXT_PATH)

        # --- 2. Train Interior Minimum Temperature Model ---
        X_int = df[FEATURES_INT]
        y_int = df["int_temp_min"]
        X_tr, X_te, y_tr, y_te = train_test_split(X_int, y_int, test_size=0.2, random_state=42)
        model_int = RandomForestRegressor(n_estimators=100, random_state=42)
        model_int.fit(X_tr, y_tr)
        rmse_int = float(np.sqrt(mean_squared_error(y_te, model_int.predict(X_te))))
        joblib.dump(model_int, MODEL_INT_PATH)

        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            INSERT INTO training_logs (timestamp, rows_ext, rows_int, rmse_ext, rmse_int, status, message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (now_str, len(df), len(df), rmse_ext, rmse_int, "success", "Models trained successfully via scheduled cron"))
        conn.commit()
        conn.close()

        return {"status": "success", "rmse_ext": round(rmse_ext, 4), "rmse_int": round(rmse_int, 4)}

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/forecast/ext")
async def forecast_ext():
    if not os.path.exists(MODEL_EXT_PATH):
        raise HTTPException(status_code=400, detail="Exterior model not trained.")

    model = joblib.load(MODEL_EXT_PATH)
    conn = sqlite3.connect(DB_PATH)
    df_m = pd.read_sql("SELECT timestamp, meteo_temp, meteo_hum, wind_speed FROM metrics ORDER BY timestamp ASC", conn)
    try:
        df_f = pd.read_sql("SELECT timestamp, meteo_temp, meteo_hum, wind_speed FROM weather_forecasts ORDER BY timestamp ASC", conn)
    except:
        df_f = pd.DataFrame()
    conn.close()

    df_combined = pd.concat([df_m, df_f]).drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    df_combined = add_solar_features(df_combined)
    df_combined = add_multiscale_features(df_combined)

    df_features = df_combined.dropna(subset=FEATURES_EXT)
    if df_features.empty:
        return {"status": "success", "forecasts": []}

    preds = model.predict(df_features[FEATURES_EXT])
    df_features["predicted_ext_temp"] = [round(float(p), 2) for p in preds]

    return {"status": "success", "forecasts": df_features[["timestamp", "predicted_ext_temp"]].to_dict(orient="records")}

@app.get("/api/forecast/int")
async def forecast_int(window_open: int = Query(0, description="1 to allow active cooling, 0 to force closed inertia")):
    if not os.path.exists(MODEL_INT_PATH):
        raise HTTPException(status_code=400, detail="Interior model not trained.")

    model = joblib.load(MODEL_INT_PATH)

    conn = sqlite3.connect(DB_PATH)
    df_m = pd.read_sql("SELECT timestamp, meteo_temp, meteo_hum, wind_speed, int_temp_min, co2 FROM metrics ORDER BY timestamp ASC", conn)
    try:
        df_f = pd.read_sql("SELECT timestamp, meteo_temp, meteo_hum, wind_speed FROM weather_forecasts ORDER BY timestamp ASC", conn)
    except:
        df_f = pd.DataFrame()
    conn.close()

    df_combined = pd.concat([df_m, df_f]).drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    df_combined = add_solar_features(df_combined)

    df_combined = add_behavioral_features(df_combined)
    df_combined = add_multiscale_features(df_combined)

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    df_combined["dt"] = pd.to_datetime(df_combined["timestamp"])
    future_mask = df_combined["dt"] > now_utc

    if window_open == 1:
        active_cooling_mask = future_mask & (df_combined["sun_elevation"] < 0) & (df_combined["meteo_temp"] < 25)

        df_combined.loc[future_mask, "window_open_flag"] = 0
        df_combined.loc[future_mask, "thermal_mode"] = 1

        df_combined.loc[active_cooling_mask, "window_open_flag"] = 1
        df_combined.loc[active_cooling_mask, "thermal_mode"] = 3
    else:
        df_combined.loc[future_mask, "window_open_flag"] = 0
        df_combined.loc[future_mask, "thermal_mode"] = 1

    df_features = df_combined.dropna(subset=FEATURES_INT)
    if df_features.empty:
        return {"status": "success", "forecasts": []}

    preds = model.predict(df_features[FEATURES_INT])
    df_features["predicted_int_temp_min"] = [round(float(p), 2) for p in preds]

    return {"status": "success", "forecasts": df_features[["timestamp", "predicted_int_temp_min"]].to_dict(orient="records")}

@app.get("/api/metrics/annotated")
async def get_annotated_metrics():
    """Returns complete metrics history with CO2 classification and computed states."""
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=404, detail="Database not found.")

    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql("SELECT * FROM metrics ORDER BY timestamp ASC", conn)
        conn.close()

        if df.empty:
            return {"status": "success", "data": []}

        df = add_behavioral_features(df)
        df = df.replace([np.inf, -np.inf], np.nan)
        df = df.where(pd.notnull(df), None)

        return clean_for_json({
                "status": "success",
                "data": df.to_dict(orient="records")
            })
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))