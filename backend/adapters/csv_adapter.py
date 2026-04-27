"""
adapters/csv_adapter.py — M1: Adaptador para fuentes CSV / Historian
=====================================================================
Lee datos de ficheros CSV con formato estándar.
Compatible con el dataset Tennessee Eastman Process (TEP).

Formato esperado del CSV:
    timestamp, tag_id, value
    2024-01-01 00:00:00, XMEAS_1, 0.251
    ...

También soporta formato wide (una columna por variable):
    timestamp, XMEAS_1, XMEAS_2, ..., XMV_1, ...
    2024-01-01 00:00:00, 0.251, 48.3, ..., 62.1, ...

El adaptador detecta el formato automáticamente.
"""

import asyncio
import glob
from datetime import datetime
from pathlib import Path
from typing import Optional
import pandas as pd

from backend.core.interfaces import DataSourceAdapter, SensorReading


class CsvAdapter(DataSourceAdapter):
    """
    Lee datos de CSV en modo polling.
    En desarrollo: simula streaming leyendo el fichero progresivamente.
    En producción con historian: lee el último archivo disponible.
    """

    def __init__(
        self,
        path: str,
        polling_interval: int = 5,
        timestamp_col: str = "timestamp",
        tag_col: Optional[str] = "tag_id",     # None si formato wide
        value_col: str = "value",
    ):
        self._path = Path(path)
        self._polling_interval = polling_interval
        self._timestamp_col = timestamp_col
        self._tag_col = tag_col
        self._value_col = value_col
        self._connected = False
        self._df: Optional[pd.DataFrame] = None    # Histórico completo cargado
        self._current_index = 0                     # Para simular streaming
        self._available_files: list[str] = []

    # ── DataSourceAdapter interface ───────────────────────────────────────────

    async def connect(self) -> bool:
        """Verifica que la ruta existe y carga el histórico en memoria."""
        try:
            if self._path.is_file():
                self._available_files = [str(self._path)]
            elif self._path.is_dir():
                patterns = ["*.csv", "*.tsv", "*.txt"]
                files = []
                for p in patterns:
                    files.extend(glob.glob(str(self._path / p)))
                self._available_files = sorted(files)
            else:
                print(f"[CsvAdapter] Ruta no encontrada: {self._path}")
                return False

            if not self._available_files:
                print(f"[CsvAdapter] No hay archivos CSV en: {self._path}")
                return False

            # Carga el primer archivo disponible
            await self._load_file(self._available_files[0])
            self._connected = True
            print(f"[CsvAdapter] Conectado. {len(self._df)} filas cargadas desde {self._available_files[0]}")
            return True

        except Exception as e:
            print(f"[CsvAdapter] Error al conectar: {e}")
            return False

    async def disconnect(self) -> None:
        self._connected = False
        self._df = None
        self._current_index = 0

    async def read(self) -> list[SensorReading]:
        """
        Retorna el siguiente batch de lecturas simulando streaming.
        En producción, leer desde el historian real.
        """
        if not self._connected or self._df is None:
            return []

        # Simula polling: devuelve las filas del último intervalo
        batch_size = max(1, len(self._df) // 1000)  # ~0.1% del dataset por tick
        end = min(self._current_index + batch_size, len(self._df))
        batch = self._df.iloc[self._current_index:end]
        self._current_index = end

        # Reinicia si llega al final (loop para desarrollo)
        if self._current_index >= len(self._df):
            self._current_index = 0
            print("[CsvAdapter] Dataset reiniciado (loop de desarrollo)")

        return self._df_to_readings(batch)

    async def write(self, tag_id: str, value: float) -> bool:
        """CSV es solo lectura. En desarrollo, loguea el comando."""
        print(f"[CsvAdapter] WRITE (simulado): {tag_id} = {value}")
        return True  # Simula éxito

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def source_name(self) -> str:
        return f"csv:{self._path}"

    # ── Métodos internos ──────────────────────────────────────────────────────

    async def _load_file(self, filepath: str) -> None:
        """Carga un CSV detectando el formato automáticamente."""
        loop = asyncio.get_running_loop()
        # Carga en thread pool para no bloquear el event loop
        self._df = await loop.run_in_executor(None, self._read_csv, filepath)

    def _read_csv(self, filepath: str) -> pd.DataFrame:
        """Lee y normaliza el CSV al formato interno (long format)."""
        raw = pd.read_csv(filepath)
        raw.columns = raw.columns.str.strip().str.lower()

        ts_col = self._find_timestamp_col(raw)

        # ── Formato wide (una columna por tag) ───────────────────────────────
        # Ej: Tennessee Eastman tiene columnas XMEAS_1, XMEAS_2, ..., XMV_1...
        if self._tag_col is None or self._tag_col not in raw.columns:
            return self._wide_to_long(raw, ts_col)

        # ── Formato long (columnas: timestamp, tag_id, value) ────────────────
        df = raw[[ts_col, self._tag_col, self._value_col]].copy()
        df.columns = ["timestamp", "tag_id", "value"]
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        return df.dropna(subset=["value"])

    def _wide_to_long(self, raw: pd.DataFrame, ts_col: str) -> pd.DataFrame:
        """Convierte formato wide a long."""
        value_cols = [c for c in raw.columns if c != ts_col]
        long = raw.melt(id_vars=[ts_col], value_vars=value_cols,
                        var_name="tag_id", value_name="value")
        long = long.rename(columns={ts_col: "timestamp"})
        long["timestamp"] = pd.to_datetime(long["timestamp"])
        long["value"] = pd.to_numeric(long["value"], errors="coerce")
        return long.dropna(subset=["value"]).reset_index(drop=True)

    def _find_timestamp_col(self, df: pd.DataFrame) -> str:
        """Detecta la columna de timestamp por nombre o tipo."""
        candidates = ["timestamp", "time", "datetime", "fecha", "date", "ts"]
        for c in candidates:
            if c in df.columns:
                return c
        # Intenta detectar por tipo de dato
        for c in df.columns:
            try:
                pd.to_datetime(df[c].head(5))
                return c
            except Exception:
                continue
        raise ValueError(f"No se encontró columna de timestamp en: {list(df.columns)}")

    def _df_to_readings(self, df: pd.DataFrame) -> list[SensorReading]:
        """Convierte un DataFrame al formato interno SensorReading."""
        readings = []
        for _, row in df.iterrows():
            try:
                readings.append(SensorReading(
                    timestamp=row["timestamp"] if isinstance(row["timestamp"], datetime)
                              else pd.to_datetime(row["timestamp"]).to_pydatetime(),
                    tag_id=str(row["tag_id"]).strip(),
                    value=float(row["value"]),
                    source="csv",
                    quality=1.0,
                ))
            except Exception:
                continue
        return readings

    # ── Utilidades públicas ───────────────────────────────────────────────────

    async def load_full_historical(self) -> pd.DataFrame:
        """
        Carga todos los archivos CSV disponibles como histórico completo.
        Útil para entrenar el modelo de anomalías (M4).
        """
        if not self._available_files:
            return pd.DataFrame()

        dfs = []
        for f in self._available_files:
            try:
                df = self._read_csv(f)
                dfs.append(df)
            except Exception as e:
                print(f"[CsvAdapter] Error cargando {f}: {e}")

        if not dfs:
            return pd.DataFrame()

        combined = pd.concat(dfs, ignore_index=True)
        combined = combined.sort_values("timestamp").reset_index(drop=True)
        print(f"[CsvAdapter] Histórico completo: {len(combined)} filas, "
              f"{combined['tag_id'].nunique()} variables")
        return combined

    def get_available_tags(self) -> list[str]:
        """Lista de variables disponibles en el dataset."""
        if self._df is None:
            return []
        return sorted(self._df["tag_id"].unique().tolist())

    def get_summary(self) -> dict:
        """Resumen del dataset para mostrar en el dashboard."""
        if self._df is None:
            return {}
        return {
            "rows": len(self._df),
            "tags": self._df["tag_id"].nunique(),
            "from": str(self._df["timestamp"].min()),
            "to": str(self._df["timestamp"].max()),
            "source": str(self._path),
        }
