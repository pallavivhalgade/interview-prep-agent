# 🎯 Interview Prep Agent

**Interview Prep Agent** is an agentic AI application that converts a job description — and optionally a candidate's resume — into a structured, role-specific interview preparation workspace.

Instead of generating generic interview questions, the system analyzes the role, identifies the most relevant requirements, reviews the candidate's resume fit, detects skill gaps, generates high-priority interview questions, creates one answer for every question, and builds a practical 3-day preparation plan.

🔗 **Live Demo:** [Open Interview Prep Agent](https://interview-prep-agent-94gjmmzu9q3w9gp4by8uan.streamlit.app/)
---
## ✨ What Makes This Project Different?

Most interview-preparation tools behave like a single LLM prompt:

> Job Description → Questions

This project uses a **multi-step agentic pipeline** where the output of one AI step becomes context for the next.

```text
Job Description
      │
      ▼
1. Role & Requirement Analysis
      │
      ▼
2. Important Question Generation
      │
      ▼
3. Reviewer Agent
      │
      ▼
4. Sample Answer Generation
      │
      ▼
5. Personalized Study Plan
```

When a resume is uploaded, an additional analysis path runs:

```text
Resume + Job Description
        │
        ├── Resume ↔ JD Match Score
        │
        └── Skill Gap Analysis
                │
                ├── Matching Skills
                ├── Missing / Weak Skills
                ├── Highest-Priority Gap
                └── Recommended Next Step
```

The **Reviewer Agent** is important because the system does not blindly trust the first generated question set. It performs a second AI review to remove weak, repetitive, or less relevant questions before downstream answer generation.

---

## 🚀 Core Features

### 1. Dynamic Role Identification

The application identifies the target role directly from the uploaded or pasted job description.

Examples:

- AI/ML Engineer
- Generative AI Engineer
- Python Developer
- Data Analyst
- Data Scientist
- Backend Developer

If the JD clearly states the role title, the system uses it. Otherwise, it infers the most suitable title from the responsibilities, technologies, and required skills.

---

### 2. Job Description Analysis

The agent extracts:

- role expectations
- responsibilities
- technical requirements
- engineering expectations
- important domain knowledge
- required skills

The Requirements section focuses on **what the employer expects the candidate to do**, rather than simply repeating a list of technologies.

---

### 3. Resume ↔ JD Match

When a resume is uploaded, the application calculates a resume-to-job-description similarity score using local sentence embeddings.

The matching workflow uses:

```text
Resume Text
    │
    ▼
Sentence Embedding

Job Description
    │
    ▼
Sentence Embedding

        │
        ▼
Cosine Similarity
        │
        ▼
Resume ↔ JD Match %
```

The embedding model runs locally, so the similarity calculation does not require another external AI API call.

---

### 4. Visual Skill Matching

Required skills are compared with the candidate's resume and displayed in a compact visual format.

**Matched skills**

```text
✓ Python
✓ Machine Learning
✓ SQL
✓ Pandas
✓ Git / GitHub
```

**Missing or weakly demonstrated skills**

```text
× REST APIs
× Model Deployment
× NLP Depth
```

Matched skills appear first, followed by areas that need strengthening.

---

### 5. Highest-Priority Skill Gap

The application does more than list missing skills.

It identifies the **single most important gap to address first** based on the job description and resume evidence.

Example:

```text
Highest-Priority Gap
REST API Integration

The JD expects model/backend integration through APIs,
but the resume does not strongly demonstrate this skill.
```

The system then gives a specific recommended next step instead of generic advice.

Example:

```text
Model
  ↓
FastAPI / Flask
  ↓
REST Endpoint
  ↓
Prediction
  ↓
Application
```

---

### 6. Important Interview Questions

The system does **not** force an arbitrary fixed question count.

It generates approximately **6–10 high-priority questions**, depending on the role and JD.

Weak filler questions are not added merely to reach a number.

Each question includes its domain, for example:

```text
01  How would you expose a trained ML model through a REST API?
    REST API · Priority Gap

02  How do you select an evaluation metric for an imbalanced dataset?
    Model Evaluation

03  Explain a Scikit-learn pipeline you have built.
    Machine Learning
```

Possible domains include:

- Python
- SQL
- Machine Learning
- NLP
- REST APIs
- Data Preparation
- Model Evaluation
- Project Discussion
- Behavioral
- Communication

---

### 7. Reviewer Agent

The first question set is passed through a dedicated review step.

The Reviewer Agent checks for:

- duplicate questions
- vague wording
- relevance to the JD
- realistic interview probability
- technical coverage
- unnecessary filler

Only the improved question set is used for answer generation.

This reviewer pattern is one of the project's main **agentic AI characteristics**.

---

### 8. One Sample Answer for Every Question

Every final interview question receives exactly one corresponding sample answer.

Answers are displayed in expandable sections so users can:

1. read the question,
2. answer it themselves,
3. expand the sample answer,
4. compare their response.

Behavioral questions use a concise **STAR-style framework**, while technical answers focus on reasoning and explanation rather than memorized definitions.

---

### 9. Personalized 3-Day Study Plan

The study plan is generated from:

- the target role
- JD requirements
- likely interview topics
- detected resume skill gaps

It is intentionally more detailed than a generic topic list.

Each day includes:

- **Why this topic matters**
- **What to understand**
- **What to practice or build**
- **Interview drills**
- **A completion checkpoint**

Example structure:

```text
Day 1 — Highest-Priority Gap

Why this matters
The JD expects REST API integration, but the resume
does not show strong evidence of it.

Learn
Understand REST architecture, POST requests,
JSON payloads, validation and HTTP status codes.

Apply / Build
Create a small /predict endpoint using FastAPI
and an existing ML model.

Interview Drill
Explain the complete request → validation →
model → prediction → response flow aloud.

Done when
You can explain the full flow confidently
without reading notes.
```

---

## 🎨 User Experience

The application uses a custom Streamlit interface rather than the default Streamlit appearance.

The current visual design includes:

- pink + lavender cloud wallpaper
- subtle wave lines and sparkles
- frosted-glass navigation
- large role-focused hero section
- compact skill chips
- highlighted priority-gap section
- expandable result sections
- expandable individual answers
- responsive workspace
- structured report downloads

Main result sections:

```text
Requirements                 +
Skill Gap Analysis            +
Important Interview Questions +
Sample Answers                +
Personalized Study Plan       +
```

This keeps long interview-preparation output organized without filling the page with large blocks of text.

---

## 📄 Supported Inputs

### Job Description

Users can:

- paste a job description directly
- upload a JD file

Supported JD file formats:

- PDF
- DOCX
- TXT

### Resume

Resume upload is optional.

Supported resume formats:

- PDF
- DOCX

Without a resume, the application still provides:

- role analysis
- required skills
- important interview questions
- sample answers
- 3-day study plan

With a resume, it additionally provides:

- Resume ↔ JD Match
- matched skills
- missing / weak skills
- highest-priority gap
- recommended next step
- resume-aware preparation priorities

---

## 📥 Report Export

The complete preparation can be exported as:

- **Markdown**
- **PDF**

The PDF report contains the generated interview-preparation content in a structured offline format.

---

## 🧠 Agentic AI Workflow

A simple way to explain the project in an interview:

> "I built an Interview Prep Agent where multiple AI stages collaborate instead of using one large prompt. The first stage analyzes the job description and extracts the role and requirements. A second stage generates likely interview questions. A reviewer agent then checks those questions and removes weak or repetitive ones. The reviewed questions are passed to an answer-generation stage, and finally another stage creates a personalized three-day study plan. If a resume is uploaded, the system also calculates a local resume-JD similarity score and performs structured skill-gap analysis."

---

## 🏗️ Architecture

```text
                         ┌──────────────────────┐
                         │  Streamlit Frontend  │
                         └──────────┬───────────┘
                                    │
                           Job Description
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │  Role Analysis Agent │
                         └──────────┬───────────┘
                                    │
                      Role + Requirements + Skills
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │ Question Generator   │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │   Reviewer Agent     │
                         └──────────┬───────────┘
                                    │
                           Reviewed Questions
                                    │
                         ┌──────────┴───────────┐
                         ▼                      ▼
                ┌─────────────────┐    ┌─────────────────┐
                │ Answer Agent    │    │ Study Plan Agent│
                └─────────────────┘    └─────────────────┘


Optional Resume Path
───────────────────────────────────────────────

Resume + JD
    │
    ├── Local Sentence Embeddings
    │       │
    │       ▼
    │   Cosine Similarity
    │       │
    │       ▼
    │   Resume ↔ JD Match %
    │
    └── Skill Gap Agent
            │
            ├── Matching Skills
            ├── Missing Skills
            ├── Priority Gap
            └── Recommendation
```

---

## 🛠️ Tech Stack

| Area | Technology |
|---|---|
| Language | Python |
| Frontend | Streamlit |
| LLM Inference | Groq API |
| Agent Pipeline | Custom multi-stage Python pipeline |
| Embeddings | Sentence Transformers |
| Similarity | Scikit-learn cosine similarity |
| PDF Parsing | pdfplumber |
| DOCX Parsing | python-docx |
| PDF Reports | fpdf2 |
| Markdown Rendering | Python-Markdown |
| Testing | pytest |
| Logging | Python `logging` |
| Configuration | python-dotenv |
| Version Control | Git + GitHub |
| Deployment | Streamlit Community Cloud |

The active LLM model is configured centrally in `src/config.py`, keeping model selection separate from pipeline logic.

---

## 📁 Project Structure

```text
interview-prep-agent/
│
├── app.py
│   └── Streamlit UI, navigation, workspace and result rendering
│
├── assets/
│   └── prep_wallpaper.webp
│
├── src/
│   ├── __init__.py
│   ├── agent.py
│   │   └── agentic interview-preparation pipeline
│   ├── config.py
│   │   └── model and application configuration
│   ├── logger.py
│   │   └── centralized logging
│   ├── models.py
│   │   └── typed result dataclasses
│   ├── parser.py
│   │   └── PDF / DOCX text extraction
│   ├── prompts.py
│   │   └── role, question, reviewer, answer,
│   │       skill-gap and study-plan prompts
│   └── utils.py
│       └── resume-JD embedding similarity
│
├── tests/
│   ├── __init__.py
│   └── test_agent.py
│
├── screenshots/
│   ├── demo-main.png
│   └── demo-results.png
│
├── .streamlit/
│   └── config.toml
│
├── .env.example
├── .gitignore
├── requirements.txt
├── runtime.txt
└── README.md
```

---

## 🖼️ Screenshots

### Home

![Interview Prep Agent Home](screenshots/demo-main.png)

### Generated Results

![Interview Prep Agent Results](screenshots/demo-results.png)

> After updating the final UI, replace these screenshots with the latest application screenshots so the README matches the deployed interface.

---

## ⚙️ Local Setup

### 1. Clone the repository

```bash
git clone https://github.com/pallavivhalgade/interview-prep-agent.git
cd interview-prep-agent
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Create the environment file

```bash
cp .env.example .env
```

On Windows PowerShell, you can instead use:

```powershell
Copy-Item .env.example .env
```

Add your Groq API key:

```env
GROQ_API_KEY=your_groq_api_key
```

### 4. Start the application

```bash
streamlit run app.py
```

The application will open at:

```text
http://localhost:8501
```

---

## 🧪 Testing

Run the test suite with:

```bash
pytest tests/ -v
```

The project uses mocked AI calls where appropriate so pipeline behavior can be tested without repeatedly calling the external LLM service.

Useful behaviors to test include:

- pipeline execution order
- structured JSON parsing
- question validation
- question-review fallback behavior
- answer count matching
- resume/JD skill-gap parsing
- invalid or empty model responses

---

## 🛡️ Error Handling

The application includes validation and error handling around:

- empty job descriptions
- unsupported files
- resume parsing
- LLM failures
- empty AI responses
- invalid structured responses
- question-format validation
- answer/question count mismatches
- PDF report generation

Failures are surfaced through user-friendly Streamlit messages instead of exposing raw application errors wherever possible.

---

## 🔐 Privacy Considerations

The Resume ↔ JD similarity score is calculated using a local sentence-transformer model.

This means the embedding similarity calculation itself does not require the resume to be sent to a separate embedding API.

However, when resume-aware AI skill-gap analysis is requested, resume and JD text may be included in the configured LLM request. Users should avoid uploading sensitive information they do not want processed by the configured AI provider.

---

## ⚠️ Current Limitations

- Generated output still depends on the quality and specificity of the supplied JD.
- The application does not maintain long-term preparation history between user sessions.
- LLM-generated interview questions represent likely preparation topics, not guaranteed real interview questions.
- Resume matching is semantic similarity and should not be treated as an ATS score.
- Skill-gap detection is based on information visible in the uploaded resume and may not represent skills the candidate has but did not mention.
- The project currently focuses on interview preparation rather than live voice/video mock interviews.

---

## 🔮 Possible Future Improvements

Potential extensions include:

- persistent interview-preparation history
- saved roles and previous JDs
- voice-based mock interviews
- answer scoring
- interviewer follow-up question simulation
- question difficulty levels
- progress tracking across study plans
- stronger structured-output enforcement
- retry/backoff policies for transient API failures

These are intentionally future improvements rather than unnecessary features in the current version. The current project focuses on a clear, explainable, end-to-end agentic workflow.

---

## 💼 Why This Project Is Valuable for Interviews

This project demonstrates more than basic prompt engineering.

It includes:

- agentic multi-step orchestration
- reviewer-agent pattern
- prompt design
- LLM output validation
- structured JSON parsing
- local embeddings
- semantic similarity
- PDF/DOCX parsing
- error handling
- logging
- report generation
- custom Streamlit UI
- deployment
- testing
- modular software architecture

The project is therefore easy to demonstrate while still providing enough engineering depth to discuss architecture, AI integration, validation, debugging, UX decisions, and limitations during a technical interview.

---

## 👩‍💻 Author

**Pallavi Vholgade**

GitHub: [pallavivhalgade](https://github.com/pallavivhalgade)

---

⭐ If you find the project useful, consider starring the repository.
