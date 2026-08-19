from datetime import datetime, timedelta, timezone
import math
import os
import sqlite3
import httpx
import numpy as np
import pandas as pd
from fastapi import APIRouter, FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import asyncio

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

app = FastAPI()
templates = Jinja2Templates(directory="templates")

HA_URL = os.getenv("HA_URL", "http://supervisor/core/api")
HA_TOKEN = os.getenv("HA_TOKEN", "")

# Les identifiants de tes capteurs dans Home Assistant
ENTITIES = {
    "ext_temp": os.getenv("HA_EXT_TEMP", "sensor.exterieur_temperature"),
    "int_temp_min": os.getenv("HA_INTERIOR_TEMP_MIN", "sensor.temperature_interieure_min"),
    "cor_temp": os.getenv("HA_COR_TEMP", "sensor.temtop_c1plus_temtop_temperature"),
}

DB_PATH = "/app/data/metrics.db"
COLLECTOR_URL = os.getenv("COLLECTOR_URL", "http://data-collector:8000")
ML_ENGINE_URL = os.getenv("ML_ENGINE_URL", "http://ml-engine:8000")

SENSOR_CONFIG = {
    "ext_temp": {"label": "Extérieur (°C) Réel", "color": "#ef4444", "dash": [], "type": "local"},
    "int_temp_min": {"label": "Intérieur Min (°C) Réel", "color": "#3b82f6", "dash": [], "type": "local"},
    "cor_temp": {"label": "Cor / Temtop (°C)", "color": "#8b5cf6", "dash": [], "type": "local"}
}

# Proxy routes for the frontend JS to avoid CORS and keep things clean
@app.get("/api/admin/chart-data")
async def proxy_admin_chart_data(days: int = 7):
    """Fetch raw metrics and open-meteo forecasts from data-collector."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(f"{COLLECTOR_URL}/api/data/admin-chart?days={days}")
            return resp.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

@app.get("/api/admin/predictions")
async def proxy_admin_predictions():
    """Fetch ML predictions (past and future) from ml-engine."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(f"{ML_ENGINE_URL}/api/admin/predictions")
            return resp.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    """
    Renders the admin dashboard.
    Fetches stats and table data asynchronously from the collector to avoid blocking.
    """
    db_exists = os.path.exists(DB_PATH)

    context = {
        "active_page": "admin",
        "db_exists": db_exists,
        "total_rows": 0,
        "start_date": "N/A",
        "end_date": "N/A",
        "sampling_freq": "N/A",
        "missing_counts": {},
        "stats_columns": {},
        "records": [],
        "columns": []
    }

    if db_exists:
        try:
            # Quick call to get the pre-computed stats for the Jinja template
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{COLLECTOR_URL}/api/data/admin-stats")
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "success":
                        context.update({
                            "total_rows": data.get("total_rows"),
                            "start_date": data.get("start_date"),
                            "end_date": data.get("end_date"),
                            "sampling_freq": data.get("sampling_freq"),
                            "stats_columns": data.get("stats_columns"),
                            "missing_counts": data.get("missing_counts"),
                            "records": data.get("records"),
                            "columns": data.get("columns")
                        })
        except Exception as e:
            print(f"Error fetching admin stats from collector: {e}")

    return templates.TemplateResponse(request, "admin.html", context)

@app.get("/trigger-collect")
async def trigger_collect(days: int = 9):
    try:
        async with httpx.AsyncClient() as client:
            await client.get(f"{COLLECTOR_URL}/api/collect?days={days}", timeout=60.0)
    except Exception as e:
        print(f"Failed to trigger collection: {e}")
    return RedirectResponse(url="/admin", status_code=303)


async def background_train_request():
    """Tâche exécutée en arrière-plan pour ne pas bloquer l'utilisateur."""
    try:
        async with httpx.AsyncClient() as client:
            # On met un timeout large car l'entraînement est long
            await client.post(f"{ML_ENGINE_URL}/api/train", timeout=120.0)
            print("Background training completed successfully.")
    except Exception as e:
        print(f"Failed to trigger background training: {e}")

@app.get("/trigger-train")
async def trigger_train(background_tasks: BackgroundTasks):
    # Ajoute la tâche à la file d'attente d'arrière-plan de FastAPI
    background_tasks.add_task(background_train_request)

    # Redirige l'utilisateur INSTANTANÉMENT, sans attendre la fin du calcul
    return RedirectResponse(url="/admin", status_code=303)

@app.get("/trigger-clear")
async def trigger_clear():
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
    return templates.TemplateResponse(request, "index.html", {"active_page": "graph"})

@app.get("/widget", response_class=HTMLResponse)
async def main_dashboard_widget(request: Request):
    return templates.TemplateResponse(request, "widget.html")



