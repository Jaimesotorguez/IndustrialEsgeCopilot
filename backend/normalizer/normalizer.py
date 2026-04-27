"""
normalizer/normalizer.py — M2: Normalización de datos
======================================================
Convierte lecturas crudas de cualquier fuente al formato interno estándar.
Limpia outliers, rellena huecos, infiere tipos de variable.
Toda comunicación hacia el resto del sistema pasa por aquí.
"""

from datetime import datetime
from typing import Optional
import numpy as np
import pandas as pd
from scipy import stats

from backend.core.interfaces import DataNormalizer, SensorReading


# ── Tipos de variable conocidos ───────────────────────────────────────────────
# El sistema intenta inferir el tipo de cada tag automáticamente

VARIABLE_TYPE_HINTS = {
    # Patrones en el nombre del tag → tipo probable
    "temp":     "temperatura",
    "t_":       "temperatura",
    "press":    "presion",
    "pres":     "presion",
    "p_":       "presion",
    "flow":     "caudal",
    "level":    "nivel",
    "lvl":      "nivel",
    "rpm":      "velocidad",
    "speed":    "velocidad",
    "vib":      "vibracion",
    "current":  "corriente",
    "amp":      "corriente",
    "volt":     "tension",
    "power":    "potencia",
    "xmeas":    "medida_proceso",   # Tennessee Eastman
    "xmv":      "variable_manipulada",
}


