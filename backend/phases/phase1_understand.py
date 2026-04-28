"""
phases/phase1_understand.py — Fase 1: Entendimiento del proceso (OFFLINE)
=========================================================================
Analiza datos históricos para entender qué hay en la planta ANTES de
conectarse en tiempo real. Sin LLM funciona con heurísticas estadísticas.
Con LLM enriquece con conocimiento de dominio.

Output: data/process_understanding.json

Uso standalone:
    python -m backend.phases.phase1_understand simulator/data/tep_normal.csv
    python -m backend.phases.phase1_understand --no-llm simulator/data/tep_normal.csv
"""

import sys
import json
import asyncio
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[2]))

from backend.analytics.feature_extractor import FeatureExtractor


# ── Heurísticas de clasificación de variables ─────────────────────────────────

_UNIT_PATTERNS = {
    "temperatura": ["temp", "tmp", "t_", "_t", "celsius", "kelvin", "tc", "tf"],
    "presion": ["pres", "press", "psi", "bar", "kpa", "mpa", "pc"],
    "caudal": ["flow", "caud", "flux", "flo", "qv", "qm"],
    "nivel": ["level", "nivel", "lvl", "lv", "liq"],
    "rpm": ["rpm", "speed", "veloc", "roto", "spd"],
    "potencia": ["pow", "watt", "kw", "kwh", "energy", "poten"],
    "vibracion": ["vib", "accel", "aceler", "shake"],
    "binario": ["status", "estado", "flag", "on_off", "alarm", "fault"],
    "porcentaje": ["pct", "perc", "percent", "ratio", "frac"],
}


def infer_variable_type(tag_id: str, values: np.ndarray) -> str:
    """Infiere el tipo de variable por nombre y rango numérico."""
    tag_lower = tag_id.lower()
    for var_type, patterns in _UNIT_PATTERNS.items():
        if any(p in tag_lower for p in patterns):
            return var_type

    # Clasificación por rango numérico cuando el nombre no ayuda
    vmin, vmax = float(np.min(values)), float(np.max(values))
    v_range = vmax - vmin
    if v_range == 0:
        return "constante"
    if set(np.unique(values.round(2))) <= {0.0, 1.0}:
        return "binario"
    if 0 <= vmin and vmax <= 100 and v_range < 50:
        return "porcentaje"
    if vmin > 200 and vmax < 900:
        return "temperatura"
    if vmin >= 0 and vmax < 50:
        return "presion_baja"
    return "desconocido"