def parse_ts(ts_str):
    """Parseur robuste qui accepte à la fois le format ISO et le format SQL."""
    if not ts_str:
        return None
    ts_str = str(ts_str).replace("Z", "+00:00")
    try:
        if "T" in ts_str:
            return datetime.fromisoformat(ts_str).replace(tzinfo=None)
        else:
            return datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
    except Exception as e:
        print(f"Date parsing error for '{ts_str}': {e}")
        return None


@app.get("/api-meteo/history/{version}")
async def get_history(version: str, mode: str = "simple"):
    hist_data, curr_data = [], {}
    errors = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        results = await asyncio.gather(
            client.get(f"{COLLECTOR_URL}/api/data/history/{version}"),
            client.get(f"{COLLECTOR_URL}/api/data/current"),
            return_exceptions=True
        )

        hist_resp, curr_resp = results

        if isinstance(hist_resp, Exception):
            errors.append(f"History connect error: {hist_resp}")
        elif hist_resp.status_code == 200:
            hist_data = hist_resp.json().get("data", [])
        else:
            errors.append(f"History API failed with {hist_resp.status_code}")

        if isinstance(curr_resp, Exception):
            errors.append(f"Current connect error: {curr_resp}")
        elif curr_resp.status_code == 200:
            curr_data = curr_resp.json().get("data", {})
        else:
            errors.append(f"Current API failed with {curr_resp.status_code}")

    def format_val(val):
        return f"{val}°C" if val is not None else "--°C"

    if mode == "detailed":
        current_values = {
            "ext": format_val(curr_data.get("ext_temp")),
            "cor": format_val(curr_data.get("cor_temp")),
            "int": format_val(curr_data.get("int_temp"))
        }
    else:
        current_values = {
            "ext": format_val(curr_data.get("ext_temp")),
            "cor": "--",
            "int": format_val(curr_data.get("int_temp_min"))
        }

    series_dict = {"ext_temp": [], "int_temp_min": [], "int_temp": [], "cor_temp": []}

    for row in hist_data:
        dt = parse_ts(row.get("timestamp"))
        if not dt: continue
        ts_ms = int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)

        if row.get("ext_temp") is not None: series_dict["ext_temp"].append([ts_ms, row["ext_temp"]])
        if row.get("int_temp_min") is not None: series_dict["int_temp_min"].append([ts_ms, row["int_temp_min"]])
        if row.get("int_temp") is not None: series_dict["int_temp"].append([ts_ms, row["int_temp"]])
        if row.get("cor_temp") is not None: series_dict["cor_temp"].append([ts_ms, row["cor_temp"]])

    # --- INJECTION DU POINT "LIVE" (HA / CURRENT) ---
    # Si on a des données courantes fraîches, on les ajoute comme point final "now"
    if curr_data:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        # On évite d'ajouter un point en double si le dernier historique est déjà très proche (< 2 min)
        def safe_append(key, val_key):
            val = curr_data.get(val_key)
            if val is not None:
                if not series_dict[key] or (now_ms - series_dict[key][-1][0] > 120000):
                    series_dict[key].append([now_ms, val])

        safe_append("ext_temp", "ext_temp")
        safe_append("int_temp_min", "int_temp_min")
        safe_append("int_temp", "int_temp")
        safe_append("cor_temp", "cor_temp")
    # -----------------------------------------------

    series_data = [{"name": "Extérieur", "data": series_dict["ext_temp"]}]
    if mode == "detailed":
        if series_dict["int_temp"]: series_data.append({"name": "Intérieur", "data": series_dict["int_temp"]})
        if series_dict["cor_temp"]: series_data.append({"name": "Couloir", "data": series_dict["cor_temp"]})
    else:
        if series_dict["int_temp_min"]: series_data.append({"name": "Intérieur min", "data": series_dict["int_temp_min"]})

    return {"series": series_data, "current": current_values, "_debug_errors": errors}


