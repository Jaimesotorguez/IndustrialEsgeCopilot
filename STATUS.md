# STATUS — INDUSTRIAL EDGE COPILOT

> Actualiza este archivo al TERMINAR cada sesión de trabajo.
> Es lo primero que lee cualquier persona o IA al arrancar.

---

## ESTADO ACTUAL

**Fecha:** 27/04/2026
**Fase:** Arquitectura iterativa implementada — pendiente tests y frontend conectado
**Siguiente acción inmediata:** Probar arranque con `python start.py` + conectar frontend React

---

## PROGRESO POR MÓDULOS

| Módulo | Estado | Archivo |
|--------|--------|---------|
| M1 Ingesta CSV | ✅ Hecho | `backend/adapters/csv_adapter.py` |
| M1 Ingesta OPC-UA | ✅ Hecho | `backend/adapters/opcua_adapter.py` |
| M1 Ingesta Modbus | ✅ Hecho | `backend/adapters/modbus_adapter.py` |
| M1 Manager | ✅ Hecho | `backend/adapters/ingestion_manager.py` |
| M2 Normalización | ✅ Hecho | `backend/normalizer/normalizer.py` |
| M3/M7 Grafo proceso | ✅ Hecho | `backend/process_model/process_graph.py` |
| M4 Anomaly Detection | ✅ Hecho | `backend/analytics/anomaly_detector.py` |
| **FeatureExtractor** | ✅ Hecho | `backend/analytics/feature_extractor.py` |
| **HypothesisEngine** | ✅ Hecho | `backend/inference/hypothesis_engine.py` |
| **Phase1 Understanding** | ✅ Hecho | `backend/phases/phase1_understand.py` |
| **Phase2 Learning** | ✅ Hecho | `backend/phases/phase2_learn.py` |
| M5/M9/M11 Claude LLM | ✅ Hecho | `backend/llm/claude_provider.py` |
| M6 Interacción | ✅ Hecho | `backend/interaction/interaction_manager.py` |
| M8 Observer RT | ✅ Hecho | `backend/observer/observer.py` |
| M9 Reasoning Engine | ✅ Hecho (refactorizado) | `backend/analytics/reasoning_engine.py` |
| M10 Recomendación | ✅ Hecho | `backend/recommender/recommender.py` |
| M12 Memoria SQLite | ✅ Hecho | `backend/memory/memory_store.py` |
| M13 Validación | ✅ Hecho | `backend/validator/safety_validator.py` |
| LLM Factory (agnóstico) | ✅ Hecho | `backend/llm/provider_factory.py` |
| AppContainer (cableado) | ✅ Hecho | `backend/core/app.py` |
| API FastAPI + WebSocket | ✅ Hecho | `backend/api/main.py` |
| Simulador TEP | ✅ Hecho | `simulator/generate_tep_data.py` |
| Script arranque | ✅ Hecho | `start.py` |
| Mockup dashboard HTML | ✅ Hecho | `docs/mockup/dashboard.html` |
| Frontend React real | ⬜ Por hacer | `frontend/` |
| Tests unitarios | ⬜ Por hacer | `tests/` |
| OpenAI/Gemini/Ollama providers | ⬜ Por hacer | `backend/llm/` |
| MQTT adapter | ⬜ Por hacer | `backend/adapters/mqtt_adapter.py` |

---

## ARQUITECTURA ITERATIVA (nueva — 3 fases)

### Fase 1 — Entendimiento del proceso (OFFLINE, una vez)
```bash
python -m backend.phases.phase1_understand simulator/data/tep_normal.csv
# Output: data/process_understanding.json
# - Clasifica variables por tipo (temperatura, presión, RPM...)
# - Detecta modos de operación (nominal, arranque, parada)
# - Agrupa variables por equipo (correlación > 0.80)
# - Con LLM: identifica tipo de proceso industrial
```

### Fase 2 — Aprendizaje profundo del histórico (OFFLINE, periódico)
```bash
python -m backend.phases.phase2_learn simulator/data/tep_normal.csv
# Output: data/learned_model.json
# - Baselines robustos por variable (media, std, percentiles, IQR)
# - Correlaciones validadas estadísticamente (p < 0.01)
# - Lags causales con cross-correlación (hasta 20 muestras)
# - Hipótesis recurrentes en ventanas históricas
# - Grafo de proceso con confianza estadística
```

