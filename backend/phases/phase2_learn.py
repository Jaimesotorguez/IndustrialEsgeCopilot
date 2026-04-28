"""
phases/phase2_learn.py — Fase 2: Aprendizaje profundo del histórico (OFFLINE)
==============================================================================
Usa el entendimiento del proceso (Phase1) para aprender del histórico completo:
  - Baselines robustos por variable (media, std, percentiles, IQR)
  - Correlaciones estructurales validadas estadísticamente
  - Relaciones causales con lag (HypothesisEngine sobre ventanas)
  - Grafo de proceso con confianza estadística
  - Detección de regímenes anómalos en el histórico

Input:  CSV histórico + data/process_understanding.json (opcional)
Output: data/learned_model.json (cargado por Phase3/Observer)

Uso standalone:
    python -m backend.phases.phase2_learn simulator/data/tep_normal.csv
    python -m backend.phases.phase2_learn --no-llm simulator/data/tep_normal.csv
    python -m backend.phases.phase2_learn --window 200 simulator/data/tep_normal.csv
"""

import sys
import json
import asyncio
import argparse
from pathlib import Path
from typing import Optional
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).parents[2]))

from backend.analytics.feature_extractor import FeatureExtractor
from backend.inference.hypothesis_engine import HypothesisEngine


# ── Clase principal ────────────────────────────────────────────────────────────

