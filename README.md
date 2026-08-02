# 🎯 Interview Prep Agent

A lightweight agentic AI tool that turns any job description into a full
interview prep kit: key requirements, likely questions, sample answers, and
a 3-day study plan.

🔗 **Live demo:** [interview-prep-agent-94gjmmzu9q3w9gp4by8uan.streamlit.app](https://interview-prep-agent-94gjmmzu9q3w9gp4by8uan.streamlit.app/)

![App hero screenshot](screenshots/demo-hero.png)
![App results screenshot](screenshots/demo-results.png)

## Problem
Preparing for an interview usually means manually re-reading a job
description, guessing what might be asked, and researching answers one by
one. This agent automates that research loop.

## Approach
This is a **4-step agent pipeline**, where each step's output feeds into
the next (not a single one-shot prompt):

```
Job Description
      │
      ▼
1. Extract key skills/requirements  ──▶  2. Generate likely questions
                                                   │
                                                   ▼
4. Generate 3-day study plan   ◀──────  3. Generate sample answers
```

Built with:
- **Groq API** (Llama 3.1 8B) — fast, free-tier LLM inference
- **Streamlit** — simple web UI
- **Python** — orchestration logic (`src/agent.py`)

## Results
Given a job description, the agent produces:
- A bulleted list of extracted requirements
- 8 likely interview questions (5 technical, 3 behavioral)
- Sample answers / STAR-method frameworks for each
- A focused 3-day study plan

## Limitations & what I'd improve next
- Currently uses a single LLM call per step — could add self-critique
  (an extra "reviewer" step that checks question relevance before showing
  them to the user)
- No memory across sessions — could store past job descriptions and
  compare prep across multiple applications
- Answer quality depends on the JD's specificity — vague JDs produce
  more generic questions

## Project Structure
```
interview-prep-agent/
├── app.py                  # Streamlit UI
├── src/
│   ├── __init__.py
│   └── agent.py            # 4-step agent pipeline logic
├── screenshots/
│   ├── demo-hero.png
│   └── demo-results.png
├── .streamlit/
│   └── config.toml         # custom theme
├── requirements.txt        # dependencies
├── runtime.txt             # pinned Python version
├── .env.example            # template for API key setup
├── .gitignore
└── README.md
```

## How to run locally

```bash
git clone https://github.com/pallavivhalgade/interview-prep-agent.git
cd interview-prep-agent
pip install -r requirements.txt
cp .env.example .env   # then add your free Groq API key to .env
streamlit run app.py
```

Get a free Groq API key at: https://console.groq.com

## Tech Stack
Python · Streamlit · Groq API (Llama 3.1) · python-dotenv

## Author
**Pallavi Vholgade**
🔗 [LinkedIn](https://www.linkedin.com/in/pallavi-vholgade-05565b24b/?skipRedirect=true)
📧 pallavivhalgade@gmail.com
