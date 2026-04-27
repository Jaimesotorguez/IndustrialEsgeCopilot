# STATUS — INDUSTRIAL EDGE COPILOT

> Actualiza este archivo al TERMINAR cada sesión de trabajo.
> Es lo primero que lee cualquier persona o IA al arrancar.

---

## ESTADO ACTUAL

**Fecha:** 26/04/2026
**Fase:** Backend completo — falta frontend React conectado
**Siguiente acción inmediata:** Probar arranque con `python start.py`, luego construir frontend React

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
| M5/M9/M11 Claude LLM | ✅ Hecho | `backend/llm/claude_provider.py` |
| M6 Interacción | ✅ Hecho | `backend/interaction/interaction_manager.py` |
| M8 Observer RT | ✅ Hecho | `backend/observer/observer.py` |
| M9 Reasoning Engine | ✅ Hecho | `backend/analytics/reasoning_engine.py` |
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

---

## PARA ARRANCAR AHORA MISMO

```bash
# 1. Instalar dependencias
cd backend && pip install -r requirements.txt && cd ..

# 2. Configurar API key
cp config.example.yaml config.yaml
# Editar config.yaml → añadir anthropic_api_key

# 3. Arrancar
python start.py

# El sistema:
# - Genera datos TEP automáticamente si no existen
# - Entrena Isolation Forest sobre el histórico
# - Aprende grafo de proceso
# - Arranca en http://localhost:8000
# - API docs en http://localhost:8000/docs
```

---

## ARQUITECTURA DEL SISTEMA (cómo se conecta todo)

```
start.py
  └── AppContainer.build() + start()
        ├── M12 SqliteMemoryStore       (data/copilot.db)
        ├── M13 SafetyValidatorImpl     (config/safety_limits.json)
        ├── M3/M7 ProcessGraph          (data/process_graph.json)
        ├── LLM ClaudeProvider          (Claude API)
        ├── M1 IngestionManager
        │     └── CsvAdapter            (simulator/data/)
        │     └── OpcUaAdapter          (si habilitado en config)
        │     └── ModbusAdapter         (si habilitado en config)
        ├── M2 SensorNormalizer
        ├── M4 IsolationForestDetector  (data/anomaly_model.joblib)
        ├── M9 ReasoningEngine          (usa LLM + ProcessGraph + Memory)
        ├── M10 ActionRecommenderImpl   (usa LLM + Validator + Memory)
        ├── M6 InteractionManager       (usa ProcessGraph + LLM)
        └── M8 RealtimeObserver         (bucle principal)
              ↓ on_anomaly()
              AppContainer._handle_anomaly()
                ├── M9.diagnose() → Claude API
                ├── M10.recommend() → acción pendiente
                └── M6.generate_question() → si confianza < 0.75

FastAPI (api/main.py)
  ├── WebSocket /ws → broadcast de eventos en RT
  ├── GET  /api/status
  ├── GET  /api/readings
  ├── GET  /api/events
  ├── GET/POST /api/commands
  ├── POST /api/emergency-stop
  ├── POST /api/chat
  ├── GET  /api/process-model
  └── GET  /api/history
```

---

## PENDIENTE — PRÓXIMAS SESIONES

### Prioritario
- [ ] Probar arranque completo y corregir errores
- [ ] Frontend React con WebSocket conectado al backend
  - Componente Monitor (reemplaza mockup HTML)
  - Componente Chat conectado a /api/chat
  - Componente Comandos con aprobación real
  - Componente Modelo de Proceso (grafo visual)

### Mejoras backend (fase 2)
- [ ] Tests unitarios por módulo (usar pytest + datos sintéticos)
- [ ] OpenAI provider (llm/openai_provider.py)
- [ ] Gemini provider (llm/gemini_provider.py)
- [ ] Ollama provider para uso local gratis
- [ ] DuckDB para analytics histórico (M12 avanzado)
- [ ] ChromaDB para RAG semántico (mejora M9)
- [ ] MQTT adapter

---

## DECISIONES TÉCNICAS

| Fecha | Decisión | Razonamiento |
|-------|----------|--------------|
| 26/04/2026 | AppContainer como único punto de cableado | Evita acoplamiento entre módulos, facilita testing |
| 26/04/2026 | SQLite sin servidor para MVP | Zero-config, funciona en Raspberry Pi, migración trivial |
| 26/04/2026 | Isolation Forest para anomalías | No supervisado, rápido, explicable, robusto con datos industriales |
| 26/04/2026 | Contexto comprimido en Claude: max 12 tags, 3 eventos pasados | Control de coste: ~€15-30/mes por fábrica |
| 26/04/2026 | LLM agnóstico via factory | Cambiar de Claude a GPT = 1 línea en config.yaml |
| 26/04/2026 | Validación de seguridad en dos puntos: al proponer Y al ejecutar | Doble seguridad para acciones críticas |

---

## CÓMO ACTUALIZAR ESTE ARCHIVO

Al terminar cada sesión:
1. Actualiza tabla de módulos (⬜ → 🟡 → ✅)
2. Mueve items de Pendiente a Hecho
3. Añade decisiones técnicas tomadas
4. Actualiza "Siguiente acción inmediata"

**Commit siempre:** `docs: update STATUS.md - [qué se hizo]`