class SensorNormalizer(DataNormalizer):
    """
    Normaliza series temporales de sensores industriales.

    Qué hace:
    - Limpia valores NaN e infinitos
    - Detecta y marca outliers extremos (no los elimina, los marca)
    - Infiere tipo de variable por nombre del tag
    - Calcula estadísticas de baseline para comparación futura
    - Convierte a DataFrame con schema fijo

    Schema de salida (siempre):
        timestamp   : datetime
        tag_id      : str
        value       : float
        value_norm  : float       (normalizado 0-1 sobre el rango observado)
        unit_guess  : str
        var_type    : str
        quality     : float       (0-1, 1 = dato limpio)
        is_outlier  : bool
        source      : str
    """

    def __init__(self):
        self._baselines: dict[str, dict] = {}   # tag_id → estadísticas
        self._fitted = False

    # ── DataNormalizer interface ──────────────────────────────────────────────

    def normalize(self, readings: list[SensorReading]) -> pd.DataFrame:
        """
        Normaliza un batch de lecturas.
        Si no hay baseline previo, calcula uno sobre el batch actual.
        """
        if not readings:
            return pd.DataFrame()

        df = self._readings_to_df(readings)
        df = self._clean(df)
        df = self._add_metadata(df)
        df = self._add_normalized_value(df)
        df = self._detect_outliers(df)
        return df

    def normalize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Normaliza un DataFrame ya en formato long.
        Útil cuando el histórico completo viene de CsvAdapter.load_full_historical().
        """
        df = df.copy()
        df = self._clean(df)
        df = self._add_metadata(df)
        df = self._add_normalized_value(df)
        df = self._detect_outliers(df)
        return df

    def infer_variable_type(self, tag_id: str, values: list[float]) -> str:
        """Infiere el tipo de variable por nombre del tag y distribución de valores."""
        tag_lower = tag_id.lower()

        # Por nombre
        for pattern, var_type in VARIABLE_TYPE_HINTS.items():
            if pattern in tag_lower:
                return var_type

        # Por distribución de valores
        if not values:
            return "desconocido"

        arr = np.array(values)
        unique_ratio = len(np.unique(arr)) / len(arr)

        if unique_ratio < 0.05:
            return "binario_o_categorico"
        if np.all((arr >= 0) & (arr <= 1)):
            return "fraccion_o_ratio"
        if np.max(arr) < 10 and np.min(arr) >= 0:
            return "conteo"

        return "numerico_continuo"

    # ── Métodos de entrenamiento ──────────────────────────────────────────────

    def fit(self, historical_df: pd.DataFrame) -> None:
        """
        Calcula estadísticas de baseline sobre el histórico.
        Llamar UNA VEZ al arrancar con el histórico completo.
        Después, normalize() usa estas estadísticas para detectar desviaciones.
        """
        if historical_df.empty:
            return

        for tag_id, group in historical_df.groupby("tag_id"):
            values = group["value"].dropna().values
            if len(values) < 10:
                continue

            self._baselines[tag_id] = {
                "mean":   float(np.mean(values)),
                "std":    float(np.std(values)),
                "min":    float(np.min(values)),
                "max":    float(np.max(values)),
                "p5":     float(np.percentile(values, 5)),
                "p95":    float(np.percentile(values, 95)),
                "count":  len(values),
                "var_type": self.infer_variable_type(str(tag_id), values.tolist()),
            }

        self._fitted = True
        print(f"[Normalizer] Baseline calculado para {len(self._baselines)} variables")

    def get_baseline(self, tag_id: str) -> Optional[dict]:
        return self._baselines.get(tag_id)

    def get_all_baselines(self) -> dict:
        return self._baselines.copy()

    def is_fitted(self) -> bool:
        return self._fitted

    # ── Procesamiento interno ─────────────────────────────────────────────────

    def _readings_to_df(self, readings: list[SensorReading]) -> pd.DataFrame:
        return pd.DataFrame([{
            "timestamp": r.timestamp,
            "tag_id":    r.tag_id,
            "value":     r.value,
            "quality":   r.quality,
            "source":    r.source,
        } for r in readings])

    def _clean(self, df: pd.DataFrame) -> pd.DataFrame:
        """Limpieza básica: NaN, infinitos, tipos."""
        df = df.copy()
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df["value"] = df["value"].replace([np.inf, -np.inf], np.nan)

        # Rellena NaN con el último valor válido por tag (forward fill)
        df = df.sort_values(["tag_id", "timestamp"])
        df["value"] = df.groupby("tag_id")["value"].ffill()

        # Después del ffill, los que siguen siendo NaN los marca con quality 0
        mask_nan = df["value"].isna()
        df.loc[mask_nan, "quality"] = 0.0
        df["value"] = df["value"].fillna(0.0)

        return df

    def _add_metadata(self, df: pd.DataFrame) -> pd.DataFrame:
        """Añade tipo de variable y unidad estimada."""
        df = df.copy()

        def get_type(tag_id: str) -> str:
            if tag_id in self._baselines:
                return self._baselines[tag_id].get("var_type", "desconocido")
            return self.infer_variable_type(tag_id, [])

        def get_unit(var_type: str) -> str:
            units = {
                "temperatura": "°C",
                "presion": "%",
                "caudal": "m³/h",
                "nivel": "%",
                "velocidad": "rpm",
                "vibracion": "Hz",
                "corriente": "A",
                "tension": "V",
                "potencia": "kW",
                "medida_proceso": "u",
                "variable_manipulada": "%",
            }
            return units.get(var_type, "u")

        df["var_type"] = df["tag_id"].apply(get_type)
        df["unit_guess"] = df["var_type"].apply(get_unit)
        return df

    def _add_normalized_value(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normaliza valores al rango 0-1 basado en el baseline."""
        df = df.copy()
        df["value_norm"] = 0.5  # Default

        for tag_id in df["tag_id"].unique():
            mask = df["tag_id"] == tag_id
            if tag_id not in self._baselines:
                # Sin baseline: normaliza sobre el rango del batch actual
                vmin = df.loc[mask, "value"].min()
                vmax = df.loc[mask, "value"].max()
                rng = vmax - vmin
                if rng > 0:
                    df.loc[mask, "value_norm"] = (df.loc[mask, "value"] - vmin) / rng
            else:
                b = self._baselines[tag_id]
                rng = b["max"] - b["min"]
                if rng > 0:
                    df.loc[mask, "value_norm"] = (
                        (df.loc[mask, "value"] - b["min"]) / rng
                    ).clip(0, 1)

        return df

    def _detect_outliers(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Marca outliers usando Z-score y rango IQR del baseline.
        No elimina — marca con is_outlier=True y reduce quality.
        """
        df = df.copy()
        df["is_outlier"] = False

        for tag_id in df["tag_id"].unique():
            mask = df["tag_id"] == tag_id
            values = df.loc[mask, "value"]

            if tag_id in self._baselines:
                b = self._baselines[tag_id]
                if b["std"] > 0:
                    zscores = np.abs((values - b["mean"]) / b["std"])
                    outlier_mask = zscores > 4.0  # 4σ = outlier extremo
                    df.loc[mask & outlier_mask, "is_outlier"] = True
                    df.loc[mask & outlier_mask, "quality"] *= 0.5
            else:
                # Sin baseline: usa Z-score interno del batch
                if len(values) > 5 and values.std() > 0:
                    zscores = np.abs(stats.zscore(values))
                    outlier_mask = zscores > 3.5
                    df.loc[mask & outlier_mask.values, "is_outlier"] = True

        return df