class Phase2Learn:
    """
    Aprendizaje profundo sobre datos históricos.
    Genera learned_model.json que alimenta al Observer en tiempo real.

    Diseño offline-first: funciona sin conexión de datos.
    Cada submódulo es testeable independientemente.
    """

    OUTPUT_FILE = Path("data/learned_model.json")
    UNDERSTANDING_FILE = Path("data/process_understanding.json")

    def __init__(self, llm=None, window_size: int = 200):
        self._llm = llm
        self._window_size = window_size
        self._extractor = FeatureExtractor()
        self._engine = HypothesisEngine(llm=llm)

    def run(self, df: pd.DataFrame) -> dict:
        return asyncio.run(self.run_async(df))

    async def run_async(self, df: pd.DataFrame) -> dict:
        """Aprendizaje completo sobre el histórico."""
        # Carga entendimiento previo si existe
        understanding = self._load_understanding()

        print("[Phase2] Preparando DataFrame...")
        wide = self._extractor._to_wide(df)
        print(f"[Phase2] {len(wide)} muestras × {len(wide.columns)} variables")

        print("[Phase2] Calculando baselines robustos...")
        baselines = self._compute_baselines(wide)

        print("[Phase2] Analizando correlaciones estructurales...")
        correlations = self._structural_correlations(wide)

        print("[Phase2] Detectando lags causales en ventanas...")
        causal_lags = self._compute_causal_lags(wide)

        print("[Phase2] Ejecutando hipótesis sobre ventanas históricas...")
        hypotheses_summary = await self._run_windowed_hypotheses(wide, baselines)

        print("[Phase2] Construyendo grafo de proceso...")
        process_graph = self._build_process_graph(
            correlations, causal_lags, hypotheses_summary, understanding
        )

        print("[Phase2] Detectando regímenes anómalos en el histórico...")
        anomaly_periods = self._detect_historical_anomalies(wide, baselines)

        result = {
            "version": "1.0",
            "n_muestras_entrenamiento": len(wide),
            "n_variables": len(wide.columns),
            "baselines": baselines,
            "correlaciones": correlations,
            "lags_causales": causal_lags,
            "hipotesis_validadas": hypotheses_summary,
            "grafo_proceso": process_graph,
            "periodos_anomalos": anomaly_periods,
            "meta": {
                "window_size": self._window_size,
                "llm_used": self._llm is not None,
                "understanding_used": bool(understanding),
            },
        }

        self._save(result)
        return result

    # ── Baselines robustos ────────────────────────────────────────────────────

    def _compute_baselines(self, wide: pd.DataFrame) -> dict:
        """
        Baselines robustos: usa percentil 5-95 como rango normal,
        MAD como dispersión (resistente a outliers).
        """
        baselines = {}
        for col in wide.columns:
            values = wide[col].dropna().values
            if len(values) < 10:
                continue
            q5, q25, q50, q75, q95 = np.percentile(values, [5, 25, 50, 75, 95])
            mad = float(np.median(np.abs(values - np.median(values))))
            mean = float(np.mean(values))
            std = float(np.std(values))

            baselines[col] = {
                "mean": round(mean, 6),
                "std": round(std, 6),
                "median": round(float(q50), 6),
                "mad": round(mad, 6),
                "q5": round(float(q5), 6),
                "q25": round(float(q25), 6),
                "q75": round(float(q75), 6),
                "q95": round(float(q95), 6),
                "iqr": round(float(q75 - q25), 6),
                "normal_min": round(float(q5), 6),
                "normal_max": round(float(q95), 6),
                "n_samples": len(values),
            }
        return baselines

    # ── Correlaciones estructurales ───────────────────────────────────────────

    def _structural_correlations(
        self,
        wide: pd.DataFrame,
        threshold: float = 0.70,
        min_samples: int = 30,
    ) -> list[dict]:
        """
        Correlaciones validadas estadísticamente (p-value < 0.01).
        Filtra correlaciones espúreas.
        """
        cols = list(wide.columns)
        validated = []

        for i, a in enumerate(cols):
            for j, b in enumerate(cols):
                if j <= i:
                    continue
                xa = wide[a].dropna()
                xb = wide[b].dropna()
                common = xa.index.intersection(xb.index)
                if len(common) < min_samples:
                    continue
                xa_c = xa[common].values
                xb_c = xb[common].values

                r, p = stats.pearsonr(xa_c, xb_c)
                if abs(r) >= threshold and p < 0.01:
                    validated.append({
                        "variables": [a, b],
                        "pearson_r": round(float(r), 4),
                        "p_value": round(float(p), 6),
                        "tipo": "positiva" if r > 0 else "negativa",
                        "n_muestras": len(common),
                    })

        validated.sort(key=lambda x: abs(x["pearson_r"]), reverse=True)
        return validated[:30]

    # ── Lags causales ─────────────────────────────────────────────────────────

    def _compute_causal_lags(
        self,
        wide: pd.DataFrame,
        max_lag: int = 20,
        base_corr_threshold: float = 0.50,
    ) -> list[dict]:
        """
        Detección de lags causales sobre todo el histórico.
        Más exhaustiva que FeatureExtractor (max_lag mayor).
        """
        cols = list(wide.columns)
        corr_matrix = wide.corr()
        lags_found = []

        for i, a in enumerate(cols):
            for j, b in enumerate(cols):
                if j <= i:
                    continue
                if abs(float(corr_matrix.loc[a, b])) < base_corr_threshold:
                    continue

                xa = wide[a].dropna().values
                xb = wide[b].dropna().values
                n = min(len(xa), len(xb))
                if n < max_lag * 4:
                    continue

                xa, xb = xa[:n], xb[:n]
                xa_n = (xa - xa.mean()) / (xa.std() + 1e-10)
                xb_n = (xb - xb.mean()) / (xb.std() + 1e-10)

                xcorr = np.correlate(xa_n, xb_n, mode="full")
                center = len(xcorr) // 2
                window = xcorr[center - max_lag: center + max_lag + 1]
                best_idx = int(np.argmax(np.abs(window)))
                best_lag = best_idx - max_lag
                best_val = float(window[best_idx] / n)

                if abs(best_lag) > 0 and abs(best_val) > 0.25:
                    lags_found.append({
                        "causa": a if best_lag > 0 else b,
                        "efecto": b if best_lag > 0 else a,
                        "lag_muestras": abs(best_lag),
                        "correlacion_con_lag": round(best_val, 4),
                        "confianza": round(min(abs(best_val), 1.0), 4),
                    })

        lags_found.sort(key=lambda x: abs(x["correlacion_con_lag"]), reverse=True)
        return lags_found[:20]

    # ── Hipótesis en ventanas ─────────────────────────────────────────────────

    async def _run_windowed_hypotheses(
        self,
        wide: pd.DataFrame,
        baselines: dict,
    ) -> dict:
        """
        Ejecuta el motor de hipótesis sobre múltiples ventanas del histórico.
        Recoge hipótesis que se repiten → mayor confianza.
        """
        if len(wide) < self._window_size * 2:
            print("[Phase2] Histórico demasiado corto para análisis de ventanas")
            return {"hipotesis_recurrentes": [], "n_ventanas_analizadas": 0}

        n_windows = min(10, len(wide) // self._window_size)
        step = (len(wide) - self._window_size) // max(n_windows - 1, 1)

        hypothesis_counts: dict[str, dict] = {}

        for i in range(n_windows):
            start = i * step
            end = start + self._window_size
            window_df = wide.iloc[start:end]

            features = self._extractor.extract(window_df, baselines=baselines, top_n=15)
            if not features:
                continue

            result = await self._engine.run(
                features=features,
                df_current=window_df,
                max_iterations=2,
            )

            for h in result.accepted:
                key = h.hypothesis[:80]
                if key not in hypothesis_counts:
                    hypothesis_counts[key] = {
                        "hypothesis": h.hypothesis,
                        "count": 0,
                        "scores": [],
                        "evidence": h.evidence_for,
                    }
                hypothesis_counts[key]["count"] += 1
                hypothesis_counts[key]["scores"].append(h.score)

            print(
                f"[Phase2] Ventana {i+1}/{n_windows}: "
                f"{len(result.accepted)} hipótesis aceptadas"
            )

        # Hipótesis que aparecen en >=2 ventanas son estructurales
        recurrent = [
            {
                "hypothesis": v["hypothesis"],
                "frecuencia": v["count"],
                "score_medio": round(float(np.mean(v["scores"])), 3),
                "evidencia": v["evidence"],
            }
            for v in hypothesis_counts.values()
            if v["count"] >= 2
        ]
        recurrent.sort(key=lambda x: x["score_medio"], reverse=True)

        return {
            "hipotesis_recurrentes": recurrent[:10],
            "n_ventanas_analizadas": n_windows,
        }

    # ── Grafo de proceso ──────────────────────────────────────────────────────

    def _build_process_graph(
        self,
        correlations: list[dict],
        causal_lags: list[dict],
        hypotheses_summary: dict,
        understanding: Optional[dict],
    ) -> dict:
        """
        Construye grafo de proceso a partir de evidencia estadística.
        Nodos = variables. Aristas = relaciones validadas.
        """
        nodes: dict[str, dict] = {}
        edges: list[dict] = []

        # Añade nodos desde correlaciones
        for corr in correlations:
            for var in corr["variables"]:
                if var not in nodes:
                    nodes[var] = {"id": var, "tipo": "variable", "confianza": 0.5}

        # Aristas desde correlaciones (relación estructural)
        for corr in correlations[:15]:
            edges.append({
                "source": corr["variables"][0],
                "target": corr["variables"][1],
                "tipo": "correlacion",
                "peso": abs(corr["pearson_r"]),
                "direccion": corr["tipo"],
            })

        # Aristas desde lags causales (relación causal)
        for lag in causal_lags[:10]:
            causa, efecto = lag["causa"], lag["efecto"]
            for var in [causa, efecto]:
                if var not in nodes:
                    nodes[var] = {"id": var, "tipo": "variable", "confianza": 0.5}
            edges.append({
                "source": causa,
                "target": efecto,
                "tipo": "causal",
                "lag_muestras": lag["lag_muestras"],
                "peso": lag["confianza"],
            })

        # Enriquece con grupos de equipo si hay entendimiento previo
        if understanding and "grupos_equipo" in understanding:
            for grp in understanding["grupos_equipo"]:
                equipo_id = grp["equipo_probable"]
                for var in grp["variables"]:
                    if var in nodes:
                        nodes[var]["equipo"] = equipo_id
                        nodes[var]["confianza"] = 0.8

        return {
            "n_nodos": len(nodes),
            "n_aristas": len(edges),
            "nodos": list(nodes.values()),
            "aristas": edges,
        }

    # ── Detección anomalías históricas ────────────────────────────────────────

    def _detect_historical_anomalies(
        self,
        wide: pd.DataFrame,
        baselines: dict,
        zscore_threshold: float = 3.0,
    ) -> list[dict]:
        """
        Identifica períodos donde múltiples variables salieron de su baseline.
        Útil para validation del modelo y para que el operario confirme.
        """
        periods = []
        window = max(10, self._window_size // 10)

        for start in range(0, len(wide) - window, window):
            chunk = wide.iloc[start:start + window]
            n_anomalous = 0
            anomalous_vars = []

            for col, b in baselines.items():
                if col not in chunk.columns or b.get("std", 0) == 0:
                    continue
                col_vals = chunk[col].dropna().values
                if len(col_vals) == 0:
                    continue
                z = abs(float(np.mean(col_vals)) - b["mean"]) / b["std"]
                if z > zscore_threshold:
                    n_anomalous += 1
                    anomalous_vars.append({"variable": col, "zscore": round(z, 2)})

            if n_anomalous >= 3:
                periods.append({
                    "inicio_idx": start,
                    "fin_idx": start + window,
                    "n_variables_anomalas": n_anomalous,
                    "variables_afectadas": sorted(
                        anomalous_vars, key=lambda x: -x["zscore"]
                    )[:5],
                })

        return periods[:20]

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _load_understanding(self) -> Optional[dict]:
        if self.UNDERSTANDING_FILE.exists():
            try:
                with open(self.UNDERSTANDING_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                print(f"[Phase2] Cargado {self.UNDERSTANDING_FILE}")
                return data
            except Exception as e:
                print(f"[Phase2] Error cargando understanding: {e}")
        return None

    def _save(self, result: dict) -> None:
        self.OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(self.OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"[Phase2] Guardado en {self.OUTPUT_FILE}")


# ── Ejecución standalone ──────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase2: Deep Historical Learning")
    parser.add_argument("csv", nargs="?", default="simulator/data/tep_normal.csv")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--window", type=int, default=200, help="Ventana de análisis")
    args = parser.parse_args()

    print(f"[Phase2] Cargando {args.csv}...")
    df = pd.read_csv(args.csv)
    print(f"[Phase2] {len(df)} filas, {len(df.columns)} columnas")

    llm_provider = None
    if not args.no_llm:
        try:
            from backend.core.config import get_settings
            from backend.llm.provider_factory import LLMProviderFactory
            cfg = get_settings()
            llm_provider = LLMProviderFactory.create(cfg.llm)
            print(f"[Phase2] LLM activo: {cfg.llm.provider}/{cfg.llm.model}")
        except Exception as e:
            print(f"[Phase2] LLM no disponible ({e}), usando heurísticas")

    phase2 = Phase2Learn(llm=llm_provider, window_size=args.window)
    result = asyncio.run(phase2.run_async(df))

    print("\n── Baselines calculados ─────────────────────────────────────────")
    print(f"  {len(result['baselines'])} variables con baseline")
    sample = list(result["baselines"].items())[:3]
    for tag, b in sample:
        print(f"  {tag:15s}  mean={b['mean']:.3f}  std={b['std']:.3f}  "
              f"rango=[{b['normal_min']:.3f}, {b['normal_max']:.3f}]")

    print("\n── Correlaciones estructurales ─────────────────────────────────")
    for corr in result["correlaciones"][:5]:
        print(f"  {corr['variables'][0]:15s} ↔ {corr['variables'][1]:15s}  "
              f"r={corr['pearson_r']:+.3f}  p={corr['p_value']:.4f}")

    print("\n── Lags causales validados ──────────────────────────────────────")
    for lag in result["lags_causales"][:5]:
        print(f"  {lag['causa']:15s} → {lag['efecto']:15s}  "
              f"lag={lag['lag_muestras']} muestras  "
              f"conf={lag['confianza']:.3f}")

    hs = result["hipotesis_validadas"]
    print(f"\n── Hipótesis estructurales ({hs['n_ventanas_analizadas']} ventanas) ──")
    for h in hs.get("hipotesis_recurrentes", [])[:5]:
        print(f"  [{h['score_medio']:.2f}] (×{h['frecuencia']}) {h['hypothesis'][:70]}")

    g = result["grafo_proceso"]
    print(f"\n── Grafo de proceso: {g['n_nodos']} nodos, {g['n_aristas']} aristas")

    if result["periodos_anomalos"]:
        print(f"\n── Períodos anómalos en histórico: {len(result['periodos_anomalos'])}")
        for p in result["periodos_anomalos"][:3]:
            print(f"  idx {p['inicio_idx']}-{p['fin_idx']}: "
                  f"{p['n_variables_anomalas']} vars anomalas")

    print("\n[OK] Phase2 completada")
