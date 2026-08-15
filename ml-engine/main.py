from datetime import datetime, timezone, timedelta
from scipy.optimize import minimize
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

import time
from functools import wraps

app = FastAPI()

DB_PATH = "/app/data/metrics.db"
MODEL_EXT_PATH = "/app/data/model_ext.joblib"
MODEL_INT_RF_PATH = "/app/data/model_int_rf.joblib"
MODEL_INT_STD_PATH = "/app/data/model_int_std.joblib"

LAT = float(os.getenv("LAT", 45.7797))
LON = float(os.getenv("LON", 3.0863))

FEATURES_EXT = [
    "meteo_temp", "meteo_hum", "wind_speed", "sun_elevation", "sun_azimuth",
    "meteo_temp_lag1", "meteo_temp_lag6", "meteo_temp_lag12", "meteo_temp_lag72", "meteo_temp_lag144",
    "sun_elevation_lag1", "sun_elevation_lag6", "sun_elevation_lag12"
]

FEATURES_INT = FEATURES_EXT.copy()

# In-memory dictionary for API response caching
_api_cache = {}

def cached_endpoint(ttl_seconds=300):
    """Cache API responses to avoid redundant SQLite queries and computations."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Generate a unique key based on function name and parameters
            cache_key = f"{func.__name__}_{kwargs}"
            now = time.time()

            if cache_key in _api_cache:
                entry = _api_cache[cache_key]
                if now - entry["timestamp"] < ttl_seconds:
                    return entry["data"]

            # If expired or missing, execute the function
            result = await func(*args, **kwargs)
            _api_cache[cache_key] = {"timestamp": now, "data": result}
            return result
        return wrapper
    return decorator

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
    lags = [1, 6, 12, 72, 144]
    for lag in lags:
        df[f"meteo_temp_lag{lag}"] = df["meteo_temp"].shift(lag)

    solar_lags = [1, 6, 12]
    for lag in solar_lags:
        df[f"sun_elevation_lag{lag}"] = df["sun_elevation"].shift(lag)

    return df

def add_behavioral_features(df: pd.DataFrame) -> pd.DataFrame:
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

def simulate_inertia(df: pd.DataFrame, a: float, b: float, c: float, d: float, e: float) -> np.ndarray:
    n = len(df)
    T_est = np.full(n, np.nan)
    if n == 0:
        return T_est

    raw_ext = df["ext_temp"].fillna(df["meteo_temp"]).values
    # Lissage de la température extérieure sur 3 heures (18 pas de 10 min) pour absorber le déphasage des murs
    ext_temps = pd.Series(raw_ext).rolling(window=18, min_periods=1).mean().values

    rad_vals = df["direct_radiation"].fillna(0.0).values if "direct_radiation" in df.columns else np.zeros(n)
    wind_vals = df["wind_speed"].fillna(0.0).values if "wind_speed" in df.columns else np.zeros(n)

    co2_raw_series = pd.Series(df["co2"].values) if "co2" in df.columns else pd.Series(np.full(n, np.nan))
    co2_smooth = co2_raw_series.rolling(window=12, min_periods=1).mean().values

    actuals = df["int_temp_min"].values if "int_temp_min" in df.columns else np.full(n, np.nan)
    window_flags = df["window_open_flag"].values if "window_open_flag" in df.columns else np.zeros(n)
    sun_elevs = df["sun_elevation"].fillna(0).values if "sun_elevation" in df.columns else np.zeros(n)

    raw_solar_series = (
        b * (rad_vals / 1000.0) +
        e * np.maximum(0.0, np.sin(np.radians(sun_elevs)))
    )
    solar_inertia_smooth = pd.Series(raw_solar_series).rolling(window=18, min_periods=1).mean().values

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    timestamps = pd.to_datetime(df["timestamp"])

    valid_indices = np.where(~np.isnan(actuals))[0]
    if len(valid_indices) == 0:
        return T_est

    first_valid_idx = valid_indices[0]
    target_start_time = timestamps.iloc[first_valid_idx] + timedelta(hours=1)

    start_indices = np.where(timestamps >= target_start_time)[0]
    if len(start_indices) == 0:
        return T_est

    valid_co2_indices = np.where(~np.isnan(co2_raw_series.values))[0]
    start_idx = valid_co2_indices[0] if len(valid_co2_indices) > 0 else 0

    base_val = float(actuals[start_idx]) if not np.isnan(actuals[start_idx]) else float(actuals[first_valid_idx])

    last_known_val = base_val
    in_future_mode = False

    for i in range(start_idx, n):
        dt = timestamps.iloc[i]
        ext = ext_temps[i]  # Utilise la température extérieure lissée (inertie des murs)
        solar_thermal_input = solar_inertia_smooth[i]
        wind = max(0.0, wind_vals[i])

        co2_val = co2_smooth[i]
        if np.isnan(co2_val):
            co2_excess = 0.0
        else:
            co2_raw = max(0.0, co2_val - 500.0)
            co2_excess = np.sqrt(co2_raw) if co2_raw > 0 else 0.0

        actual = actuals[i] if not np.isnan(actuals[i]) else np.nan

        if not np.isnan(actual):
            last_known_val = actual

        if dt > now_utc:
            co2_excess = 0.0
            if not in_future_mode:
                prev = last_known_val
                in_future_mode = True
            else:
                prev = T_est[i - 1]

            effective_a = a * (1.0 + 0.03 * wind)
            next_val = prev + (effective_a * (ext - prev)) + solar_thermal_input + (d * co2_excess) - c
            T_est[i] = np.clip(next_val, prev - 0.7, prev + 0.7)
            continue

        if window_flags[i] == 1:
            T_est[i] = actual if not np.isnan(actual) else (T_est[i-1] if i > 0 else base_val)
            continue

        if i == start_idx or window_flags[i - 1] == 1:
            T_est[i] = actual if not np.isnan(actual) else last_known_val
            continue

        prev = T_est[i - 1] if not np.isnan(T_est[i - 1]) else last_known_val

        effective_a = a * (1.0 + 0.03 * wind)
        next_val = prev + (effective_a * (ext - prev)) + solar_thermal_input + (d * co2_excess) - c
        T_est[i] = np.clip(next_val, prev - 0.7, prev + 0.7)

    return T_est

def optimize_thermal_inertia(df: pd.DataFrame):
    # Centered 'a' around the new found minimum, and expanded 'e' upwards
    # temperature exérieure (couplée au vent)
    a_grid = [0.000008, 0.000012, 0.000016]
    # radiation directe
    b_grid = [0.02, 0.03, 0.045]
    # cave
    c_grid = [0.009, 0.011, 0.013]
    # effet CO2 (activité)
    d_grid = [0.00007, 0.0001, 0.00015]
    # élévation du soleil
    e_grid = [0.032, 0.038, 0.045]

    best_params = {"a": 0.000012, "b": 0.03, "c": 0.011, "d": 0.0001, "e": 0.035}
    best_score = float("inf")

    df_eval = df.dropna(subset=["ext_temp", "int_temp_min", "window_open_flag"]).copy()
    eval_mask = (df_eval["window_open_flag"] == 0).values
    actuals = df_eval["int_temp_min"].values

    for a in a_grid:
        for b in b_grid:
            for c in c_grid:
                for d in d_grid:
                    for e in e_grid:
                        preds = simulate_inertia(df_eval, a, b, c, d, e)
                        valid_mask = eval_mask & ~np.isnan(actuals)
                        if not np.any(valid_mask): continue

                        diff = actuals[valid_mask] - preds[valid_mask]
                        normal_error_mask = np.abs(diff) < 2.5
                        if not np.any(normal_error_mask): continue

                        filtered_diff = diff[normal_error_mask]
                        score = np.percentile(np.abs(filtered_diff), 90) + np.abs(np.mean(filtered_diff))

                        if score < best_score:
                            best_score = score
                            best_params = {"a": a, "b": b, "c": c, "d": d, "e": e}

    return best_params, best_score

def scipy_fine_tuning(df: pd.DataFrame, initial_params: dict):
    df_eval = df.dropna(subset=["ext_temp", "int_temp_min", "window_open_flag"]).copy()
    eval_mask = (df_eval["window_open_flag"] == 0).values
    actuals = df_eval["int_temp_min"].values

    def objective(x):
        a, b, c, d, e = x[0], x[1], x[2], x[3], x[4]
        if a < 0 or b < 0 or d < 0 or e < 0:
            return 1e6

        preds = simulate_inertia(df_eval, a, b, c, d, e)
        valid_mask = eval_mask & ~np.isnan(actuals)
        if not np.any(valid_mask):
            return 1e6

        diff = actuals[valid_mask] - preds[valid_mask]
        normal_error_mask = np.abs(diff) < 2.5
        if not np.any(normal_error_mask):
            return 1e6

        filtered_diff = diff[normal_error_mask]
        return float(np.percentile(np.abs(filtered_diff), 90) + (1.0 * np.abs(np.mean(filtered_diff))))

    # On part des meilleurs paramètres trouvés par le Grid Search
    initial_guess = [
        initial_params["a"],
        initial_params["b"],
        initial_params["c"],
        initial_params["d"],
        initial_params["e"]
    ]

    # On augmente un peu les itérations pour laisser Nelder-Mead converger finement
    result = minimize(objective, initial_guess, method="Nelder-Mead", options={"maxiter": 200, "xatol": 1e-6})

    refined_params = {
        "a": float(result.x[0]),
        "b": float(result.x[1]),
        "c": float(result.x[2]),
        "d": float(result.x[3]),
        "e": float(result.x[4])
    }
    return refined_params, float(result.fun)

def scipy_fine_tuning(df: pd.DataFrame, initial_params: dict):
    df_eval = df.dropna(subset=["ext_temp", "int_temp_min", "window_open_flag"]).copy()
    eval_mask = (df_eval["window_open_flag"] == 0).values
    actuals = df_eval["int_temp_min"].values

    def objective(x):
        a, b, c, d, e = x[0], x[1], x[2], x[3], x[4]
        if a < 0 or b < 0 or d < 0 or e < 0:
            return 1e6

        preds = simulate_inertia(df_eval, a, b, c, d, e)
        valid_mask = eval_mask & ~np.isnan(actuals)
        if not np.any(valid_mask):
            return 1e6

        diff = actuals[valid_mask] - preds[valid_mask]
        normal_error_mask = np.abs(diff) < 2.5
        if not np.any(normal_error_mask):
            return 1e6

        filtered_diff = diff[normal_error_mask]
        return float(np.percentile(np.abs(filtered_diff), 90) + (1.0 * np.abs(np.mean(filtered_diff))))

    initial_guess = [
        initial_params["a"],
        initial_params["b"],
        initial_params["c"],
        initial_params["d"],
        initial_params.get("e", 0.0001)
    ]

    result = minimize(objective, initial_guess, method="Nelder-Mead", options={"maxiter": 100, "xatol": 1e-5})

    refined_params = {
        "a": float(result.x[0]),
        "b": float(result.x[1]),
        "c": float(result.x[2]),
        "d": float(result.x[3]),
        "e": float(result.x[4])
    }
    return refined_params, float(result.fun)

def load_and_prepare_data() -> pd.DataFrame:
    """Helper unifié pour charger et préparer les données métriques et prévisions."""
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=404, detail="Database not found.")

    conn = sqlite3.connect(DB_PATH)
    df_m = pd.read_sql("SELECT * FROM metrics ORDER BY timestamp ASC", conn)
    try:
        df_f = pd.read_sql("SELECT * FROM weather_forecasts ORDER BY timestamp ASC", conn)
    except:
        df_f = pd.DataFrame()
    conn.close()

    if df_m.empty:
        raise HTTPException(status_code=400, detail="Database is empty.")

    df = pd.concat([df_m, df_f]).drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    df = add_solar_features(df)
    df = add_behavioral_features(df)
    df = add_multiscale_features(df)
    df["ext_temp"] = df["ext_temp"].fillna(df["meteo_temp"])
    return df

@app.on_event("startup")
@cached_endpoint(ttl_seconds=300)
async def startup_event():
    init_db()

@app.post("/api/train")
def train_models():  # <-- Retiré 'async' et retiré '@cached_endpoint'
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    df = load_and_prepare_data()
    df_clean = df.dropna(subset=["ext_temp", "int_temp_min"])

    if df_clean.empty:
        raise HTTPException(status_code=400, detail="Not enough valid data after cleaning.")

    # 1. Train Exterior Model (RF)
    X_ext = df_clean[FEATURES_EXT]
    y_ext = df_clean["ext_temp"]
    X_tr_ext, X_te_ext, y_tr_ext, y_te_ext = train_test_split(X_ext, y_ext, test_size=0.2, random_state=42)
    model_ext = RandomForestRegressor(n_estimators=100, random_state=42)
    model_ext.fit(X_tr_ext, y_tr_ext)
    rmse_ext = float(np.sqrt(mean_squared_error(y_te_ext, model_ext.predict(X_te_ext))))
    joblib.dump(model_ext, MODEL_EXT_PATH)

    # 2. Train Interior Model (RF - Generalist)
    X_int = df_clean[FEATURES_INT]
    y_int = df_clean["int_temp_min"]
    X_tr_int, X_te_int, y_tr_int, y_te_int = train_test_split(X_int, y_int, test_size=0.2, random_state=42)
    model_int_rf = RandomForestRegressor(n_estimators=100, random_state=42)
    model_int_rf.fit(X_tr_int, y_tr_int)
    rmse_int_rf = float(np.sqrt(mean_squared_error(y_te_int, model_int_rf.predict(X_te_int))))
    joblib.dump(model_int_rf, MODEL_INT_RF_PATH)

    # 3. Optimize Interior Model (Grid Search + SciPy)
    grid_params_std, rmse_std = optimize_thermal_inertia(df_clean)
    best_params_std, rmse_std = scipy_fine_tuning(df_clean, grid_params_std)
    joblib.dump(best_params_std, MODEL_INT_STD_PATH)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO training_logs (timestamp, rows_ext, rows_int, rmse_ext, rmse_int, status, message)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (now_str, len(df_clean), len(df_clean), rmse_ext, rmse_int_rf, "success", f"RF Models + STD trained. STD params: {best_params_std}"))
    conn.commit()
    conn.close()

    # CRical: Clear the API cache so future predictions use the newly trained models!
    _api_cache.clear()
    print(f"[{datetime.now()}] Models retrained successfully. API cache cleared.")

    return {
        "status": "success",
        "rmse_ext": round(rmse_ext, 4),
        "rmse_int_rf": round(rmse_int_rf, 4),
        "rmse_int_std": round(rmse_std, 4),
        "params_std": best_params_std
    }

@app.get("/api/forecast/ext")
@cached_endpoint(ttl_seconds=300)
async def forecast_ext():
    if not os.path.exists(MODEL_EXT_PATH):
        raise HTTPException(status_code=400, detail="Exterior model not trained.")

    model = joblib.load(MODEL_EXT_PATH)
    df = load_and_prepare_data()
    df_features = df.dropna(subset=FEATURES_EXT)
    if df_features.empty:
        return {"status": "success", "forecasts": []}

    preds = model.predict(df_features[FEATURES_EXT])
    df_features["predicted_ext_temp"] = [round(float(p), 2) for p in preds]

    return {"status": "success", "forecasts": df_features[["timestamp", "predicted_ext_temp"]].to_dict(orient="records")}

def get_next_exterior_peak(df: pd.DataFrame, model_ext) -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    future_df = df[pd.to_datetime(df["timestamp"]) > now].copy()
    if future_df.empty:
        return {"peak_temp": None, "timestamp": None}

    feat_df = future_df.dropna(subset=FEATURES_EXT)
    if feat_df.empty:
        return {"peak_temp": None, "timestamp": None}

    feat_df["predicted_ext"] = model_ext.predict(feat_df[FEATURES_EXT])

    # On restreint la fenêtre aux 6 prochaines heures maximum
    limit_time = now + timedelta(hours=6)
    window_df = feat_df[(pd.to_datetime(feat_df["timestamp"]) >= now) & (pd.to_datetime(feat_df["timestamp"]) <= limit_time)]

    if window_df.empty:
        return {"peak_temp": None, "timestamp": None}

    max_idx = window_df["predicted_ext"].idxmax()
    if max_idx == window_df.index[0]:
        return {"peak_temp": None, "timestamp": None}

    peak_row = window_df.loc[max_idx]

    return {
        "peak_temp": round(float(peak_row["predicted_ext"]), 2),
        "timestamp": str(peak_row["timestamp"])
    }


def get_optimal_window_opening_time(df: pd.DataFrame, preds_std: np.ndarray) -> str:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    timestamps = pd.to_datetime(df["timestamp"])
    ext_vals = df["ext_temp"].fillna(df["meteo_temp"]).values

    for i in range(len(df)):
        dt = timestamps.iloc[i]
        if dt > now and not np.isnan(preds_std[i]):
            if ext_vals[i] < (preds_std[i] - 0.5):
                return str(df["timestamp"].iloc[i])
    return None

@app.get("/api/forecast/analysis")
@cached_endpoint(ttl_seconds=300)
async def forecast_analysis():
    if not os.path.exists(MODEL_EXT_PATH) or not os.path.exists(MODEL_INT_STD_PATH):
        raise HTTPException(status_code=400, detail="Models not trained.")

    model_ext = joblib.load(MODEL_EXT_PATH)
    params_std = joblib.load(MODEL_INT_STD_PATH)
    a, b, c, d, e = params_std["a"], params_std["b"], params_std["c"], params_std["d"], params_std.get("e", 0.0)

    df = load_and_prepare_data()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Predict future exterior temperatures
    ext_mask = df[FEATURES_EXT].notna().all(axis=1)
    if not df[ext_mask].empty:
        df.loc[ext_mask, "predicted_ext_temp"] = model_ext.predict(df[ext_mask][FEATURES_EXT])
        future_mask = (pd.to_datetime(df["timestamp"]) > now) & df["predicted_ext_temp"].notna()
        df.loc[future_mask, "ext_temp"] = df.loc[future_mask, "predicted_ext_temp"]

    preds_std = simulate_inertia(df, a, b, c, d, e)
    df["predicted_int_temp_std"] = preds_std

    peak_info = get_next_exterior_peak(df, model_ext)

    # Filtrer le pic s'il est prévu dans plus de 6 heures
    if peak_info and peak_info.get("timestamp"):
        try:
            peak_dt = datetime.strptime(str(peak_info["timestamp"]), "%Y-%m-%d %H:%M:%S")
            time_diff_hours = (peak_dt - now).total_seconds() / 3600.0
            if time_diff_hours > 6.0:
                peak_info = {"peak_temp": None, "timestamp": None}
        except Exception:
            pass

    # Find exact opening time when exterior temp < STD temp - 0.5°C in the future
    opening_time = None
    timestamps = pd.to_datetime(df["timestamp"])

    for i in range(len(df)):
        dt = timestamps.iloc[i].replace(tzinfo=None)
        if dt > now:
            ext = df.iloc[i]["ext_temp"]
            std_val = df.iloc[i]["predicted_int_temp_std"]
            if pd.notna(ext) and pd.notna(std_val) and ext < std_val:
                opening_time = str(df.iloc[i]["timestamp"])
                break

    peak_msg = None
    if peak_info and peak_info.get("peak_temp") and peak_info.get("timestamp"):
        time_str = str(peak_info["timestamp"])[11:16]
        peak_msg = f"Pic extérieur: {peak_info['peak_temp']}°C prévu à {time_str}"

    return clean_for_json({
        "exterior_peak": peak_info,
        "opening_time": opening_time,
        "peak_message": peak_msg
    })


@app.get("/api/forecast/smart")
@cached_endpoint(ttl_seconds=300)
async def forecast_smart(scope: str = "all"):
    """
    Smart curve using STD before the opening marker, and switching permanently
    to Random Forest from the opening marker onwards.
    """
    if not os.path.exists(MODEL_INT_RF_PATH) or not os.path.exists(MODEL_INT_STD_PATH):
        raise HTTPException(status_code=400, detail="Models not trained.")

    model_rf = joblib.load(MODEL_INT_RF_PATH)
    params_std = joblib.load(MODEL_INT_STD_PATH)
    a, b, c, d, e = params_std["a"], params_std["b"], params_std["c"], params_std["d"], params_std.get("e", 0.0)

    df = load_and_prepare_data()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # 1. Predict future exterior temp
    if os.path.exists(MODEL_EXT_PATH):
        model_ext = joblib.load(MODEL_EXT_PATH)
        ext_mask = df[FEATURES_EXT].notna().all(axis=1)
        if not df[ext_mask].empty:
            df.loc[ext_mask, "predicted_ext_temp"] = model_ext.predict(df[ext_mask][FEATURES_EXT])
            future_mask = (pd.to_datetime(df["timestamp"]) > now) & df["predicted_ext_temp"].notna()
            df.loc[future_mask, "ext_temp"] = df.loc[future_mask, "predicted_ext_temp"]

    # 2. Compute STD and RF predictions
    preds_std = simulate_inertia(df, a, b, c, d, e)
    df["predicted_int_temp_std"] = preds_std

    df["predicted_int_temp_rf"] = np.nan
    rf_mask = df[FEATURES_INT].notna().all(axis=1)
    if not df[rf_mask].empty:
        df.loc[rf_mask, "predicted_int_temp_rf"] = model_rf.predict(df[rf_mask][FEATURES_INT])

    timestamps = pd.to_datetime(df["timestamp"])

    # 3. Detect opening time (when exterior drops below STD for the first time in the future)
    opening_dt = None
    for i in range(len(df)):
        dt = timestamps.iloc[i].replace(tzinfo=timezone.utc).replace(tzinfo=None)
        if dt > now:
            ext = df.iloc[i]["ext_temp"]
            std_val = df.iloc[i]["predicted_int_temp_std"]
            if pd.notna(ext) and pd.notna(std_val) and ext < std_val:
                opening_dt = dt
                break

    smart_series = []

    for i in range(len(df)):
        row = df.iloc[i]
        dt = timestamps.iloc[i].replace(tzinfo=timezone.utc).replace(tzinfo=None)

        if scope == "past" and dt > now: continue
        if scope == "future" and dt <= now: continue

        # 4. Determine whether to use RF or STD
        if dt <= now:
            # Past: use historical flag
            use_rf = (row["window_open_flag"] == 1)
        else:
            # Future: once opening_dt is reached, stay on Random Forest permanently
            if opening_dt and dt >= opening_dt:
                use_rf = True
            else:
                use_rf = False

        # Select the appropriate model prediction
        val = row["predicted_int_temp_rf"] if use_rf else row["predicted_int_temp_std"]

        if not pd.isna(val):
            ts_ms = int(timestamps.iloc[i].replace(tzinfo=timezone.utc).timestamp() * 1000)
            smart_series.append([ts_ms, round(float(val), 2)])

    return clean_for_json({"smart_series": smart_series})

@app.get("/api/forecast/int")
@cached_endpoint(ttl_seconds=300)
async def forecast_int():
    """
    Provides both Random Forest and STD predictions separately
    for detailed error validation and analysis.
    """
    if not os.path.exists(MODEL_INT_RF_PATH) or not os.path.exists(MODEL_INT_STD_PATH):
        raise HTTPException(status_code=400, detail="Models not trained.")

    model_rf = joblib.load(MODEL_INT_RF_PATH)
    params_std = joblib.load(MODEL_INT_STD_PATH)
    a, b, c, d, e = params_std["a"], params_std["b"], params_std["c"], params_std["d"], params_std.get("e", 0.0)

    df = load_and_prepare_data()

    preds_std = simulate_inertia(df, a, b, c, d, e)
    df["predicted_int_temp_std"] = preds_std

    df["predicted_int_temp_rf"] = np.nan
    rf_mask = df[FEATURES_INT].notna().all(axis=1)
    if not df[rf_mask].empty:
        df.loc[rf_mask, "predicted_int_temp_rf"] = model_rf.predict(df[rf_mask][FEATURES_INT])

    forecasts = []
    timestamps = pd.to_datetime(df["timestamp"])

    for i in range(len(df)):
        row = df.iloc[i]
        ts_str = str(timestamps.iloc[i].strftime("%Y-%m-%d %H:%M:%S"))

        forecasts.append({
            "timestamp": ts_str,
            "predicted_int_temp_rf": round(float(row["predicted_int_temp_rf"]), 2) if pd.notna(row["predicted_int_temp_rf"]) else None,
            "predicted_int_temp_std": round(float(row["predicted_int_temp_std"]), 2) if pd.notna(row["predicted_int_temp_std"]) else None
        })

    return clean_for_json({"status": "success", "forecasts": forecasts})

@app.get("/api/metrics/annotated")
@cached_endpoint(ttl_seconds=300)
async def get_annotated_metrics():
    """
    Returns the historical data enriched with behavioral flags
    (window_open_flag, thermal_mode, is_fit_ready) computed on the fly.
    """
    try:
        df = load_and_prepare_data()

        # Select relevant columns to keep the JSON payload light
        columns_to_keep = [
            "timestamp", "ext_temp", "int_temp_min", "co2",
            "window_open_flag", "is_fit_ready", "thermal_mode"
        ]

        # Keep only columns that actually exist in the dataframe to avoid KeyErrors
        existing_cols = [col for col in columns_to_keep if col in df.columns]
        df_annotated = df[existing_cols]

        # Filter out future forecasts (where window_open_flag might just be 0 by default)
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        df_annotated = df_annotated[pd.to_datetime(df_annotated["timestamp"]) <= now_utc]

        # Convert timestamps to string for JSON serialization
        df_annotated.loc[:, "timestamp"] = df_annotated["timestamp"].astype(str)

        return clean_for_json({
            "status": "success",
            "data": df_annotated.to_dict(orient="records")
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))