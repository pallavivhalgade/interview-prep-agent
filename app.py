import time
import streamlit as st
from src.agent import (
    extract_requirements,
    generate_questions,
    generate_answers,
    generate_study_plan,
)

st.set_page_config(
    page_title="Interview Prep Agent",
    page_icon="🎯",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ============================================================
# Custom CSS — cards, gradients, spacing, animation
# ============================================================
st.markdown(
    """
    <style>
        /* Hero */
        .hero {
            text-align: center;
            padding: 1.5rem 0 0.8rem 0;
        }
        .hero .badge {
            display: inline-block;
            background: rgba(139, 92, 246, 0.15);
            color: #a78bfa;
            padding: 4px 14px;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 600;
            letter-spacing: 0.03em;
            margin-bottom: 12px;
        }
        .hero h1 {
            font-size: 2.5rem;
            margin: 0.2rem 0;
            background: linear-gradient(90deg, #a78bfa, #f472b6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .hero p {
            color: #9aa0a6;
            font-size: 1.02rem;
            max-width: 540px;
            margin: 0 auto;
        }

        /* Buttons */
        .stButton>button {
            width: 100%;
            border-radius: 10px;
            height: 3.1em;
            font-weight: 600;
            font-size: 1rem;
            background: linear-gradient(90deg, #8b5cf6, #ec4899);
            color: white;
            border: none;
            transition: all 0.2s ease;
        }
        .stButton>button:hover {
            transform: translateY(-1px);
            box-shadow: 0 6px 20px rgba(139, 92, 246, 0.35);
            color: white;
        }

        /* Input */
        .stTextArea textarea {
            border-radius: 12px;
            border: 1px solid #2a2e39;
        }

        /* Result cards */
        .result-card {
            background: #161b22;
            border: 1px solid #2a2e39;
            border-radius: 14px;
            padding: 1.4rem 1.6rem;
            margin-bottom: 1rem;
        }
        .result-card h4 {
            margin-top: 0;
            color: #e6edf3;
        }
        .card-label {
            display: inline-block;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.05em;
            color: #a78bfa;
            text-transform: uppercase;
            margin-bottom: 6px;
        }

        /* Step tracker */
        .step-row {
            display: flex;
            justify-content: space-between;
            margin: 1.2rem 0;
        }
        .step-item {
            text-align: center;
            flex: 1;
            font-size: 0.78rem;
            color: #6b7280;
        }
        .step-item.active {
            color: #a78bfa;
            font-weight: 700;
        }
        .step-item.done {
            color: #34d399;
        }

        footer {visibility: hidden;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# Hero header
# ============================================================
st.markdown(
    """
    <div class="hero">
        <span class="badge">AGENTIC AI · 4-STEP PIPELINE</span>
        <h1>🎯 Interview Prep Agent</h1>
        <p>Paste any job description. The agent extracts what matters, predicts
        likely questions, drafts sample answers, and builds a study plan —
        automatically.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.write("")

# ============================================================
# Input
# ============================================================
job_description = st.text_area(
    "Job description",
    height=220,
    placeholder="Paste the full job description here...",
    label_visibility="collapsed",
)

col1, col2 = st.columns([3, 1])
with col1:
    generate = st.button("✨ Generate Interview Prep", type="primary")
with col2:
    st.caption(f"{len(job_description)} characters")

# ============================================================
# Pipeline run with animated step tracker
# ============================================================
STEPS = ["Requirements", "Questions", "Answers", "Study Plan"]


def render_steps(active_index):
    """active_index: -1 = none started, 0..3 = current step running, 4 = all done"""
    html = '<div class="step-row">'
    for i, label in enumerate(STEPS):
        if i < active_index:
            css_class = "done"
            icon = "✓"
        elif i == active_index:
            css_class = "active"
            icon = "●"
        else:
            css_class = ""
            icon = "○"
        html += f'<div class="step-item {css_class}">{icon}<br>{label}</div>'
    html += "</div>"
    return html


if generate:
    if not job_description.strip():
        st.warning("Please paste a job description first.")
    else:
        step_tracker = st.empty()

        step_tracker.markdown(render_steps(0), unsafe_allow_html=True)
        requirements = extract_requirements(job_description)

        step_tracker.markdown(render_steps(1), unsafe_allow_html=True)
        questions = generate_questions(requirements)

        step_tracker.markdown(render_steps(2), unsafe_allow_html=True)
        answers = generate_answers(questions)

        step_tracker.markdown(render_steps(3), unsafe_allow_html=True)
        study_plan = generate_study_plan(requirements)

        step_tracker.markdown(render_steps(4), unsafe_allow_html=True)
        time.sleep(0.3)
        step_tracker.empty()

        st.success("Your interview prep kit is ready ⬇️")

        tab1, tab2, tab3, tab4 = st.tabs(
            ["📋 Requirements", "❓ Questions", "💡 Answers", "📅 Study Plan"]
        )

        with tab1:
            st.markdown(
                f'<div class="result-card">{requirements}</div>',
                unsafe_allow_html=True,
            )
        with tab2:
            st.markdown(
                f'<div class="result-card">{questions}</div>',
                unsafe_allow_html=True,
            )
        with tab3:
            st.markdown(
                f'<div class="result-card">{answers}</div>',
                unsafe_allow_html=True,
            )
        with tab4:
            st.markdown(
                f'<div class="result-card">{study_plan}</div>',
                unsafe_allow_html=True,
            )

        full_report = f"""# Interview Prep Report

## Extracted Requirements
{requirements}

## Likely Interview Questions
{questions}

## Sample Answers / Frameworks
{answers}

## 3-Day Study Plan
{study_plan}
"""
        st.download_button(
            label="⬇️ Download full report (Markdown)",
            data=full_report,
            file_name="interview_prep_report.md",
            mime="text/markdown",
        )

# ============================================================
# Footer
# ============================================================
st.markdown(
    """
    <div style="text-align:center; margin-top: 3rem; color: #6b7280; font-size: 0.8rem;">
        Built with Streamlit + Groq (Llama 3.1) · Agentic 4-step pipeline
    </div>
    """,
    unsafe_allow_html=True,
)