def detect_operating_modes(df_wide: pd.DataFrame, n_clusters: int = 3) -> list[dict]:
    """
    Detecta modos de operación distintos (arranque, nominal, parada...)
    usando clustering simple sobre estadísticas de ventana.
    """
    try:
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler

        # Ventanas de 50 muestras
        window = 50
        if len(df_wide) < window * 2:
            return [{"modo": "unico", "n_muestras": len(df_wide), "fraccion": 1.0}]

        stats = []
        for i in range(0, len(df_wide) - window, window // 2):
            chunk = df_wide.iloc[i:i + window]
            stats.append(chunk.mean().values)

        X = StandardScaler().fit_transform(np.array(stats))
        k = min(n_clusters, len(stats) // 2)
        km = KMeans(n_clusters=k, random_state=42, n_init=5)
        labels = km.fit_predict(X)

        modes = []
        for lbl in range(k):
            mask = labels == lbl
            modes.append({
                "modo": f"modo_{lbl}",
                "n_ventanas": int(mask.sum()),
                "fraccion": round(float(mask.mean()), 3),
            })
        modes.sort(key=lambda x: x["fraccion"], reverse=True)
        if modes:
            modes[0]["modo"] = "nominal"
        return modes
    except Exception:
        return [{"modo": "unico", "n_muestras": len(df_wide), "fraccion": 1.0}]


def group_variables_by_correlation(
    df_wide: pd.DataFrame,
    threshold: float = 0.80,
) -> list[dict]:
    """
    Agrupa variables por correlación fuerte → probable mismo equipo.
    """
    corr = df_wide.corr().abs()
    cols = list(corr.columns)
    visited = set()
    groups = []

    for col in cols:
        if col in visited:
            continue
        group = [col]
        visited.add(col)
        for other in cols:
            if other in visited:
                continue
            if corr.loc[col, other] >= threshold:
                group.append(other)
                visited.add(other)
        if len(group) > 1:
            groups.append({
                "equipo_probable": f"equipo_{len(groups)+1}",
                "variables": group,
                "n_variables": len(group),
            })

    return groups


# ── Clase principal ────────────────────────────────────────────────────────────

class Phase1Understand:
    """
    Módulo offline de entendimiento del proceso.
    Genera process_understanding.json que alimenta Phase2 y el Observer.
    """

    OUTPUT_FILE = Path("data/process_understanding.json")

    def __init__(self, llm=None):
        self._llm = llm
        self._extractor = FeatureExtractor()

    def run(self, df: pd.DataFrame) -> dict:
        """
        Análisis completo sin LLM. Devuelve el dict de entendimiento.
        Llama a run_async() si quieres enriquecimiento con LLM.
        """
        return asyncio.run(self.run_async(df))

    async def run_async(self, df: pd.DataFrame) -> dict:
        """Análisis completo, con LLM si está disponible."""
        print("[Phase1] Extrayendo features...")
        wide = self._extractor._to_wide(df)
        features = self._extractor.extract(df, top_n=50)

        print("[Phase1] Clasificando variables...")
        variables_meta = self._classify_variables(wide, features)

        print("[Phase1] Detectando modos de operación...")
        operating_modes = detect_operating_modes(wide)

        print("[Phase1] Agrupando por correlación de equipo...")
        equipment_groups = group_variables_by_correlation(wide)

        print("[Phase1] Calculando estadísticas de estabilidad...")
        stability = self._compute_stability(wide)

        result: dict = {
            "version": "1.0",
            "n_variables": len(wide.columns),
            "n_muestras": len(wide),
            "rango_temporal": {
                "inicio": str(wide.index.min()),
                "fin": str(wide.index.max()),
            },
            "variables": variables_meta,
            "modos_operacion": operating_modes,
            "grupos_equipo": equipment_groups,
            "estabilidad": stability,
            "features_summary": {
                "correlaciones_fuertes": features.get("correlaciones_fuertes", [])[:10],
                "lags_causales": features.get("lags_causales", [])[:5],
            },
            "llm_enriched": False,
        }

        # Enriquecimiento con LLM (opcional)
        if self._llm:
            print("[Phase1] Enriqueciendo con LLM...")
            result = await self._enrich_with_llm(result, features)
            result["llm_enriched"] = True

        self._save(result)
        return result

    def _classify_variables(self, wide: pd.DataFrame, features: dict) -> dict:
        meta = {}
        for col in wide.columns:
            values = wide[col].dropna().values
            var_type = infer_variable_type(col, values)
            feat = features.get("variables", {}).get(col, {})
            meta[col] = {
                "tipo": var_type,
                "media": round(float(np.mean(values)), 4),
                "std": round(float(np.std(values)), 4),
                "min": round(float(np.min(values)), 4),
                "max": round(float(np.max(values)), 4),
                "tendencia_global": feat.get("tendencia", "estable"),
                "es_constante": float(np.std(values)) < 1e-6,
            }
        return meta

    def _compute_stability(self, wide: pd.DataFrame) -> dict:
        """Métricas de estabilidad global del proceso."""
        cv_list = []
        for col in wide.columns:
            vals = wide[col].dropna().values
            if len(vals) < 3 or np.mean(vals) == 0:
                continue
            cv = float(np.std(vals) / (abs(np.mean(vals)) + 1e-10))
            cv_list.append(cv)

        return {
            "coef_variacion_medio": round(float(np.mean(cv_list)), 4) if cv_list else 0,
            "variables_estables": sum(1 for cv in cv_list if cv < 0.05),
            "variables_inestables": sum(1 for cv in cv_list if cv > 0.20),
        }

    async def _enrich_with_llm(self, result: dict, features: dict) -> dict:
        """Usa el LLM para identificar tipo de proceso e interpretar variables."""
        sample_vars = list(result["variables"].items())[:15]
        var_summary = {
            tag: {
                "tipo_inferido": meta["tipo"],
                "rango": f"{meta['min']:.2f} - {meta['max']:.2f}",
                "media": meta["media"],
            }
            for tag, meta in sample_vars
        }

        schema = {
            "type": "object",
            "properties": {
                "tipo_proceso": {"type": "string"},
                "descripcion_proceso": {"type": "string"},
                "variables_clave": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 10,
                },
                "variables_interpretadas": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {
                            "nombre_fisico": {"type": "string"},
                            "unidad": {"type": "string"},
                            "equipo": {"type": "string"},
                        },
                    },
                },
            },
        }

        try:
            llm_result = await self._llm.complete_json(
                system_prompt=(
                    "Eres un experto en procesos industriales. "
                    "Analiza las variables de proceso y determina qué tipo de "
                    "planta industrial es y qué significa cada variable."
                ),
                user_message=(
                    "Identifica el tipo de proceso industrial y "
                    "el significado físico de estas variables de planta."
                ),
                context={"variables": var_summary},
                output_schema=schema,
            )
            result["tipo_proceso"] = llm_result.get("tipo_proceso", "desconocido")
            result["descripcion_proceso"] = llm_result.get("descripcion_proceso", "")
            result["variables_clave"] = llm_result.get("variables_clave", [])
            result["interpretacion_llm"] = llm_result.get("variables_interpretadas", {})
        except Exception as e:
            print(f"[Phase1] Error LLM: {e}")

        return result

    def _save(self, result: dict) -> None:
        self.OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(self.OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"[Phase1] Guardado en {self.OUTPUT_FILE}")