### Fase 3 — Observación en tiempo real (ONLINE, continuo)
```
RealtimeObserver → AnomalyEvent
  → FeatureExtractor (€0) → features estructuradas
  → HypothesisEngine: genera hipótesis (LLM) → testa con Python (€0) → itera
  → Diagnosis con evidencia estadística
  → ActionRecommender → RecommendedAction (pendiente aprobación humana)
```

### Motor de hipótesis standalone
```bash
python -m backend.inference.hypothesis_engine simulator/data/tep_normal.csv
# Testa el bucle generar→evaluar→clasificar sin el sistema completo
```

---

## PARA ARRANCAR AHORA MISMO

```bash
# 1. Instalar dependencias
cd backend && pip install -r requirements.txt && cd ..

# 2. Configurar API key
cp config.example.yaml config.yaml
# Editar config.yaml → añadir anthropic_api_key

# 3. (Opcional) Fase offline antes de arrancar en RT
python -m backend.phases.phase1_understand simulator/data/tep_normal.csv
python -m backend.phases.phase2_learn simulator/data/tep_normal.csv

# 4. Arrancar
python start.py
# http://localhost:8000
# http://localhost:8000/docs
```

---

## PENDIENTE — PRÓXIMAS SESIONES

### Prioritario
- [ ] Probar arranque completo (`python start.py`) y corregir errores de integración
- [ ] Cargar `learned_model.json` en Observer y ReasoningEngine al arrancar
- [ ] Frontend React con WebSocket conectado al backend
  - Componente Monitor (reemplaza mockup HTML)
  - Componente Chat conectado a /api/chat
  - Componente Comandos con aprobación real
  - Componente Modelo de Proceso (grafo visual)
- [ ] Tests unitarios por módulo (pytest + datos sintéticos)

### Mejoras backend
- [ ] OpenAI provider (`backend/llm/openai_provider.py`)
- [ ] Gemini provider (`backend/llm/gemini_provider.py`)
- [ ] Ollama provider para uso local gratis
- [ ] DuckDB para analytics histórico
- [ ] ChromaDB para RAG semántico
- [ ] MQTT adapter
- [ ] Endpoint API para lanzar Phase1/Phase2 desde el frontend

---

## DECISIONES TÉCNICAS

| Fecha | Decisión | Razonamiento |
|-------|----------|--------------|
| 26/04/2026 | AppContainer como único punto de cableado | Evita acoplamiento entre módulos, facilita testing |
| 26/04/2026 | SQLite sin servidor para MVP | Zero-config, funciona en Raspberry Pi, migración trivial |
| 26/04/2026 | Isolation Forest para anomalías | No supervisado, rápido, explicable, robusto con datos industriales |
| 26/04/2026 | Contexto comprimido en Claude: max 15 vars via FeatureExtractor | Control de coste: ~€15-30/mes por fábrica |
| 26/04/2026 | LLM agnóstico via factory | Cambiar de Claude a GPT = 1 línea en config.yaml |
| 26/04/2026 | Validación de seguridad en dos puntos: al proponer Y al ejecutar | Doble seguridad para acciones críticas |
| 27/04/2026 | HypothesisEngine iterativo en lugar de one-shot LLM | Diagnóstico con evidencia estadística verificable, no inventado |
| 27/04/2026 | FeatureExtractor como capa entre datos y LLM | LLM nunca recibe datos crudos; solo features comprimidas (€0) |
| 27/04/2026 | Fases 1 y 2 offline e independientemente testeables | Módulo a módulo, sin necesidad de datos RT para desarrollar |
| 27/04/2026 | Hipótesis heurísticas como fallback sin LLM | Sistema funciona sin API key; LLM solo mejora la semántica |

---

## CÓMO ACTUALIZAR ESTE ARCHIVO

Al terminar cada sesión:
1. Actualiza tabla de módulos (⬜ → 🟡 → ✅)
2. Mueve items de Pendiente a Hecho
3. Añade decisiones técnicas tomadas
4. Actualiza "Siguiente acción inmediata"

**Commit siempre:** `docs: update STATUS.md - [qué se hizo]`
