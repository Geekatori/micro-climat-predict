"""Publication des prédictions dans Home Assistant.

Écrit trois capteurs via l'API REST de HA (``POST /api/states/<entity_id>``).

Pourquoi cette voie plutôt que des capteurs REST côté HA : rien à éditer dans
``configuration.yaml`` (l'intégration ``rest`` n'existe qu'en YAML) et aucun port
à ouvrir, puisque le trafic ne part que vers HA.

Contrepartie assumée : un état créé ainsi vit en mémoire dans HA. Il disparaît à
chaque redémarrage de HA et revient à la publication suivante, donc au pire
trente minutes plus tard. Ces entités n'ont pas d'identifiant unique, elles ne
sont donc ni renommables ni rattachables à une pièce depuis l'interface. Pour
cela il faudra passer à MQTT.

Les horodatages du moteur de prédiction sont en temps universel et naïfs. Ils
sont convertis en ISO 8601 avec fuseau explicite, sans quoi HA les afficherait
avec deux heures de décalage en été.
"""

import os
from datetime import datetime, timedelta, timezone

import httpx

HA_URL = os.getenv("HA_URL", "").rstrip("/")
HA_TOKEN = os.getenv("HA_TOKEN", "")
ML_ENGINE_URL = os.getenv("ML_ENGINE_URL", "http://ml-engine:8000")
PREFIX = os.getenv("HA_SENSOR_PREFIX", "micro_climat")

# Horizon de la valeur ponctuelle publiée, et tolérance d'appariement.
HORIZON_HOURS = int(os.getenv("HA_PUBLISH_HORIZON_HOURS", 6))
MATCH_TOLERANCE = timedelta(minutes=30)

ATTRIBUTION = "micro-climat-predict"


def _to_iso_utc(naive_utc: str) -> str | None:
    """« 2026-09-04 19:40:00 » (UTC naïf) -> « 2026-09-04T19:40:00+00:00 »."""
    if not naive_utc:
        return None
    text = str(naive_utc).strip().replace(" ", "T").rstrip("Z")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _series_points(smart_series: list) -> list[tuple[datetime, float]]:
    """Convertit [[epoch_ms, valeur], ...] en points datés (UTC)."""
    points = []
    for item in smart_series or []:
        try:
            ts_ms, val = item[0], item[1]
            if val is None:
                continue
            dt = datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc)
            points.append((dt, float(val)))
        except (TypeError, ValueError, IndexError):
            continue
    return sorted(points, key=lambda p: p[0])


def _value_at_horizon(points, now, hours):
    """Valeur prévue la plus proche de now + hours, si l'écart reste tolérable."""
    target = now + timedelta(hours=hours)
    future = [p for p in points if p[0] > now]
    if not future:
        return None, None
    dt, val = min(future, key=lambda p: abs(p[0] - target))
    if abs(dt - target) > MATCH_TOLERANCE:
        return None, None
    return val, dt


def _max_over(points, now, hours):
    """Maximum prévu et son horaire sur la fenêtre (now, now + hours]."""
    window = [p for p in points if now < p[0] <= now + timedelta(hours=hours)]
    if not window:
        return None, None
    dt, val = max(window, key=lambda p: p[1])
    return val, dt


async def _fetch_predictions(client: httpx.AsyncClient) -> tuple[dict, list, list[str]]:
    """Récupère analyse et série intérieure auprès du moteur de prédiction."""
    errors: list[str] = []
    analysis: dict = {}
    series: list = []

    try:
        resp = await client.get(f"{ML_ENGINE_URL}/api/forecast/analysis")
        if resp.status_code == 200:
            analysis = resp.json()
        elif resp.status_code == 400:
            errors.append("modèles non entraînés")
        else:
            errors.append(f"analyse HTTP {resp.status_code}")
    except Exception as exc:
        errors.append(f"analyse indisponible : {type(exc).__name__}")

    try:
        resp = await client.get(f"{ML_ENGINE_URL}/api/forecast/smart?scope=all")
        if resp.status_code == 200:
            series = resp.json().get("smart_series", [])
        elif resp.status_code == 400:
            if "modèles non entraînés" not in errors:
                errors.append("modèles non entraînés")
        else:
            errors.append(f"série HTTP {resp.status_code}")
    except Exception as exc:
        errors.append(f"série indisponible : {type(exc).__name__}")

    return analysis, series, errors


def _build_states(analysis: dict, series: list) -> list[dict]:
    """Construit les trois états à écrire dans HA."""
    now = datetime.now(timezone.utc)
    points = _series_points(series)

    opening_iso = _to_iso_utc(analysis.get("opening_time"))

    horizon_val, horizon_dt = _value_at_horizon(points, now, HORIZON_HOURS)
    max_val, max_dt = _max_over(points, now, 24)

    return [
        {
            "entity_id": f"sensor.{PREFIX}_ouverture_fenetres",
            "state": opening_iso or "unknown",
            "attributes": {
                "friendly_name": "Ouverture des fenêtres conseillée",
                "device_class": "timestamp",
                "icon": "mdi:window-open-variant",
                "attribution": ATTRIBUTION,
            },
        },
        {
            "entity_id": f"sensor.{PREFIX}_interieur_dans_{HORIZON_HOURS}h",
            "state": round(horizon_val, 1) if horizon_val is not None else "unknown",
            "attributes": {
                "friendly_name": f"Température intérieure prévue dans {HORIZON_HOURS} h",
                "unit_of_measurement": "°C",
                "device_class": "temperature",
                "icon": "mdi:home-thermometer-outline",
                "attribution": ATTRIBUTION,
                "horodatage_prevision": horizon_dt.isoformat() if horizon_dt else None,
            },
        },
        {
            "entity_id": f"sensor.{PREFIX}_interieur_max_24h",
            "state": round(max_val, 1) if max_val is not None else "unknown",
            "attributes": {
                "friendly_name": "Maximum intérieur prévu sur 24 h",
                "unit_of_measurement": "°C",
                "device_class": "temperature",
                "icon": "mdi:thermometer-high",
                "attribution": ATTRIBUTION,
                "horodatage_maximum": max_dt.isoformat() if max_dt else None,
            },
        },
    ]


async def publish_predictions() -> dict:
    """Publie les prédictions dans HA. Ne lève jamais : renvoie un compte rendu."""
    if not HA_URL or not HA_TOKEN:
        return {"status": "error", "message": "HA_URL ou HA_TOKEN absent"}

    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    written, errors = [], []

    async with httpx.AsyncClient(timeout=30.0) as client:
        analysis, series, errors_pred = await _fetch_predictions(client)
        errors.extend(errors_pred)

        states = _build_states(analysis, series)

        # Sans aucune donnée exploitable, on n'écrase pas les états existants
        # par des « unknown » : mieux vaut laisser la valeur précédente en place.
        if all(s["state"] == "unknown" for s in states):
            return {
                "status": "skipped",
                "message": "aucune prédiction exploitable, états HA laissés intacts",
                "errors": errors,
            }

        for state in states:
            entity_id = state.pop("entity_id")
            try:
                resp = await client.post(
                    f"{HA_URL}/api/states/{entity_id}", headers=headers, json=state
                )
                if resp.status_code in (200, 201):
                    written.append({"entity_id": entity_id, "state": state["state"]})
                else:
                    errors.append(f"{entity_id} : HTTP {resp.status_code}")
            except Exception as exc:
                errors.append(f"{entity_id} : {type(exc).__name__}")

    return {
        "status": "success" if written and not errors else ("partial" if written else "error"),
        "written": written,
        "errors": errors,
    }
