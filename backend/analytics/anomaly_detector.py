"""
analytics/anomaly_detector.py — M4: Detección de anomalías
===========================================================
Usa Isolation Forest (scikit-learn) para detectar anomalías
en series temporales multivariables sin necesidad de etiquetas.

Por qué Isolation Forest:
- No supervisado: no necesita datos de fallos etiquetados
- Rápido para inferencia en tiempo real
- Robusto con datos industriales ruidosos
- Explicable: el score tiene significado directo
- Se entrena en minutos con el histórico del TEP

Flujo:
1. fit(historical_df)  → entrena sobre operación normal
2. detect(batch_df)    → detecta anomalías en nuevos datos
3. Si score > threshold → dispara evento → escala a Claude (M9)
"""

import joblib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from backend.core.interfaces import AnomalyDetector, AnomalyEvent, Severity, SensorReading


class IsolationForestDetector(AnomalyDetector):
    """
    Detector de anomalías basado en Isolation Forest multivariable.

    Estrategia:
    - Entrena un modelo global con todas las variables como features
    - También mantiene modelos univariables por tag para localizar el fallo
    - El score global decide si hay anomalía
    - Los scores por variable identifican cuáles están fuera de rango
    """

    def __init__(
        self,
        contamination: float = 0.05,   # % de anomalías esperadas en el histórico
        anomaly_threshold: float = 0.7, # Score mínimo para disparar evento (0-1)
        n_estimators: int = 100,
        model_path: Optional[str] = None,
    ):
        self._contamination = contamination
        self._threshold = anomaly_threshold
        self._n_estimators = n_estimators
        self._model_path = model_path

        self._model: Optional[IsolationForest] = None
        self._scaler: Optional[StandardScaler] = None
        self._feature_cols: list[str] = []     # columnas usadas para el modelo
        self._fitted = False
        self._stats = {
            "total_anomalies_detected": 0,
            "last_anomaly_at": None,
            "fit_date": None,
            "n_training_samples": 0,
        }

    # ── AnomalyDetector interface ─────────────────────────────────────────────

    def fit(self, historical_data: pd.DataFrame) -> None:
        """
        Entrena el modelo con datos históricos de operación normal.
        historical_data debe estar en formato long (timestamp, tag_id, value).
        """
        if historical_data.empty:
            print("[AnomalyDetector] Sin datos para entrenar")
            return

        # Pivota a formato wide: una columna por variable
        wide = self._to_wide(historical_data)
        if wide.empty or len(wide.columns) < 2:
            print("[AnomalyDetector] Datos insuficientes para entrenar")
            return

        self._feature_cols = list(wide.columns)
        X = wide.values

        # Escala los datos
        self._scaler = StandardScaler()
        X_scaled = self._scaler.fit_transform(X)

        # Entrena Isolation Forest
        self._model = IsolationForest(
            n_estimators=self._n_estimators,
            contamination=self._contamination,
            random_state=42,
            n_jobs=-1,   # Usa todos los cores disponibles
        )
        self._model.fit(X_scaled)
        self._fitted = True

        self._stats["fit_date"] = datetime.now().isoformat()
        self._stats["n_training_samples"] = len(X)

        print(f"[AnomalyDetector] Modelo entrenado: {len(X)} muestras, "
              f"{len(self._feature_cols)} variables")

        # Guarda en disco si se especificó ruta
        if self._model_path:
            self.save(self._model_path)

    def detect(self, current_data: pd.DataFrame) -> list[AnomalyEvent]:
        """
        Detecta anomalías en el batch actual.
        Retorna lista de AnomalyEvent — vacía si todo está normal.
        """
        if not self._fitted or current_data.empty:
            return []

        wide = self._to_wide(current_data)
        if wide.empty:
            return []

        # Alinea columnas con las del entrenamiento
        for col in self._feature_cols:
            if col not in wide.columns:
                wide[col] = 0.0
        wide = wide[self._feature_cols]

        X = self._scaler.transform(wide.fillna(0).values)

        # Score: -1 = anomalía, 1 = normal (Isolation Forest estándar)
        raw_scores = self._model.decision_function(X)
        predictions = self._model.predict(X)

        # Convierte a score 0-1 (0=normal, 1=anomalía severa)
        # decision_function retorna valores negativos para anomalías
        anomaly_scores = self._normalize_scores(raw_scores)

        events = []
        for i, (score, pred) in enumerate(zip(anomaly_scores, predictions)):
            if score >= self._threshold:
                # Identifica qué variables contribuyen más a la anomalía
                guilty_tags = self._identify_guilty_tags(wide.iloc[i])

                # Timestamp del batch (usa el más reciente disponible)
                ts = self._extract_timestamp(current_data)

                event = AnomalyEvent(
                    timestamp=ts,
                    tag_ids=guilty_tags,
                    anomaly_score=float(score),
                    severity=self._score_to_severity(score),
                    description=self._build_description(guilty_tags, score),
                    raw_values={col: float(wide.iloc[i][col])
                                for col in guilty_tags if col in wide.columns},
                )
                events.append(event)
                self._stats["total_anomalies_detected"] += 1
                self._stats["last_anomaly_at"] = ts.isoformat()

        return events

    def get_anomaly_score(self, reading: SensorReading) -> float:
        """Score de anomalía para una sola lectura (univariable)."""
        if not self._fitted or reading.tag_id not in self._feature_cols:
            return 0.0

        row = {col: 0.0 for col in self._feature_cols}
        row[reading.tag_id] = reading.value
        X = self._scaler.transform([list(row.values())])
        raw = self._model.decision_function(X)[0]
        scores = self._normalize_scores(np.array([raw]))
        return float(scores[0])

    # ── Persistencia ──────────────────────────────────────────────────────────

    def save(self, path: str) -> None:
        """Guarda el modelo entrenado en disco."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "model": self._model,
            "scaler": self._scaler,
            "feature_cols": self._feature_cols,
            "threshold": self._threshold,
            "stats": self._stats,
        }, path)
        print(f"[AnomalyDetector] Modelo guardado en {path}")

    def load(self, path: str) -> bool:
        """Carga un modelo previamente entrenado."""
        try:
            data = joblib.load(path)
            self._model = data["model"]
            self._scaler = data["scaler"]
            self._feature_cols = data["feature_cols"]
            self._threshold = data["threshold"]
            self._stats = data.get("stats", self._stats)
            self._fitted = True
            print(f"[AnomalyDetector] Modelo cargado desde {path}")
            return True
        except Exception as e:
            print(f"[AnomalyDetector] Error cargando modelo: {e}")
            return False

    def get_stats(self) -> dict:
        return {**self._stats, "fitted": self._fitted,
                "n_features": len(self._feature_cols),
                "threshold": self._threshold}

    # ── Métodos internos ──────────────────────────────────────────────────────

    def _to_wide(self, df: pd.DataFrame) -> pd.DataFrame:
        """Convierte formato long a wide para el modelo ML."""
        try:
            if "tag_id" not in df.columns or "value" not in df.columns:
                return pd.DataFrame()

            # Agrupa por timestamp y pivota
            if "timestamp" in df.columns:
                wide = df.pivot_table(
                    index="timestamp",
                    columns="tag_id",
                    values="value",
                    aggfunc="mean"
                )
            else:
                wide = df.pivot_table(
                    columns="tag_id",
                    values="value",
                    aggfunc="mean"
                )

            return wide.ffill().fillna(0)
        except Exception as e:
            print(f"[AnomalyDetector] Error en pivot: {e}")
            return pd.DataFrame()

    def _normalize_scores(self, raw_scores: np.ndarray) -> np.ndarray:
        """
        Normaliza los scores del Isolation Forest a rango 0-1.
        decision_function: valores negativos = más anómalos.
        """
        # Clipa al rango típico [-0.5, 0.5]
        clipped = np.clip(raw_scores, -0.5, 0.5)
        # Invierte y normaliza: negativo → alto score de anomalía
        normalized = (0.5 - clipped) / 1.0
        return np.clip(normalized, 0, 1)

    def _identify_guilty_tags(self, row: pd.Series, top_n: int = 5) -> list[str]:
        """
        Identifica los tags más responsables de la anomalía.
        Usa la desviación normalizada de cada variable.
        """
        if self._scaler is None:
            return list(row.index[:top_n])

        scaled_row = self._scaler.transform([row.values])[0]
        # Los valores más alejados del centro son los más "culpables"
        deviations = np.abs(scaled_row)
        top_indices = np.argsort(deviations)[-top_n:][::-1]
        return [self._feature_cols[i] for i in top_indices
                if i < len(self._feature_cols)]

    def _score_to_severity(self, score: float) -> Severity:
        if score >= 0.9:
            return Severity.CRITICAL
        if score >= 0.8:
            return Severity.HIGH
        if score >= 0.7:
            return Severity.MEDIUM
        return Severity.LOW

    def _build_description(self, tags: list[str], score: float) -> str:
        tag_str = ", ".join(tags[:3])
        pct = int(score * 100)
        return f"Anomalía detectada (score {pct}%) en variables: {tag_str}"

    def _extract_timestamp(self, df: pd.DataFrame) -> datetime:
        if "timestamp" in df.columns:
            ts = df["timestamp"].max()
            if pd.notna(ts):
                return ts if isinstance(ts, datetime) else pd.to_datetime(ts).to_pydatetime()
        return datetime.now()
