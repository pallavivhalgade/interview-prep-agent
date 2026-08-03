import streamlit as st
from src.agent import run_pipeline
from src.parser import extract_resume_text
from src.utils import compute_match_score

st.set_page_config(
    page_title="Interview Prep Agent",
    page_icon="🎯",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ============================================================
# Custom CSS
# ============================================================
st.markdown(
    """
    <style>
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
        .stTextArea textarea {
            border-radius: 12px;
            border: 1px solid #2a2e39;
        }
        .result-card {
            background: #161b22;
            border: 1px solid #2a2e39;
            border-radius: 14px;
            padding: 1.4rem 1.6rem;
            margin-bottom: 1rem;
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
        .match-score {
            text-align: center;
            font-size: 2.2rem;
            font-weight: 700;
            color: #34d399;
            margin: 0.5rem 0;
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
        <span class="badge">AGENTIC AI · 5-STEP PIPELINE + REVIEWER</span>
        <h1>🎯 Interview Prep Agent</h1>
        <p>Paste a job description and optionally your resume — get a
        match score, reviewed interview questions, sample answers, and
        a study plan.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.write("")

# ============================================================
# Inputs
# ============================================================
job_description = st.text_area(
    "Job description",
    height=200,
    placeholder="Paste the full job description here...",
    label_visibility="collapsed",
)

resume_file = st.file_uploader(
    "Upload your resume (optional — enables match score)",
    type=["pdf", "docx"],
)

col1, col2 = st.columns([3, 1])
with col1:
    generate = st.button("✨ Generate Interview Prep", type="primary")
with col2:
    st.caption(f"{len(job_description)} characters")

# ============================================================
# Pipeline run
# ============================================================
if generate:
    if not job_description.strip():
        st.warning("Please paste a job description first.")
    else:
        match_score = None

        # --- Resume match score (only if a resume was uploaded) ---
        if resume_file is not None:
            with st.spinner("Reading resume and computing match score..."):
                try:
                    resume_text = extract_resume_text(resume_file)
                    match_score = compute_match_score(resume_text, job_description)
                except Exception as e:
                    st.error(f"Couldn't process the resume: {e}")

        # --- Main pipeline ---
        with st.spinner("Agent is working through the job description..."):
            result = run_pipeline(job_description)

        st.success("Your interview prep kit is ready ⬇️")

        # --- Match score display ---
        if match_score is not None:
            st.markdown(
                f'<div class="result-card"><div style="text-align:center;">'
                f'<div class="card-label">RESUME-JD MATCH</div>'
                f'<div class="match-score">{match_score}%</div></div></div>',
                unsafe_allow_html=True,
            )

        tab1, tab2, tab3, tab4 = st.tabs(
            ["📋 Requirements", "❓ Questions (Reviewed)", "💡 Answers", "📅 Study Plan"]
        )

        with tab1:
            st.markdown(
                f'<div class="result-card">{result.requirements}</div>',
                unsafe_allow_html=True,
            )
        with tab2:
            st.markdown(
                f'<div class="result-card">{result.reviewed_questions}</div>',
                unsafe_allow_html=True,
            )
        with tab3:
            st.markdown(
                f'<div class="result-card">{result.answers}</div>',
                unsafe_allow_html=True,
            )
        with tab4:
            st.markdown(
                f'<div class="result-card">{result.study_plan}</div>',
                unsafe_allow_html=True,
            )

        full_report = f"""# Interview Prep Report

## Extracted Requirements
{result.requirements}

## Interview Questions (Reviewed)
{result.reviewed_questions}

## Sample Answers / Frameworks
{result.answers}

## 3-Day Study Plan
{result.study_plan}
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
        Built with Streamlit + Groq (Llama 3.1) · Agentic 5-step pipeline with Reviewer Agent
    </div>
    """,
    unsafe_allow_html=True,
)