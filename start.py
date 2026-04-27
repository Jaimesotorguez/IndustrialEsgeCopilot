#!/usr/bin/env python3
"""
start.py — Arranque rápido del Industrial Edge Copilot
=======================================================
Ejecuta esto para arrancar el sistema completo:

    python start.py

Qué hace:
1. Verifica dependencias
2. Genera datos del simulador si no existen
3. Crea config.yaml si no existe
4. Arranca el servidor FastAPI

Accede al dashboard en: http://localhost:8000
"""

import os
import sys
import subprocess
from pathlib import Path


def check_python_version():
    if sys.version_info < (3, 11):
        print("❌ Requiere Python 3.11 o superior")
        print(f"   Versión actual: {sys.version}")
        sys.exit(1)
    print(f"✓ Python {sys.version.split()[0]}")


def check_dependencies():
    try:
        import fastapi, uvicorn, pandas, sklearn, anthropic
        print("✓ Dependencias principales instaladas")
        return True
    except ImportError as e:
        print(f"❌ Dependencia no encontrada: {e}")
        print("\n  Instala con:")
        print("  pip install -r backend/requirements.txt")
        return False


def create_config_if_missing():
    config = Path("config.yaml")
    example = Path("config.example.yaml")
    if not config.exists():
        if example.exists():
            import shutil
            shutil.copy(example, config)
            print("✓ config.yaml creado desde config.example.yaml")
            print("  ⚠ IMPORTANTE: Edita config.yaml y añade tu ANTHROPIC_API_KEY")
        else:
            # Crea configuración mínima
            config.write_text("""llm:
  provider: claude
  model: claude-sonnet-4-6
  anthropic_api_key: ""  # ← Añade tu API key aquí

data_sources:
  csv:
    enabled: true
    path: "simulator/data/"

plant:
  name: "Planta de Desarrollo"
  sector: "general"
  language: "es"

server:
  host: "0.0.0.0"
  port: 8000
  debug: true
""")
            print("✓ config.yaml mínimo creado")
    else:
        print("✓ config.yaml encontrado")


def generate_simulator_data():
    data_dir = Path("simulator/data")
    normal_file = data_dir / "tep_normal.csv"

    if not normal_file.exists():
        print("📊 Generando datos del simulador Tennessee Eastman...")
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            from simulator.generate_tep_data import generate_normal_operation, generate_fault_1
            import numpy as np
            np.random.seed(42)
            generate_normal_operation(hours=48)
            generate_fault_1(hours=24, fault_start_hour=8)
            print("✓ Datos del simulador generados")
        except Exception as e:
            print(f"⚠ No se pudieron generar datos del simulador: {e}")
            print("  El sistema arrancará sin datos históricos")
    else:
        print(f"✓ Datos del simulador encontrados ({normal_file})")


def create_data_dirs():
    for d in ["data", "simulator/data", "logs"]:
        Path(d).mkdir(parents=True, exist_ok=True)
    print("✓ Directorios de datos creados")


def check_api_key():
    """Verifica que hay API key configurada."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        print("✓ ANTHROPIC_API_KEY encontrada en variables de entorno")
        return True

    try:
        import yaml
        with open("config.yaml") as f:
            cfg = yaml.safe_load(f)
        key = cfg.get("llm", {}).get("anthropic_api_key", "")
        if key and not key.startswith("sk-ant-..."):
            print("✓ ANTHROPIC_API_KEY encontrada en config.yaml")
            return True
    except Exception:
        pass

    print("⚠ ANTHROPIC_API_KEY no configurada")
    print("  El sistema arrancará pero el chat con el agente no funcionará")
    print("  Añádela en config.yaml o como variable de entorno:")
    print("  export ANTHROPIC_API_KEY=sk-ant-...")
    return False


def start_server():
    import yaml
    cfg = {}
    if Path("config.yaml").exists():
        with open("config.yaml") as f:
            cfg = yaml.safe_load(f) or {}

    host = cfg.get("server", {}).get("host", "0.0.0.0")
    port = cfg.get("server", {}).get("port", 8000)

    print(f"\n🚀 Arrancando Industrial Edge Copilot...")
    print(f"   Dashboard: http://localhost:{port}")
    print(f"   API docs:  http://localhost:{port}/docs")
    print(f"   Ctrl+C para parar\n")

    import uvicorn
    uvicorn.run(
        "backend.api.main:app",
        host=host,
        port=port,
        reload=cfg.get("server", {}).get("debug", False),
        log_level="info",
    )


if __name__ == "__main__":
    print("=" * 50)
    print("  INDUSTRIAL EDGE COPILOT — Arranque")
    print("=" * 50)
    print()

    check_python_version()
    if not check_dependencies():
        sys.exit(1)

    create_data_dirs()
    create_config_if_missing()
    check_api_key()
    generate_simulator_data()

    print()
    start_server()
