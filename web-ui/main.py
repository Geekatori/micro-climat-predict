from datetime import datetime, timedelta, timezone
import math
import os
import sqlite3
import httpx
import numpy as np
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

app = FastAPI()
templates = Jinja2Templates(directory="templates")

HA_URL = os.getenv("HA_URL", "http://supervisor/core/api")
HA_TOKEN = os.getenv("HA_TOKEN", "")

# Les identifiants de tes capteurs dans Home Assistant
ENTITIES = {
    "ext_temp": os.getenv("HA_EXT_TEMP", "sensor.exterieur_temperature"),
    "int_temp": os.getenv("HA_INTERIOR_TEMP", "sensor.0x8c73dafffeda02b5_temperature"),
    "cor_temp": os.getenv("HA_COR_TEMP", "sensor.temtop_c1plus_temtop_temperature"),
}

DB_PATH = "/app/data/metrics.db"
COLLECTOR_URL = os.getenv("COLLECTOR_URL", "http://data-collector:8000")
ML_ENGINE_URL = os.getenv("ML_ENGINE_URL", "http://ml-engine:8000")

SENSOR_CONFIG = {
    "ext_temp": {"label": "Extérieur (°C) Réel", "color": "#ef4444", "dash": [], "type": "local"},
    "int_temp": {"label": "Intérieur (°C) Réel", "color": "#3b82f6", "dash": [], "type": "local"},
    "cor_temp": {"label": "Cor / Temtop (°C)", "color": "#8b5cf6", "dash": [], "type": "local"}
}

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    db_exists = os.path.exists(DB_PATH)
    total_rows = 0
    start_date = "N/A"
    end_date = "N/A"
    sampling_freq = "N/A"
    missing_counts = {}
    stats_columns = {}
    records = []
    columns = []
    chart_data_payload = {}

    if db_exists:
        try:
            conn = sqlite3.connect(DB_PATH)
            df_metrics = pd.read_sql("SELECT * FROM metrics ORDER BY timestamp ASC", conn)
            try:
                df_forecasts = pd.read_sql("SELECT * FROM weather_forecasts ORDER BY timestamp ASC", conn)
            except:
                df_forecasts = pd.DataFrame()
            conn.close()

            if not df_metrics.empty:
                total_rows = len(df_metrics)
                start_date = df_metrics.iloc[0]["timestamp"]
                end_date = df_metrics.iloc[-1]["timestamp"]

                if len(df_metrics) > 1:
                    dt1 = pd.to_datetime(df_metrics.iloc[0]["timestamp"])
                    dt2 = pd.to_datetime(df_metrics.iloc[1]["timestamp"])
                    diff_minutes = int((dt2 - dt1).total_seconds() / 60)
                    sampling_freq = f"{diff_minutes} minutes" if diff_minutes >= 1 else f"{int((dt2 - dt1).total_seconds())} secondes"

                missing_counts = df_metrics.isnull().sum().to_dict()

                numeric_cols = df_metrics.select_dtypes(include=['float64', 'int64']).columns
                for col in numeric_cols:
                    stats_columns[col] = {
                        "min": round(df_metrics[col].min(), 2) if not pd.isna(df_metrics[col].min()) else "N/A",
                        "max": round(df_metrics[col].max(), 2) if not pd.isna(df_metrics[col].max()) else "N/A",
                        "mean": round(df_metrics[col].mean(), 2) if not pd.isna(df_metrics[col].mean()) else "N/A"
                    }

                df = pd.concat([df_metrics, df_forecasts]).drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
                now_dt = datetime.now(timezone.utc).replace(tzinfo=None)
                df["dt"] = pd.to_datetime(df["timestamp"])

                forecast_ext_dict, forecast_int_dict = {}, {}
                try:
                    async with httpx.AsyncClient() as client:
                        resp_ext = await client.get(f"{ML_ENGINE_URL}/api/forecast/ext", timeout=5.0)
                        if resp_ext.status_code == 200:
                            for item in resp_ext.json().get("forecasts", []):
                                forecast_ext_dict[item["timestamp"]] = item["predicted_ext_temp"]
                except Exception as e:
                    print(f"ML Ext Forecast unreachable: {e}")

                try:
                    async with httpx.AsyncClient() as client:
                        resp_int = await client.get(f"{ML_ENGINE_URL}/api/forecast/int", timeout=5.0)
                        if resp_int.status_code == 200:
                            for item in resp_int.json().get("forecasts", []):
                                forecast_int_dict[item["timestamp"]] = item["predicted_int_temp"]
                except Exception as e:
                    print(f"ML Int Forecast unreachable: {e}")

                df["predicted_ext_temp"] = df["timestamp"].map(forecast_ext_dict)
                df["predicted_int_temp"] = df["timestamp"].map(forecast_int_dict)

                df["ext_temp_pred_past"] = df.apply(lambda r: r["predicted_ext_temp"] if r["dt"] <= now_dt else None, axis=1)
                df["int_temp_pred_past"] = df.apply(lambda r: r["predicted_int_temp"] if r["dt"] <= now_dt else None, axis=1)

                df["ext_temp_forecast_mode"] = df.apply(lambda r: r["ext_temp"] if r["dt"] <= now_dt else r["predicted_ext_temp"], axis=1)
                df["int_temp_forecast_mode"] = df.apply(lambda r: r["int_temp"] if r["dt"] <= now_dt else r["predicted_int_temp"], axis=1)

                for col in ["meteo_temp", "meteo_hum", "wind_speed"]:
                    if col in df.columns:
                        df[f"{col}_past"] = df.apply(lambda row: row[col] if row["dt"] <= now_dt else None, axis=1)
                        df[f"{col}_forecast"] = df.apply(lambda row: row[col] if row["dt"] > now_dt else None, axis=1)

                chart_data_payload = {
                    "timestamps": df["timestamp"].tolist(),
                    "ext_temp": df["ext_temp"].tolist() if "ext_temp" in df else [],
                    "int_temp": df["int_temp"].tolist() if "int_temp" in df else [],
                    "cor_temp": df["cor_temp"].tolist() if "cor_temp" in df else [],
                    "ext_temp_pred_past": df["ext_temp_pred_past"].tolist(),
                    "int_temp_pred_past": df["int_temp_pred_past"].tolist(),
                    "ext_temp_forecast_mode": df["ext_temp_forecast_mode"].tolist(),
                    "int_temp_forecast_mode": df["int_temp_forecast_mode"].tolist(),
                    "meteo_temp_past": df["meteo_temp_past"].tolist() if "meteo_temp_past" in df else [],
                    "meteo_temp_forecast": df["meteo_temp_forecast"].tolist() if "meteo_temp_forecast" in df else [],
                    "meteo_hum_past": df["meteo_hum_past"].tolist() if "meteo_hum_past" in df else [],
                    "meteo_hum_forecast": df["meteo_hum_forecast"].tolist() if "meteo_hum_forecast" in df else [],
                    "wind_speed_past": df["wind_speed_past"].tolist() if "wind_speed_past" in df else [],
                    "wind_speed_forecast": df["wind_speed_forecast"].tolist() if "wind_speed_forecast" in df else [],
                    "ext_hum": df["ext_hum"].tolist() if "ext_hum" in df else [],
                    "int_hum": df["int_hum"].tolist() if "int_hum" in df else [],
                    "cor_hum": df["cor_hum"].tolist() if "cor_hum" in df else [],
                    "meteo_temp": df["meteo_temp"].tolist() if "meteo_temp" in df else [],
                    "meteo_hum": df["meteo_hum"].tolist() if "meteo_hum" in df else [],
                    "wind_speed": df["wind_speed"].tolist() if "wind_speed" in df else []
                }

                drop_cols = [c for c in ["dt", "predicted_ext_temp", "predicted_int_temp", "ext_temp_pred_past", "int_temp_pred_past", "ext_temp_forecast_mode", "int_temp_forecast_mode"] if c in df_metrics.columns]
                df_tail = df_metrics.drop(columns=drop_cols, errors="ignore").tail(50).sort_values(by="timestamp", ascending=False)
                records = df_tail.to_dict(orient="records")
                columns = list(df_tail.columns)

        except Exception as e:
            print(f"Error reading database for stats: {e}")

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "active_page": "admin",
            "db_exists": db_exists,
            "total_rows": total_rows,
            "start_date": start_date,
            "end_date": end_date,
            "sampling_freq": sampling_freq,
            "missing_counts": missing_counts,
            "stats_columns": stats_columns,
            "records": records,
            "columns": columns,
            "chart_data_payload": chart_data_payload
        }
    )

