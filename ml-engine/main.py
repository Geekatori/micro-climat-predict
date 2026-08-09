from datetime import datetime, timezone
import os
import sqlite3
import joblib
from fastapi import FastAPI, HTTPException
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

FEATURES_EXT = [
    "meteo_temp", "meteo_hum", "wind_speed", "sun_elevation", "sun_azimuth",
    "ext_lag1", "ext_lag2"
]

FEATURES_INT = [
    "meteo_temp", "meteo_hum", "wind_speed", "sun_elevation", "sun_azimuth",
    "int_lag1", "int_lag2"
]

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

def calculate_solar_position(dt: datetime, lat: float, lon: float):
    loc = LocationInfo(latitude=lat, longitude=lon)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    elev = elevation(loc.observer, dt)
    azim = azimuth(loc.observer, dt)
    return round(float(elev), 2), round(float(azim), 2)

def add_solar_features(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute les colonnes sun_elevation et sun_azimuth à partir des timestamps."""
    elevs, azims = [], []
    loc = LocationInfo(latitude=LAT, longitude=LON)
    for ts in pd.to_datetime(df["timestamp"]):
        dt = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
        elevs.append(elevation(loc.observer, dt))
        azims.append(azimuth(loc.observer, dt))
    df["sun_elevation"] = elevs
    df["sun_azimuth"] = azims
    return df

@app.on_event("startup")
async def startup_event():
    init_db()

@app.post("/api/train")
async def train_models():
    """Entraîne les modèles avec intégration des lag features et calcul solaire à la volée."""
    init_db()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=404, detail="Database not found.")

    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql("SELECT * FROM metrics ORDER BY timestamp ASC", conn)
        conn.close()

        if df.empty:
            raise HTTPException(status_code=400, detail="Database is empty.")

        # Calcul à la volée de la position du soleil
        df = add_solar_features(df)

        df["ext_lag1"] = df["ext_temp"].shift(6)
        df["ext_lag2"] = df["ext_temp"].shift(12)
        df["int_lag1"] = df["int_temp"].shift(6)
        df["int_lag2"] = df["int_temp"].shift(12)
        df = df.dropna()

        # --- 1. Train Exterior Model ---
        X_ext = df[FEATURES_EXT]
        y_ext = df["ext_temp"]
        X_tr, X_te, y_tr, y_te = train_test_split(X_ext, y_ext, test_size=0.2, random_state=42)
        model_ext = RandomForestRegressor(n_estimators=100, random_state=42)
        model_ext.fit(X_tr, y_tr)
        rmse_ext = float(np.sqrt(mean_squared_error(y_te, model_ext.predict(X_te))))
        joblib.dump(model_ext, MODEL_EXT_PATH)

        # --- 2. Train Interior Model ---
        X_int = df[FEATURES_INT]
        y_int = df["int_temp"]
        X_tr, X_te, y_tr, y_te = train_test_split(X_int, y_int, test_size=0.2, random_state=42)
        model_int = RandomForestRegressor(n_estimators=100, random_state=42)
        model_int.fit(X_tr, y_tr)
        rmse_int = float(np.sqrt(mean_squared_error(y_te, model_int.predict(X_te))))
        joblib.dump(model_int, MODEL_INT_PATH)

        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            INSERT INTO training_logs (timestamp, rows_ext, rows_int, rmse_ext, rmse_int, status, message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (now_str, len(df), len(df), rmse_ext, rmse_int, "success", "Models trained with solar calc and lag features"))
        conn.commit()
        conn.close()

        return {"status": "success", "rmse_ext": round(rmse_ext, 4), "rmse_int": round(rmse_int, 4)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/forecast/ext")
async def forecast_ext():
    if not os.path.exists(MODEL_EXT_PATH):
        raise HTTPException(status_code=400, detail="Exterior model not trained.")

    model = joblib.load(MODEL_EXT_PATH)
    conn = sqlite3.connect(DB_PATH)
    df_m = pd.read_sql("SELECT timestamp, ext_temp, meteo_temp, meteo_hum, wind_speed FROM metrics ORDER BY timestamp ASC", conn)
    try:
        df_f = pd.read_sql("SELECT timestamp, meteo_temp, meteo_hum, wind_speed FROM weather_forecasts ORDER BY timestamp ASC", conn)
    except:
        df_f = pd.DataFrame()
    conn.close()

    # Fusion des données passées et futures (Open-Meteo)
    df_combined = pd.concat([df_m, df_f]).drop_duplicates(subset=["timestamp"]).sort_values("timestamp")

    # Calcul de la position du soleil sur l'ensemble combiné
    df_combined = add_solar_features(df_combined)

    df_combined["ext_lag1"] = df_combined["ext_temp"].shift(6)
    df_combined["ext_lag2"] = df_combined["ext_temp"].shift(12)
    last_val = df_m["ext_temp"].dropna().iloc[-1] if not df_m["ext_temp"].dropna().empty else 20.0

    df_combined["ext_lag1"] = df_combined["ext_lag1"].ffill().fillna(last_val)
    df_combined["ext_lag2"] = df_combined["ext_lag2"].ffill().fillna(last_val)

    df_features = df_combined.dropna(subset=FEATURES_EXT)
    if df_features.empty:
        return {"status": "success", "forecasts": []}

    preds = model.predict(df_features[FEATURES_EXT])
    df_features["predicted_ext_temp"] = [round(float(p), 2) for p in preds]

    return {"status": "success", "forecasts": df_features[["timestamp", "predicted_ext_temp"]].to_dict(orient="records")}

@app.get("/api/forecast/int")
async def forecast_int():
    if not os.path.exists(MODEL_INT_PATH):
        raise HTTPException(status_code=400, detail="Interior model not trained.")

    model = joblib.load(MODEL_INT_PATH)
    conn = sqlite3.connect(DB_PATH)
    df_m = pd.read_sql("SELECT timestamp, int_temp, meteo_temp, meteo_hum, wind_speed FROM metrics ORDER BY timestamp ASC", conn)
    try:
        df_f = pd.read_sql("SELECT timestamp, meteo_temp, meteo_hum, wind_speed FROM weather_forecasts ORDER BY timestamp ASC", conn)
    except:
        df_f = pd.DataFrame()
    conn.close()

    # Fusion des données passées et futures (Open-Meteo)
    df_combined = pd.concat([df_m, df_f]).drop_duplicates(subset=["timestamp"]).sort_values("timestamp")

    # Calcul de la position du soleil sur l'ensemble combiné
    df_combined = add_solar_features(df_combined)

    df_combined["int_lag1"] = df_combined["int_temp"].shift(6)
    df_combined["int_lag2"] = df_combined["int_temp"].shift(12)
    last_val = df_m["int_temp"].dropna().iloc[-1] if not df_m["int_temp"].dropna().empty else 20.0

    df_combined["int_lag1"] = df_combined["int_lag1"].ffill().fillna(last_val)
    df_combined["int_lag2"] = df_combined["int_lag2"].ffill().fillna(last_val)

    df_features = df_combined.dropna(subset=FEATURES_INT)
    if df_features.empty:
        return {"status": "success", "forecasts": []}

    preds = model.predict(df_features[FEATURES_INT])
    df_features["predicted_int_temp"] = [round(float(p), 2) for p in preds]

    return {"status": "success", "forecasts": df_features[["timestamp", "predicted_int_temp"]].to_dict(orient="records")}