"""
analytics/feature_extractor.py — Extractor de features estructuradas
=====================================================================
Convierte datos normalizados en features interpretables por el LLM.
NO usa LLM — solo Python/numpy/scipy. Coste: €0.

El LLM nunca recibe datos crudos. Solo recibe este resumen estructurado.
Esto es lo que controla el coste y lo que hace que las respuestas
sean concretas en lugar de genéricas.

Features:
  Por variable : estadísticas, tendencia, tasa de cambio, zscore vs baseline
  Entre vars   : correlaciones fuertes (>0.7), lags causales
  Temporal     : ventana analizada, número de muestras

Uso standalone (testeable sin el resto del sistema):
    python -m backend.analytics.feature_extractor simulator/data/tep_normal.csv
"""

import sys
import numpy as np
import pandas as pd
from scipy import stats
from typing import Optional


class FeatureExtractor:
    """
    Extrae features estructuradas de datos de sensores industriales.

    Regla de coste: filtra a top_n variables antes de pasar al LLM.
    Con top_n=20 y estructura compacta → ~800 tokens de contexto máximo.
    """

    def extract(
        self,
        df: pd.DataFrame,
        baselines: Optional[dict] = None,
        top_n: int = 20,
    ) -> dict:
        """
        Input : DataFrame long (timestamp, tag_id, value) o wide
        Output: dict de features listo para pasar como contexto al LLM
        """
        if df.empty:
            return {}

        wide = self._to_wide(df)
        if wide.empty:
            return {}

        # Selecciona las top_n variables por varianza (las más informativas)
        variances = wide.var().sort_values(ascending=False)
        top_tags = list(variances.head(top_n).index)
        wide = wide[top_tags]

        return {
            "variables": self._per_variable(wide, baselines or {}),
            "correlaciones_fuertes": self._correlations(wide),
            "lags_causales": self._lags(wide),
            "meta": {
                "n_variables_analizadas": len(top_tags),
                "n_variables_totales": len(variances),
                "inicio": str(wide.index.min()),
                "fin": str(wide.index.max()),
                "n_muestras": len(wide),
            },
        }

    # ── Features por variable ─────────────────────────────────────────────────

    def _per_variable(self, wide: pd.DataFrame, baselines: dict) -> dict:
        result = {}
        for col in wide.columns:
            values = wide[col].dropna().values
            if len(values) < 3:
                continue

            # Tendencia lineal sobre toda la ventana
            t = np.arange(len(values))
            slope, _, r2, _, _ = stats.linregress(t, values)
            r2 = r2 ** 2

            # Tasa de cambio en las últimas 10 muestras
            recent = values[-min(10, len(values)):]
            roc = (recent[-1] - recent[0]) / max(len(recent) - 1, 1)

            feat: dict = {
                "valor_actual": round(float(values[-1]), 4),
                "media": round(float(np.mean(values)), 4),
                "std": round(float(np.std(values)), 4),
                "min": round(float(np.min(values)), 4),
                "max": round(float(np.max(values)), 4),
                "tendencia": (
                    "creciente" if slope > 1e-4
                    else "decreciente" if slope < -1e-4
                    else "estable"
                ),
                "pendiente": round(float(slope), 6),
                "r2_lineal": round(float(r2), 3),
                "tasa_cambio_reciente": round(float(roc), 6),
            }

            # Comparación con baseline si existe
            b = baselines.get(col)
            if b and b.get("std", 0) > 0:
                z = (values[-1] - b["mean"]) / b["std"]
                feat["zscore_vs_baseline"] = round(float(z), 2)
                feat["estado"] = (
                    "normal" if abs(z) < 2
                    else "atipico" if abs(z) < 3
                    else "critico"
                )

            result[col] = feat
        return result

    # ── Correlaciones fuertes ─────────────────────────────────────────────────

    def _correlations(self, wide: pd.DataFrame, threshold: float = 0.70) -> list:
        corr = wide.corr()
        cols = list(corr.columns)
        pairs = []
        for i, a in enumerate(cols):
            for j, b in enumerate(cols):
                if j <= i:
                    continue
                c = float(corr.loc[a, b])
                if abs(c) >= threshold:
                    pairs.append({
                        "variables": [a, b],
                        "correlacion": round(c, 3),
                        "tipo": "positiva" if c > 0 else "negativa",
                    })
        pairs.sort(key=lambda x: abs(x["correlacion"]), reverse=True)
        return pairs[:15]

    # ── Lags causales por cross-correlación ───────────────────────────────────

    def _lags(self, wide: pd.DataFrame, max_lag: int = 12) -> list:
        corr = wide.corr()
        cols = list(wide.columns)
        lags_found = []

        for i, a in enumerate(cols):
            for j, b in enumerate(cols):
                if j <= i:
                    continue
                # Solo analiza pares con correlación base >= 0.5
                if abs(float(corr.loc[a, b])) < 0.50:
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

                if abs(best_lag) > 0 and abs(best_val) > 0.30:
                    lags_found.append({
                        "causa": a if best_lag > 0 else b,
                        "efecto": b if best_lag > 0 else a,
                        "lag_muestras": abs(best_lag),
                        "correlacion_con_lag": round(best_val, 3),
                    })

        lags_found.sort(key=lambda x: abs(x["correlacion_con_lag"]), reverse=True)
        return lags_found[:10]

    # ── Utilidades ────────────────────────────────────────────────────────────

    def _to_wide(self, df: pd.DataFrame) -> pd.DataFrame:
        if "tag_id" in df.columns and "value" in df.columns:
            index_col = "timestamp" if "timestamp" in df.columns else df.index.name
            if index_col and index_col in df.columns:
                wide = df.pivot_table(index=index_col, columns="tag_id",
                                      values="value", aggfunc="mean")
            else:
                wide = df.pivot_table(columns="tag_id", values="value", aggfunc="mean")
            return wide.ffill().fillna(0)
        # Ya está en formato wide
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        return df[numeric_cols].ffill().fillna(0)


# ── Ejecución standalone ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    path = sys.argv[1] if len(sys.argv) > 1 else "simulator/data/tep_normal.csv"
    print(f"[FeatureExtractor] Cargando {path}...")

    df = pd.read_csv(path)
    extractor = FeatureExtractor()
    features = extractor.extract(df, top_n=10)

    print("\n── Variables analizadas ──────────────────────────────")
    for tag, f in features["variables"].items():
        print(f"  {tag:12s}  val={f['valor_actual']:8.3f}  "
              f"tendencia={f['tendencia']:10s}  "
              f"estado={f.get('estado', 'sin_baseline')}")

    print("\n── Correlaciones fuertes ─────────────────────────────")
    for c in features["correlaciones_fuertes"][:5]:
        print(f"  {c['variables'][0]:12s} ↔ {c['variables'][1]:12s}  "
              f"corr={c['correlacion']:+.3f}  {c['tipo']}")

    print("\n── Lags causales detectados ──────────────────────────")
    for lag in features["lags_causales"][:5]:
        print(f"  {lag['causa']:12s} → {lag['efecto']:12s}  "
              f"lag={lag['lag_muestras']} muestras  "
              f"corr={lag['correlacion_con_lag']:+.3f}")

    print(f"\n── Meta: {features['meta']}")
    print("\n[OK] Feature extraction completada")
