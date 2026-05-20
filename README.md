---
title: Service Orchestrator
emoji: 🚀
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
app_port: 7860
---

# Service Orchestrator — Antigravity Edition 🚀

An **agentic AI system** for the informal service economy that automates the full service lifecycle: multilingual request understanding → provider matching → scheduling → dynamic pricing → booking → follow-up → feedback → dispute resolution.

**Powered by Google Antigravity** (Groq LLM) as the central reasoning engine with full trace transparency.

---

## 🏗 Architecture

```
┌─────────────────────────────────────┐
│     📱 Mobile Web App (PWA)         │
│   Chat UI → Booking → Feedback      │
└──────────────┬──────────────────────┘
               │ HTTP/JSON
┌──────────────▼──────────────────────┐
│     🔧 FastAPI Backend (8000)       │
├─────────────────────────────────────┤
│  🧠 Antigravity LLM (Groq)         │
│  ├── NLU Engine (multilingual)      │
│  ├── Provider Matcher (8-factor)    │
│  ├── Scheduler (conflict-aware)     │
│  ├── Dynamic Pricer (transparent)   │
│  ├── Booking Engine (full lifecycle)│
│  ├── Quality Loop (sentiment+rep)   │
│  ├── Dispute Handler (auto-resolve) │
│  └── Provider Optimizer (fairness)  │
├─────────────────────────────────────┤
│  📊 Data Layer (JSON files)         │
│  └── providers, bookings, reputation│
└─────────────────────────────────────┘
```

## 🚀 Quick Start

### 1. Install Dependencies
```bash
py -m pip install -r requirements.txt
```

### 2. Configure Environment
```bash
copy .env.example .env
# Edit .env with your API keys
```

### 3. Run the Backend
```bash
py orchestrator.py
```

### 4. Open the Mobile App
- **Local Development:** Open in browser: **http://localhost:8000/app**
- **Production Server (Hugging Face):** **`https://talha-khan4131-service-orchestrator.hf.space`**
  *(Copy this URL and paste it into the **API Server URL** settings box inside the APK if you need to manual reconnect)*

### 5. Try the Example Scenario
Type in the chat:
> "AC bilkul kaam nahi kar raha, kal subah G-13 mein technician chahiye, budget zyada nahi hai"

---

## 📊 Provider Dataset Schema

| Field | Type | Description |
|-------|------|-------------|
| id | string | Unique provider ID |
| name | string | Provider business name |
| service | string | Service category |
| specializations | string[] | Specific skills |
| base_rate | int | Base price in PKR |
| rating | float | Overall rating (0-5) |
| review_count | int | Total reviews |
| recent_negative_reviews | int | Recent negative count |
| skill_level | string | basic/intermediate/expert |
| certifications | string[] | Professional certs |
| on_time_percentage | int | Reliability score |
| cancellation_rate | int | Cancellation % |
| lat, lng | float | GPS coordinates |
| availability | object | Weekly schedule |
| capacity_per_day | int | Max daily jobs |
| current_load | int | Current job count |
| risk_score | int | Computed risk (0-100) |

**16 providers** across 6 categories: AC repair, electrician, plumber, beautician, mechanic, tutor.

---

## 🧠 Matching Algorithm (8 Factors)

| Factor | Weight | Description |
|--------|--------|-------------|
| Distance | 15% | Road distance via Google Routes API |
| Availability | 15% | Capacity and slot availability |
| Rating | 15% | Overall star rating |
| Review Recency | 5% | Recent negative review penalty |
| Reliability | 15% | On-time percentage |
| Skill Match | 15% | Job complexity vs provider expertise |
| Price | 10% | Budget-sensitive competitiveness |
| Cancellation Risk | 10% | Historical cancellation rate |

---

## 🔄 Antigravity Workflow

Every decision generates a structured trace:
1. **NLU Parsing** — Language detection, intent extraction, confidence scoring
2. **Location Normalization** — Map area names to GPS coordinates
3. **Provider Scoring** — Individual 8-factor score per candidate
4. **Ranking Decision** — Why Provider A was chosen over B
5. **Time Resolution** — Natural language → datetime conversion
6. **Scheduling Check** — Availability, conflicts, buffers
7. **Dynamic Pricing** — Transparent breakdown with fairness note
8. **Booking Creation** — Confirmation, notifications, receipt
9. **Quality Feedback** — Sentiment analysis, rating adjustment
10. **Dispute Resolution** — Auto-resolve or AI assessment

---

## 🛠 API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/webhook/message` | POST | Main lifecycle orchestration |
| `/booking/{id}` | GET | Booking details + traces |
| `/booking/{id}/cancel` | POST | Cancel (triggers reschedule) |
| `/booking/{id}/status` | POST | Update status |
| `/booking/{id}/rate` | POST | Submit feedback |
| `/booking/{id}/dispute` | POST | Open dispute |
| `/providers/dashboard` | GET | Workload dashboard |
| `/providers/forecast` | GET | Demand forecast |
| `/providers/{id}/optimize` | GET | Provider optimization |
| `/providers/earnings` | GET | Fairness analysis |
| `/traces` | GET | AI reasoning traces |
| `/simulate/scenarios` | GET | List stress tests |
| `/app` | GET | Mobile web app |

---

## 🌐 Multilingual Support

- **English**: "I need an AC repair tomorrow morning in G-13"
- **Urdu**: "مجھے کل صبح AC کی مرمت چاہیے"
- **Roman Urdu**: "Mujhe kal subah AC repair chahiye"
- **Code-switched**: "AC bilkul kaam nahi kar raha, need technician ASAP"
- **Misspellings**: "electrition", "plumer", "mecanic"
- **Slang**: "bijli ka masla", "pani leak ho raha"

---

## 🔧 Tools & Technologies

- **Backend**: Python 3.13, FastAPI, Uvicorn
- **LLM**: Groq API (Llama 3.3 70B Versatile)
- **Maps**: Google Routes API (with Haversine fallback)
- **Frontend**: HTML5, CSS3, Vanilla JavaScript (PWA)
- **Data**: JSON file-based storage

---

## ⚠ Assumptions & Limitations

1. Provider data is mock (realistic Islamabad coordinates)
2. SMS/WhatsApp notifications are simulated (not actually sent)
3. Payment processing is simulated
4. GPS coordinates default to G-13, Islamabad
5. Groq free tier has rate limits (~30 req/min)

---

## 🔒 Privacy Note

- User messages are sent to Groq API for NLU processing
- No personal data is stored beyond booking records
- API keys should be kept in `.env` (not committed)
- All data stays local (JSON file storage)