@app.get("/api-meteo/forecast")
async def get_forecast(ml: str = "forecast"):
    ext_data, smart_data, om_data = [], [], []
    errors = []

    async with httpx.AsyncClient(timeout=20.0) as client:
        results = await asyncio.gather(
            client.get(f"{ML_ENGINE_URL}/api/forecast/ext"),
            client.get(f"{ML_ENGINE_URL}/api/forecast/smart?scope=all"),
            client.get(f"{COLLECTOR_URL}/api/data/openmeteo"),
            return_exceptions=True
        )

        ext_resp, smart_resp, om_resp = results

        if isinstance(ext_resp, Exception): errors.append(f"ML Ext error: {ext_resp}")
        elif ext_resp.status_code == 200: ext_data = ext_resp.json().get("forecasts", [])
        else: errors.append(f"ML Ext error {ext_resp.status_code}")

        if isinstance(smart_resp, Exception): errors.append(f"ML Smart error: {smart_resp}")
        elif smart_resp.status_code == 200: smart_data = smart_resp.json().get("smart_series", [])
        else: errors.append(f"ML Smart error {smart_resp.status_code}")

        if isinstance(om_resp, Exception): errors.append(f"OpenMeteo error: {om_resp}")
        elif om_resp.status_code == 200: om_data = om_resp.json().get("data", [])
        else: errors.append(f"OpenMeteo error {om_resp.status_code}")

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    sim_ext_points = []
    for item in ext_data:
        dt = parse_ts(item.get("timestamp"))
        if not dt: continue
        ts_ms = int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
        val = float(item["predicted_ext_temp"])
        if (ml == "eval" and dt <= now_utc) or (ml == "forecast" and dt > now_utc):
            sim_ext_points.append([ts_ms, val])

    filtered_smart_series = []
    for ts_ms, val in smart_data:
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).replace(tzinfo=None)
        if (ml == "eval" and dt <= now_utc) or (ml == "forecast" and dt > now_utc):
            filtered_smart_series.append([ts_ms, float(val)])

    om_points = []
    for row in om_data:
        dt = parse_ts(row.get("timestamp"))
        if not dt: continue
        ts_ms = int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
        if row.get("meteo_temp") is not None:
            om_points.append([ts_ms, row["meteo_temp"]])

    ext_pred_name = "Extérieur (prévu)" if ml == "forecast" else "Extérieur (ML passé)"
    int_pred_name = "Intérieur (Modèle prévu)" if ml == "forecast" else "Intérieur (Modèle passé)"

    series_data = []
    if sim_ext_points: series_data.append({"name": ext_pred_name, "data": sim_ext_points})
    if filtered_smart_series: series_data.append({"name": int_pred_name, "data": filtered_smart_series})
    if om_points: series_data.append({"name": "Open-Meteo", "data": om_points})

    return {"series": series_data, "_debug_errors": errors}


@app.get("/api-meteo/analysis")
async def get_analysis():
    data = {}
    errors = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{ML_ENGINE_URL}/api/forecast/analysis")
            if resp.status_code == 200:
                data = resp.json()
            else:
                errors.append(f"Analysis API failed with {resp.status_code}")
        except Exception as e:
            errors.append(str(e))

    inversion_time_iso = None
    if data.get("opening_time"):
        inversion_time_iso = str(data["opening_time"]).replace(" ", "T")
        if not inversion_time_iso.endswith("Z") and "+" not in inversion_time_iso:
            inversion_time_iso += "Z"

    return {
        "inversion_time": inversion_time_iso,
        "peak_message": data.get("peak_message"),
        "_debug_errors": errors
    }


@app.get("/api/backfill-co2")
async def backfill_co2(days: int = 30):
    co2_entity = "sensor.temtop_c1plus_temtop_co2"

    if not os.path.exists(DB_PATH):
        return {"status": "error", "message": "Database not found."}

    async with httpx.AsyncClient() as client:
        now_utc = datetime.now(timezone.utc)
        start_time = now_utc - timedelta(days=days)
        end_time = now_utc

        ha_headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
        start_str = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")

        co2_points = []
        try:
            url = f"{HA_URL}/api/history/period/{start_str}?filter_entity_id={co2_entity}&end_time={end_str}"
            ha_resp = await client.get(url, headers=ha_headers, timeout=60.0)

            if ha_resp.status_code == 200:
                history_data = ha_resp.json()
                if history_data and len(history_data) > 0:
                    for state in history_data[0]:
                        try:
                            dt = datetime.fromisoformat(state["last_updated"])
                            val = float(state["state"])
                            if not math.isnan(val) and not math.isinf(val):
                                co2_points.append([dt, val])
                        except:
                            continue
        except Exception as e:
            return {"status": "error", "message": f"Erreur HA API: {str(e)}"}

        if not co2_points:
            return {"status": "success", "message": "Aucune donnée CO2 trouvée sur cette période."}

        df_co2 = pd.DataFrame(co2_points, columns=["timestamp", "co2"])
        df_co2["timestamp"] = pd.to_datetime(df_co2["timestamp"]).dt.tz_convert("UTC").dt.tz_localize(None)

        df_co2 = df_co2.set_index("timestamp").resample("10min").mean().interpolate(method="linear").reset_index()
        df_co2["co2"] = df_co2["co2"].round(2)
        df_co2["timestamp"] = df_co2["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        updated_count = 0
        for _, row in df_co2.iterrows():
            cursor.execute("""
                UPDATE metrics
                SET co2 = ?
                WHERE timestamp = ? AND (co2 IS NULL)
            """, (row["co2"], row["timestamp"]))
            updated_count += cursor.rowcount

        conn.commit()
        conn.close()

        return {
            "status": "success",
            "points_fetched": len(co2_points),
            "rows_updated_in_db": updated_count
        }

@app.get("/api-meteo/status/collection")
async def proxy_last_collection():
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(f"{COLLECTOR_URL}/api/status/last-collection")
            return resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Collector unavailable: {e}")

@app.get("/api-meteo/status/training")
async def proxy_last_training():
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(f"{ML_ENGINE_URL}/api/status/last-training")
            return resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"ML Engine unavailable: {e}")

