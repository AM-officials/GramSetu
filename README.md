<div align="center">

# 🌱 GramSetu

### *Bridging the Rural-Digital Divide — One WhatsApp Message at a Time*

**A serverless WhatsApp AI agent that helps rural Indian citizens apply for government welfare schemes using voice notes and document photos — in their own language.**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Google Gemini](https://img.shields.io/badge/Gemini-AI-4285F4?style=for-the-badge&logo=google&logoColor=white)](https://ai.google.dev)
[![AWS Lambda](https://img.shields.io/badge/AWS-Lambda-FF9900?style=for-the-badge&logo=amazon-aws&logoColor=white)](https://aws.amazon.com/lambda/)
[![WhatsApp](https://img.shields.io/badge/WhatsApp-Cloud_API-25D366?style=for-the-badge&logo=whatsapp&logoColor=white)](https://developers.facebook.com/docs/whatsapp)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![DynamoDB](https://img.shields.io/badge/DynamoDB-Sessions-4053D6?style=for-the-badge&logo=amazon-dynamodb&logoColor=white)](https://aws.amazon.com/dynamodb/)

</div>

---

## 🎬 Live Demo

<div align="center">

[![GramSetu Demo](https://img.youtube.com/vi/Ta11OqlqiZE/maxresdefault.jpg)](https://youtu.be/Ta11OqlqiZE?si=rKkNKg4JMO3vZEoH)

**▶️ [Watch Full Demo on YouTube](https://youtu.be/Ta11OqlqiZE?si=rKkNKg4JMO3vZEoH)**

</div>

---

## 📸 Screenshots

<div align="center">

| Welcome & Scheme Selection | Document Upload & OCR | Eligibility & Submission |
|:---:|:---:|:---:|
| ![Welcome](docs/screenshots/welcome.jpg) | ![Document OCR](docs/screenshots/document_ocr.jpg) | ![Submission](docs/screenshots/submission.jpg) |
| Bilingual welcome + scheme picker | Gemini extracts data from Aadhaar photo | Auto-generates reference number |

</div>

---

## 🔄 Process Flow

```mermaid
flowchart TD
    A([👤 Rural User\nSends WhatsApp Message]) --> B{Message Type?}

    B -->|💬 Text| C{Intent Check}
    B -->|🎙️ Voice Note| D[Audio Pipeline]
    B -->|📷 Document Photo| E[Document Pipeline]

    C -->|Greeting / hi / hello| F[🌱 Welcome Message\nBilingual EN + HI]
    C -->|STOP| G[🚨 Clear DynamoDB Session\nFresh Start Confirmed]
    C -->|Apply / Proceed / Submit| H{Session Has\nAadhaar Name?}
    C -->|General Query| I[🤖 Gemini Conversational\nGuide to Next Step]

    H -->|Yes ✅| J[🎉 Generate Reference\nGS-2026-XXXXXX]
    H -->|No ❌| I

    D --> K[⬇️ Download OGG/MP3\nfrom Meta CDN]
    K --> L[🔊 Gemini Native Audio\nTranscription + Intent]
    L --> M[💾 Save to DynamoDB Session]
    M --> N[📤 Bilingual Reply]

    E --> O[⬇️ Download Image\nfrom Meta CDN]
    O --> P[🔍 DocumentProcessor\nQuality Gate]
    P -->|Poor Quality| Q[⚠️ Retry Prompt\nRetake Photo]
    P -->|Pass ✅| R[🧠 Gemini Multimodal OCR\nClassify + Extract]

    R --> S{Document Type?}
    S -->|Aadhaar| T[Store Name for\nIdentity Verification]
    S -->|Income Certificate| U[Extract Annual\nIncome INR]
    S -->|Land Record| V[Extract Land Area\n& Ownership]
    S -->|Bank Passbook| W[Extract Account No.\n& IFSC Code]
    S -->|Caste Certificate| X[Extract SC/ST/OBC\nCategory]
    S -->|Ration Card| Y[Extract Head of HH\n& Family Count]
    S -->|Unknown| Z[❓ Unknown Doc\nGuide User]

    T & U & V & W & X & Y --> AA[💾 Merge into\nDynamoDB Session\n15-min TTL]
    AA --> AB[✅ Eligibility Check\nPM-KISAN / PMAY / Ayushman]
    AB --> AC[📤 Bilingual AI Reply\n→ Next Required Document]

    J --> AD[📱 Submission Confirmation\nSent to User]
    AD --> AE[🗑️ Clear DynamoDB Session\nReady for New Application]

    style A fill:#25D366,color:#fff
    style F fill:#1a73e8,color:#fff
    style G fill:#ea4335,color:#fff
    style J fill:#34a853,color:#fff
    style R fill:#4285f4,color:#fff
    style AD fill:#fbbc04,color:#000
    style AE fill:#34a853,color:#fff
    style Q fill:#ea4335,color:#fff
    style Z fill:#ea4335,color:#fff
```

---

## ✨ Features

| Feature | Description |
|---|---|
| 🌐 **Zero-App Access** | Works entirely over WhatsApp — no app download required |
| 🗣️ **Voice-First** | Send a voice note; Gemini transcribes and understands intent natively |
| 📄 **Universal OCR** | Snap a photo of any document — AI classifies and extracts data automatically |
| 🤝 **Bilingual** | Every reply is in both English and Hindi (हिंदी) |
| 🧠 **Session Memory** | DynamoDB tracks uploaded documents for 15 minutes so users are never asked twice |
| 🔒 **Identity Verification** | Cross-checks names across documents against the registered Aadhaar |
| 🧾 **7 Document Types** | Aadhaar, Income Certificate, Land Record, Bank Passbook, Caste Certificate, Ration Card, Crop Certificate |
| 🚀 **One-Tap Submission** | Say "proceed" or "submit" to get an instant application reference number |
| 🚨 **STOP Command** | Text "STOP" to instantly wipe session and start fresh |
| ☁️ **Fully Serverless** | AWS Lambda + API Gateway — scales to zero when idle |

---

## 🏛️ Supported Government Schemes

| Scheme | Benefit | Key Requirement |
|---|---|---|
| **PM-KISAN Samman Nidhi** | ₹6,000/year | Farmer with land record |
| **Ayushman Bharat (PM-JAY)** | ₹5 Lakh health cover | Family income < ₹1,00,000 |
| **PM Awas Yojana (PMAY-G)** | Housing assistance | Kutcha house, income < ₹1,50,000 |
| **MGNREGA** | 100 days guaranteed work | Rural household |
| **PM Jan Dhan Yojana** | Zero-balance bank account | Any resident |

---

## 🏗️ Architecture

```
WhatsApp User
     │  (Cloud API webhook POST)
     ▼
API Gateway (HTTP API)
     │
     ▼
WebhookHandler Lambda  ──── FastAPI router
     │
     ├── text  ──────────► Gemini Conversational  ──► DynamoDB Session
     │                                                      │
     ├── audio ──────────► Gemini Native Audio  ────────────┤
     │                     (transcribe + intent)            │
     └── image/doc ──────► DocumentProcessor               │
                           (quality gate)                   │
                               │                           │
                               ▼                           │
                          AI Reasoner                      │
                          (Gemini Multimodal OCR) ◄────────┘
                               │
                          S3 Media Bucket
                          (temp storage)
```

**AWS Resources deployed via SAM:**
- `WebhookHandlerFunction` — FastAPI webhook receiver
- `DocumentProcessorFunction` — Image quality gate
- `AIReasonerFunction` — Gemini multimodal OCR & classification
- `VoiceProcessorFunction` — Gemini native audio pipeline
- `PDFGeneratorFunction` — Pre-filled government form generation
- `GramSetuSessionsTable` — DynamoDB (15-min TTL session store)
- `GramSetuTable` — DynamoDB (permanent scheme + user data)
- `GramSetuMediaBucket` — S3 (incoming media + generated PDFs)

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **AI / LLM** | Google Gemini `gemini-3.1-flash-lite-preview` (multimodal) |
| **Messaging** | Meta WhatsApp Cloud API v18.0 |
| **Backend** | FastAPI + Uvicorn on AWS Lambda |
| **Infrastructure** | AWS SAM (Lambda, API Gateway, DynamoDB, S3) |
| **Session Store** | Amazon DynamoDB (on-demand, AES-256 encrypted, 15-min TTL) |
| **HTTP Client** | httpx (async-ready) |
| **Runtime** | Python 3.12 |
| **IaC** | AWS SAM + CloudFormation |

---

## 🚀 Local Setup

### Prerequisites
- Python 3.12+
- AWS CLI configured (`aws configure`)
- AWS SAM CLI (`pip install aws-sam-cli`)
- A Meta WhatsApp Business account + phone number ID
- A Google AI Studio API key ([get one free](https://aistudio.google.com))

### 1. Clone & install

```bash
git clone https://github.com/AM-officials/GramSetu.git
cd GramSetu
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
GEMINI_API_KEY=your_google_ai_studio_key
WHATSAPP_API_TOKEN=your_meta_bearer_token
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
WHATSAPP_VERIFY_TOKEN=your_custom_verify_token
AWS_REGION=ap-south-1
TABLE_NAME=gramsetu-sessions-dev
```

### 3. Run locally

```bash
python run_webhook.py
# Webhook available at http://localhost:8000/webhook
```

Use [ngrok](https://ngrok.com) to expose it to Meta:
```bash
ngrok http 8000
# Set the ngrok HTTPS URL as your Meta webhook URL
```

### 4. Run tests

```bash
pytest tests/ -v
```

---

## ☁️ Deploy to AWS

```bash
cp samconfig.toml.example samconfig.toml
# Edit samconfig.toml with your values

sam build
sam deploy
```

SAM will provision all AWS resources and output the API Gateway URL. Set this as your Meta webhook URL.

---

## 📁 Project Structure

```
GramSetu/
├── src/
│   ├── ai_reasoner/          # Gemini multimodal client + prompt builder
│   ├── document_processor/   # Image quality gate (blur, brightness checks)
│   ├── pdf_generator/        # Pre-filled government form PDF generation
│   ├── shared/               # DynamoDB session manager, types, models
│   ├── voice_processor/      # Audio pipeline helpers
│   ├── webhook_handler/      # FastAPI routes (main entry point)
│   └── whatsapp_client/      # Meta Cloud API send/download client
├── tests/                    # pytest test suite (56 tests)
├── layer/                    # Lambda Layer dependencies
├── template.yaml             # AWS SAM infrastructure definition
├── samconfig.toml.example    # Deploy configuration template
├── .env.example              # Environment variable template
└── run_webhook.py            # Local development server
```

---

## 🔐 Security

- All API credentials are loaded from environment variables — **never hardcoded**
- `.env` and `samconfig.toml` are in `.gitignore` and never committed
- DynamoDB tables use **AES-256 server-side encryption** at rest
- Session data auto-expires after **15 minutes** via DynamoDB TTL
- `WHATSAPP_API_TOKEN` and `WhatsAppAccessToken` are marked `NoEcho: true` in SAM

---

## 📄 License

This project is private. All rights reserved © 2026 AM-officials.

---

<div align="center">

Built with ❤️ to serve rural India 🇮🇳

*"Technology should reach the last mile."*

</div>