# ── Ejecución standalone ──────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase1: Process Understanding")
    parser.add_argument("csv", nargs="?", default="simulator/data/tep_normal.csv")
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()

    print(f"[Phase1] Cargando {args.csv}...")
    df = pd.read_csv(args.csv)
    print(f"[Phase1] {len(df)} filas, {len(df.columns)} columnas")

    llm_provider = None
    if not args.no_llm:
        try:
            from backend.core.config import get_settings
            from backend.llm.provider_factory import LLMProviderFactory
            cfg = get_settings()
            llm_provider = LLMProviderFactory.create(cfg.llm)
            print(f"[Phase1] LLM activo: {cfg.llm.provider}/{cfg.llm.model}")
        except Exception as e:
            print(f"[Phase1] LLM no disponible ({e}), usando heurísticas")

    phase1 = Phase1Understand(llm=llm_provider)
    result = asyncio.run(phase1.run_async(df))

    print("\n── Resumen de variables ──────────────────────────────────────────")
    tipo_counts: dict = {}
    for tag, meta in result["variables"].items():
        t = meta["tipo"]
        tipo_counts[t] = tipo_counts.get(t, 0) + 1
    for tipo, count in sorted(tipo_counts.items(), key=lambda x: -x[1]):
        print(f"  {tipo:20s}: {count} variables")

    print("\n── Modos de operación detectados ────────────────────────────────")
    for mode in result["modos_operacion"]:
        print(f"  {mode['modo']:15s}: {mode.get('fraccion', 0)*100:.1f}% del tiempo")

    print("\n── Grupos de equipo detectados ──────────────────────────────────")
    for grp in result["grupos_equipo"][:5]:
        print(f"  {grp['equipo_probable']}: {grp['variables'][:4]}...")

    print(f"\n── Estabilidad: {result['estabilidad']}")
    if result.get("tipo_proceso"):
        print(f"\n── Tipo de proceso (LLM): {result['tipo_proceso']}")
        print(f"   {result.get('descripcion_proceso', '')}")

    print("\n[OK] Phase1 completada")
