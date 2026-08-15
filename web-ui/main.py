from datetime import datetime, timedelta, timezone
import math
import os
import sqlite3
import httpx
import numpy as np
import pandas as pd
from fastapi import APIRouter, FastAPI, Request, BackgroundTasks
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
            # 1. Récupération des métriques annotées directement depuis l'API du ml-engine
            df_metrics = pd.DataFrame()
            async with httpx.AsyncClient() as client:
                try:
                    resp_annotated = await client.get(f"{ML_ENGINE_URL}/api/metrics/annotated", timeout=10.0)
                    if resp_annotated.status_code == 200:
                        data_list = resp_annotated.json().get("data", [])
                        df_metrics = pd.DataFrame(data_list)
                except Exception as e:
                    print(f"ML Engine Annotated Metrics unreachable, falling back to local DB: {e}")

            # Fallback local direct si le ml-engine est injoignable
            if df_metrics.empty:
                conn = sqlite3.connect(DB_PATH)
                df_metrics = pd.read_sql("SELECT * FROM metrics ORDER BY timestamp ASC", conn)
                conn.close()

            # Récupération des prévisions météo pour fusion
            conn = sqlite3.connect(DB_PATH)
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

                forecast_ext_dict, forecast_int_rf_dict, forecast_int_std_dict = {}, {}, {}

                # --- Récupération des prédictions (RF & STD) ---
                async with httpx.AsyncClient() as client:
                    try:
                        resp_ext = await client.get(f"{ML_ENGINE_URL}/api/forecast/ext", timeout=5.0)
                        if resp_ext.status_code == 200:
                            for item in resp_ext.json().get("forecasts", []):
                                forecast_ext_dict[item["timestamp"]] = item.get("predicted_ext_temp")
                    except Exception as e:
                        print(f"ML Ext Forecast unreachable: {e}")

                    try:
                        resp_int = await client.get(f"{ML_ENGINE_URL}/api/forecast/int", timeout=10.0)
                        if resp_int.status_code == 200:
                            for item in resp_int.json().get("forecasts", []):
                                forecast_int_rf_dict[item["timestamp"]] = item.get("predicted_int_temp_rf")
                                forecast_int_std_dict[item["timestamp"]] = item.get("predicted_int_temp_std")
                    except Exception as e:
                        print(f"ML Int Forecast unreachable: {e}")

                df["predicted_ext_temp"] = df["timestamp"].map(forecast_ext_dict)
                df["predicted_int_temp_rf"] = df["timestamp"].map(forecast_int_rf_dict)
                df["predicted_int_temp_std"] = df["timestamp"].map(forecast_int_std_dict)

                # S'assurer que le DataFrame possède la colonne window_open_flag
                if "window_open_flag" not in df.columns:
                    df["window_open_flag"] = 0

                # Préparation des modes pour l'affichage
                df["ext_temp_forecast_mode"] = df.apply(lambda r: r["ext_temp"] if r["dt"] <= now_dt else r["predicted_ext_temp"], axis=1)
                df["int_temp_rf_forecast_mode"] = df.apply(lambda r: r["int_temp_min"] if r["dt"] <= now_dt else r["predicted_int_temp_rf"], axis=1)

                # Masquage de la courbe STD : on affiche la valeur QUE si on est confiné (ou dans le futur)
                df["int_temp_std_masked"] = df.apply(
                    lambda r: r["predicted_int_temp_std"] if (r["window_open_flag"] == 0 or r["dt"] > now_dt) else None,
                    axis=1
                )

                for col in ["meteo_temp", "meteo_hum", "wind_speed", "cloud_cover", "direct_radiation"]:
                    if col in df.columns:
                        df[f"{col}_past"] = df.apply(lambda row: row[col] if row["dt"] <= now_dt else None, axis=1)
                        df[f"{col}_forecast"] = df.apply(lambda row: row[col] if row["dt"] > now_dt else None, axis=1)

                chart_data_payload = clean_for_json({
                    "timestamps": df["timestamp"].tolist(),
                    "ext_temp": df["ext_temp"].tolist() if "ext_temp" in df else [],
                    "int_temp_min": df["int_temp_min"].tolist() if "int_temp_min" in df else [],
                    "cor_temp": df["cor_temp"].tolist() if "cor_temp" in df else [],
                    "co2": df["co2"].tolist() if "co2" in df else [],
                    "ext_temp_forecast_mode": df["ext_temp_forecast_mode"].tolist(),
                    "int_temp_rf_forecast_mode": df["int_temp_rf_forecast_mode"].tolist(),
                    "int_temp_std_masked": df["int_temp_std_masked"].tolist(),
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
                    "meteo_hum": df["meteo_hum"].tolist() if "meteo_hum_hum" in df else [],
                    "wind_speed": df["wind_speed"].tolist() if "wind_speed" in df else [],
                    "window_open_flag": df["window_open_flag"].fillna(0).astype(int).tolist(),
                    "cloud_cover_past": df["cloud_cover_past"].tolist() if "cloud_cover_past" in df else [],
                    "cloud_cover_forecast": df["cloud_cover_forecast"].tolist() if "cloud_cover_forecast" in df else [],
                    "direct_radiation_past": df["direct_radiation_past"].tolist() if "direct_radiation_past" in df else [],
                    "direct_radiation_forecast": df["direct_radiation_forecast"].tolist() if "direct_radiation_forecast" in df else [],
                    "cloud_cover": df["cloud_cover"].tolist() if "cloud_cover" in df else [],
                    "direct_radiation": df["direct_radiation"].tolist() if "direct_radiation" in df else [],
                    "int_temp_rf": df["predicted_int_temp_rf"].tolist(),
                    "int_temp_std": df["predicted_int_temp_std"].tolist(),
                })

                drop_cols = [c for c in ["dt", "predicted_ext_temp", "predicted_int_temp_rf", "predicted_int_temp_std", "ext_temp_forecast_mode", "int_temp_rf_forecast_mode", "int_temp_std_masked", "is_fit_ready", "thermal_mode"] if c in df.columns]
                df_tail = df.drop(columns=drop_cols, errors="ignore").tail(50).sort_values(by="timestamp", ascending=False)
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
async def trigger_collect(days: int = 10):
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
        # return_exceptions=True empêche un échec de faire crasher les autres
        results = await asyncio.gather(
            client.get(f"{COLLECTOR_URL}/api/data/history/{version}"),
            client.get(f"{COLLECTOR_URL}/api/data/current"),
            return_exceptions=True
        )

        hist_resp, curr_resp = results

        # Traitement sécurisé History
        if isinstance(hist_resp, Exception):
            errors.append(f"History connect error: {hist_resp}")
        elif hist_resp.status_code == 200:
            hist_data = hist_resp.json().get("data", [])
        else:
            errors.append(f"History API failed with {hist_resp.status_code}")

        # Traitement sécurisé Current
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