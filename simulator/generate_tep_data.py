"""
simulator/generate_tep_data.py — Generador de datos Tennessee Eastman
======================================================================
Genera datos sintéticos similares al proceso Tennessee Eastman (TEP)
para desarrollo y pruebas SIN necesitar el dataset original.

Si tienes el dataset real de Kaggle, úsalo directamente con CsvAdapter.
Este script es un fallback para poder arrancar sin descargar nada.

Variables simuladas (subset del TEP real):
  XMEAS_1  a XMEAS_22  : Variables de proceso medidas
  XMV_1    a XMV_11    : Variables manipuladas (actuadores)

Uso:
    python simulator/generate_tep_data.py
    → Genera simulator/data/tep_normal.csv (operación normal, 48h)
    → Genera simulator/data/tep_fault1.csv (fallo IDV(1) — step en feed A)
"""

import os
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path


# ── Parámetros del proceso ────────────────────────────────────────────────────

PROCESS_PARAMS = {
    # Variable: (media, std, min, max)
    "XMEAS_1":  (0.251, 0.010, 0.22,  0.28),   # A feed (stream 1)
    "XMEAS_2":  (3664, 150,    3200,   4100),    # D feed (stream 2)
    "XMEAS_3":  (4509, 100,    4200,   4800),    # E feed (stream 3)
    "XMEAS_4":  (9.35, 0.5,   8.0,    11.0),    # Total feed (stream 4)
    "XMEAS_5":  (26.9, 1.0,   23.0,   31.0),    # Recycle flow (stream 8)
    "XMEAS_6":  (42.3, 2.0,   36.0,   50.0),    # Reactor feed rate
    "XMEAS_7":  (2705, 50,    2500,   2900),    # Reactor pressure
    "XMEAS_8":  (75.0, 2.0,   68.0,   82.0),    # Reactor level
    "XMEAS_9":  (120.4, 1.0, 116.0,  125.0),   # Reactor temperature
    "XMEAS_10": (336.8, 8.0, 310.0,  365.0),   # Purge rate
    "XMEAS_11": (80.1, 2.0,   73.0,   88.0),    # Separator temperature
    "XMEAS_12": (50.0, 3.0,   42.0,   58.0),    # Separator level
    "XMEAS_13": (3102, 80,   2900,   3300),    # Separator pressure
    "XMEAS_14": (26.9, 1.5,   22.0,   32.0),    # Separator underflow
    "XMEAS_15": (65.7, 2.0,   59.0,   73.0),    # Stripper level
    "XMEAS_16": (18.8, 1.0,   15.0,   23.0),    # Stripper pressure
    "XMEAS_17": (50.0, 2.0,   44.0,   56.0),    # Stripper underflow
    "XMEAS_18": (65.7, 1.5,   60.0,   72.0),    # Stripper temperature
    "XMEAS_19": (230.1, 5.0, 218.0,  242.0),   # Stripper steam flow
    "XMEAS_20": (341.4, 6.0, 325.0,  358.0),   # Compressor work
    "XMEAS_21": (94.6, 1.0,   91.0,   98.0),    # Reactor coolant temp
    "XMEAS_22": (77.3, 1.0,   73.0,   82.0),    # Separator coolant temp
    "XMV_1":    (62.9, 3.0,   50.0,   78.0),    # D feed valve
    "XMV_2":    (53.3, 2.0,   44.0,   63.0),    # E feed valve
    "XMV_3":    (26.9, 2.0,   20.0,   35.0),    # A feed valve
    "XMV_4":    (60.9, 3.0,   50.0,   72.0),    # Total feed valve
    "XMV_5":    (22.2, 1.5,   16.0,   29.0),    # Compressor recycle
    "XMV_6":    (40.1, 2.0,   33.0,   48.0),    # Purge valve
    "XMV_7":    (38.1, 2.0,   31.0,   46.0),    # Separator liquid valve
    "XMV_8":    (46.5, 2.5,   38.0,   56.0),    # Stripper liquid valve
    "XMV_9":    (47.4, 2.0,   40.0,   56.0),    # Stripper steam valve
    "XMV_10":   (41.1, 2.0,   34.0,   49.0),    # Reactor cooling valve
    "XMV_11":   (18.1, 1.5,   13.0,   24.0),    # Condenser cooling valve
}

# Correlaciones entre variables (simplificado)
CORRELATIONS = {
    "XMEAS_9": ["XMEAS_21", "XMV_10"],   # Temp reactor ~ cooling
    "XMEAS_7": ["XMEAS_13", "XMV_6"],    # Presión reactor ~ separador ~ purga
    "XMEAS_8": ["XMEAS_15", "XMV_7"],    # Nivel reactor ~ nivel separador
}


