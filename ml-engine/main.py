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

app = FastAPI()

DB_PATH = "/app/data/metrics.db"
MODEL_EXT_PATH = "/app/data/model_ext.joblib"
MODEL_INT_PATH = "/app/data/model_int.joblib"

FEATURES_EXT = [
    "meteo_temp",
    "meteo_hum",
    "wind_speed",
    "sun_elevation",
    "sun_azimuth"
]

FEATURES_INT = [
    "meteo_temp",
    "meteo_hum",
    "wind_speed",
    "sun_elevation",
    "sun_azimuth"
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

@app.on_event("startup")
async def startup_event():
    init_db()

@app.post("/api/train")
async def train_models():
    """Train both exterior (urban heat island) and interior temperature models using strictly past metrics."""
    init_db()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=404, detail="Database not found.")

    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql("SELECT * FROM metrics", conn)
        conn.close()

        if df.empty:
            raise HTTPException(status_code=400, detail="Database is empty.")

        # --- 1. Train Exterior Model ---
        df_ext = df.dropna(subset=FEATURES_EXT + ["ext_temp"])
        rows_ext = len(df_ext)
        rmse_ext = None
        if rows_ext >= 50:
            X_ext = df_ext[FEATURES_EXT]
            y_ext = df_ext["ext_temp"]
            X_tr, X_te, y_tr, y_te = train_test_split(X_ext, y_ext, test_size=0.2, random_state=42)
            model_ext = RandomForestRegressor(n_estimators=100, random_state=42)
            model_ext.fit(X_tr, y_tr)
            rmse_ext = float(np.sqrt(mean_squared_error(y_te, model_ext.predict(X_te))))
            joblib.dump(model_ext, MODEL_EXT_PATH)

        # --- 2. Train Interior Model ---
        df_int = df.dropna(subset=FEATURES_INT + ["int_temp"])
        rows_int = len(df_int)
        rmse_int = None
        if rows_int >= 50:
            X_int = df_int[FEATURES_INT]
            y_int = df_int["int_temp"]
            X_tr, X_te, y_tr, y_te = train_test_split(X_int, y_int, test_size=0.2, random_state=42)
            model_int = RandomForestRegressor(n_estimators=100, random_state=42)
            model_int.fit(X_tr, y_tr)
            rmse_int = float(np.sqrt(mean_squared_error(y_te, model_int.predict(X_te))))
            joblib.dump(model_int, MODEL_INT_PATH)

        # Log de succès
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            INSERT INTO training_logs (timestamp, rows_ext, rows_int, rmse_ext, rmse_int, status, message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (now_str, rows_ext, rows_int, rmse_ext, rmse_int, "success", "Models trained successfully"))
        conn.commit()
        conn.close()

        print(f"Models trained. Ext RMSE: {rmse_ext}, Int RMSE: {rmse_int}")
        return {
            "status": "success",
            "message": "Models trained successfully",
            "rmse_ext": round(rmse_ext, 4) if rmse_ext is not None else "N/A",
            "rmse_int": round(rmse_int, 4) if rmse_int is not None else "N/A"
        }

    except Exception as e:
        print(f"Error during training: {e}")
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("""
                INSERT INTO training_logs (timestamp, rows_ext, rows_int, rmse_ext, rmse_int, status, message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (now_str, 0, 0, None, None, "error", str(e)))
            conn.commit()
            conn.close()
        except:
            pass
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/forecast/ext")
async def forecast_ext():
    """Forecast exterior urban temperature combining past metrics and future weather forecasts."""
    if not os.path.exists(MODEL_EXT_PATH):
        raise HTTPException(status_code=400, detail="Exterior model not trained yet.")

    model = joblib.load(MODEL_EXT_PATH)
    conn = sqlite3.connect(DB_PATH)

    # Récupération du passé et du futur depuis les deux tables dédiées
    df_metrics = pd.read_sql("SELECT timestamp, meteo_temp, meteo_hum, wind_speed, sun_elevation, sun_azimuth FROM metrics ORDER BY timestamp ASC", conn)

    try:
        df_forecasts = pd.read_sql("SELECT timestamp, meteo_temp, meteo_hum, wind_speed, sun_elevation, sun_azimuth FROM weather_forecasts ORDER BY timestamp ASC", conn)
    except:
        df_forecasts = pd.DataFrame()

    conn.close()

    # Fusion des deux sources pour couvrir tout le spectre temporel (passé + futur)
    df_combined = pd.concat([df_metrics, df_forecasts]).drop_duplicates(subset=["timestamp"]).sort_values("timestamp")

    df_features = df_combined.dropna(subset=FEATURES_EXT)
    if df_features.empty:
        return {"status": "success", "forecasts": []}

    predictions = model.predict(df_features[FEATURES_EXT])
    df_features["predicted_ext_temp"] = [round(float(p), 2) for p in predictions]

    return {
        "status": "success",
        "forecasts": df_features[["timestamp", "predicted_ext_temp"]].to_dict(orient="records")
    }

@app.get("/api/forecast/int")
async def forecast_int():
    """Forecast interior temperature combining past metrics and future weather forecasts."""
    if not os.path.exists(MODEL_INT_PATH):
        raise HTTPException(status_code=400, detail="Interior model not trained yet.")

    model = joblib.load(MODEL_INT_PATH)
    conn = sqlite3.connect(DB_PATH)

    df_metrics = pd.read_sql("SELECT timestamp, meteo_temp, meteo_hum, wind_speed, sun_elevation, sun_azimuth FROM metrics ORDER BY timestamp ASC", conn)

    try:
        df_forecasts = pd.read_sql("SELECT timestamp, meteo_temp, meteo_hum, wind_speed, sun_elevation, sun_azimuth FROM weather_forecasts ORDER BY timestamp ASC", conn)
    except:
        df_forecasts = pd.DataFrame()

    conn.close()

    df_combined = pd.concat([df_metrics, df_forecasts]).drop_duplicates(subset=["timestamp"]).sort_values("timestamp")

    df_features = df_combined.dropna(subset=FEATURES_INT)
    if df_features.empty:
        return {"status": "success", "forecasts": []}

    predictions = model.predict(df_features[FEATURES_INT])
    df_features["predicted_int_temp"] = [round(float(p), 2) for p in predictions]

    return {
        "status": "success",
        "forecasts": df_features[["timestamp", "predicted_int_temp"]].to_dict(orient="records")
    }