@app.get("/trigger-clear-cache")
async def trigger_clear_cache():
    """Trigger cache clearing across data-collector and ml-engine."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            await client.get(f"{COLLECTOR_URL}/api/clear-cache")
            print("Collector cache cleared.")
        except Exception as e:
            print(f"Failed to clear collector cache: {e}")

        try:
            await client.get(f"{ML_ENGINE_URL}/api/clear-cache")
            print("ML engine cache cleared.")
        except Exception as e:
            print(f"Failed to clear ML engine cache: {e}")

    return RedirectResponse(url="/admin", status_code=303)

@app.get("/validation/error", response_class=HTMLResponse)
async def validation_error_page(request: Request, model: str = "ext", filter: str = "all"):
    db_exists = os.path.exists(DB_PATH)
    chart_payload = {}
    metrics_summary = {"mean_error": "N/A", "mae": "N/A", "rmse": "N/A"}

    if db_exists:
        try:
            df_metrics = pd.DataFrame()
            async with httpx.AsyncClient() as client:
                try:
                    resp_annotated = await client.get(f"{ML_ENGINE_URL}/api/metrics/annotated", timeout=10.0)
                    if resp_annotated.status_code == 200:
                        data_list = resp_annotated.json().get("data", [])
                        df_metrics = pd.DataFrame(data_list)
                except Exception as e:
                    print(f"ML Engine Annotated Metrics unreachable, falling back to local DB: {e}")

            if df_metrics.empty:
                conn = sqlite3.connect(DB_PATH)
                df_metrics = pd.read_sql("SELECT * FROM metrics ORDER BY timestamp ASC", conn)
                conn.close()

            if not df_metrics.empty:
                forecast_dict = {}
                async with httpx.AsyncClient() as client:
                    # On adapte l'appel selon le type de modèle demandé
                    api_path = "ext" if model == "ext" else "int"
                    resp = await client.get(f"{ML_ENGINE_URL}/api/forecast/{api_path}", timeout=5.0)

                    if resp.status_code == 200:
                        for item in resp.json().get("forecasts", []):
                            if model == "ext":
                                val_pred = item.get("predicted_ext_temp")
                            elif model == "int_gb":
                                val_pred = item.get("predicted_int_temp_gb")
                            elif model == "int_std":
                                val_pred = item.get("predicted_int_temp_std")
                            else:  # Par défaut, on prend RF pour "int"
                                val_pred = item.get("predicted_int_temp_gb")

                            forecast_dict[item["timestamp"]] = val_pred

                col_name = "ext_temp" if model == "ext" else "int_temp_min"
                if col_name not in df_metrics.columns:
                    col_name = "ext" if model == "ext" else "int"

                if col_name in df_metrics.columns:
                    df_metrics["pred"] = df_metrics["timestamp"].map(forecast_dict)
                    df_valid = df_metrics.dropna(subset=[col_name, "pred"]).copy()

                    if not df_valid.empty:
                        if "window_open_flag" in df_valid.columns:
                            df_valid["window_open"] = df_valid["window_open_flag"]
                        else:
                            df_valid["window_open"] = 0

                        if model.startswith("int"):
                            if filter == "int_open":
                                df_valid = df_valid[df_valid["window_open"] == 1]
                            elif filter == "int_closed":
                                df_valid = df_valid[df_valid["window_open"] == 0]

                        if not df_valid.empty:
                            df_valid["error"] = df_valid[col_name] - df_valid["pred"]

                            errors = df_valid["error"]
                            metrics_summary["mean_error"] = round(float(errors.mean()), 2)
                            metrics_summary["mae"] = round(float(errors.abs().mean()), 2)
                            metrics_summary["rmse"] = round(float(np.sqrt((errors ** 2).mean())), 2)

                            chart_payload = {
                                "timestamps": df_valid["timestamp"].tolist(),
                                "errors": df_valid["error"].round(2).tolist(),
                                "window_open": df_valid["window_open"].tolist(),
                                "thermal_mode": df_valid["thermal_mode"].tolist() if "thermal_mode" in df_valid.columns else [],
                                "model": model
                            }
        except Exception as e:
            print(f"Error generating error validation view: {e}")

    return templates.TemplateResponse(
        request,
        "validation_error.html",
        {
            "active_page": "validation",
            "db_exists": db_exists,
            "current_model": model,
            "current_filter": filter,
            "metrics_summary": metrics_summary,
            "chart_payload": chart_payload
        }
    )