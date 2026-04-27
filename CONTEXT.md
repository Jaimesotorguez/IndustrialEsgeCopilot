# INDUSTRIAL EDGE COPILOT — CONTEXTO COMPLETO DEL PROYECTO

> **Este archivo es el punto de entrada para cualquier persona o IA que trabaje en este proyecto.**
> Léelo entero antes de tocar cualquier cosa. Contiene todo lo que necesitas saber.

---

## QUÉ ES ESTE PRODUCTO

**Industrial Edge Copilot** es un agente IA que actúa como copiloto para operarios de planta industrial.

Se conecta a los datos existentes de cualquier fábrica (SCADA, historian, sensores), aprende solo el comportamiento del proceso sin configuración previa, detecta anomalías antes de que ocurran, y propone acciones concretas que el operario aprueba con un clic.

**El agente propone. El humano decide siempre. El sistema ejecuta.**

No sustituye al ingeniero — amplifica su capacidad.

---

## EL PROBLEMA QUE RESUELVE

Una parada no planificada en una fábrica cuesta entre €5.000 y €50.000 por hora dependiendo del sector.
Los sistemas actuales (Siemens, ABB, Aveva) cuestan €80k-500k/año y tardan meses en implementarse.
No hay nada en el mercado que:
- Se conecte en horas sin configuración
- Aprenda el proceso solo
- Sea conversacional y accesible para el operario

---

## A QUIÉN SE VENDE

**Cliente objetivo MVP:** Plantas industriales medianas (50-500 empleados) en sectores:
1. Alimentación y bebidas (ciclos repetitivos, fácil medir ROI)
2. Farmacéutica (alta regulación, muy sensibles a paradas)
3. Automoción - tier 2/3 (no los grandes, los proveedores)

**Decisor de compra:** Director de Operaciones o Jefe de Mantenimiento

**Precio:** €1.500-3.000/mes por línea de producción

---

## ARQUITECTURA DEL SISTEMA — VISIÓN GENERAL

```
FUENTES DE DATOS          EDGE (Raspberry Pi / Mini PC)         CLOUD / API
─────────────────         ──────────────────────────────        ────────────
OPC-UA (máquinas)    →    M1 Ingesta                            Claude API
Modbus (legacy)      →    M2 Normalización          →  →  →    (razonamiento)
MQTT (IoT)           →    M3 Modelo de proceso
CSV / Historian      →    M4 Detección anomalías
                          M8 Observación RT
                                ↓ (solo si hay evento)
                          M5 Hipótesis
                          M9 Diagnóstico            → Claude API
                          M10 Recomendación         → Aprobación humana
                                ↓ (si aprobado)
                          Escritura OPC-UA/Modbus → PLC → Máquina
```

**Principio de coste:** Claude API solo se llama cuando hay un evento relevante detectado por los modelos ML locales. Coste estimado: €15-30/mes por fábrica. Irrelevante sobre un ticket de €2.000+/mes.

---

## LOS 13 MÓDULOS

| ID | Nombre | Descripción corta | Estado |
|----|--------|-------------------|--------|
| M1 | Ingesta Multimodal | Lee OPC-UA, Modbus, MQTT, CSV, PDF | ⬜ Por hacer |
| M2 | Normalización | Limpia y estandariza datos | ⬜ Por hacer |
| M3 | Modelado de Proceso | Aprende la estructura de la planta solo | ⬜ Por hacer |
| M4 | Análisis Histórico | Isolation Forest, detección de patrones | ⬜ Por hacer |
| M5 | Generación de Hipótesis | Claude API genera hipótesis con contexto comprimido | ⬜ Por hacer |
| M6 | Interacción Humano-IA | Preguntas mínimas al operario, aprobación de comandos | ⬜ Por hacer |
| M7 | Construcción de Conocimiento | Grafo de proceso NetworkX + JSON | ⬜ Por hacer |
| M8 | Observación RT | Bucle de monitorización continua, dispara eventos | ⬜ Por hacer |
| M9 | Razonamiento Operativo | Diagnóstico con Claude API + contexto quirúrgico | ⬜ Por hacer |
| M10 | Recomendación y Control | Propone acción → humano aprueba → PLC ejecuta | ⬜ Por hacer |
| M11 | Explicación (Chat) | Interfaz conversacional con el operario | ⬜ Por hacer |
| M12 | Memoria | Persistencia de conocimiento entre sesiones | ⬜ Por hacer |
| M13 | Validación | Capa de seguridad transversal | ⬜ Por hacer |

---

## STACK TECNOLÓGICO

### Backend (Python)
- **FastAPI** — servidor principal, WebSocket, REST API
- **asyncua** — protocolo OPC-UA (leer Y escribir en PLCs)
- **pymodbus** — protocolo Modbus TCP (máquinas legacy)
- **paho-mqtt** — protocolo MQTT (IoT moderno)
- **pandas + scipy** — normalización y análisis de series temporales
- **scikit-learn** — Isolation Forest para detección de anomalías
- **Prophet** — forecasting de comportamiento esperado
- **NetworkX** — grafo de proceso (relaciones entre variables/equipos)
- **ChromaDB** — vector store local para búsqueda semántica (RAG)
- **DuckDB** — SQL analítico sobre datos históricos sin servidor
- **SQLite** — eventos, diagnósticos, log de auditoría
- **Pydantic v2** — contratos de datos entre módulos
- **tenacity** — circuit breaker y retry
- **Redis (Docker)** — cola de eventos en tiempo real