@app.get("/trigger-collect")
async def trigger_collect():
    try:
        async with httpx.AsyncClient() as client:
            await client.get(f"{COLLECTOR_URL}/api/collect", timeout=30.0)
    except Exception as e:
        print(f"Failed to trigger collection: {e}")
    return RedirectResponse(url="/admin", status_code=303)

@app.get("/trigger-train")
async def trigger_train():
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{ML_ENGINE_URL}/api/train", timeout=60.0)
    except Exception as e:
        print(f"Failed to trigger training: {e}")
    return RedirectResponse(url="/admin", status_code=303)

@app.get("/trigger-clear")
async def trigger_clear():
    """Delete the SQLite database and all trained ML models to completely reset state."""
    try:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
            print("Database successfully cleared.")

        model_paths = [
            "/app/data/model_ext.joblib",
            "/app/data/model_int.joblib"
        ]
        for path in model_paths:
            if os.path.exists(path):
                os.remove(path)
                print(f"Removed model file: {path}")

    except Exception as e:
        print(f"Failed to clear data and models: {e}")

    return RedirectResponse(url="/admin", status_code=303)

@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    collection_logs = []
    training_logs = []
    db_exists = os.path.exists(DB_PATH)

    if db_exists:
        try:
            conn = sqlite3.connect(DB_PATH)
            df_col = pd.read_sql("SELECT * FROM collection_logs ORDER BY id DESC", conn)
            collection_logs = df_col.to_dict(orient="records")

            df_train = pd.read_sql("SELECT * FROM training_logs ORDER BY id DESC", conn)
            training_logs = df_train.to_dict(orient="records")
            conn.close()
        except Exception as e:
            print(f"Error reading logs: {e}")

    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "active_page": "logs",
            "db_exists": db_exists,
            "collection_logs": collection_logs,
            "training_logs": training_logs
        }
    )