def generate_normal_operation(
    hours: int = 48,
    sample_interval_seconds: int = 180,
    output_path: str = "simulator/data/tep_normal.csv",
) -> pd.DataFrame:
    """
    Genera datos de operación normal del proceso TEP.
    Incluye variaciones naturales, deriva gradual y ciclos.
    """
    n_samples = int(hours * 3600 / sample_interval_seconds)
    start = datetime(2024, 1, 1, 0, 0, 0)
    timestamps = [start + timedelta(seconds=i * sample_interval_seconds)
                  for i in range(n_samples)]

    data = {"timestamp": timestamps}
    t = np.linspace(0, hours * 2 * np.pi, n_samples)

    for var, (mean, std, vmin, vmax) in PROCESS_PARAMS.items():
        # Componente aleatoria base
        noise = np.random.normal(0, std * 0.5, n_samples)
        # Deriva suave (simula cambios graduales normales)
        drift = std * 0.3 * np.sin(t / 24)
        # Ciclos de turno (8h)
        cycle = std * 0.2 * np.sin(t * 3)
        values = mean + noise + drift + cycle
        values = np.clip(values, vmin, vmax)
        data[var] = np.round(values, 4)

    df = pd.DataFrame(data)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"[Simulator] Normal operation: {len(df)} muestras → {output_path}")
    return df


def generate_fault_1(
    hours: int = 24,
    fault_start_hour: int = 8,
    sample_interval_seconds: int = 180,
    output_path: str = "simulator/data/tep_fault1.csv",
) -> pd.DataFrame:
    """
    Genera datos con Fallo IDV(1): step en composición del feed A.
    El sistema debe detectar este fallo antes de que cause una parada.

    Comportamiento esperado del sistema:
    - Horas 0-8: operación normal
    - Hora 8: inicio del fallo (step en XMEAS_1)
    - Horas 8-12: propagación a temperatura y presión del reactor
    - Hora 12+: condición crítica si no se actúa
    """
    n_samples = int(hours * 3600 / sample_interval_seconds)
    fault_start_idx = int(fault_start_hour * 3600 / sample_interval_seconds)
    start = datetime(2024, 1, 3, 0, 0, 0)
    timestamps = [start + timedelta(seconds=i * sample_interval_seconds)
                  for i in range(n_samples)]

    data = {"timestamp": timestamps}
    t = np.linspace(0, hours * 2 * np.pi, n_samples)

    for var, (mean, std, vmin, vmax) in PROCESS_PARAMS.items():
        noise = np.random.normal(0, std * 0.5, n_samples)
        values = mean + noise + std * 0.2 * np.sin(t / 24)

        # Aplicar fallo IDV(1) a partir del índice de fallo
        if var == "XMEAS_1":
            # Step en feed A: sube un 20% y sigue subiendo
            fault_ramp = np.zeros(n_samples)
            fault_ramp[fault_start_idx:] = np.linspace(
                0, mean * 0.25, n_samples - fault_start_idx
            )
            values += fault_ramp

        elif var == "XMEAS_9" and fault_start_idx < n_samples:
            # Temperatura reactor: sube gradualmente tras el fallo
            delay = int(fault_start_idx * 1.2)
            if delay < n_samples:
                fault_effect = np.zeros(n_samples)
                fault_effect[delay:] = np.linspace(0, 8, n_samples - delay)
                values += fault_effect

        elif var == "XMEAS_7" and fault_start_idx < n_samples:
            # Presión reactor: oscila más
            delay = int(fault_start_idx * 1.5)
            if delay < n_samples:
                fault_effect = np.zeros(n_samples)
                fault_effect[delay:] = np.random.normal(0, std * 2, n_samples - delay)
                values += fault_effect

        values = np.clip(values, vmin, vmax * 1.1)  # Permite superar límites (fallo)
        data[var] = np.round(values, 4)

    # Añade etiqueta de fallo (útil para evaluar el detector)
    fault_label = np.zeros(n_samples, dtype=int)
    fault_label[fault_start_idx:] = 1
    data["fault_active"] = fault_label
    data["fault_type"] = ["normal"] * fault_start_idx + ["IDV1"] * (n_samples - fault_start_idx)

    df = pd.DataFrame(data)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"[Simulator] Fault IDV(1): {len(df)} muestras → {output_path}")
    print(f"  Normal: {fault_start_idx} muestras | Con fallo: {n_samples - fault_start_idx} muestras")
    return df


if __name__ == "__main__":
    print("Generando datos del simulador Tennessee Eastman...")
    np.random.seed(42)
    generate_normal_operation(hours=48)
    generate_fault_1(hours=24, fault_start_hour=8)
    print("\n✓ Datos generados en simulator/data/")
    print("  Siguiente paso: arrancar el backend con 'python -m backend.api.main'")