### LLM (agnóstico por diseño)
- **Claude API** como proveedor por defecto (claude-sonnet)
- Arquitectura: clase abstracta `LLMProvider` con implementaciones para Claude, OpenAI, Gemini, Ollama
- Cambiar de modelo = cambiar una línea en `config.yaml`
- Contexto comprimido con RAG: nunca se manda el histórico completo, solo lo quirúrgicamente relevante

### Frontend
- **React + TypeScript**
- **WebSocket** para datos en tiempo real
- **Tailwind CSS**

### Infraestructura desarrollo
- **Raspberry Pi** — simula el edge device industrial
- **Tennessee Eastman Process** — simulador industrial estándar para desarrollo y validación
- **Factory I/O** — simulador 3D para demos comerciales (opcional)

---

## PRINCIPIOS DE DISEÑO QUE NO SE TOCAN

1. **Interfaces explícitas:** Cada módulo tiene una Abstract Base Class. Cambiar implementación = nueva clase, no tocar el resto.
2. **Datos como contratos:** Toda comunicación entre módulos es JSON validado con Pydantic.
3. **Configuración externalizada:** Todo en `config.yaml`. Cero hardcoding de URLs, modelos o umbrales.
4. **Agnóstico al proveedor:** LLM, base de datos, protocolo industrial — todo intercambiable sin tocar la lógica de negocio.
5. **Claude Code friendly:** Herramientas con APIs limpias, buena documentación pública, sin SDKs propietarios opacos.

---

## ESTRUCTURA DE CARPETAS DEL REPOSITORIO

```
industrial-edge-copilot/
├── CONTEXT.md              ← ESTE ARCHIVO. Léelo primero siempre.
├── STATUS.md               ← Estado actual del proyecto (actualizar al cerrar sesión)
├── README.md               ← Descripción pública del proyecto
├── config.yaml             ← Configuración del sistema (LLM, DB, protocolos)
│
├── docs/
│   ├── arquitectura.md     ← Descripción detallada de cada módulo
│   ├── decisiones.md       ← Por qué elegimos cada herramienta
│   └── mockup/             ← HTMLs del mockup de la interfaz
│
├── backend/
│   ├── core/
│   │   ├── interfaces.py   ← Abstract Base Classes de todos los módulos
│   │   └── config.py       ← Carga de config.yaml
│   ├── adapters/           ← M1: conectores OPC-UA, Modbus, MQTT, CSV
│   ├── normalizer/         ← M2
│   ├── process_model/      ← M3 + M7: grafo de proceso
│   ├── analytics/          ← M4: Isolation Forest, análisis histórico
│   ├── llm/                ← M5, M9, M11: proveedores LLM agnósticos
│   ├── interaction/        ← M6: preguntas al operario, aprobaciones
│   ├── observer/           ← M8: bucle de observación RT
│   ├── recommender/        ← M10: recomendación y control
│   ├── memory/             ← M12: persistencia
│   ├── validator/          ← M13: validación transversal
│   └── api/                ← FastAPI routes y WebSocket
│
├── frontend/               ← React + TypeScript dashboard
│
├── simulator/              ← Scripts para conectar con Tennessee Eastman
│
└── tests/                  ← Tests por módulo con datos sintéticos
```

---

## ESTADO DEL PROYECTO

→ Ver **STATUS.md** para el estado actualizado al día de hoy.

---

## CÓMO ARRANCAR EN UNA MÁQUINA NUEVA

```bash
# 1. Clonar
git clone https://github.com/[org]/industrial-edge-copilot
cd industrial-edge-copilot

# 2. Leer el estado actual
cat STATUS.md

# 3. Backend
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 4. Configurar
cp config.example.yaml config.yaml
# Editar config.yaml: añadir ANTHROPIC_API_KEY y ajustar parámetros

# 5. Arrancar
uvicorn api.main:app --reload

# 6. Frontend (en otra terminal)
cd frontend
npm install
npm run dev
```

---

## HOJA DE RUTA — MVP

| Semana | Objetivo | Módulos |
|--------|----------|---------|
| 1-2 | Leer datos del simulador Tennessee Eastman | M1, M2 |
| 3-4 | Detectar anomalías con datos reales | M4, M8 |
| 5-6 | Primera hipótesis y diagnóstico con Claude | M5, M9 |
| 7-8 | Flujo completo: evento → diagnóstico → recomendación → aprobación | M6, M10 |
| 9-10 | Chat conversacional + dashboard básico | M11, Frontend |
| 11-12 | Modelo de proceso automático (el diferenciador) | M3, M7 |
| Mes 4 | Demo completa con Factory I/O (visual) | Integración |
| Mes 5-6 | Primera reunión con fábricas reales | Go-to-market |

---

## CONTEXTO DE NEGOCIO

- **Mercado:** Industrial AI — >€50.000M en 2030
- **Ventana competitiva:** 18-24 meses antes de que los grandes integren LLMs conversacionales
- **Inversión objetivo:** Pre-seed €200k-500k (CDTI/Enisa primero, luego aceleradoras)
- **Requisito para inversión:** 1 cliente de pago + métricas de impacto + equipo de 3
- **Coste API estimado:** €15-30/mes por fábrica (irrelevante sobre ticket de €2.000+/mes)

---

## CONTACTOS Y RECURSOS

- Documento de arquitectura completa: `docs/arquitectura.md`
- Decisiones técnicas: `docs/decisiones.md`
- Dataset Tennessee Eastman: https://www.kaggle.com/datasets/averkij/tennessee-eastman-process-simulation-dataset
- Documentación Claude API: https://docs.anthropic.com
- asyncua (OPC-UA Python): https://github.com/FreeOpcUa/opcua-asyncio

---

*Última actualización: ver STATUS.md*