@app.get("/", response_class=HTMLResponse)
async def main_dashboard(request: Request):
    """Affiche la page principale épurée (ApexCharts, vue 24h/7d, temps réel)."""
    return templates.TemplateResponse(request, "index.html", {"active_page": "graph"})

@app.get("/api-meteo/data/{version}")
async def get_apex_metrics(version: str):
    """Récupère l'historique capteurs en direct de Home Assistant et combine avec le ML/Open-Meteo."""
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    hours_back = 24 if version == '24h' else (7 * 24)
    start_time = now_utc - timedelta(hours=hours_back)
    end_time = now_utc + timedelta(days=2)

    start_str = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    ha_headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    entities_filter = ",".join(ENTITIES.values())

    ha_data_dict = {key: [] for key in ENTITIES.keys()}
    meteo_points = []
    forecast_ext_dict, forecast_int_dict = {}, {}

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Récupération Home Assistant
        try:
            url_ha = f"{HA_URL}/api/history/period/{start_str}?filter_entity_id={entities_filter}&end_time={end_str}"
            ha_resp = await client.get(url_ha, headers=ha_headers)
            if ha_resp.status_code == 200:
                json_data = ha_resp.json()
                for entity_history in json_data:
                    if not entity_history:
                        continue
                    entity_id = entity_history[0].get("entity_id")
                    key = next((k for k, v in ENTITIES.items() if v == entity_id), None)
                    if key:
                        for state in entity_history:
                            try:
                                dt_raw = datetime.fromisoformat(state["last_updated"].replace("Z", "+00:00"))
                                dt = dt_raw.astimezone(timezone.utc).replace(tzinfo=None)
                                val = float(state["state"])
                                if not math.isnan(val) and not math.isinf(val):
                                    ha_data_dict[key].append((dt, val))
                            except:
                                continue
        except Exception as e:
            print(f"HA Direct API Error: {e}")

        # 2. Récupération Open-Meteo
        try:
            lat = os.getenv("LATITUDE", "45.78")
            lon = os.getenv("LONGITUDE", "3.08")
            meteo_resp = await client.get(
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m&past_days={7 if version == '7d' else 1}&forecast_days=2"
            )
            if meteo_resp.status_code == 200:
                data = meteo_resp.json()["hourly"]
                for t_str, temp in zip(data["time"], data["temperature_2m"]):
                    dt = datetime.fromisoformat(t_str)
                    ts_ms = int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
                    if start_time <= dt <= end_time:
                        meteo_points.append([ts_ms, float(temp)])
        except Exception as e:
            print(f"Meteo Error: {e}")

        # 3. Récupération Prévisions ML Extérieur
        try:
            resp_ext = await client.get(f"{ML_ENGINE_URL}/api/forecast/ext")
            if resp_ext.status_code == 200:
                for item in resp_ext.json().get("forecasts", []):
                    forecast_ext_dict[item["timestamp"]] = item["predicted_ext_temp"]
        except Exception as e:
            print(f"ML Ext Forecast unreachable: {e}")

        # 4. Récupération Prévisions ML Intérieur
        try:
            resp_int = await client.get(f"{ML_ENGINE_URL}/api/forecast/int")
            if resp_int.status_code == 200:
                for item in resp_int.json().get("forecasts", []):
                    forecast_int_dict[item["timestamp"]] = item["predicted_int_temp"]
        except Exception as e:
            print(f"ML Int Forecast unreachable: {e}")

    def format_series(points_list):
        series = []
        for dt, val in sorted(points_list, key=lambda x: x[0]):
            ts_ms = int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
            series.append([ts_ms, val])
        return series

    sim_ext_points, sim_int_points = [], []
    for ts_str, val in forecast_ext_dict.items():
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=None)
            if dt > now_utc and dt <= end_time:
                sim_ext_points.append((dt, float(val)))
        except:
            pass

    for ts_str, val in forecast_int_dict.items():
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=None)
            if dt > now_utc and dt <= end_time:
                sim_int_points.append((dt, float(val)))
        except:
            pass

    def get_last_val(key):
        valid = [v for dt, v in ha_data_dict.get(key, []) if dt <= now_utc]
        return f"{valid[-1]}°C" if valid else "--°C"

    # --- 1. CALCUL DU MESSAGE DU PIC DE CHALEUR ---
    peak_message = None

    ext_history = ha_data_dict.get("ext_temp", [])
    if len(ext_history) > 1:
        current_ext_val = ext_history[-1][1]
        one_hour_ago = now_utc - timedelta(hours=1)
        past_ext_candidates = [v for dt, v in ext_history if dt <= one_hour_ago]

        is_growing = True
        if past_ext_candidates:
            is_growing = current_ext_val > past_ext_candidates[-1]

        if is_growing and sim_ext_points:
            max_sim_dt = None
            max_sim_val = -999.0
            for dt, val in sim_ext_points:
                if val > max_sim_val:
                    max_sim_val = val
                    max_sim_dt = dt

            if max_sim_dt and max_sim_dt > now_utc:
                time_to_peak = max_sim_dt - now_utc
                total_minutes = int(time_to_peak.total_seconds() // 60)
                if total_minutes > 0:
                    hours = total_minutes // 60
                    minutes = total_minutes % 60
                    if hours > 0:
                        peak_message = f"Il reste {hours}h{minutes:02d} avant que le maximum de la journée soit atteint"
                    else:
                        peak_message = f"Il reste {minutes} minutes avant que le maximum de la journée soit atteint"

    # --- 2. CALCUL DE L'INTERSECTION (TIMESTAMP D'INVERSION) ---
    inversion_timestamp = None
    if sim_int_points and sim_ext_points:
        ext_dict = {dt: val for dt, val in sim_ext_points}
        sorted_int = sorted(sim_int_points, key=lambda x: x[0])

        for i in range(1, len(sorted_int)):
            dt1, int1 = sorted_int[i-1]
            dt2, int2 = sorted_int[i]

            if dt1 < now_utc:
                continue

            ext1 = ext_dict.get(dt1)
            ext2 = ext_dict.get(dt2)

            if ext1 is not None and ext2 is not None:
                if (ext1 >= int1 and ext2 < int2) or (ext1 <= int1 and ext2 > int2):
                    diff1 = ext1 - int1
                    diff2 = ext2 - int2
                    if diff1 - diff2 != 0:
                        fraction = diff1 / (diff1 - diff2)
                        delta_seconds = (dt2 - dt1).total_seconds() * fraction
                        inversion_dt = dt1 + timedelta(seconds=delta_seconds)
                    else:
                        inversion_dt = dt1

                    inversion_timestamp = int(inversion_dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
                    break

    current_values = {
        "ext": get_last_val("ext_temp"),
        "cor": get_last_val("cor_temp"),
        "int": get_last_val("int_temp")
    }

    series_data = [
        {"name": "Intérieur", "data": format_series([(dt, v) for dt, v in ha_data_dict["int_temp"] if dt <= now_utc])},
        {"name": "Couloir", "data": format_series([(dt, v) for dt, v in ha_data_dict["cor_temp"] if dt <= now_utc])},
        {"name": "Extérieur", "data": format_series([(dt, v) for dt, v in ha_data_dict["ext_temp"] if dt <= now_utc])},
        {"name": "Open-Meteo", "data": meteo_points},
        {"name": "Intérieur (Prévu)", "data": format_series(sim_int_points)},
        {"name": "Extérieur (Prévu)", "data": format_series(sim_ext_points)}
    ]

    series_data = [s for s in series_data if len(s["data"]) > 0]

    return {
        "series": series_data,
        "current": current_values,
        "inversion_time": inversion_timestamp,
        "peak_message": peak_message
    }

@app.get("/validation/error", response_class=HTMLResponse)
async def validation_error_page(request: Request, model: str = "ext"):
    """Affiche une vue histogramme de l'erreur (Mesure - Inférence) pour un modèle donné."""
    db_exists = os.path.exists(DB_PATH)
    chart_payload = {}
    metrics_summary = {"mean_error": "N/A", "mae": "N/A", "rmse": "N/A"}

    if db_exists:
        try:
            conn = sqlite3.connect(DB_PATH)
            df_metrics = pd.read_sql("SELECT * FROM metrics ORDER BY timestamp ASC", conn)
            conn.close()

            if not df_metrics.empty:
                forecast_dict = {}
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{ML_ENGINE_URL}/api/forecast/{model}", timeout=5.0)
                    if resp.status_code == 200:
                        for item in resp.json().get("forecasts", []):
                            forecast_dict[item["timestamp"]] = item.get(f"predicted_{model}_temp")

                col_name = "ext_temp" if model == "ext" else "int_temp"
                if col_name not in df_metrics.columns:
                    col_name = "ext" if model == "ext" else "int"

                if col_name in df_metrics.columns:
                    df_metrics["pred"] = df_metrics["timestamp"].map(forecast_dict)
                    df_valid = df_metrics.dropna(subset=[col_name, "pred"]).copy()

                    if not df_valid.empty:
                        df_valid["error"] = df_valid[col_name] - df_valid["pred"]

                        errors = df_valid["error"]
                        metrics_summary["mean_error"] = round(errors.mean(), 2)
                        metrics_summary["mae"] = round(errors.abs().mean(), 2)
                        metrics_summary["rmse"] = round(np.sqrt((errors ** 2).mean()), 2)

                        chart_payload = {
                            "timestamps": df_valid["timestamp"].tolist(),
                            "errors": df_valid["error"].round(2).tolist(),
                            "model": model
                        }
        except Exception as e:
            print(f"Error generating error validation view: {e}")

    return templates.TemplateResponse(
        request,
        "validation_error.html",
        {
            "active_page": "admin",
            "db_exists": db_exists,
            "current_model": model,
            "metrics_summary": metrics_summary,
            "chart_payload": chart_payload
        }
    )