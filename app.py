import base64
import html
import re
from pathlib import Path
from typing import Any

import streamlit as st
from markdown import markdown

from src.agent import analyze_skill_gap
from src.graph import run_graph_pipeline
from src.parser import extract_resume_text
from src.utils import compute_match_score


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Interview Prep Agent",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# APPROVED WALLPAPER ASSET
# ============================================================

WALLPAPER_PATH = Path(__file__).resolve().parent / "assets" / "prep_wallpaper.webp"

if WALLPAPER_PATH.exists():
    WALLPAPER_B64 = base64.b64encode(WALLPAPER_PATH.read_bytes()).decode("utf-8")
else:
    WALLPAPER_B64 = ""



# ============================================================
# SESSION STATE
# ============================================================

DEFAULTS = {
    "view": "home",
    "result": None,
    "match_score": None,
    "skill_gap": None,
    "last_jd": "",
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


NAV_ITEMS = [
    ("Home", "home"),
    ("Features", "features"),
    ("Workflow", "workflow"),
    ("FAQ", "faq"),
]


def go_to(view_name: str) -> None:
    """Switch view and rerun immediately."""
    st.session_state.view = view_name
    st.rerun()


# ============================================================
# HELPERS
# ============================================================

def read_jd_file(uploaded_file) -> str:
    """Read a JD uploaded as PDF, DOCX, or TXT."""
    if uploaded_file is None:
        return ""

    filename = uploaded_file.name.lower()

    if filename.endswith(".txt"):
        return uploaded_file.getvalue().decode("utf-8", errors="ignore")

    uploaded_file.seek(0)
    return extract_resume_text(uploaded_file)


def get_result_field(result: Any, *names: str) -> str:
    """Read a pipeline field from either an object or a dict."""
    if result is None:
        return ""

    for name in names:
        if isinstance(result, dict) and name in result:
            value = result.get(name)
            if value is not None:
                return str(value)

        value = getattr(result, name, None)
        if value is not None:
            return str(value)

    return ""


def clean_markdown_text(value: str) -> str:
    """Normalize LLM markdown without changing its meaning."""
    if not value:
        return ""

    value = str(value).strip()

    # Remove accidental outer code fences if a model wrapped the whole answer.
    if value.startswith("```") and value.endswith("```"):
        lines = value.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()

    # Normalize common bullet characters.
    value = value.replace("• ", "- ")
    value = value.replace("– ", "- ")
    value = value.replace("— ", "- ")

    # Avoid excessive blank lines.
    while "\n\n\n" in value:
        value = value.replace("\n\n\n", "\n\n")

    return value.strip()


def get_result_field(result: Any, *names: str) -> str:
    """Read a pipeline field from either an object or a dict."""
    if result is None:
        return ""

    for name in names:
        if isinstance(result, dict) and name in result:
            value = result.get(name)
            if value is not None:
                return clean_markdown_text(str(value))

        value = getattr(result, name, None)
        if value is not None:
            return clean_markdown_text(str(value))

    return ""


def _as_skill_list(value) -> list[str]:
    """Normalize a skill value from list/string into a clean list."""
    if value is None:
        return []

    if isinstance(value, (list, tuple, set)):
        raw_items = [str(item) for item in value]
    else:
        text = clean_markdown_text(str(value))
        raw_items = re.split(r"[\n,;]+", text)

    cleaned = []
    seen = set()

    for item in raw_items:
        item = re.sub(r"^[\-\*\u2022]\s*", "", item).strip()
        item = re.sub(r"^\d+[\.\)]\s*", "", item).strip()
        item = item.strip("[]'\" ")
        if not item:
            continue

        key = item.casefold()
        if key not in seen:
            cleaned.append(item)
            seen.add(key)

    return cleaned


def _markdown_fragment(text: str) -> str:
    """Render model Markdown safely inside custom result accordions."""
    if not text:
        return "<p>No content was returned.</p>"

    safe_source = html.escape(clean_markdown_text(text), quote=False)

    return markdown(
        safe_source,
        extensions=["extra", "sane_lists"],
        output_format="html5",
    )


def _parse_questions(text: str) -> list[dict]:
    """Parse `1. [Domain] Question?` output into structured rows."""
    items = []

    for line in clean_markdown_text(text).splitlines():
        line = line.strip()
        if not line:
            continue

        match = re.match(
            r"^\s*(\d+)[\.\)]\s*(?:\[(.*?)\]\s*)?(.*)$",
            line,
        )

        if not match:
            continue

        number = int(match.group(1))
        domain = (match.group(2) or "Role").strip()
        question = match.group(3).strip()

        if question:
            items.append(
                {
                    "number": number,
                    "domain": domain,
                    "question": question,
                }
            )

    return items


def _parse_answers(text: str) -> dict[int, str]:
    """Parse numbered answer paragraphs into {question_number: answer}."""
    blocks = {}
    current_number = None
    current_lines = []

    for raw_line in clean_markdown_text(text).splitlines():
        line = raw_line.rstrip()
        match = re.match(r"^\s*(\d+)[\.\)]\s+(.*)$", line)

        if match:
            if current_number is not None:
                blocks[current_number] = "\n".join(current_lines).strip()

            current_number = int(match.group(1))
            current_lines = [match.group(2).strip()]
        elif current_number is not None:
            current_lines.append(line)

    if current_number is not None:
        blocks[current_number] = "\n".join(current_lines).strip()

    return blocks


def _escape(value) -> str:
    return html.escape(str(value or ""), quote=True)


def _skills_html(skills: list[str], kind: str) -> str:
    if not skills:
        return '<span class="result-empty-note">No skills returned.</span>'

    if kind == "matched":
        icon = "✓"
        css_class = "result-skill-chip matched"
    elif kind == "missing":
        icon = "×"
        css_class = "result-skill-chip missing"
    else:
        icon = "•"
        css_class = "result-skill-chip neutral"

    return "".join(
        f'<span class="{css_class}"><i>{icon}</i>{_escape(skill)}</span>'
        for skill in skills
    )


def build_report(result: Any, match_score, skill_gap) -> str:
    """Build one clean Markdown report matching the final web structure."""
    role_title = get_result_field(result, "role_title") or "Target Role"

    required_skills = getattr(result, "required_skills", [])
    required_skills = _as_skill_list(required_skills)

    requirements = get_result_field(result, "requirements")
    questions = get_result_field(
        result,
        "reviewed_questions",
        "questions",
        "interview_questions",
    )
    answers = get_result_field(
        result,
        "answers",
        "sample_answers",
        "answer_frameworks",
    )
    study_plan = get_result_field(
        result,
        "study_plan",
        "plan",
        "preparation_plan",
    )

    parts = [
        f"# {role_title} Interview Preparation",
        "",
    ]

    if required_skills:
        parts.extend(
            [
                "## Skills Required by the Role",
                "",
                *[f"- {skill}" for skill in required_skills],
                "",
            ]
        )

    if skill_gap is not None:
        matching = _as_skill_list(getattr(skill_gap, "matching_skills", []))
        missing = _as_skill_list(getattr(skill_gap, "missing_skills", []))
        priority_gap = clean_markdown_text(
            getattr(skill_gap, "priority_gap", "")
        )
        priority_reason = clean_markdown_text(
            getattr(skill_gap, "priority_reason", "")
        )
        suggestion = clean_markdown_text(
            getattr(skill_gap, "suggestion", "")
        )

        parts.extend(
            [
                "## Resume - JD Analysis",
                "",
                f"**Resume–JD Match:** {match_score if match_score is not None else 'N/A'}%",
                "",
                "### Skills Found in Resume",
                "",
                *[f"- {skill}" for skill in matching],
                "",
                "### Skills to Strengthen",
                "",
                *[f"- {skill}" for skill in missing],
            ]
        )

        if priority_gap:
            parts.extend(
                [
                    "",
                    f"### Highest-Priority Gap — {priority_gap}",
                    "",
                    priority_reason,
                ]
            )

        if suggestion:
            parts.extend(
                [
                    "",
                    "### Recommended Next Step",
                    "",
                    suggestion,
                ]
            )

    parts.extend(
        [
            "",
            "## Requirements",
            "",
            requirements or "No requirements were returned.",
            "",
            "## Important Interview Questions",
            "",
            questions or "No interview questions were returned.",
            "",
            "## Sample Answers",
            "",
            answers or "No sample answers were returned.",
            "",
            "## Personalized Study Plan",
            "",
            study_plan or "No study plan was returned.",
            "",
            "---",
            "",
            "Generated by Interview Prep Agent",
        ]
    )

    return "\n".join(parts).strip() + "\n"


def _pdf_safe_text(value: str) -> str:
    """Convert Unicode/Markdown into safe ASCII text for built-in PDF fonts."""
    import unicodedata

    value = str(value)

    replacements = {
        "•": "-",
        "→": "->",
        "←": "<-",
        "↔": "<->",
        "↗": "->",
        "✓": "Yes",
        "✔": "Yes",
        "✦": "*",
        "–": "-",
        "—": "-",
        "‑": "-",
        "−": "-",
        "“": '"',
        "”": '"',
        "„": '"',
        "’": "'",
        "‘": "'",
        "…": "...",
        "≈": "~",
        "≥": ">=",
        "≤": "<=",
        "×": "x",
        "±": "+/-",
        "°": " deg",
        "\u00a0": " ",
        "\u202f": " ",
        "\u2009": " ",
        "\u2007": " ",
        "\u200b": "",
        "\ufeff": "",
    }

    for old, new in replacements.items():
        value = value.replace(old, new)

    value = value.replace("**", "")
    value = value.replace("__", "")
    value = value.replace("`", "")

    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        ch for ch in value
        if not unicodedata.combining(ch)
    )

    # Remove unsupported symbols instead of letting Helvetica show '?'.
    value = value.encode("ascii", "ignore").decode("ascii")

    return value.strip()

def report_to_pdf(report_text: str) -> bytes:
    """Create a robust, readable PDF from the Markdown report."""
    from fpdf import FPDF
    from fpdf.enums import WrapMode, XPos, YPos

    pdf = FPDF(format="A4")
    pdf.set_margins(16, 16, 16)
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()

    # Document title
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(37, 26, 32)
    pdf.multi_cell(
        pdf.epw,
        9,
        "Interview Prep Agent",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
        wrapmode=WrapMode.CHAR,
    )

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(120, 100, 111)
    pdf.multi_cell(
        pdf.epw,
        6,
        "Interview Preparation Report",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
        wrapmode=WrapMode.CHAR,
    )
    pdf.ln(3)

    for raw_line in report_text.splitlines():
        line = raw_line.strip()

        # Skip the repeated top-level Markdown title because we already drew it.
        if line.startswith("# ") and "Interview Prep Agent" in line:
            continue

        if not line:
            pdf.ln(2)
            continue

        if line == "---":
            pdf.set_draw_color(225, 210, 218)
            y = pdf.get_y() + 2
            pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
            pdf.ln(5)
            continue

        safe_line = _pdf_safe_text(line)

        # Always reset X before each multi_cell. This prevents the
        # "Not enough horizontal space to render a single character" error.
        pdf.set_x(pdf.l_margin)

        if line.startswith("## "):
            heading = _pdf_safe_text(line[3:])
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(204, 62, 133)
            pdf.multi_cell(
                pdf.epw,
                8,
                heading,
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
                wrapmode=WrapMode.CHAR,
            )
            pdf.set_text_color(45, 37, 42)
            continue

        if line.startswith("### "):
            heading = _pdf_safe_text(line[4:])
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(90, 70, 81)
            pdf.multi_cell(
                pdf.epw,
                7,
                heading,
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
                wrapmode=WrapMode.CHAR,
            )
            pdf.set_text_color(45, 37, 42)
            continue

        if line.startswith("- ") or line.startswith("* "):
            bullet_text = _pdf_safe_text(line[2:].strip())
            pdf.set_font("Helvetica", "", 10.5)
            pdf.set_text_color(45, 37, 42)
            pdf.multi_cell(
                pdf.epw,
                6,
                f"- {bullet_text}",
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
                wrapmode=WrapMode.CHAR,
            )
            continue

        # Numbered item such as "1. Question..."
        prefix_is_number = False
        if ". " in line:
            first_piece = line.split(". ", 1)[0]
            prefix_is_number = first_piece.isdigit()

        if prefix_is_number:
            pdf.set_font("Helvetica", "B", 10.5)
            pdf.set_text_color(45, 37, 42)
            pdf.multi_cell(
                pdf.epw,
                6,
                safe_line,
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
                wrapmode=WrapMode.CHAR,
            )
            continue

        pdf.set_font("Helvetica", "", 10.5)
        pdf.set_text_color(55, 45, 51)
        pdf.multi_cell(
            pdf.epw,
            6,
            safe_line,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
            wrapmode=WrapMode.CHAR,
        )

    return bytes(pdf.output())


# ============================================================
# FINAL UI THEME
# ============================================================

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Serif+Display&family=Manrope:wght@500;600;700;800&display=swap');

:root {
    --bg: #fff9fc;
    --paper: #fffefe;
    --text: #20171e;
    --muted: #7e7079;
    --line: rgba(75,45,62,.10);
    --pink: #e45c9d;
    --pink-strong: #d63e88;
    --pink-soft: #fde9f3;
    --shadow: 0 24px 70px rgba(101,54,77,.10);
}

html {
    scroll-behavior: smooth;
}

body {
    font-family: "DM Sans", sans-serif;
}

.stApp {
    color: var(--text);
    background:
        linear-gradient(rgba(255,249,252,.52), rgba(255,251,253,.58)),
        url("data:image/jpeg;base64,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AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAfIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB6mAAAAAAAAAAAAAB8AAAAAAAAAAHwAAAfIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHuAAAAAAAAAAAAAAAAAAAfAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB8AAAAf6AAAAAAAAAAAH9AAAAAAAAAAAAAAAAAAAAAAA+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD5AAAAAAAAAAAAAAAAAAAAAAAAAOgAAAAAAAAAPgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAPjoAAAAAAAAAAAAAAAAAAD4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADIAAAAAAAAAAHsAAAAAAAAAAAAAAD4AAAAAAA+QAAAAAAAAAAAAAAAAAAAAAAAAAAPgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACegAAAAAAAAAAAAA0AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAPk+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD8AAAAAAAAAAAAAAAAAAAAAAAAAAA+QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP9AAPkAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/AAAAAAAAAAAAAAAAAAAAAAAAPkAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIAAAAAAAAAAAAAAfIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB8AAAAAAAAb2AAH+gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAfIfAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHyfIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHwAAB+gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAfAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHsAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADQA+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD5AAAAAAAAAAAAAAAAAAA9wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP6AAAAAAAAAAAB8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB8AAAAAAAAAAAAAAAAAAAAAAAfAAAAAAAAAAAAAAAAAAAAAAAHyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAaAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAfIAAAAAAAAAAAAAAAAAAAAAAAAAAB8gfIAAAAAAAAAAAHqaAAAAAAAAAAAAAAAAAAAAAAAHyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAfIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA0AyNAMjQDI0AyNAMjScfX9oINAMjQDOjQDI0AyNAMjQDI0AyNAMjQDI0AyNAMiz3f8AVBkWf/GE9f0EGgGRoBkaAZGsn0ZPoGRpP/tQQaAZGgGRoBkaAZGgGRoBkaAZGgGRoBkaAZGgGRoBkaAZGgGRoBkaAZGgGRrJ9AMjWT6AZGsn0AyNAMjQDIs9RQZGk+wQaAZGjJ9AyNAMjQDI0AyNAMjRk+gZ+RoBkaAZGgGRoBkaAZFnu/6oMjQDI0AyLx/+Ev4oMjRk+gZGgGRpICDQDIt9UgINAMi/KgyNAMjQDI0AyNAMjQDI1k+gGRoBkaAZGsn0AyNAMjQDI0AyLy9f2LkBkaAZGgGRrIAyNAMjWT6AZGsgDI1kAZGgGRoBkaAZGgGRoBkX7UGRoBkaAZGjJ9AyNAMjQDI0AyNAMjQDI0AyNAMjQDI0AyNAMjQDI0AyNAP/2Q==") center/cover fixed no-repeat;
}

[data-testid="stHeader"] {
    background: transparent !important;
}

[data-testid="stDecoration"] {
    display: none !important;
}

.block-container {
    max-width: 1180px !important;
    padding-top: 4.35rem !important;
    padding-bottom: 3rem !important;
}

#MainMenu,
footer {
    visibility: hidden;
}


/* ---------------- NAV ---------------- */

.nav-shell {
    min-height: 64px;
    display: flex;
    align-items: center;
    padding: 8px 14px;
    margin-bottom: 4px;
    border: 1px solid var(--line);
    border-radius: 22px;
    background: rgba(255,255,255,.82);
    backdrop-filter: blur(22px);
    -webkit-backdrop-filter: blur(22px);
    box-shadow: 0 10px 32px rgba(75,40,59,.06);
}

.nav-brand {
    font-family: "Manrope", sans-serif;
    font-size: 23px;
    font-weight: 800;
    letter-spacing: -1.5px;
    color: var(--text);
}

.nav-brand span {
    color: var(--pink);
}

.nav-spacer {
    height: 4px;
}

.stButton > button {
    border: 1px solid transparent !important;
    border-radius: 999px !important;
    min-height: 42px !important;
    font-family: "DM Sans", sans-serif !important;
    font-size: 12px !important;
    font-weight: 700 !important;
    transition: transform .22s ease, box-shadow .22s ease, background .22s ease !important;
}

.stButton > button:not([kind="primary"]) {
    background: rgba(255,255,255,.72) !important;
    color: #7f7079 !important;
}

.stButton > button:not([kind="primary"]):hover {
    background: #ffffff !important;
    color: var(--text) !important;
    transform: translateY(-1px);
    border-color: rgba(228,92,157,.14) !important;
}

.stButton > button[kind="primary"] {
    background: #2b1f27 !important;
    color: #ffffff !important;
    border-color: #2b1f27 !important;
    box-shadow: 0 10px 26px rgba(42,29,36,.14);
}

.stButton > button[kind="primary"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 13px 30px rgba(42,29,36,.19);
}


/* ---------------- HOME ---------------- */

.hero {
    position: relative;
    min-height: 690px;
    overflow: hidden;
    margin-top: 18px;
    border: 1px solid rgba(97,54,76,.07);
    border-radius: 34px;
    background:
        linear-gradient(rgba(255,251,253,.22),rgba(255,251,253,.36)),
        url("data:image/jpeg;base64,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AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAfIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB6mAAAAAAAAAAAAAB8AAAAAAAAAAHwAAAfIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHuAAAAAAAAAAAAAAAAAAAfAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB8AAAAf6AAAAAAAAAAAH9AAAAAAAAAAAAAAAAAAAAAAA+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD5AAAAAAAAAAAAAAAAAAAAAAAAAOgAAAAAAAAAPgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAPjoAAAAAAAAAAAAAAAAAAD4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADIAAAAAAAAAAHsAAAAAAAAAAAAAAD4AAAAAAA+QAAAAAAAAAAAAAAAAAAAAAAAAAAPgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACegAAAAAAAAAAAAA0AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAPk+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD8AAAAAAAAAAAAAAAAAAAAAAAAAAA+QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP9AAPkAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/AAAAAAAAAAAAAAAAAAAAAAAAPkAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIAAAAAAAAAAAAAAfIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB8AAAAAAAAb2AAH+gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAfIfAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHyfIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHwAAB+gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAfAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHsAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADQA+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD5AAAAAAAAAAAAAAAAAAA9wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP6AAAAAAAAAAAB8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB8AAAAAAAAAAAAAAAAAAAAAAAfAAAAAAAAAAAAAAAAAAAAAAAHyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAaAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAfIAAAAAAAAAAAAAAAAAAAAAAAAAAB8gfIAAAAAAAAAAAHqaAAAAAAAAAAAAAAAAAAAAAAAHyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAfIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA0AyNAMjQDI0AyNAMjScfX9oINAMjQDOjQDI0AyNAMjQDI0AyNAMjQDI0AyNAMiz3f8AVBkWf/GE9f0EGgGRoBkaAZGsn0ZPoGRpP/tQQaAZGgGRoBkaAZGgGRoBkaAZGgGRoBkaAZGgGRoBkaAZGgGRoBkaAZGgGRrJ9AMjWT6AZGsn0AyNAMjQDIs9RQZGk+wQaAZGjJ9AyNAMjQDI0AyNAMjRk+gZ+RoBkaAZGgGRoBkaAZFnu/6oMjQDI0AyLx/+Ev4oMjRk+gZGgGRpICDQDIt9UgINAMi/KgyNAMjQDI0AyNAMjQDI1k+gGRoBkaAZGsn0AyNAMjQDI0AyLy9f2LkBkaAZGgGRrIAyNAMjWT6AZGsgDI1kAZGgGRoBkaAZGgGRoBkX7UGRoBkaAZGjJ9AyNAMjQDI0AyNAMjQDI0AyNAMjQDI0AyNAMjQDI0AyNAP/2Q==") center/cover no-repeat;
    box-shadow: 0 20px 70px rgba(110,60,84,.06);
}

.hero-atmosphere {
    position: absolute;
    inset: 0;
    pointer-events: none;
    overflow: hidden;
}

.bird {
    position: absolute;
    width: 46px;
    height: 26px;
    opacity: .30;
    animation: birdFlight linear infinite;
}

.bird svg {
    width: 100%;
    height: 100%;
}

.bird path {
    fill: rgba(74,54,65,.72);
}

.bird.b1 {
    top: 20%;
    left: -80px;
    animation-duration: 21s;
}

.bird.b2 {
    top: 32%;
    left: -100px;
    width: 31px;
    opacity: .24;
    animation-duration: 27s;
    animation-delay: 7s;
}

.bird.b3 {
    top: 14%;
    left: -100px;
    width: 24px;
    opacity: .18;
    animation-duration: 33s;
    animation-delay: 14s;
}

@keyframes birdFlight {
    0% { left: -90px; transform: translateY(4px) rotate(-4deg); }
    30% { transform: translateY(-14px) rotate(2deg); }
    58% { transform: translateY(7px) rotate(-1deg); }
    100% { left: calc(100% + 100px); transform: translateY(-5px) rotate(3deg); }
}

.spark {
    position: absolute;
    color: var(--pink);
    opacity: .22;
    font-size: 15px;
    animation: spark 4.2s ease-in-out infinite;
}

.s1 { left: 15%; top: 27%; }
.s2 { right: 17%; top: 20%; animation-delay: 1.2s; }
.s3 { left: 20%; bottom: 20%; animation-delay: 2.2s; }
.s4 { right: 24%; bottom: 25%; animation-delay: 3s; }

@keyframes spark {
    0%,100% { opacity: .10; transform: translateY(0) scale(.78) rotate(0); }
    50% { opacity: .50; transform: translateY(-9px) scale(1.18) rotate(12deg); }
}

.hero-inner {
    position: relative;
    z-index: 3;
    min-height: 690px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 62px 24px 66px;
}

.project-title {
    margin: 0;
    max-width: 920px;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: clamp(64px, 8vw, 105px);
    line-height: .90;
    letter-spacing: -.052em;
    font-weight: 400;
    color: var(--text);
}

.project-title span {
    color: var(--pink-strong);
}

.hero-tagline {
    margin-top: 18px;
    font-family: "Manrope", sans-serif;
    font-size: clamp(28px, 4vw, 48px);
    line-height: 1.02;
    letter-spacing: -.045em;
    font-weight: 700;
    color: #2d2229;
}

.gradient {
    background: linear-gradient(90deg, #21181e 0%, #d63e88 44%, #ee8ebc 65%, #21181e 100%);
    background-size: 220% auto;
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
    animation: gradientShift 7s linear infinite;
}

@keyframes gradientShift {
    to { background-position: 220% center; }
}

.hero-copy {
    max-width: 620px;
    margin-top: 18px;
    color: #776a72;
    font-size: 15px;
    line-height: 1.78;
}

.capability-strip {
    display: flex;
    justify-content: center;
    flex-wrap: wrap;
    gap: 7px;
    margin-top: 21px;
}

.mini-pill {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    min-height: 30px;
    padding: 7px 10px;
    border: 1px solid rgba(92,54,74,.09);
    border-radius: 999px;
    background: rgba(255,255,255,.58);
    color: #755f6b;
    font-size: 9px;
    font-weight: 700;
    box-shadow: 0 6px 16px rgba(91,50,70,.04);
}

.mini-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--pink);
    box-shadow: 0 0 0 4px rgba(228,92,157,.08);
}


/* ---------------- CONTENT PANELS ---------------- */

.page-panel {
    margin-top: 28px;
    padding: 46px 30px 38px;
    border: 1px solid rgba(73,44,60,.09);
    border-radius: 34px;
    background: rgba(255,255,255,.91);
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
    box-shadow: 0 28px 80px rgba(78,46,62,.11);
    animation: pageIn .45s cubic-bezier(.2,.8,.2,1) both;
}

@keyframes pageIn {
    from { opacity: 0; transform: translateY(14px); filter: blur(3px); }
    to { opacity: 1; transform: none; filter: blur(0); }
}

.section-head {
    max-width: 760px;
    margin: 0 auto 38px;
    text-align: center;
}

.kicker {
    color: var(--pink-strong);
    font-size: 10px;
    font-weight: 800;
    letter-spacing: .16em;
    text-transform: uppercase;
}

.section-title {
    margin-top: 11px;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: clamp(42px, 5vw, 64px);
    line-height: 1.02;
    letter-spacing: -.035em;
    font-weight: 400;
}

.section-title span {
    color: var(--pink-strong);
}

.section-copy {
    max-width: 620px;
    margin: 17px auto 0;
    color: #8d7d86;
    font-size: 14px;
    line-height: 1.75;
}

.cards-4 {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 14px;
}

.cards-5 {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 12px;
}

.pretty-card {
    position: relative;
    min-height: 235px;
    overflow: hidden;
    padding: 24px;
    border: 1px solid rgba(68,43,56,.09);
    border-radius: 24px;
    color: #251b21;
    transition: .28s cubic-bezier(.2,.8,.2,1);
    animation: cardRise .58s cubic-bezier(.2,.8,.2,1) both;
}

.pretty-card:nth-child(2) { animation-delay: .07s; }
.pretty-card:nth-child(3) { animation-delay: .14s; }
.pretty-card:nth-child(4) { animation-delay: .21s; }
.pretty-card:nth-child(5) { animation-delay: .28s; }

.cards-4 .pretty-card:nth-child(1),
.cards-5 .pretty-card:nth-child(1) { background: #ffd7e1; }

.cards-4 .pretty-card:nth-child(2),
.cards-5 .pretty-card:nth-child(2) { background: #d9e9ff; }

.cards-4 .pretty-card:nth-child(3),
.cards-5 .pretty-card:nth-child(3) { background: #d7f2df; }

.cards-4 .pretty-card:nth-child(4),
.cards-5 .pretty-card:nth-child(4) { background: #ffe8b7; }

.cards-5 .pretty-card:nth-child(5) { background: #eadcff; }

.pretty-card:hover {
    transform: translateY(-8px) rotate(-.25deg);
    box-shadow: 0 24px 50px rgba(74,44,59,.13);
}

@keyframes cardRise {
    from { opacity: 0; transform: translateY(18px) scale(.985); }
    to { opacity: 1; transform: translateY(0) scale(1); }
}

.card-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.card-icon {
    width: 44px;
    height: 44px;
    display: grid;
    place-items: center;
    border-radius: 14px;
    background: rgba(255,255,255,.88);
    color: #4f3c46;
    box-shadow: 0 6px 18px rgba(69,43,56,.07);
    font-weight: 800;
}

.card-num {
    color: #806c76;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: .11em;
}

.card-label {
    margin-top: 17px;
    color: #8f7482;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: .15em;
    text-transform: uppercase;
}

.pretty-card h3 {
    margin: 10px 0 0;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: 21px;
    font-weight: 400;
    letter-spacing: -.018em;
}

.pretty-card p {
    margin: 9px 0 0;
    color: #685963;
    font-size: 12px;
    line-height: 1.7;
}

.card-foot {
    position: absolute;
    left: 24px;
    bottom: 19px;
    padding: 6px 9px;
    border: 1px solid rgba(255,255,255,.55);
    border-radius: 999px;
    background: rgba(255,255,255,.48);
    color: #7e6673;
    font-size: 9px;
    font-weight: 800;
}


/* ---------------- WORKSPACE ---------------- */

.workspace-card {
    padding: 28px;
    border: 1px solid var(--line);
    border-radius: 28px;
    background: #ffffff;
    box-shadow: var(--shadow);
}

.workspace-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 18px;
    margin-bottom: 17px;
}

.workspace-head h3 {
    margin: 0;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: 28px;
    font-weight: 400;
}

.workspace-head p {
    margin: 7px 0 0;
    color: var(--muted);
    font-size: 13px;
}

.status-pill {
    white-space: nowrap;
    padding: 8px 11px;
    border: 1px solid #f6dce8;
    border-radius: 999px;
    background: #fff4f8;
    color: #b84c7e;
    font-size: 10px;
    font-weight: 800;
}

.stTextArea textarea {
    min-height: 210px !important;
    border: 1px solid var(--line) !important;
    border-radius: 20px !important;
    background: #fffdfd !important;
    color: var(--text) !important;
    padding: 18px !important;
    font-family: "DM Sans", sans-serif !important;
    font-size: 13px !important;
    line-height: 1.7 !important;
}

.stTextArea textarea:focus {
    border-color: rgba(228,92,157,.50) !important;
    box-shadow: 0 0 0 4px rgba(228,92,157,.08) !important;
}

[data-testid="stFileUploader"] {
    padding: 8px;
    border: 1px dashed rgba(100,58,80,.16);
    border-radius: 16px;
    background: #fffbfd;
}

[data-testid="stPopover"] button {
    border-radius: 17px !important;
}

.upload-note {
    color: #a08c97;
    font-size: 10px;
}


/* ---------------- RESULTS ---------------- */

[data-testid="stVerticalBlockBorderWrapper"] {
    border-color: var(--line) !important;
    border-radius: 20px !important;
    background: #ffffff;
}

.stTabs [data-baseweb="tab-list"] {
    gap: 5px;
    padding: 5px;
    border-radius: 999px;
    background: #f8edf3;
}

.stTabs [data-baseweb="tab"] {
    border-radius: 999px;
    padding: 9px 14px;
    color: #8d7884;
    font-size: 11px;
}

.stTabs [aria-selected="true"] {
    background: #ffffff;
    color: var(--text) !important;
    box-shadow: 0 2px 8px rgba(70,41,57,.07);
}

.score-box {
    text-align: center;
    padding: 18px;
    border: 1px solid var(--line);
    border-radius: 20px;
    background: #fff7fa;
}

.score-label {
    color: #9f818f;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: .11em;
    text-transform: uppercase;
}

.score-value {
    margin-top: 5px;
    font-family: "Manrope", sans-serif;
    color: var(--pink-strong);
    font-size: 42px;
    font-weight: 800;
    letter-spacing: -.05em;
}


/* ---------------- FAQ ---------------- */

[data-testid="stExpander"] {
    border: 1px solid var(--line) !important;
    border-radius: 19px !important;
    background: rgba(255,255,255,.96) !important;
    transition: .22s ease;
}

[data-testid="stExpander"]:hover {
    border-color: rgba(228,92,157,.23) !important;
    box-shadow: 0 12px 30px rgba(93,53,73,.05);
}


/* ---------------- FOOTER ---------------- */

.site-footer {
    margin-top: 48px;
    padding: 22px 0 8px;
    text-align: center;
}

.feedback-row {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-wrap: wrap;
    gap: 9px;
    color: #8b7a83;
    font-size: 11px;
}

.feedback-label {
    font-family: "DM Serif Display", Georgia, serif;
    font-size: 14px;
    color: #75636d;
}

.footer-link {
    display: inline-flex;
    align-items: center;
    padding: 8px 11px;
    border: 1px solid rgba(74,44,59,.10);
    border-radius: 999px;
    background: rgba(255,255,255,.84);
    color: #4f3d47 !important;
    text-decoration: none !important;
    font-size: 10px;
    font-weight: 800;
}

.github-footer {
    width: min(680px,100%);
    margin: 15px auto 0;
    padding: 11px 14px;
    border-top: 1px solid rgba(73,44,60,.07);
    border-bottom: 1px solid rgba(73,44,60,.07);
    color: #81717a;
    font-size: 10px;
}

.project-year {
    margin-top: 12px;
    color: #aa97a1;
    font-size: 9px;
    letter-spacing: .06em;
}

@media (max-width: 900px) {
    .cards-4,
    .cards-5 {
        grid-template-columns: repeat(2, 1fr);
    }
}

@media (max-width: 650px) {
    .block-container {
        padding-left: .55rem !important;
        padding-right: .55rem !important;
    }

    .hero {
        min-height: 650px;
        border-radius: 26px;
    }

    .hero-inner {
        min-height: 650px;
        padding: 55px 18px;
    }

    .project-title {
        font-size: 56px;
    }

    .hero-tagline {
        font-size: 31px;
    }

    .page-panel {
        padding: 34px 16px 28px;
        border-radius: 26px;
    }

    .cards-4,
    .cards-5 {
        grid-template-columns: 1fr;
    }

    .workspace-head {
        display: block;
    }

    .status-pill {
        display: inline-block;
        margin-top: 12px;
    }
}

@media (prefers-reduced-motion: reduce) {
    *,*::before,*::after {
        animation-duration: .001ms !important;
        animation-iteration-count: 1 !important;
        scroll-behavior: auto !important;
    }
}


/* ---------------- DESKTOP FIT + RELIABLE NAV ---------------- */

[data-testid="stAppViewContainer"] .main .block-container {
    width: calc(100% - 32px) !important;
    max-width: 1400px !important;
    padding-left: 0 !important;
    padding-right: 0 !important;
    padding-top: .65rem !important;
}

.desktop-nav-row {
    margin-bottom: 6px;
}


.hero,
.hero-inner {
    height: clamp(510px, calc(100vh - 220px), 590px) !important;
    min-height: 510px !important;
}

.hero-inner {
    padding-top: 42px !important;
    padding-bottom: 42px !important;
}

.project-title {
    font-size: clamp(58px, 7vw, 94px) !important;
}

.hero-tagline {
    font-size: clamp(25px, 3.3vw, 42px) !important;
}

.page-panel {
    margin-top: 18px !important;
}

@media (min-width: 1200px) {
    .cards-4 { gap: 18px !important; }
    .cards-5 { gap: 14px !important; }
    .pretty-card { min-height: 225px !important; }
}

@media (max-width: 900px) {
    [data-testid="stAppViewContainer"] .main .block-container {
        width: calc(100% - 20px) !important;
    }
}


/* Reliable desktop navigation */
div[data-testid="stHorizontalBlock"]:has(.nav-brand){
    position: relative !important;
    top: auto !important;
    z-index: 30 !important;
    padding: 7px 10px;
    border: 1px solid rgba(75,45,62,.09);
    border-radius: 22px;
    background: rgba(255,255,255,.90);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    box-shadow: 0 10px 30px rgba(75,40,59,.07);
}

div[data-testid="stHorizontalBlock"]:has(.nav-brand) .stButton > button{
    min-height: 40px !important;
    padding: 8px 11px !important;
    box-shadow: none !important;
}

div[data-testid="stHorizontalBlock"]:has(.nav-brand) .stButton > button[kind="secondary"]{
    background: transparent !important;
    color: #75656e !important;
    border-color: transparent !important;
}

div[data-testid="stHorizontalBlock"]:has(.nav-brand) .stButton > button[kind="secondary"]:hover{
    background: rgba(250,244,247,.95) !important;
    color: #20171e !important;
}

div[data-testid="stHorizontalBlock"]:has(.nav-brand) .stButton > button[kind="primary"]{
    background: #2b1f27 !important;
    color: white !important;
    border-color: #2b1f27 !important;
}

@media(max-width: 820px){
    div[data-testid="stHorizontalBlock"]:has(.nav-brand){
        position: static;
        padding: 6px;
    }
}


/* FINAL NAV CLICK-TARGET FIX
   The visible rounded tab and the real Streamlit button now share the same box. */
div[data-testid="stHorizontalBlock"]:has(.nav-brand) div[data-testid="column"] {
    position: relative !important;
    min-width: 0 !important;
    overflow: visible !important;
}

div[data-testid="stHorizontalBlock"]:has(.nav-brand) .stButton {
    width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
}

div[data-testid="stHorizontalBlock"]:has(.nav-brand) .stButton > button {
    position: relative !important;
    z-index: 50 !important;
    width: 100% !important;
    min-width: 0 !important;
    height: 44px !important;
    min-height: 44px !important;
    margin: 0 !important;
    padding: 0 14px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    border-radius: 14px !important;
    cursor: pointer !important;
    pointer-events: auto !important;
    transform: none !important;
    line-height: 1 !important;
}

/* Child text must never steal the pointer event from the button. */
div[data-testid="stHorizontalBlock"]:has(.nav-brand) .stButton > button * {
    pointer-events: none !important;
}

div[data-testid="stHorizontalBlock"]:has(.nav-brand) .stButton > button[kind="secondary"] {
    background: rgba(249,243,247,.94) !important;
    border: 1px solid rgba(77,48,64,.08) !important;
    color: #75656e !important;
}

div[data-testid="stHorizontalBlock"]:has(.nav-brand) .stButton > button[kind="secondary"]:hover {
    background: #ffffff !important;
    border-color: rgba(228,92,157,.20) !important;
    color: #20171e !important;
    transform: none !important;
}

div[data-testid="stHorizontalBlock"]:has(.nav-brand) .stButton > button[kind="primary"] {
    background: #2b1f27 !important;
    border: 1px solid #2b1f27 !important;
    color: #ffffff !important;
    transform: none !important;
}

div[data-testid="stHorizontalBlock"]:has(.nav-brand) .stButton > button:focus,
div[data-testid="stHorizontalBlock"]:has(.nav-brand) .stButton > button:focus-visible {
    outline: 2px solid rgba(228,92,157,.42) !important;
    outline-offset: 2px !important;
    box-shadow: none !important;
}


/* ==========================================================
   REFINED TOP NAV — TEXT LINKS, NOT BIG BOXES
   ========================================================== */

/* keep the sticky nav shell subtle and compact */
div[data-testid="stHorizontalBlock"]:has(.nav-brand){
    padding: 5px 14px !important;
    min-height: 54px !important;
    border-radius: 18px !important;
    align-items: center !important;
}

/* text-only Home / Features / Workflow / FAQ */
.st-key-top_home button,
.st-key-top_features button,
.st-key-top_workflow button,
.st-key-top_faq button{
    width: auto !important;
    min-width: 0 !important;
    min-height: 34px !important;
    height: auto !important;
    padding: 7px 2px !important;
    margin: 0 !important;
    border: 0 !important;
    border-radius: 0 !important;
    background: transparent !important;
    box-shadow: none !important;
    color: #75656e !important;
    font-size: 12px !important;
    font-weight: 650 !important;
    line-height: 1.15 !important;
    transform: none !important;
}

.st-key-top_home button:hover,
.st-key-top_features button:hover,
.st-key-top_workflow button:hover,
.st-key-top_faq button:hover{
    color: #20171e !important;
    background: transparent !important;
    border: 0 !important;
    box-shadow: inset 0 -1px 0 #e45c9d !important;
    transform: none !important;
}

.st-key-top_home button:focus,
.st-key-top_features button:focus,
.st-key-top_workflow button:focus,
.st-key-top_faq button:focus{
    outline: none !important;
    box-shadow: inset 0 -2px 0 #e45c9d !important;
}

/* selected page gets a clean pink underline */

/* Start Preparing stays a small intentional CTA */
.st-key-top_prepare button{
    width: auto !important;
    min-height: 36px !important;
    padding: 9px 14px !important;
    border-radius: 999px !important;
    background: #2b1f27 !important;
    border-color: #2b1f27 !important;
    color: #fff !important;
    font-size: 11px !important;
    font-weight: 750 !important;
    box-shadow: 0 8px 18px rgba(42,29,36,.10) !important;
    transform: none !important;
}

.st-key-top_prepare button:hover{
    transform: none !important;
    background: #3a2933 !important;
}

/* ==========================================================
   FEATURES / WORKFLOW — NO OUTER STARTING RECTANGLE
   ========================================================== */

.section-free{
    margin-top: 46px;
    padding: 12px 4px 34px;
    background: transparent;
    border: 0;
    box-shadow: none;
    animation: pageIn .45s cubic-bezier(.2,.8,.2,1) both;
}

.section-free .section-head{
    margin-bottom: 34px;
}

/* slightly more editorial, not boxed */
.section-free .kicker{
    font-size: 11px;
    letter-spacing: .15em;
}

.section-free .section-title{
    font-size: clamp(42px, 4.8vw, 62px);
}

.section-free .section-copy{
    max-width: 580px;
}

/* ==========================================================
   FAQ — EDITORIAL / FOLIO-LIKE STRUCTURE
   ========================================================== */

.faq-editorial-head{
    margin: 52px auto 30px;
    max-width: 860px;
    padding: 0 6px;
    text-align: left;
}

.faq-main-title{
    margin: 0;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: clamp(64px, 8vw, 96px);
    line-height: .90;
    letter-spacing: -.045em;
    font-weight: 400;
    color: #d63e88;
}

.faq-main-title span{
    color: #20171e;
}

.faq-intro{
    margin-top: 18px;
    max-width: 620px;
    color: #7d6e76;
    font-size: 14px;
    line-height: 1.72;
}

/* Remove large rounded FAQ rectangles */
div[data-testid="stExpander"]{
    max-width: 860px !important;
    margin-left: auto !important;
    margin-right: auto !important;
    border: 0 !important;
    border-bottom: 1px solid rgba(75,45,62,.12) !important;
    border-radius: 0 !important;
    background: transparent !important;
    box-shadow: none !important;
    overflow: visible !important;
}

div[data-testid="stExpander"]:hover{
    border-color: rgba(214,62,136,.30) !important;
    box-shadow: none !important;
    transform: none !important;
}

div[data-testid="stExpander"] details{
    background: transparent !important;
}

/* Question = dark, elegant, smaller and not overly bold */
div[data-testid="stExpander"] summary{
    padding: 15px 2px !important;
    color: #241a20 !important;
}

div[data-testid="stExpander"] summary p{
    font-family: "DM Serif Display", Georgia, serif !important;
    font-size: 17px !important;
    line-height: 1.35 !important;
    font-weight: 400 !important;
    letter-spacing: -.008em !important;
    color: #241a20 !important;
}

/* pink disclosure arrow/accent */
div[data-testid="stExpander"] summary svg{
    fill: #d63e88 !important;
    color: #d63e88 !important;
}

/* Answer = smaller, regular, readable dark gray */
div[data-testid="stExpander"] [data-testid="stExpanderDetails"]{
    padding: 0 2px 16px !important;
}

div[data-testid="stExpander"] [data-testid="stExpanderDetails"] p{
    margin: 0 !important;
    color: #5f5259 !important;
    font-family: "DM Sans", sans-serif !important;
    font-size: 13px !important;
    line-height: 1.72 !important;
    font-weight: 400 !important;
}

@media(max-width: 760px){
    div[data-testid="stHorizontalBlock"]:has(.nav-brand){
        padding: 4px 8px !important;
    }

    .st-key-top_home button,
    .st-key-top_features button,
    .st-key-top_workflow button,
    .st-key-top_faq button{
        font-size: 11px !important;
        padding: 6px 1px !important;
    }

    .st-key-top_prepare button{
        padding: 8px 10px !important;
        font-size: 10px !important;
    }

    .section-free{
        margin-top: 28px;
        padding-left: 2px;
        padding-right: 2px;
    }

    .faq-editorial-head{
        margin-top: 34px;
    }

    .faq-main-title{
        font-size: 62px;
    }

    div[data-testid="stExpander"] summary p{
        font-size: 16px !important;
    }
}


/* ==========================================================
   FINAL TOP NAV — TRUE TEXT-ONLY LINKS
   ========================================================== */

div[data-testid="stHorizontalBlock"]:has(.nav-brand){
    padding: 4px 12px !important;
    min-height: 48px !important;
    border: 0 !important;
    border-bottom: 1px solid rgba(75,45,62,.08) !important;
    border-radius: 0 !important;
    background: rgba(255,255,255,.68) !important;
    box-shadow: none !important;
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
}

/* shrink the columns so the clickable hitbox stays close to the word */
div[data-testid="stHorizontalBlock"]:has(.nav-brand) div[data-testid="column"]{
    min-width: 0 !important;
}

/* Home / Features / Workflow / FAQ = plain words */
.st-key-top_home,
.st-key-top_features,
.st-key-top_workflow,
.st-key-top_faq{
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}

.st-key-top_home .stButton,
.st-key-top_features .stButton,
.st-key-top_workflow .stButton,
.st-key-top_faq .stButton{
    width: auto !important;
    display: inline-flex !important;
}

.st-key-top_home button,
.st-key-top_features button,
.st-key-top_workflow button,
.st-key-top_faq button{
    width: auto !important;
    min-width: 0 !important;
    max-width: max-content !important;
    min-height: 30px !important;
    padding: 5px 1px !important;
    margin: 0 auto !important;
    border: 0 !important;
    border-radius: 0 !important;
    background: transparent !important;
    box-shadow: none !important;
    color: #6f6069 !important;
    font-size: 12px !important;
    font-weight: 650 !important;
    line-height: 1.2 !important;
    transform: none !important;
}

.st-key-top_home button:hover,
.st-key-top_features button:hover,
.st-key-top_workflow button:hover,
.st-key-top_faq button:hover{
    color: #d63e88 !important;
    background: transparent !important;
    box-shadow: inset 0 -1px 0 #d63e88 !important;
    transform: none !important;
}

/* Start preparing remains the only actual pill */
.st-key-top_prepare button{
    min-height: 34px !important;
    padding: 8px 13px !important;
    border-radius: 999px !important;
    font-size: 10.5px !important;
}

/* ==========================================================
   HOME — SAME DESIGN LANGUAGE AS FEATURES / WORKFLOW
   ========================================================== */

.home-structured{
    margin-top: 38px;
}

.home-structured .section-head{
    max-width: 780px;
    margin-bottom: 34px;
}

.home-structured .kicker{
    color: #d63e88;
    font-size: 11px;
}

.home-structured .section-title{
    font-size: clamp(48px, 5.7vw, 72px);
}

.home-structured .section-copy{
    max-width: 650px;
    font-size: 14px;
}

.home-cards{
    display: grid;
    grid-template-columns: repeat(3, minmax(0,1fr));
    gap: 14px;
}

.home-card{
    position: relative;
    min-height: 250px;
    overflow: hidden;
    padding: 24px;
    border: 1px solid rgba(68,43,56,.08);
    border-radius: 22px;
    transition: transform .28s cubic-bezier(.2,.8,.2,1), box-shadow .28s ease;
    animation: cardRise .58s cubic-bezier(.2,.8,.2,1) both;
}

.home-card:nth-child(2){ animation-delay: .08s; }
.home-card:nth-child(3){ animation-delay: .16s; }

.home-card-pink{ background: #ffd7e1; }
.home-card-blue{ background: #d9e9ff; }
.home-card-green{ background: #d7f2df; }

.home-card:hover{
    transform: translateY(-7px) rotate(-.2deg);
    box-shadow: 0 24px 48px rgba(74,44,59,.12);
}

.home-card h3{
    margin: 10px 0 0;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: 22px;
    font-weight: 400;
    letter-spacing: -.018em;
    color: #251b21;
}

.home-card p{
    margin: 9px 0 0;
    color: #685963;
    font-size: 12px;
    line-height: 1.7;
}

/* ==========================================================
   FAQ — SAME STRUCTURE AS FEATURES / WORKFLOW
   ========================================================== */

.faq-structured{
    margin-top: 42px;
}

.faq-structured .section-head{
    max-width: 760px;
    margin-bottom: 34px;
}

.faq-structured .kicker{
    color: #d63e88;
    font-size: 11px;
}

.faq-structured .section-title{
    font-size: clamp(42px, 4.8vw, 62px);
}

.faq-grid{
    display: grid;
    grid-template-columns: repeat(2, minmax(0,1fr));
    gap: 13px;
}

.faq-card{
    min-width: 0;
    overflow: hidden;
    border: 1px solid rgba(68,43,56,.08);
    border-radius: 20px;
    transition: transform .25s ease, box-shadow .25s ease;
}

.faq-card:hover{
    transform: translateY(-4px);
    box-shadow: 0 18px 36px rgba(74,44,59,.09);
}

.faq-pink{ background: #ffdce6; }
.faq-blue{ background: #deebff; }
.faq-green{ background: #ddf2e3; }
.faq-yellow{ background: #ffedc5; }
.faq-lilac{ background: #eadfff; }
.faq-peach{ background: #ffe1ce; }

.faq-card summary{
    position: relative;
    cursor: pointer;
    list-style: none;
    padding: 18px 44px 18px 19px;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: 17px;
    line-height: 1.3;
    font-weight: 400;
    letter-spacing: -.008em;
    color: #281e24;
}

.faq-card summary::-webkit-details-marker{
    display: none;
}

.faq-card summary::after{
    content: "+";
    position: absolute;
    right: 18px;
    top: 15px;
    color: #d63e88;
    font-family: "DM Sans", sans-serif;
    font-size: 20px;
    font-weight: 500;
    transition: transform .2s ease;
}

.faq-card[open] summary::after{
    content: "–";
}

.faq-card p{
    margin: 0;
    padding: 0 19px 18px;
    color: #5e5158;
    font-family: "DM Sans", sans-serif;
    font-size: 12.5px;
    line-height: 1.72;
    font-weight: 400;
}

@media(max-width: 850px){
    .home-cards{
        grid-template-columns: 1fr;
    }

    .faq-grid{
        grid-template-columns: 1fr;
    }
}

@media(max-width: 650px){
    .home-structured,
    .faq-structured{
        margin-top: 26px;
    }

    .home-structured .section-title{
        font-size: 48px;
    }

    .faq-structured .section-title{
        font-size: 40px;
    }

    .faq-card summary{
        font-size: 16px;
    }
}


/* ==========================================================
   HOME CARDS — SMALLER + NEUTRAL
   ========================================================== */

.home-cards{
    max-width: 880px;
    margin: 0 auto;
    gap: 12px;
}

.home-card{
    min-height: 190px !important;
    padding: 18px 18px 17px !important;
    border-radius: 18px !important;
    background: rgba(255,255,255,.86) !important;
    border: 1px solid rgba(75,45,62,.10) !important;
    box-shadow: 0 8px 22px rgba(74,44,59,.05);
}

.home-card-pink,
.home-card-blue,
.home-card-green{
    background: rgba(255,255,255,.86) !important;
}

.home-card:hover{
    transform: translateY(-4px) !important;
    border-color: rgba(214,62,136,.18) !important;
    box-shadow: 0 16px 32px rgba(74,44,59,.08) !important;
}

.home-card .card-icon{
    width: 38px !important;
    height: 38px !important;
    border-radius: 12px !important;
    background: #fff3f8 !important;
    color: #d63e88 !important;
}

.home-card .card-num{
    font-size: 9px !important;
}

.home-card .card-label{
    margin-top: 13px !important;
    font-size: 8.5px !important;
    color: #a1798c !important;
}

.home-card h3{
    margin-top: 7px !important;
    font-size: 18px !important;
}

.home-card p{
    margin-top: 7px !important;
    font-size: 11.5px !important;
    line-height: 1.62 !important;
}

.home-card .card-foot{
    left: 18px !important;
    bottom: 14px !important;
    padding: 5px 8px !important;
    background: #fff7fa !important;
    border-color: rgba(214,62,136,.08) !important;
    color: #9b6e82 !important;
    font-size: 8.5px !important;
}

@media(max-width: 850px){
    .home-cards{
        max-width: 620px;
    }

    .home-card{
        min-height: 175px !important;
    }
}


/* ==========================================================
   FINAL HOME — CLEAN, NO REPEATED FEATURE CARDS
   ========================================================== */

.home-structured{
    max-width: 900px;
    margin: 54px auto 0;
    padding-bottom: 12px;
}

.home-structured .section-head{
    margin-bottom: 28px;
}

.home-structured .section-title{
    font-size: clamp(52px, 6vw, 76px);
}

.home-structured .section-copy{
    max-width: 650px;
    margin-left: auto;
    margin-right: auto;
}

/* Hide any leftover Home card styling/output if older Streamlit cache exists */
.home-cards{
    display: none !important;
}

/* ==========================================================
   FINAL FAQ — CLEAN COLLAPSIBLE ROWS, NO COLORED RECTANGLES
   ========================================================== */

.faq-clean{
    max-width: 900px;
    margin: 42px auto 0;
}

.faq-clean .section-head{
    margin-bottom: 30px;
}

.faq-clean .section-title{
    font-size: clamp(42px, 4.8vw, 62px);
}

.faq-list{
    max-width: 820px;
    margin: 0 auto;
    border-top: 1px solid rgba(75,45,62,.12);
}

.faq-row{
    border: 0 !important;
    border-bottom: 1px solid rgba(75,45,62,.12) !important;
    border-radius: 0 !important;
    background: transparent !important;
    box-shadow: none !important;
    overflow: visible !important;
}

.faq-row:hover{
    background: transparent !important;
    box-shadow: none !important;
    transform: none !important;
}

.faq-row summary{
    position: relative;
    cursor: pointer;
    list-style: none;
    padding: 17px 42px 17px 2px;
    color: #d63e88;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: 17px;
    line-height: 1.35;
    font-weight: 400;
    letter-spacing: -.008em;
}

.faq-row summary::-webkit-details-marker{
    display: none;
}

.faq-row summary::after{
    content: "+";
    position: absolute;
    top: 14px;
    right: 4px;
    color: #d63e88;
    font-family: "DM Sans", sans-serif;
    font-size: 20px;
    font-weight: 500;
}

.faq-row[open] summary::after{
    content: "–";
}

.faq-row p{
    margin: 0;
    padding: 0 36px 17px 2px;
    color: #352b31;
    font-family: "DM Sans", sans-serif;
    font-size: 12.5px;
    line-height: 1.75;
    font-weight: 400;
}

@media(max-width: 650px){
    .home-structured{
        margin-top: 32px;
    }

    .home-structured .section-title{
        font-size: 48px;
    }

    .faq-clean{
        margin-top: 28px;
    }

    .faq-row summary{
        font-size: 16px;
    }
}


/* ==========================================================
   FINAL WORKSPACE — ONE MAIN JD RECTANGLE ONLY
   ========================================================== */

.workspace-clean-head{
    max-width: 900px;
    margin: 42px auto 0;
    padding-bottom: 4px;
}

.workspace-clean-head .section-head{
    margin-bottom: 25px;
}

.workspace-input-label{
    max-width: 950px;
    margin: 0 auto 8px;
    padding: 0 2px;
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
}

.workspace-input-label span{
    color: #2a2026;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: 17px;
    font-weight: 400;
}

.workspace-input-label small{
    color: #9b8992;
    font-family: "DM Sans", sans-serif;
    font-size: 10px;
}

/* The textarea is the one main visible rectangle */
.st-key-jd_text textarea{
    min-height: 225px !important;
    border: 1px solid rgba(75,45,62,.12) !important;
    border-radius: 20px !important;
    background: rgba(255,255,255,.92) !important;
    box-shadow: 0 10px 28px rgba(74,44,59,.05) !important;
    padding: 18px !important;
}

.st-key-jd_text textarea:hover{
    border-color: rgba(214,62,136,.20) !important;
}

.st-key-jd_text textarea:focus{
    border-color: rgba(214,62,136,.42) !important;
    box-shadow: 0 0 0 4px rgba(214,62,136,.07) !important;
}

/* + remains small and secondary */
.st-key-generate_interview_prep button{
    margin-top: 8px !important;
}

/* The visible + trigger should not become another large box */
div[data-testid="stPopover"] > button,
[data-testid="stPopover"] button{
    min-width: 42px !important;
    width: 42px !important;
    height: 42px !important;
    min-height: 42px !important;
    padding: 0 !important;
    border-radius: 12px !important;
    background: #fff5f9 !important;
    color: #d63e88 !important;
    border: 1px solid rgba(214,62,136,.12) !important;
    box-shadow: none !important;
    font-size: 20px !important;
}

div[data-testid="stPopover"] > button:hover,
[data-testid="stPopover"] button:hover{
    background: #fff0f6 !important;
    transform: none !important;
}

/* File upload boxes exist only inside the + popover, not on the main page */
[data-testid="stPopover"] [data-testid="stFileUploader"]{
    border: 0 !important;
    background: transparent !important;
    padding: 4px 0 !important;
}

@media(max-width: 650px){
    .workspace-clean-head{
        margin-top: 28px;
    }

    .workspace-input-label{
        display: block;
    }

    .workspace-input-label small{
        display: block;
        margin-top: 3px;
    }
}


/* ==========================================================
   STRUCTURED RESULTS + DOWNLOAD AREA
   ========================================================== */

.results-clean-head{
    max-width: 850px;
    margin: 48px auto 28px;
    text-align: center;
}

.results-clean-head .section-title{
    margin-top: 9px;
    font-size: clamp(42px, 4.7vw, 60px);
}

.results-clean-head .section-copy{
    max-width: 650px;
}

.score-clean{
    max-width: 420px;
    margin: 0 auto 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 18px;
    padding: 12px 16px;
    border-top: 1px solid rgba(75,45,62,.10);
    border-bottom: 1px solid rgba(75,45,62,.10);
}

.score-clean span{
    color: #887680;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .08em;
}

.score-clean strong{
    color: #d63e88;
    font-family: "Manrope", sans-serif;
    font-size: 25px;
}

.result-tab-heading{
    display: flex;
    align-items: flex-start;
    gap: 12px;
    margin: 18px 0 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid rgba(75,45,62,.09);
}

.result-tab-heading > span{
    color: #d63e88;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: .08em;
}

.result-tab-heading strong{
    display: block;
    color: #2b2026;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: 21px;
    font-weight: 400;
}

.result-tab-heading small{
    display: block;
    margin-top: 3px;
    color: #94838c;
    font-size: 10.5px;
    line-height: 1.5;
}

.stTabs [data-baseweb="tab-panel"]{
    padding-top: 2px !important;
}

.stTabs [data-baseweb="tab-panel"] p,
.stTabs [data-baseweb="tab-panel"] li{
    color: #40343a;
    font-size: 13px;
    line-height: 1.72;
}

.stTabs [data-baseweb="tab-panel"] h1,
.stTabs [data-baseweb="tab-panel"] h2,
.stTabs [data-baseweb="tab-panel"] h3,
.stTabs [data-baseweb="tab-panel"] h4{
    color: #2c2228;
    font-family: "DM Serif Display", Georgia, serif;
    font-weight: 400;
}

.download-clean-head{
    margin: 34px 0 12px;
    padding-top: 20px;
    border-top: 1px solid rgba(75,45,62,.10);
}

.download-clean-head strong{
    display: block;
    color: #2a2026;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: 21px;
    font-weight: 400;
}

.download-clean-head span{
    display: block;
    margin-top: 3px;
    color: #94838c;
    font-size: 10.5px;
}

/* Remove Streamlit's heading-anchor visual from generated result UI */
.download-clean-head a,
.result-tab-heading a{
    display: none !important;
}


/* ==========================================================
   COMPACT WORKSPACE — REMOVE EMPTY VERTICAL SPACE
   ========================================================== */

.workspace-clean-head{
    max-width: 820px !important;
    margin-top: 34px !important;
    padding-top: 18px !important;
}

.workspace-clean-head .section-head{
    margin-bottom: 18px !important;
}

.workspace-clean-head .section-title{
    font-size: clamp(44px, 5vw, 62px) !important;
}

.workspace-clean-head .section-copy{
    max-width: 610px !important;
}

.workspace-input-label{
    max-width: 980px !important;
    margin-bottom: 7px !important;
}

/* Main JD field: shorter, cleaner, no wasted space */
.st-key-jd_text{
    max-width: 100% !important;
}

.st-key-jd_text textarea{
    min-height: 145px !important;
    height: 145px !important;
    max-height: 190px !important;
    border-radius: 16px !important;
    padding: 15px 16px !important;
    box-shadow: 0 7px 20px rgba(74,44,59,.04) !important;
    resize: vertical !important;
}

/* Keep character/help line close to textarea */
.st-key-jd_text + div{
    margin-top: 2px !important;
}

/* Pull Generate button upward */
.st-key-generate_interview_prep button{
    margin-top: 3px !important;
    min-height: 42px !important;
}

/* Make the upload trigger visually lighter and smaller */
div[data-testid="stPopover"] > button,
[data-testid="stPopover"] button{
    width: 40px !important;
    min-width: 40px !important;
    height: 40px !important;
    min-height: 40px !important;
    border-radius: 11px !important;
}

/* Keep workspace area from feeling too wide on large desktop screens */
@media(min-width: 1100px){
    .st-key-jd_text textarea{
        font-size: 13px !important;
    }
}

@media(max-width: 650px){
    .st-key-jd_text textarea{
        min-height: 135px !important;
        height: 135px !important;
    }

    .workspace-clean-head{
        padding-top: 10px !important;
    }
}


/* ==========================================================
   EXTRA-COMPACT WORKSPACE
   ========================================================== */

.st-key-jd_text textarea{
    min-height: 105px !important;
    height: 105px !important;
    max-height: 150px !important;
    padding: 12px 14px !important;
    border-radius: 14px !important;
}

.workspace-clean-head{
    margin-top: 24px !important;
    padding-top: 10px !important;
}

.workspace-clean-head .section-head{
    margin-bottom: 14px !important;
}

.workspace-input-label{
    margin-bottom: 5px !important;
}

.st-key-generate_interview_prep button{
    margin-top: 0 !important;
}

div[data-testid="stPopover"] > button,
[data-testid="stPopover"] button{
    width: 36px !important;
    min-width: 36px !important;
    height: 36px !important;
    min-height: 36px !important;
    border-radius: 10px !important;
}

@media(max-width: 650px){
    .st-key-jd_text textarea{
        min-height: 100px !important;
        height: 100px !important;
    }
}


/* ==========================================================
   CENTERED JD INPUT — COMPACT DESKTOP BOX
   ========================================================== */

/* Keep the heading area clean */
.workspace-clean-head{
    max-width: 760px !important;
    margin: 22px auto 0 !important;
    padding-top: 8px !important;
}

.workspace-clean-head .section-head{
    margin-bottom: 14px !important;
}

/* Label directly above the input */
.workspace-input-label{
    max-width: 760px !important;
    margin: 0 auto 6px !important;
    padding: 0 2px !important;
}

.workspace-input-label span{
    font-size: 16px !important;
}

.workspace-input-label small{
    font-size: 9.5px !important;
}

/* The row containing JD box + plus is centered and compact */
div[data-testid="stHorizontalBlock"]:has(.st-key-jd_text){
    max-width: 760px !important;
    margin-left: auto !important;
    margin-right: auto !important;
    gap: 10px !important;
    align-items: flex-start !important;
}

/* Compact centered JD field */
.st-key-jd_text textarea{
    min-height: 82px !important;
    height: 82px !important;
    max-height: 130px !important;
    padding: 12px 14px !important;
    border-radius: 12px !important;
    background: #f5f3f4 !important;
    border: 1px solid rgba(75,45,62,.08) !important;
    box-shadow: none !important;
    font-size: 12px !important;
    line-height: 1.55 !important;
    resize: vertical !important;
}

.st-key-jd_text textarea:hover{
    border-color: rgba(214,62,136,.16) !important;
}

.st-key-jd_text textarea:focus{
    border-color: rgba(214,62,136,.30) !important;
    box-shadow: 0 0 0 3px rgba(214,62,136,.06) !important;
}

/* Small plus upload control aligned to the right of JD box */
div[data-testid="stPopover"] > button,
[data-testid="stPopover"] button{
    width: 34px !important;
    min-width: 34px !important;
    height: 34px !important;
    min-height: 34px !important;
    border-radius: 10px !important;
    background: #f8f4f6 !important;
    border: 1px solid rgba(214,62,136,.10) !important;
    color: #d63e88 !important;
    box-shadow: none !important;
    padding: 0 !important;
    margin-top: 2px !important;
}

/* Keep helper/caption aligned with the same compact width */
div[data-testid="stCaptionContainer"]{
    max-width: 760px !important;
    margin-left: auto !important;
    margin-right: auto !important;
}

/* Generate/Get Results button stays centered underneath */
.st-key-generate_interview_prep{
    margin-top: 2px !important;
}

.st-key-generate_interview_prep button{
    max-width: 580px !important;
    margin-left: auto !important;
    margin-right: auto !important;
}

/* Mobile */
@media(max-width: 760px){
    .workspace-input-label,
    div[data-testid="stHorizontalBlock"]:has(.st-key-jd_text),
    div[data-testid="stCaptionContainer"]{
        max-width: 94% !important;
    }

    .st-key-jd_text textarea{
        min-height: 78px !important;
        height: 78px !important;
    }
}


/* ==========================================================
   TRULY CENTERED JD INPUT
   ========================================================== */

.workspace-clean-head{
    max-width: 760px !important;
    margin: 18px auto 0 !important;
    padding-top: 6px !important;
}

.workspace-clean-head .section-head{
    margin-bottom: 12px !important;
}

.workspace-clean-head .section-title{
    font-size: clamp(42px, 5vw, 58px) !important;
}

.workspace-clean-head .section-copy{
    max-width: 560px !important;
}

.workspace-input-label.centered{
    max-width: 100% !important;
    margin: 0 0 6px 0 !important;
    padding: 0 !important;
    display: block !important;
    text-align: left !important;
}

.workspace-input-label.centered span{
    color: #2a2026 !important;
    font-family: "DM Serif Display", Georgia, serif !important;
    font-size: 16px !important;
    font-weight: 400 !important;
}

.plus-align-space{
    height: 1px;
    margin-top: 2px;
}

/* compact centered box */
.st-key-jd_text textarea{
    min-height: 72px !important;
    height: 72px !important;
    max-height: 120px !important;
    padding: 12px 14px !important;
    border-radius: 12px !important;
    background: #f3f2f3 !important;
    border: 1px solid rgba(75,45,62,.08) !important;
    box-shadow: none !important;
    font-size: 12px !important;
    line-height: 1.45 !important;
    resize: vertical !important;
}

.st-key-jd_text textarea:hover{
    border-color: rgba(214,62,136,.14) !important;
}

.st-key-jd_text textarea:focus{
    border-color: rgba(214,62,136,.28) !important;
    box-shadow: 0 0 0 3px rgba(214,62,136,.05) !important;
}

/* smaller upload button */
div[data-testid="stPopover"] > button,
[data-testid="stPopover"] button{
    width: 32px !important;
    min-width: 32px !important;
    height: 32px !important;
    min-height: 32px !important;
    border-radius: 9px !important;
    background: #f8f4f6 !important;
    border: 1px solid rgba(214,62,136,.10) !important;
    color: #d63e88 !important;
    box-shadow: none !important;
    padding: 0 !important;
    margin-top: 0 !important;
}

/* keep caption aligned with the input width */
div[data-testid="stCaptionContainer"] p{
    font-size: 11px !important;
}

/* button closer */
.st-key-generate_interview_prep button{
    margin-top: 2px !important;
    max-width: 560px !important;
    margin-left: auto !important;
    margin-right: auto !important;
}

@media(max-width: 900px){
    .workspace-clean-head{
        max-width: 92% !important;
    }
}

@media(max-width: 700px){
    .st-key-jd_text textarea{
        min-height: 70px !important;
        height: 70px !important;
    }
}


/* ==========================================================
   FINAL APPROVED RESULTS UI
   ========================================================== */

.result-final-hero{
    max-width: 940px;
    margin: 48px auto 18px;
}

.result-final-eyebrow{
    color: #d84288;
    font-family: "DM Sans", sans-serif;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: .15em;
    text-transform: uppercase;
}

.result-final-hero h1{
    margin: 7px 0 7px;
    color: #281e24;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: clamp(44px, 5.3vw, 68px);
    line-height: 1.04;
    font-weight: 400;
    letter-spacing: -.035em;
}

.result-final-hero h1 span{
    color: #d84288;
}

.result-final-hero > p{
    max-width: 720px;
    margin: 0;
    color: #8f7c85;
    font-family: "DM Sans", sans-serif;
    font-size: 13px;
    line-height: 1.7;
}

.result-resume-badge{
    display: inline-flex;
    align-items: center;
    gap: 7px;
    margin-top: 14px;
    color: #77656f;
    font-family: "DM Sans", sans-serif;
    font-size: 10px;
    font-weight: 700;
}

.result-resume-badge i{
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #50a568;
}

.result-fit-section,
.result-no-resume-skills{
    max-width: 940px;
    margin: 0 auto;
    padding: 21px 0 25px;
    border-top: 1px solid rgba(92,60,76,.12);
    border-bottom: 1px solid rgba(92,60,76,.12);
}

.result-match-line{
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 20px;
}

.result-match-copy{
    flex: 1;
}

.result-match-label{
    color: #917d86;
    font-family: "DM Sans", sans-serif;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: .09em;
    text-transform: uppercase;
}

.result-match-bar{
    height: 7px;
    margin-top: 10px;
    overflow: hidden;
    border-radius: 999px;
    background: #eee4e8;
}

.result-match-bar span{
    display: block;
    height: 100%;
    border-radius: inherit;
    background: #d84288;
}

.result-match-score{
    color: #d84288;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: 38px;
    line-height: 1;
}

.result-skill-block{
    margin-top: 20px;
}

.result-skill-block h3{
    margin: 0 0 10px;
    color: #86737c;
    font-family: "DM Sans", sans-serif;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: .09em;
    text-transform: uppercase;
}

.result-skill-chips{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}

.result-skill-chip{
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 8px 11px;
    border: 1px solid transparent;
    border-radius: 999px;
    font-family: "DM Sans", sans-serif;
    font-size: 10.5px;
    font-weight: 700;
}

.result-skill-chip i{
    width: 17px;
    height: 17px;
    display: grid;
    place-items: center;
    border-radius: 50%;
    font-style: normal;
    font-size: 9px;
    font-weight: 800;
}

.result-skill-chip.matched{
    color: #39704a;
    border-color: #d9efdf;
    background: #f3fbf5;
}

.result-skill-chip.matched i{
    color: #278346;
    background: #dff4e5;
}

.result-skill-chip.missing{
    color: #9f4962;
    border-color: #f1d9e0;
    background: #fff5f7;
}

.result-skill-chip.missing i{
    color: #be365c;
    background: #f8dfe6;
}

.result-skill-chip.neutral{
    color: #67555f;
    border-color: #eadfe4;
    background: #fff;
}

.result-skill-chip.neutral i{
    color: #d84288;
    background: #fff0f6;
}

.result-priority-gap{
    margin-top: 24px;
    padding: 18px 20px;
    border: 1px solid #efd9e3;
    border-radius: 18px;
    background: linear-gradient(135deg,#fff0f6,#fff8fb);
}

.result-priority-top{
    display: flex;
    align-items: flex-start;
    gap: 14px;
}

.result-priority-number{
    width: 42px;
    height: 42px;
    display: grid;
    place-items: center;
    flex: none;
    border-radius: 50%;
    color: #fff;
    background: #d84288;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: 18px;
}

.result-priority-gap small{
    display: block;
    margin-bottom: 4px;
    color: #d84288;
    font-family: "DM Sans", sans-serif;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: .11em;
    text-transform: uppercase;
}

.result-priority-gap h2{
    margin: 0;
    color: #2c2228;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: 23px;
    font-weight: 400;
}

.result-priority-gap p{
    margin: 7px 0 0;
    color: #725f69;
    font-family: "DM Sans", sans-serif;
    font-size: 12px;
    line-height: 1.7;
}

.result-next-step{
    margin-top: 15px;
    padding: 15px 17px;
    border-radius: 14px;
    color: #fff;
    background: #2f2129;
}

.result-next-step span{
    display: block;
    color: #f4b6d0;
    font-family: "DM Sans", sans-serif;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: .1em;
    text-transform: uppercase;
}

.result-next-step strong{
    display: block;
    margin-top: 4px;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: 19px;
    font-weight: 400;
}

.result-next-step p{
    margin: 7px 0 0;
    color: #f2e9ed;
    font-family: "DM Sans", sans-serif;
    font-size: 11.5px;
    line-height: 1.7;
}

.result-no-resume-note,
.result-empty-note{
    color: #96838c;
    font-family: "DM Sans", sans-serif;
    font-size: 10.5px;
    line-height: 1.6;
}

.result-no-resume-note{
    margin: 14px 0 0;
}

.result-accordion-stack{
    max-width: 940px;
    margin: 25px auto 0;
}

.result-accordion-box{
    margin-bottom: 12px;
    overflow: hidden;
    border: 1px solid #eadfe4;
    border-radius: 16px;
    background: rgba(255,255,255,.78);
}

.result-accordion-box[open]{
    background: #fff;
    box-shadow: 0 12px 28px rgba(86,53,69,.05);
}

.result-accordion-box > summary{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 16px 18px;
    list-style: none;
    cursor: pointer;
}

.result-accordion-box > summary::-webkit-details-marker{
    display: none;
}

.result-accordion-left{
    display: flex;
    align-items: center;
    gap: 12px;
}

.result-accordion-index{
    color: #d84288;
    font-family: "DM Sans", sans-serif;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: .1em;
}

.result-accordion-title{
    color: #2d2329;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: 19px;
    font-weight: 400;
}

.result-accordion-subtitle{
    margin-top: 2px;
    color: #9a8790;
    font-family: "DM Sans", sans-serif;
    font-size: 9.5px;
}

.result-accordion-toggle{
    width: 29px;
    height: 29px;
    display: grid;
    place-items: center;
    flex: none;
    border-radius: 50%;
    color: #d84288;
    background: #fff3f8;
}

.result-accordion-toggle::before{
    content: "+";
    font-family: "DM Sans", sans-serif;
    font-size: 18px;
}

.result-accordion-box[open] .result-accordion-toggle::before{
    content: "−";
}

.result-accordion-content{
    padding: 18px 20px 21px 48px;
    border-top: 1px solid #f0e7eb;
}

.result-question-row{
    display: grid;
    grid-template-columns: 36px minmax(0,1fr) auto;
    gap: 11px;
    padding: 13px 0;
    border-bottom: 1px solid #f0e7eb;
}

.result-question-row:last-child{
    border-bottom: 0;
}

.result-question-number{
    color: #d84288;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: 17px;
}

.result-question-text,
.result-answer-question{
    color: #33282e;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: 17px;
    line-height: 1.45;
}

.result-question-domain{
    padding-top: 4px;
    color: #9f8b95;
    font-family: "DM Sans", sans-serif;
    font-size: 8.5px;
    font-weight: 800;
    letter-spacing: .07em;
    text-transform: uppercase;
}

.result-answer-row{
    border-bottom: 1px solid #f0e7eb;
}

.result-answer-row:last-child{
    border-bottom: 0;
}

.result-answer-row > summary{
    display: grid;
    grid-template-columns: 36px minmax(0,1fr) auto;
    gap: 11px;
    padding: 13px 0;
    list-style: none;
    cursor: pointer;
}

.result-answer-row > summary::-webkit-details-marker{
    display: none;
}

.result-answer-row > summary::after{
    content: "+";
    color: #d84288;
    font-family: "DM Sans", sans-serif;
    font-size: 17px;
}

.result-answer-row[open] > summary::after{
    content: "−";
}

.result-answer-body{
    padding: 0 24px 15px 47px;
}

.result-gap-row{
    padding: 13px 0;
    border-bottom: 1px solid #f0e7eb;
}

.result-gap-row > span{
    color: #c23a60;
    font-family: "DM Sans", sans-serif;
    font-size: 8.5px;
    font-weight: 800;
    letter-spacing: .08em;
    text-transform: uppercase;
}

.result-gap-row h4{
    margin: 5px 0;
    color: #33282e;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: 18px;
    font-weight: 400;
}

.result-gap-row p{
    margin: 0;
    color: #7d6b74;
    font-family: "DM Sans", sans-serif;
    font-size: 11.5px;
    line-height: 1.7;
}

.result-gap-recommendation{
    margin-top: 16px;
    padding: 13px 15px;
    border-left: 3px solid #d84288;
    background: #fff7fa;
}

.result-gap-recommendation strong{
    color: #33282e;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: 17px;
    font-weight: 400;
}

.result-gap-recommendation p{
    margin: 5px 0 0;
    color: #78666f;
    font-family: "DM Sans", sans-serif;
    font-size: 11px;
    line-height: 1.7;
}

/* Markdown typography inside Requirements / Answers / Study Plan */
.result-markdown,
.result-answer-body{
    color: #66545e;
    font-family: "DM Sans", sans-serif;
    font-size: 11.7px;
    line-height: 1.76;
}

.result-markdown h2,
.result-markdown h3,
.result-markdown h4,
.result-answer-body h2,
.result-answer-body h3,
.result-answer-body h4{
    color: #33282e;
    font-family: "DM Serif Display", Georgia, serif;
    font-weight: 400;
}

.result-markdown h2{
    margin: 18px 0 7px;
    font-size: 22px;
}

.result-markdown h3{
    margin: 17px 0 7px;
    font-size: 18px;
}

.result-markdown h4{
    margin: 14px 0 6px;
    font-size: 16px;
}

.result-markdown p,
.result-answer-body p{
    margin: 6px 0 10px;
}

.result-markdown ul,
.result-markdown ol,
.result-answer-body ul,
.result-answer-body ol{
    margin: 6px 0 12px;
    padding-left: 20px;
}

.result-markdown li,
.result-answer-body li{
    margin: 4px 0;
}

.result-markdown strong,
.result-answer-body strong{
    color: #392c34;
    font-weight: 700;
}

/* Study plan gets more space and stronger hierarchy */
.result-study-plan{
    font-size: 12.2px;
    line-height: 1.8;
}

.result-study-plan h2{
    margin-top: 5px;
    color: #d84288;
    font-size: 25px;
}

.result-study-plan h3{
    margin-top: 22px;
    font-size: 20px;
}

.result-study-plan blockquote{
    margin: 13px 0 18px;
    padding: 11px 13px;
    border-left: 3px solid #d84288;
    border-radius: 0 10px 10px 0;
    color: #6f5e67;
    background: #fff6fa;
}

.result-download-head{
    max-width: 940px;
    margin: 25px auto 12px;
    padding-top: 18px;
    border-top: 1px solid rgba(92,60,76,.12);
}

.result-download-head strong{
    display: block;
    color: #33282e;
    font-family: "DM Serif Display", Georgia, serif;
    font-size: 19px;
    font-weight: 400;
}

.result-download-head span{
    display: block;
    margin-top: 3px;
    color: #96838c;
    font-family: "DM Sans", sans-serif;
    font-size: 10.5px;
}

@media(max-width: 700px){
    .result-final-hero,
    .result-fit-section,
    .result-no-resume-skills,
    .result-accordion-stack,
    .result-download-head{
        max-width: 96%;
    }

    .result-final-hero{
        margin-top: 30px;
    }

    .result-final-hero h1{
        font-size: 42px;
    }

    .result-accordion-content{
        padding-left: 18px;
        padding-right: 18px;
    }

    .result-question-row{
        grid-template-columns: 32px 1fr;
    }

    .result-question-domain{
        grid-column: 2;
    }

    .result-priority-top{
        align-items: flex-start;
    }
}



/* ==========================================================
   ROSE QUARTZ + PLUM THEME — LIGHT / DARK
   Typography refinement for requirements, questions & study plan
   ========================================================== */

:root{
    --ui-bg: #fff8fb;
    --ui-bg-soft: #fdf2f7;
    --ui-surface: rgba(255,255,255,.82);
    --ui-surface-solid: #fffdfd;
    --ui-text: #281d25;
    --ui-muted: #806d79;
    --ui-line: rgba(89,52,73,.11);
    --ui-rose: #c75386;
    --ui-rose-strong: #ad3e73;
    --ui-rose-soft: #f8e3ed;
    --ui-plum: #73567f;
    --ui-plum-soft: #eee7f4;
    --ui-green: #347a4c;
    --ui-green-soft: #edf8f0;
    --ui-red: #a84561;
    --ui-red-soft: #fceef2;
    --ui-shadow: 0 18px 48px rgba(93,57,77,.08);
}





.stApp{
    color: var(--ui-text) !important;
    background:
        radial-gradient(circle at 13% 12%, color-mix(in srgb, var(--ui-rose) 12%, transparent), transparent 28%),
        radial-gradient(circle at 88% 20%, color-mix(in srgb, var(--ui-plum) 10%, transparent), transparent 30%),
        linear-gradient(180deg, var(--ui-bg), var(--ui-bg-soft)) !important;
}

/* Top navigation and generic app copy. */
.nav-link,
.stButton > button,
[data-testid="stPopover"] button{
    font-family: "Manrope", "DM Sans", sans-serif !important;
}

/* Keep the approved large hero font, but make the accent less candy-pink. */
.hero-title,
.section-title,
.result-final-hero h1{
    color: var(--ui-text) !important;
}

.hero-title em,
.hero-title span,
.section-title em,
.result-final-hero h1 span,
.result-final-eyebrow,
.result-accordion-index{
    color: var(--ui-rose) !important;
}

.hero-copy,
.section-copy,
.result-final-hero > p,
.result-accordion-subtitle,
.result-no-resume-note,
.result-empty-note,
.result-download-head span{
    color: var(--ui-muted) !important;
}

/* Resume/JD analysis — preserve the skill typography the user approved. */
.result-fit-section,
.result-no-resume-skills{
    border-color: var(--ui-line) !important;
}

.result-match-label,
.result-skill-block h3{
    color: var(--ui-muted) !important;
}

.result-match-bar{
    background: color-mix(in srgb, var(--ui-muted) 18%, transparent) !important;
}

.result-match-bar span{
    background: linear-gradient(90deg, var(--ui-rose), var(--ui-plum)) !important;
}

.result-match-score{
    color: var(--ui-rose) !important;
}

.result-skill-chip.matched{
    color: var(--ui-green) !important;
    border-color: color-mix(in srgb, var(--ui-green) 24%, transparent) !important;
    background: var(--ui-green-soft) !important;
}

.result-skill-chip.matched i{
    color: var(--ui-green) !important;
    background: color-mix(in srgb, var(--ui-green) 14%, transparent) !important;
}

.result-skill-chip.missing{
    color: var(--ui-red) !important;
    border-color: color-mix(in srgb, var(--ui-red) 23%, transparent) !important;
    background: var(--ui-red-soft) !important;
}

.result-skill-chip.missing i{
    color: var(--ui-red) !important;
    background: color-mix(in srgb, var(--ui-red) 13%, transparent) !important;
}

.result-skill-chip.neutral{
    color: var(--ui-text) !important;
    border-color: var(--ui-line) !important;
    background: var(--ui-surface) !important;
}

.result-skill-chip.neutral i{
    color: var(--ui-rose) !important;
    background: var(--ui-rose-soft) !important;
}

/* Priority gap becomes a rose/plum spotlight. */
.result-priority-gap{
    border-color: color-mix(in srgb, var(--ui-rose) 25%, var(--ui-line)) !important;
    background:
        linear-gradient(135deg,
            color-mix(in srgb, var(--ui-rose-soft) 82%, var(--ui-surface-solid)),
            color-mix(in srgb, var(--ui-plum-soft) 55%, var(--ui-surface-solid))) !important;
    box-shadow: var(--ui-shadow) !important;
}

.result-priority-number{
    background: linear-gradient(145deg, var(--ui-rose), var(--ui-plum)) !important;
}

.result-priority-gap small{
    color: var(--ui-rose) !important;
}

.result-priority-gap h2,
.result-priority-gap p{
    color: var(--ui-text) !important;
}

.result-next-step{
    border: 1px solid color-mix(in srgb, var(--ui-plum) 30%, transparent) !important;
    background:
        linear-gradient(135deg,
            color-mix(in srgb, var(--ui-plum) 78%, #211923),
            color-mix(in srgb, var(--ui-rose-strong) 66%, #211923)) !important;
    box-shadow: 0 14px 34px color-mix(in srgb, var(--ui-plum) 16%, transparent) !important;
}

.result-next-step span{
    color: #ffd9e9 !important;
}

.result-next-step strong,
.result-next-step p{
    color: #fff8fb !important;
}

/* Accordion surfaces use a softer neutral/plum treatment, not pink boxes everywhere. */
.result-accordion-box{
    border-color: var(--ui-line) !important;
    background: var(--ui-surface) !important;
    box-shadow: none !important;
}

.result-accordion-box[open]{
    border-color: color-mix(in srgb, var(--ui-plum) 24%, var(--ui-line)) !important;
    background: var(--ui-surface-solid) !important;
    box-shadow: var(--ui-shadow) !important;
}

.result-accordion-box > summary,
.result-accordion-content,
.result-question-row,
.result-answer-row,
.result-gap-row{
    border-color: var(--ui-line) !important;
}

.result-accordion-toggle{
    color: var(--ui-rose) !important;
    background: color-mix(in srgb, var(--ui-rose-soft) 72%, transparent) !important;
}

/* USER-REQUESTED FONT CHANGE:
   Section labels such as Requirements / Questions / Answers / Study Plan
   become modern Manrope instead of serif. */
.result-accordion-title{
    color: var(--ui-text) !important;
    font-family: "Manrope", "DM Sans", sans-serif !important;
    font-size: 18px !important;
    font-weight: 700 !important;
    letter-spacing: -.018em !important;
}

/* USER-REQUESTED FONT CHANGE:
   Interview question text is no longer DM Serif Display. */
.result-question-text,
.result-answer-question{
    color: var(--ui-text) !important;
    font-family: "Manrope", "DM Sans", sans-serif !important;
    font-size: 15.5px !important;
    font-weight: 650 !important;
    line-height: 1.52 !important;
    letter-spacing: -.01em !important;
}

.result-question-number{
    color: var(--ui-rose) !important;
    font-family: "Manrope", "DM Sans", sans-serif !important;
    font-size: 13px !important;
    font-weight: 800 !important;
}

.result-question-domain{
    color: var(--ui-plum) !important;
    font-size: 9px !important;
}

.result-answer-row > summary::after{
    color: var(--ui-rose) !important;
}

/* Requirements / skill-gap content — clean editorial sans, not decorative serif. */
.result-markdown,
.result-answer-body,
.result-gap-row p,
.result-gap-recommendation p{
    color: var(--ui-muted) !important;
    font-family: "DM Sans", sans-serif !important;
    font-size: 12.3px !important;
    line-height: 1.78 !important;
}

.result-markdown h2,
.result-markdown h3,
.result-markdown h4,
.result-answer-body h2,
.result-answer-body h3,
.result-answer-body h4,
.result-gap-row h4,
.result-gap-recommendation strong{
    color: var(--ui-text) !important;
    font-family: "Manrope", "DM Sans", sans-serif !important;
    font-weight: 700 !important;
    letter-spacing: -.016em !important;
}

.result-markdown h2{
    font-size: 20px !important;
}

.result-markdown h3,
.result-gap-row h4{
    font-size: 16.5px !important;
}

.result-markdown h4{
    font-size: 14.5px !important;
}

.result-markdown strong,
.result-answer-body strong{
    color: var(--ui-text) !important;
}

.result-gap-row > span{
    color: var(--ui-red) !important;
}

.result-gap-recommendation{
    border-left-color: var(--ui-rose) !important;
    background: color-mix(in srgb, var(--ui-rose-soft) 54%, var(--ui-surface-solid)) !important;
}

/* Study plan: larger, more readable, ChatGPT-like hierarchy. */
.result-study-plan{
    color: var(--ui-text) !important;
    font-family: "DM Sans", sans-serif !important;
    font-size: 13px !important;
    line-height: 1.82 !important;
}

.result-study-plan h2{
    margin: 8px 0 10px !important;
    color: var(--ui-rose) !important;
    font-family: "Manrope", "DM Sans", sans-serif !important;
    font-size: 22px !important;
    font-weight: 800 !important;
    letter-spacing: -.025em !important;
}

.result-study-plan h3{
    margin: 24px 0 9px !important;
    color: var(--ui-text) !important;
    font-family: "Manrope", "DM Sans", sans-serif !important;
    font-size: 18px !important;
    font-weight: 750 !important;
}

.result-study-plan h4{
    margin: 17px 0 6px !important;
    color: var(--ui-plum) !important;
    font-family: "Manrope", "DM Sans", sans-serif !important;
    font-size: 14.5px !important;
    font-weight: 750 !important;
}

.result-study-plan p,
.result-study-plan li{
    color: var(--ui-text) !important;
    font-size: 12.6px !important;
    line-height: 1.82 !important;
}

.result-study-plan blockquote{
    border-left-color: var(--ui-rose) !important;
    color: var(--ui-text) !important;
    background: color-mix(in srgb, var(--ui-rose-soft) 56%, var(--ui-surface-solid)) !important;
}

.result-download-head{
    border-color: var(--ui-line) !important;
}

.result-download-head strong{
    color: var(--ui-text) !important;
    font-family: "Manrope", "DM Sans", sans-serif !important;
    font-size: 17px !important;
    font-weight: 700 !important;
}

/* Inputs and workspace surfaces follow the same palette. */
.stTextArea textarea,
.stTextInput input,
.stSelectbox [data-baseweb="select"] > div,
[data-testid="stFileUploader"]{
    color: var(--ui-text) !important;
    border-color: var(--ui-line) !important;
    background: var(--ui-surface) !important;
}

.stTextArea textarea::placeholder,
.stTextInput input::placeholder{
    color: var(--ui-muted) !important;
}

.stButton > button[kind="primary"],
.st-key-generate_interview_prep button{
    border-color: transparent !important;
    color: #fff !important;
    background: linear-gradient(120deg, var(--ui-rose-strong), var(--ui-plum)) !important;
    box-shadow: 0 10px 26px color-mix(in srgb, var(--ui-rose) 18%, transparent) !important;
}

.stButton > button[kind="primary"]:hover,
.st-key-generate_interview_prep button:hover{
    filter: brightness(1.04);
    transform: translateY(-1px);
}

</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# FINAL SINGLE PREP+ THEME
# ============================================================

st.markdown(
    """
<style>
:root{
    color-scheme: light !important;

    --ui-text:#2b2028;
    --ui-heading:#251b22;
    --ui-muted:#806e79;
    --ui-line:rgba(86,50,71,.11);

    --ui-rose:#c94f86;
    --ui-rose-strong:#ad3d72;
    --ui-plum:#73567e;

    --ui-green:#347a4c;
    --ui-green-soft:#edf8f0;
    --ui-red:#a84561;
    --ui-red-soft:#fceef2;
}

/* MAIN PAGE — no stark white */
html,
body{
    background:#f7edf3 !important;
}

.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"]{
    min-height:100vh !important;
    color:var(--ui-text) !important;
    background:
        radial-gradient(circle at 9% 7%, rgba(201,79,134,.14), transparent 27%),
        radial-gradient(circle at 91% 13%, rgba(115,86,126,.11), transparent 29%),
        radial-gradient(circle at 51% 83%, rgba(231,183,207,.16), transparent 35%),
        linear-gradient(
            145deg,
            #fbf4f8 0%,
            #f7edf3 43%,
            #f1ecf6 100%
        ) !important;
}

[data-testid="stAppViewContainer"] .main .block-container,
.block-container{
    background:transparent !important;
}

/* Streamlit top bar blends into theme */
[data-testid="stHeader"]{
    height:3.25rem !important;
    color:var(--ui-text) !important;
    background:rgba(247,237,243,.94) !important;
    border-bottom:1px solid var(--ui-line) !important;
    backdrop-filter:blur(18px) !important;
}

/* NAVIGATION */
div[data-testid="stHorizontalBlock"]:has(.nav-brand){
    position:relative !important;
    top:auto !important;
    z-index:30 !important;
    min-height:60px !important;
    margin:0 0 8px !important;
    padding:8px 14px !important;
    overflow:visible !important;
    border:1px solid rgba(89,53,73,.10) !important;
    border-radius:18px !important;
    background:
        linear-gradient(
            135deg,
            rgba(255,250,253,.78),
            rgba(246,234,242,.76)
        ) !important;
    box-shadow:0 12px 34px rgba(77,42,62,.05) !important;
    backdrop-filter:blur(18px) !important;
}

.nav-brand{
    color:var(--ui-heading) !important;
}

.nav-brand span{
    color:var(--ui-rose) !important;
}

div[data-testid="stHorizontalBlock"]:has(.nav-brand) .st-key-top_home button,
div[data-testid="stHorizontalBlock"]:has(.nav-brand) .st-key-top_features button,
div[data-testid="stHorizontalBlock"]:has(.nav-brand) .st-key-top_workflow button,
div[data-testid="stHorizontalBlock"]:has(.nav-brand) .st-key-top_faq button{
    width:auto !important;
    min-width:0 !important;
    max-width:max-content !important;
    height:34px !important;
    min-height:34px !important;
    margin:0 auto !important;
    padding:5px 3px !important;
    border:0 !important;
    border-radius:0 !important;
    color:#6d5c66 !important;
    background:transparent !important;
    box-shadow:none !important;
    font-family:"Manrope","DM Sans",sans-serif !important;
    font-size:12px !important;
    font-weight:650 !important;
}

div[data-testid="stHorizontalBlock"]:has(.nav-brand) .st-key-top_home button:hover,
div[data-testid="stHorizontalBlock"]:has(.nav-brand) .st-key-top_features button:hover,
div[data-testid="stHorizontalBlock"]:has(.nav-brand) .st-key-top_workflow button:hover,
div[data-testid="stHorizontalBlock"]:has(.nav-brand) .st-key-top_faq button:hover{
    color:var(--ui-rose-strong) !important;
    background:transparent !important;
    box-shadow:inset 0 -2px 0 var(--ui-rose) !important;
}

.st-key-top_prepare button{
    min-height:38px !important;
    color:#fff !important;
    border:0 !important;
    border-radius:999px !important;
    background:linear-gradient(115deg,#34232d,#55394d) !important;
    box-shadow:0 9px 23px rgba(44,29,38,.12) !important;
}

/* HOME HERO — tinted rather than white */
.home-structured{
    position:relative !important;
    padding:34px 24px 42px !important;
    border:1px solid rgba(255,255,255,.43) !important;
    border-radius:28px !important;
    background:
        radial-gradient(circle at 50% 18%, rgba(255,255,255,.68), transparent 48%),
        linear-gradient(
            145deg,
            rgba(255,248,252,.58),
            rgba(241,226,236,.38)
        ) !important;
    box-shadow:
        0 25px 68px rgba(106,67,87,.045),
        inset 0 1px 0 rgba(255,255,255,.46) !important;
}

.kicker,
.result-final-eyebrow{
    color:var(--ui-rose) !important;
}

.section-title,
.home-structured .section-title,
.workspace-clean-head .section-title,
.result-final-hero h1,
.result-accordion-title,
.result-question-text,
.result-answer-question,
.result-gap-row h4,
.result-markdown h2,
.result-markdown h3,
.result-markdown h4,
.result-study-plan h2,
.result-study-plan h3,
.result-study-plan h4,
.result-download-head strong{
    color:var(--ui-heading) !important;
}

.section-title span,
.home-structured .section-title span,
.faq-main-title,
.result-final-hero h1 span{
    color:var(--ui-rose) !important;
}

.section-copy,
.home-structured .section-copy,
.faq-intro,
.result-final-hero > p,
.result-accordion-subtitle,
.result-no-resume-note,
.result-download-head span,
[data-testid="stCaptionContainer"] p{
    color:var(--ui-muted) !important;
}

/* CTA buttons */
.st-key-home_prepare button,
.st-key-generate_interview_prep button,
.stButton > button[kind="primary"]{
    color:#fff !important;
    border-color:transparent !important;
    background:
        linear-gradient(
            115deg,
            #ca5489 0%,
            #bb6499 52%,
            #765a82 100%
        ) !important;
    box-shadow:0 12px 27px rgba(176,69,120,.14) !important;
}

.st-key-home_workflow button{
    color:var(--ui-plum) !important;
    border:0 !important;
    background:transparent !important;
}

/* Workspace / upload surfaces */
.stTextArea textarea,
.stTextInput input,
[data-baseweb="select"] > div,
[data-testid="stFileUploader"] section,
[data-testid="stPopover"] > div{
    color:var(--ui-text) !important;
    border-color:rgba(94,58,78,.11) !important;
    background:
        linear-gradient(
            145deg,
            rgba(255,252,254,.86),
            rgba(247,237,243,.90)
        ) !important;
}

.stTextArea textarea::placeholder,
.stTextInput input::placeholder{
    color:#a28d98 !important;
}

/* Feature / workflow surfaces */
.page-panel{
    color:var(--ui-text) !important;
    border-color:var(--ui-line) !important;
    background:
        linear-gradient(
            145deg,
            rgba(255,249,252,.77),
            rgba(245,233,241,.71)
        ) !important;
    box-shadow:0 18px 46px rgba(86,52,70,.04) !important;
}

.pretty-card{
    color:#33262e !important;
    border-color:rgba(83,47,68,.10) !important;
}

.cards-4 .pretty-card:nth-child(1),
.cards-5 .pretty-card:nth-child(1){
    background:linear-gradient(145deg,#f8dce8,#f4d5e2) !important;
}

.cards-4 .pretty-card:nth-child(2),
.cards-5 .pretty-card:nth-child(2){
    background:linear-gradient(145deg,#eee5f5,#e9ddf1) !important;
}

.cards-4 .pretty-card:nth-child(3),
.cards-5 .pretty-card:nth-child(3){
    background:linear-gradient(145deg,#f6e6ed,#f1dce5) !important;
}

.cards-4 .pretty-card:nth-child(4),
.cards-5 .pretty-card:nth-child(4){
    background:linear-gradient(145deg,#eadff1,#e4d7ed) !important;
}

.cards-5 .pretty-card:nth-child(5){
    background:linear-gradient(145deg,#f8e3eb,#f1d8e2) !important;
}

.pretty-card h3,
.pretty-card p,
.pretty-card .card-label,
.pretty-card .card-num,
.pretty-card .card-foot{
    color:#33262e !important;
}

/* FAQ */
.faq-clean details{
    color:var(--ui-text) !important;
    border-color:var(--ui-line) !important;
    background:
        linear-gradient(
            145deg,
            rgba(255,250,253,.61),
            rgba(246,235,242,.57)
        ) !important;
}

/* Results */
.result-fit-section,
.result-no-resume-skills,
.result-download-head{
    border-color:var(--ui-line) !important;
}

.result-match-label,
.result-skill-block h3{
    color:var(--ui-muted) !important;
}

.result-match-score,
.result-question-number,
.result-accordion-index{
    color:var(--ui-rose) !important;
}

.result-match-bar{
    background:rgba(128,110,121,.14) !important;
}

.result-match-bar span{
    background:linear-gradient(90deg,var(--ui-rose),var(--ui-plum)) !important;
}

.result-skill-chip.matched{
    color:var(--ui-green) !important;
    border-color:rgba(52,122,76,.18) !important;
    background:var(--ui-green-soft) !important;
}

.result-skill-chip.matched i{
    color:var(--ui-green) !important;
    background:rgba(52,122,76,.10) !important;
}

.result-skill-chip.missing{
    color:var(--ui-red) !important;
    border-color:rgba(168,69,97,.18) !important;
    background:var(--ui-red-soft) !important;
}

.result-skill-chip.missing i{
    color:var(--ui-red) !important;
    background:rgba(168,69,97,.10) !important;
}

.result-priority-gap{
    color:var(--ui-text) !important;
    border-color:rgba(201,79,134,.20) !important;
    background:linear-gradient(135deg,#fff0f6,#f0e8f4) !important;
}

.result-priority-gap h2{
    color:var(--ui-heading) !important;
}

.result-priority-gap p{
    color:#725f69 !important;
}

.result-next-step{
    border:1px solid rgba(255,255,255,.07) !important;
    background:linear-gradient(120deg,#392630,#67465e) !important;
    box-shadow:0 12px 28px rgba(61,39,52,.10) !important;
}

.result-next-step span{
    color:#f8bed8 !important;
}

.result-next-step strong,
.result-next-step p{
    color:#fff7fb !important;
}

.result-accordion-box{
    color:var(--ui-text) !important;
    border-color:var(--ui-line) !important;
    background:
        linear-gradient(
            145deg,
            rgba(255,250,253,.76),
            rgba(246,235,242,.72)
        ) !important;
}

.result-accordion-box[open]{
    background:linear-gradient(145deg,#fff9fc,#f8edf4) !important;
    box-shadow:0 14px 34px rgba(87,52,72,.05) !important;
}

.result-accordion-content,
.result-question-row,
.result-answer-row,
.result-gap-row{
    border-color:var(--ui-line) !important;
}

.result-question-domain{
    color:var(--ui-plum) !important;
}

.result-markdown,
.result-answer-body,
.result-gap-row p,
.result-study-plan,
.result-study-plan p,
.result-study-plan li{
    color:#66545e !important;
}

.result-gap-recommendation{
    background:rgba(255,243,249,.73) !important;
}

.result-study-plan blockquote{
    color:#6f5e67 !important;
    background:rgba(255,243,249,.82) !important;
}

.stDownloadButton > button{
    color:var(--ui-text) !important;
    border-color:var(--ui-line) !important;
    background:linear-gradient(145deg,#fff9fc,#f7edf3) !important;
}

@media(max-width:900px){
    .block-container{
        padding-top:4.1rem !important;
    }

    div[data-testid="stHorizontalBlock"]:has(.nav-brand){
        overflow-x:auto !important;
        overflow-y:visible !important;
    }

    .home-structured{
        padding-left:16px !important;
        padding-right:16px !important;
    }
}


/* ==========================================================
   DREAMY PREP+ WALLPAPER — FINAL
   Pink + lavender clouds, soft waves and subtle sparkle.
   ========================================================== */

html,
body{
    background: #f6e9f1 !important;
}

.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"]{
    position: relative !important;
    min-height: 100vh !important;
    overflow-x: hidden !important;

    background:
        /* top-left warm blush glow */
        radial-gradient(
            circle at 8% 8%,
            rgba(246, 177, 204, .70) 0%,
            rgba(246, 177, 204, .28) 17%,
            transparent 36%
        ),

        /* top-right lavender glow */
        radial-gradient(
            circle at 92% 10%,
            rgba(199, 181, 226, .56) 0%,
            rgba(199, 181, 226, .22) 18%,
            transparent 37%
        ),

        /* soft left cloud */
        radial-gradient(
            ellipse at 0% 52%,
            rgba(255,255,255,.88) 0%,
            rgba(255,255,255,.48) 17%,
            rgba(255,255,255,.12) 32%,
            transparent 44%
        ),

        /* soft lower-left cloud */
        radial-gradient(
            ellipse at 14% 90%,
            rgba(255,255,255,.74) 0%,
            rgba(255,255,255,.30) 22%,
            transparent 43%
        ),

        /* soft right cloud */
        radial-gradient(
            ellipse at 100% 55%,
            rgba(255,255,255,.84) 0%,
            rgba(255,255,255,.34) 19%,
            transparent 43%
        ),

        /* lower lavender cloud */
        radial-gradient(
            ellipse at 78% 92%,
            rgba(221, 204, 235, .34) 0%,
            rgba(221, 204, 235, .16) 23%,
            transparent 45%
        ),

        /* center soft ivory wash */
        radial-gradient(
            ellipse at 50% 42%,
            rgba(255, 250, 252, .58) 0%,
            rgba(255, 250, 252, .18) 42%,
            transparent 67%
        ),

        /* base */
        linear-gradient(
            135deg,
            #f9dce8 0%,
            #f7e6ed 28%,
            #f1e5f2 58%,
            #e8e0f2 100%
        ) !important;
}

/* Decorative wallpaper waves */
.stApp::before{
    content: "";
    position: fixed;
    z-index: 0;
    inset: 0;
    pointer-events: none;

    background-image:
        url("data:image/svg+xml,%3Csvg width='1600' height='900' viewBox='0 0 1600 900' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' stroke='white' stroke-opacity='.32'%3E%3Cpath d='M-80 250 C220 120 350 410 650 275 S1120 165 1680 380' stroke-width='2'/%3E%3Cpath d='M-90 270 C210 145 360 435 665 295 S1130 190 1680 405' stroke-width='1.2'/%3E%3Cpath d='M-90 705 C230 550 470 830 760 650 S1260 565 1690 760' stroke-width='2'/%3E%3Cpath d='M-100 730 C230 575 480 855 770 675 S1270 590 1700 785' stroke-width='1.15'/%3E%3C/g%3E%3C/svg%3E"),
        radial-gradient(circle at 7% 23%, rgba(255,255,255,.95) 0 1.5px, transparent 2.2px),
        radial-gradient(circle at 16% 12%, rgba(255,255,255,.86) 0 1.2px, transparent 2px),
        radial-gradient(circle at 66% 15%, rgba(255,255,255,.90) 0 1.5px, transparent 2.2px),
        radial-gradient(circle at 88% 25%, rgba(255,255,255,.86) 0 1.2px, transparent 2px),
        radial-gradient(circle at 91% 62%, rgba(255,255,255,.82) 0 1.2px, transparent 2px),
        radial-gradient(circle at 10% 70%, rgba(255,255,255,.82) 0 1.2px, transparent 2px);

    background-repeat: no-repeat;
    background-size:
        cover,
        100% 100%,
        100% 100%,
        100% 100%,
        100% 100%,
        100% 100%,
        100% 100%;

    opacity: .92;
}

/* Keep app content above wallpaper */
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
[data-testid="stMainBlockContainer"],
.block-container{
    position: relative !important;
    z-index: 1 !important;
}

/* Streamlit header merges into the wallpaper */
[data-testid="stHeader"]{
    background:
        linear-gradient(
            90deg,
            rgba(248,228,238,.92),
            rgba(241,229,244,.92)
        ) !important;
    backdrop-filter: blur(18px) !important;
}

/* Navigation: soft frosted glass, not pure white */
div[data-testid="stHorizontalBlock"]:has(.nav-brand){
    background:
        linear-gradient(
            135deg,
            rgba(255,250,253,.82),
            rgba(249,239,246,.75)
        ) !important;

    border: 1px solid rgba(255,255,255,.72) !important;

    box-shadow:
        0 12px 34px rgba(91,56,75,.07),
        inset 0 1px 0 rgba(255,255,255,.55) !important;

    backdrop-filter: blur(22px) !important;
}

/* Main hero: light frosted panel, matching reference */
.home-structured{
    background:
        radial-gradient(
            circle at 50% 15%,
            rgba(255,255,255,.78),
            rgba(255,255,255,.34) 48%,
            transparent 72%
        ),
        linear-gradient(
            145deg,
            rgba(255,250,253,.76),
            rgba(248,237,244,.63)
        ) !important;

    border: 1.5px solid rgba(255,255,255,.76) !important;

    box-shadow:
        0 28px 70px rgba(106,67,87,.08),
        inset 0 1px 0 rgba(255,255,255,.62) !important;

    backdrop-filter: blur(14px) !important;
}

/* Secondary surfaces should be tinted rather than white */
.page-panel,
.faq-clean details,
.result-accordion-box,
.result-accordion-box[open],
.stDownloadButton > button,
.stTextArea textarea,
.stTextInput input,
[data-baseweb="select"] > div,
[data-testid="stFileUploader"] section,
[data-testid="stPopover"] > div{
    background:
        linear-gradient(
            145deg,
            rgba(255,251,253,.82),
            rgba(247,236,244,.78)
        ) !important;

    border-color: rgba(255,255,255,.66) !important;

    box-shadow:
        inset 0 1px 0 rgba(255,255,255,.42) !important;

    backdrop-filter: blur(12px) !important;
}

/* CTA remains vivid and readable */
.st-key-home_prepare button,
.st-key-generate_interview_prep button,
.stButton > button[kind="primary"]{
    background:
        linear-gradient(
            110deg,
            #cf4f89 0%,
            #bc6197 50%,
            #765785 100%
        ) !important;

    color: #fff !important;

    box-shadow:
        0 14px 32px rgba(184,78,132,.18) !important;
}

/* Preserve excellent text contrast */
.section-title,
.home-structured .section-title,
.workspace-clean-head .section-title{
    color: #2b2028 !important;
}

.section-title span,
.home-structured .section-title span,
.faq-main-title,
.result-final-hero h1 span{
    color: #c94f86 !important;
}

.section-copy,
.home-structured .section-copy{
    color: #796872 !important;
}

/* A little more visual breathing room */
.home-structured{
    margin-top: 18px !important;
}

@media(max-width: 900px){
    .stApp::before{
        opacity: .66;
    }

    .home-structured{
        border-radius: 24px !important;
    }
}

</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# APPROVED REFERENCE DESIGN — FINAL OVERRIDE
# ============================================================

st.markdown(
    f"""
<style>

/* ----------------------------------------------------------
   0. REMOVE STREAMLIT CHROME THAT WAS COVERING THE NAV
   ---------------------------------------------------------- */

#MainMenu,
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
footer{{
    display:none !important;
}}

[data-testid="stHeader"]{{
    height:0 !important;
    min-height:0 !important;
    background:transparent !important;
}}

.block-container{{
    max-width:1920px !important;
    padding:8px 14px 38px !important;
}}

/* ----------------------------------------------------------
   1. EXACT WALLPAPER FEEL
   ---------------------------------------------------------- */

html,
body{{
    background:#f3e7ef !important;
}}

.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"]{{
    min-height:100vh !important;
    color:#2a2027 !important;

    background-image:
        linear-gradient(
            rgba(255,255,255,.02),
            rgba(255,255,255,.02)
        ),
        url("data:image/webp;base64,{WALLPAPER_B64}") !important;

    background-size:cover !important;
    background-position:center top !important;
    background-repeat:no-repeat !important;
    background-attachment:fixed !important;
}}

/* Disable older generated wallpaper overlays so the actual asset wins. */
.stApp::before,
.stApp::after{{
    display:none !important;
}}

[data-testid="stAppViewContainer"] .main .block-container,
.block-container{{
    position:relative !important;
    z-index:2 !important;
    background:transparent !important;
}}

/* ----------------------------------------------------------
   2. TOP FROSTED NAVIGATION
   ---------------------------------------------------------- */

div[data-testid="stHorizontalBlock"]:has(.nav-brand){{
    position:relative !important;
    top:auto !important;
    z-index:20 !important;

    min-height:66px !important;
    margin:0 !important;
    padding:5px 8px !important;

    overflow:visible !important;

    border:1px solid rgba(255,255,255,.76) !important;
    border-radius:20px !important;

    background:
        linear-gradient(
            135deg,
            rgba(255,252,254,.86),
            rgba(249,242,247,.80)
        ) !important;

    box-shadow:
        0 10px 28px rgba(90,57,76,.075),
        inset 0 1px 0 rgba(255,255,255,.82) !important;

    backdrop-filter:blur(20px) !important;
}}

/* Equal visual height in every nav cell */
div[data-testid="stHorizontalBlock"]:has(.nav-brand) div[data-testid="column"]{{
    display:flex !important;
    align-items:center !important;
    min-height:54px !important;
}}

/* prep+ logo becomes its own soft pill like the reference */
.nav-brand{{
    width:100% !important;
    min-height:52px !important;

    display:flex !important;
    align-items:center !important;

    padding:0 18px !important;

    border-radius:18px !important;
    border:1px solid rgba(255,255,255,.70) !important;

    color:#2b2027 !important;
    background:rgba(255,255,255,.72) !important;

    font-family:"Manrope","DM Sans",sans-serif !important;
    font-size:27px !important;
    font-weight:800 !important;
    letter-spacing:-.04em !important;

    box-shadow:
        inset 0 1px 0 rgba(255,255,255,.80),
        0 8px 18px rgba(92,58,77,.035) !important;
}}

.nav-brand span{{
    color:#d64f8e !important;
}}

/* Reference-style pale rounded navigation tabs */
div[data-testid="stHorizontalBlock"]:has(.nav-brand) .st-key-top_home,
div[data-testid="stHorizontalBlock"]:has(.nav-brand) .st-key-top_features,
div[data-testid="stHorizontalBlock"]:has(.nav-brand) .st-key-top_workflow,
div[data-testid="stHorizontalBlock"]:has(.nav-brand) .st-key-top_faq{{
    width:100% !important;
}}

div[data-testid="stHorizontalBlock"]:has(.nav-brand) .st-key-top_home button,
div[data-testid="stHorizontalBlock"]:has(.nav-brand) .st-key-top_features button,
div[data-testid="stHorizontalBlock"]:has(.nav-brand) .st-key-top_workflow button,
div[data-testid="stHorizontalBlock"]:has(.nav-brand) .st-key-top_faq button{{
    width:100% !important;
    max-width:none !important;
    min-height:52px !important;
    height:52px !important;

    margin:0 !important;
    padding:0 14px !important;

    border:1px solid rgba(91,62,78,.08) !important;
    border-radius:18px !important;

    color:#65545f !important;
    background:
        linear-gradient(
            145deg,
            rgba(255,252,254,.66),
            rgba(247,239,245,.70)
        ) !important;

    box-shadow:
        inset 0 1px 0 rgba(255,255,255,.72) !important;

    font-family:"Manrope","DM Sans",sans-serif !important;
    font-size:17px !important;
    font-weight:500 !important;
}}

div[data-testid="stHorizontalBlock"]:has(.nav-brand) .st-key-top_home button:hover,
div[data-testid="stHorizontalBlock"]:has(.nav-brand) .st-key-top_features button:hover,
div[data-testid="stHorizontalBlock"]:has(.nav-brand) .st-key-top_workflow button:hover,
div[data-testid="stHorizontalBlock"]:has(.nav-brand) .st-key-top_faq button:hover{{
    color:#b54478 !important;
    border-color:rgba(201,79,134,.18) !important;
    background:
        linear-gradient(
            145deg,
            rgba(255,248,252,.84),
            rgba(245,229,239,.84)
        ) !important;
    transform:translateY(-1px) !important;
}}

/* Dark Start preparing pill */
.st-key-top_prepare{{
    width:100% !important;
}}

.st-key-top_prepare button{{
    width:100% !important;
    max-width:none !important;
    min-height:54px !important;
    height:54px !important;

    margin:0 !important;
    padding:0 24px !important;

    border:0 !important;
    border-radius:18px !important;

    color:#fff !important;
    background:
        linear-gradient(
            115deg,
            #2f2029,
            #382630
        ) !important;

    box-shadow:
        0 10px 25px rgba(47,32,41,.16),
        inset 0 1px 0 rgba(255,255,255,.05) !important;

    font-family:"Manrope","DM Sans",sans-serif !important;
    font-size:17px !important;
    font-weight:650 !important;
}}

.nav-spacer{{
    height:0 !important;
}}

/* ----------------------------------------------------------
   3. HOME HERO — MATCH THE APPROVED IMAGE
   ---------------------------------------------------------- */

.home-structured{{
    width:min(64vw, 1160px) !important;
    min-height:505px !important;

    margin:108px auto 0 !important;
    padding:50px 72px 54px !important;

    display:flex !important;
    align-items:center !important;
    justify-content:center !important;

    border:2px solid rgba(255,255,255,.78) !important;
    border-radius:48px !important;

    background:
        radial-gradient(
            circle at 50% 12%,
            rgba(255,255,255,.72),
            rgba(255,255,255,.28) 48%,
            transparent 75%
        ),
        linear-gradient(
            145deg,
            rgba(255,250,253,.76),
            rgba(247,236,243,.61)
        ) !important;

    box-shadow:
        0 28px 70px rgba(99,61,81,.085),
        inset 0 1px 0 rgba(255,255,255,.84) !important;

    backdrop-filter:blur(15px) !important;
}}

.home-structured .section-head{{
    width:100% !important;
    max-width:900px !important;
    margin:0 auto !important;
    text-align:center !important;
}}

.home-structured .kicker{{
    margin-bottom:24px !important;

    color:#d64f8e !important;

    font-family:"Manrope","DM Sans",sans-serif !important;
    font-size:13px !important;
    font-weight:800 !important;
    letter-spacing:.15em !important;
    text-transform:uppercase !important;
}}

.home-structured .section-title{{
    color:#281d24 !important;

    font-family:"DM Serif Display",Georgia,serif !important;
    font-size:clamp(64px, 5.5vw, 94px) !important;
    line-height:.98 !important;
    font-weight:400 !important;
    letter-spacing:-.045em !important;
}}

.home-structured .section-title span{{
    color:#cf4c87 !important;
}}

.home-structured .section-copy{{
    max-width:790px !important;
    margin:30px auto 0 !important;

    color:#776671 !important;

    font-family:"Manrope","DM Sans",sans-serif !important;
    font-size:16px !important;
    font-weight:430 !important;
    line-height:1.72 !important;
}}

/* ----------------------------------------------------------
   4. HOME CTA BUTTONS
   ---------------------------------------------------------- */

/* Streamlit's existing button row sits directly below the hero. */
.st-key-home_prepare button,
.st-key-home_workflow button{{
    min-height:56px !important;
    height:56px !important;
    border-radius:999px !important;

    font-family:"Manrope","DM Sans",sans-serif !important;
    font-size:16px !important;
    font-weight:650 !important;
}}

.st-key-home_prepare button{{
    color:#fff !important;
    border:0 !important;

    background:
        linear-gradient(
            110deg,
            #d04e89 0%,
            #bb6197 52%,
            #765785 100%
        ) !important;

    box-shadow:
        0 14px 30px rgba(188,78,133,.19) !important;
}}

.st-key-home_workflow button{{
    color:#65545f !important;

    border:1px solid rgba(255,255,255,.72) !important;

    background:
        linear-gradient(
            145deg,
            rgba(255,252,254,.80),
            rgba(250,244,248,.78)
        ) !important;

    box-shadow:
        inset 0 1px 0 rgba(255,255,255,.75) !important;
}}

/* Pull the CTA row close to the hero like the reference. */
div[data-testid="stHorizontalBlock"]:has(.st-key-home_prepare){{
    width:min(52vw, 840px) !important;
    margin:18px auto 0 !important;
    gap:18px !important;
}}

/* ----------------------------------------------------------
   5. OTHER PAGES KEEP THE SAME WALLPAPER LANGUAGE
   ---------------------------------------------------------- */

.section-free:not(.home-structured),
.page-panel,
.faq-clean,
.workspace-clean-head,
.result-final-hero,
.result-fit-section,
.result-no-resume-skills,
.result-accordion-stack,
.result-download-head{{
    position:relative !important;
    z-index:2 !important;
}}

.page-panel,
.faq-clean details,
.result-accordion-box,
.result-accordion-box[open],
.stDownloadButton > button,
.stTextArea textarea,
.stTextInput input,
[data-baseweb="select"] > div,
[data-testid="stFileUploader"] section,
[data-testid="stPopover"] > div{{
    border-color:rgba(255,255,255,.62) !important;

    background:
        linear-gradient(
            145deg,
            rgba(255,251,253,.84),
            rgba(247,236,244,.76)
        ) !important;

    box-shadow:
        0 12px 32px rgba(92,57,76,.045),
        inset 0 1px 0 rgba(255,255,255,.68) !important;

    backdrop-filter:blur(12px) !important;
}}

/* Preserve your approved result colors */
.result-next-step{{
    color:#fff !important;
    background:
        linear-gradient(
            120deg,
            #382630,
            #67465e
        ) !important;
}}

.result-next-step strong,
.result-next-step p{{
    color:#fff7fb !important;
}}

/* ----------------------------------------------------------
   6. RESPONSIVE
   ---------------------------------------------------------- */

@media(max-width:1100px){{
    .home-structured{{
        width:78vw !important;
        min-height:470px !important;
        margin-top:72px !important;
    }}

    div[data-testid="stHorizontalBlock"]:has(.st-key-home_prepare){{
        width:68vw !important;
    }}
}}

@media(max-width:780px){{
    .block-container{{
        padding:8px 10px 28px !important;
    }}

    div[data-testid="stHorizontalBlock"]:has(.nav-brand){{
        overflow-x:auto !important;
        overflow-y:visible !important;
        min-width:700px !important;
    }}

    .home-structured{{
        width:94vw !important;
        min-height:auto !important;
        margin-top:48px !important;
        padding:42px 22px 46px !important;
        border-radius:32px !important;
    }}

    .home-structured .section-title{{
        font-size:clamp(50px, 13vw, 72px) !important;
    }}

    .home-structured .section-copy{{
        font-size:14px !important;
    }}

    div[data-testid="stHorizontalBlock"]:has(.st-key-home_prepare){{
        width:94vw !important;
    }}
}}

</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# NAVIGATION
# ============================================================

st.html('<div class="nav-bar-marker"></div>')

brand_col, home_col, features_col, workflow_col, faq_col, prepare_col = st.columns(
    [1.62, 0.90, 0.98, 1.02, 0.78, 1.72],
    vertical_alignment="center",
)

with brand_col:
    st.html('<div class="nav-brand">prep<span>+</span></div>')

with home_col:
    if st.button(
        "Home",
        key="top_home",
        type="secondary",
        use_container_width=False,
    ):
        go_to("home")

with features_col:
    if st.button(
        "Features",
        key="top_features",
        type="secondary",
        use_container_width=False,
    ):
        go_to("features")

with workflow_col:
    if st.button(
        "Workflow",
        key="top_workflow",
        type="secondary",
        use_container_width=False,
    ):
        go_to("workflow")

with faq_col:
    if st.button(
        "FAQ",
        key="top_faq",
        type="secondary",
        use_container_width=False,
    ):
        go_to("faq")

with prepare_col:
    if st.button(
        "Start preparing ↗",
        key="top_prepare",
        type="primary",
        use_container_width=False,
    ):
        go_to("workspace")

st.markdown('<div class="nav-spacer"></div>', unsafe_allow_html=True)


# ============================================================
# HOME
# ============================================================

def show_home() -> None:
    st.html(
        """
<div class="section-free home-structured">
  <div class="section-head">
    <div class="kicker">Interview Prep Agent</div>

    <div class="section-title">
      Prepare smarter.<br><span>Interview better.</span>
    </div>

    <div class="section-copy">
      Turn a target job description and your resume into a focused preparation
      workspace with role requirements, skill gaps, reviewed interview questions,
      answer frameworks and a practical study plan.
    </div>
  </div>
</div>
"""
    )

    left, primary_col, secondary_col, right = st.columns([1.4, 1.2, 1.2, 1.4])

    with primary_col:
        if st.button(
            "Build my interview plan ↗",
            key="home_prepare",
            type="primary",
            use_container_width=True,
        ):
            go_to("workspace")

    with secondary_col:
        if st.button(
            "See the AI workflow",
            key="home_workflow",
            use_container_width=True,
        ):
            go_to("workflow")


# ============================================================
# FEATURES
# ============================================================

def show_features() -> None:
    st.html(
        """
<div class="section-free">
  <div class="section-head">
    <div class="kicker">Features</div>
    <div class="section-title">
      Everything you need to <span>prepare properly.</span>
    </div>
    <div class="section-copy">
      One focused workspace for understanding the role, spotting gaps and
      preparing for the actual interview.
    </div>
  </div>

  <div class="cards-4">
    <article class="pretty-card">
      <div class="card-top"><div class="card-icon">⌕</div><div class="card-num">01</div></div>
      <div class="card-label">Role intelligence</div>
      <h3>Job Analysis</h3>
      <p>Extract important requirements, responsibilities and skills from the target job description.</p>
      <span class="card-foot">✦ AI assisted</span>
    </article>

    <article class="pretty-card">
      <div class="card-top"><div class="card-icon">◌</div><div class="card-num">02</div></div>
      <div class="card-label">Resume fit</div>
      <h3>Resume Matching</h3>
      <p>Compare the resume with the target role and identify matching strengths and missing skills.</p>
      <span class="card-foot">◎ Skill match</span>
    </article>

    <article class="pretty-card">
      <div class="card-top"><div class="card-icon">?</div><div class="card-num">03</div></div>
      <div class="card-label">Question engine</div>
      <h3>Interview Questions</h3>
      <p>Generate technical, behavioral and practical questions aligned to the target role.</p>
      <span class="card-foot">? Role specific</span>
    </article>

    <article class="pretty-card">
      <div class="card-top"><div class="card-icon">↗</div><div class="card-num">04</div></div>
      <div class="card-label">Preparation</div>
      <h3>Study Plan</h3>
      <p>Turn identified gaps into a focused preparation plan that is easy to follow.</p>
      <span class="card-foot">↗ Focused plan</span>
    </article>
  </div>
</div>
"""
    )


# ============================================================
# WORKFLOW
# ============================================================

def show_workflow() -> None:
    st.html(
        """
<div class="section-free">
  <div class="section-head">
    <div class="kicker">Agentic workflow</div>
    <div class="section-title">
      Five focused stages.<br><span>One preparation system.</span>
    </div>
    <div class="section-copy">
      The workflow shows how Interview Prep Agent transforms a job description
      into structured interview preparation.
    </div>
  </div>

  <div class="cards-5">
    <article class="pretty-card">
      <div class="card-top"><div class="card-icon">⌕</div><div class="card-num">01</div></div>
      <div class="card-label">Understand role</div>
      <h3>Analyze</h3>
      <p>Extract role requirements and identify what the company needs.</p>
      <span class="card-foot">01 · Input</span>
    </article>

    <article class="pretty-card">
      <div class="card-top"><div class="card-icon">?</div><div class="card-num">02</div></div>
      <div class="card-label">Create set</div>
      <h3>Generate</h3>
      <p>Create likely interview questions from the extracted requirements.</p>
      <span class="card-foot">02 · Questions</span>
    </article>

    <article class="pretty-card">
      <div class="card-top"><div class="card-icon">✓</div><div class="card-num">03</div></div>
      <div class="card-label">Quality check</div>
      <h3>Review</h3>
      <p>The reviewer stage critiques and improves the generated question set.</p>
      <span class="card-foot">03 · Refine</span>
    </article>

    <article class="pretty-card">
      <div class="card-top"><div class="card-icon">✦</div><div class="card-num">04</div></div>
      <div class="card-label">Prepare response</div>
      <h3>Answer</h3>
      <p>Create answer frameworks and useful preparation guidance.</p>
      <span class="card-foot">04 · Guidance</span>
    </article>

    <article class="pretty-card">
      <div class="card-top"><div class="card-icon">↗</div><div class="card-num">05</div></div>
      <div class="card-label">Prioritize</div>
      <h3>Plan</h3>
      <p>Turn the role requirements into a focused study plan.</p>
      <span class="card-foot">05 · Study</span>
    </article>
  </div>
</div>
"""
    )


# ============================================================
# FAQ
# ============================================================

FAQS = [
    ("What do I need to start?", "A job description is enough. Paste it directly or upload it as PDF, DOCX or TXT."),
    ("Do I need to upload my resume?", "No. A resume is optional, but uploading it enables match score and skill-gap analysis."),
    ("What file types can I upload?", "Resume: PDF or DOCX. Job description: PDF, DOCX or TXT."),
    ("What does the AI workflow generate?", "It extracts requirements, generates questions, reviews them, creates answer frameworks and builds a study plan."),
    ("Are the questions specific to the job I am applying for?", "Yes. The workflow analyzes the supplied job description before creating the interview set."),
    ("Does the app generate sample answers?", "Yes. The Answer stage produces answer frameworks and preparation guidance."),
    ("What if my resume is missing important skills?", "The resume analysis identifies missing skills so the study plan can focus on the gaps."),
    ("Can I prepare with only a job description?", "Yes. The main interview workflow can run using only the job description."),
    ("Can I prepare for another company later?", "Yes. Replace the previous JD and resume with the new ones and generate a fresh preparation set."),
    ("Can I download the complete preparation?", "Yes. The generated preparation can be downloaded as Markdown and PDF."),
    ("What will the report contain?", "Requirements, interview questions, answer frameworks, study plan, and resume analysis when a resume is uploaded."),
    ("Is my resume displayed publicly?", "No. Uploaded files are used only by the interview-preparation workflow in this app."),
]


def show_faq() -> None:
    st.html(
        """
<div class="section-free faq-clean">
  <div class="section-head">
    <div class="kicker">FAQ</div>

    <div class="section-title">
      Questions before you <span>get started.</span>
    </div>

    <div class="section-copy">
      The most useful things to know about job descriptions, resumes,
      AI preparation and downloadable reports.
    </div>
  </div>

  <div class="faq-list">

    <details class="faq-row" open>
      <summary>What do I need to start?</summary>
      <p>A job description is enough. You can paste it directly or upload it as PDF, DOCX or TXT.</p>
    </details>

    <details class="faq-row">
      <summary>Do I need to upload my resume?</summary>
      <p>No. A resume is optional, but adding one enables resume matching and skill-gap analysis.</p>
    </details>

    <details class="faq-row">
      <summary>What does Interview Prep Agent generate?</summary>
      <p>It creates role requirements, reviewed interview questions, answer frameworks and a focused study plan.</p>
    </details>

    <details class="faq-row">
      <summary>Are the interview questions specific to the role?</summary>
      <p>Yes. The system analyzes the job description first, then prepares questions around that role.</p>
    </details>

    <details class="faq-row">
      <summary>What happens if my resume is missing important skills?</summary>
      <p>The resume analysis highlights missing skills so you know what to focus on before the interview.</p>
    </details>

    <details class="faq-row">
      <summary>Can I download my preparation?</summary>
      <p>Yes. The generated preparation can be downloaded as a Markdown or PDF report.</p>
    </details>

  </div>
</div>
"""
    )


# ============================================================
# RESULTS
# ============================================================

def show_results() -> None:
    result = st.session_state.result

    if result is None:
        return

    match_score = st.session_state.match_score
    skill_gap = st.session_state.skill_gap

    role_title = (
        get_result_field(result, "role_title").strip()
        or "Target Role"
    )

    required_skills = _as_skill_list(
        getattr(result, "required_skills", [])
    )

    requirements = get_result_field(result, "requirements")
    questions_text = get_result_field(
        result,
        "reviewed_questions",
        "questions",
        "interview_questions",
    )
    answers_text = get_result_field(
        result,
        "answers",
        "sample_answers",
        "answer_frameworks",
    )
    study_plan = get_result_field(
        result,
        "study_plan",
        "plan",
        "preparation_plan",
    )

    question_items = _parse_questions(questions_text)
    answer_items = _parse_answers(answers_text)

    resume_uploaded = skill_gap is not None

    hero_badge = (
        '<div class="result-resume-badge"><i></i>Resume uploaded</div>'
        if resume_uploaded
        else ""
    )

    st.html(
        f"""
<section class="result-final-hero">
  <div class="result-final-eyebrow">Interview preparation</div>
  <h1>{_escape(role_title)} <span>Preparation</span></h1>
  <p>
    Personalized preparation based on the job description
    {'and uploaded resume' if resume_uploaded else ''}.
    The most important role requirements and interview topics are prioritized first.
  </p>
  {hero_badge}
</section>
"""
    )

    # --------------------------------------------------------
    # SKILLS / RESUME FIT — not inside another rectangle.
    # --------------------------------------------------------
    if resume_uploaded:
        matching_skills = _as_skill_list(
            getattr(skill_gap, "matching_skills", [])
        )
        missing_skills = _as_skill_list(
            getattr(skill_gap, "missing_skills", [])
        )
        priority_gap = clean_markdown_text(
            getattr(skill_gap, "priority_gap", "")
        )
        priority_reason = clean_markdown_text(
            getattr(skill_gap, "priority_reason", "")
        )
        recommendation = clean_markdown_text(
            getattr(skill_gap, "suggestion", "")
        )

        if not priority_gap and missing_skills:
            priority_gap = missing_skills[0]

        if not priority_reason:
            priority_reason = (
                "This skill is required by the role but is missing or not "
                "strongly demonstrated in the uploaded resume."
            )

        if not recommendation:
            recommendation = (
                f"Create or prepare one practical example that demonstrates "
                f"{priority_gap or 'the highest-priority missing skill'} "
                "and be ready to explain how you used it."
            )

        safe_score = (
            f"{float(match_score):.0f}%"
            if isinstance(match_score, (int, float))
            else _escape(match_score or "N/A")
        )

        st.html(
            f"""
<section class="result-fit-section">
  <div class="result-match-line">
    <div class="result-match-copy">
      <div class="result-match-label">Resume ↔ JD Match</div>
      <div class="result-match-bar">
        <span style="width:{min(max(float(match_score or 0), 0), 100):.0f}%"></span>
      </div>
    </div>
    <div class="result-match-score">{safe_score}</div>
  </div>

  <div class="result-skill-block">
    <h3>Skills found in resume</h3>
    <div class="result-skill-chips">
      {_skills_html(matching_skills, "matched")}
    </div>
  </div>

  <div class="result-skill-block">
    <h3>Skills to strengthen</h3>
    <div class="result-skill-chips">
      {_skills_html(missing_skills, "missing")}
    </div>
  </div>

  <div class="result-priority-gap">
    <div class="result-priority-top">
      <div class="result-priority-number">01</div>
      <div>
        <small>Highest-priority gap</small>
        <h2>{_escape(priority_gap or "Priority skill gap")}</h2>
        <p>{_escape(priority_reason)}</p>
      </div>
    </div>

    <div class="result-next-step">
      <span>Recommended next step</span>
      <strong>Focus on this before the interview</strong>
      <p>{_escape(recommendation)}</p>
    </div>
  </div>
</section>
"""
        )
    else:
        st.html(
            f"""
<section class="result-no-resume-skills">
  <div class="result-skill-block">
    <h3>Skills required for {_escape(role_title)}</h3>
    <div class="result-skill-chips">
      {_skills_html(required_skills, "neutral")}
    </div>
  </div>
  <p class="result-no-resume-note">
    Upload a resume to see Resume ↔ JD Match, matched skills,
    missing skills, priority gaps and personalized recommendations.
  </p>
</section>
"""
        )

    # --------------------------------------------------------
    # ACCORDION SECTIONS
    # --------------------------------------------------------
    requirements_html = _markdown_fragment(requirements)

    skill_gap_box = ""
    if resume_uploaded:
        missing_skills = _as_skill_list(
            getattr(skill_gap, "missing_skills", [])
        )
        priority_gap = clean_markdown_text(
            getattr(skill_gap, "priority_gap", "")
        )
        priority_reason = clean_markdown_text(
            getattr(skill_gap, "priority_reason", "")
        )
        recommendation = clean_markdown_text(
            getattr(skill_gap, "suggestion", "")
        )

        gap_rows = "".join(
            f"""
<div class="result-gap-row">
  <span>Needs preparation</span>
  <h4>{_escape(skill)}</h4>
  <p>
    This skill is required by the JD but is missing or not strongly demonstrated
    in the resume. Prepare a concrete explanation or hands-on example.
  </p>
</div>
"""
            for skill in missing_skills[:5]
        )

        skill_gap_box = f"""
<details class="result-accordion-box">
  <summary>
    <div class="result-accordion-left">
      <span class="result-accordion-index">02</span>
      <div>
        <div class="result-accordion-title">Skill Gap Analysis</div>
        <div class="result-accordion-subtitle">
          Only the areas that need preparation
        </div>
      </div>
    </div>
    <span class="result-accordion-toggle"></span>
  </summary>
  <div class="result-accordion-content">
    {gap_rows or '<p>No major skill gaps were identified.</p>'}
    {
        f'<div class="result-gap-recommendation"><strong>{_escape(priority_gap or "Recommended preparation")}</strong>'
        f'<p>{_escape(priority_reason)}</p><p><b>Action:</b> {_escape(recommendation)}</p></div>'
        if priority_gap or recommendation else ''
    }
  </div>
</details>
"""

    questions_html = ""
    if question_items:
        questions_html = "".join(
            f"""
<div class="result-question-row">
  <span class="result-question-number">{item['number']:02d}</span>
  <span class="result-question-text">{_escape(item['question'])}</span>
  <span class="result-question-domain">{_escape(item['domain'])}</span>
</div>
"""
            for item in question_items
        )
    else:
        questions_html = _markdown_fragment(questions_text)

    answers_html = ""
    if question_items:
        answer_parts = []
        for item in question_items:
            answer = answer_items.get(item["number"], "")
            answer_fragment = _markdown_fragment(
                answer or "No sample answer was returned for this question."
            )
            answer_parts.append(
                f"""
<details class="result-answer-row">
  <summary>
    <span class="result-question-number">{item['number']:02d}</span>
    <span class="result-answer-question">{_escape(item['question'])}</span>
  </summary>
  <div class="result-answer-body">
    {answer_fragment}
  </div>
</details>
"""
            )
        answers_html = "".join(answer_parts)
    else:
        answers_html = _markdown_fragment(answers_text)

    study_plan_html = _markdown_fragment(study_plan)

    accordion_html = f"""
<section class="result-accordion-stack">

  <details class="result-accordion-box">
    <summary>
      <div class="result-accordion-left">
        <span class="result-accordion-index">01</span>
        <div>
          <div class="result-accordion-title">Requirements</div>
          <div class="result-accordion-subtitle">
            What the employer expects you to do
          </div>
        </div>
      </div>
      <span class="result-accordion-toggle"></span>
    </summary>
    <div class="result-accordion-content result-markdown">
      {requirements_html}
    </div>
  </details>

  {skill_gap_box}

  <details class="result-accordion-box">
    <summary>
      <div class="result-accordion-left">
        <span class="result-accordion-index">{'03' if resume_uploaded else '02'}</span>
        <div>
          <div class="result-accordion-title">Important Interview Questions</div>
          <div class="result-accordion-subtitle">
            High-priority questions selected from this JD
          </div>
        </div>
      </div>
      <span class="result-accordion-toggle"></span>
    </summary>
    <div class="result-accordion-content">
      {questions_html}
    </div>
  </details>

  <details class="result-accordion-box">
    <summary>
      <div class="result-accordion-left">
        <span class="result-accordion-index">{'04' if resume_uploaded else '03'}</span>
        <div>
          <div class="result-accordion-title">Sample Answers</div>
          <div class="result-accordion-subtitle">
            One answer for every generated question
          </div>
        </div>
      </div>
      <span class="result-accordion-toggle"></span>
    </summary>
    <div class="result-accordion-content">
      {answers_html}
    </div>
  </details>

  <details class="result-accordion-box">
    <summary>
      <div class="result-accordion-left">
        <span class="result-accordion-index">{'05' if resume_uploaded else '04'}</span>
        <div>
          <div class="result-accordion-title">Personalized Study Plan</div>
          <div class="result-accordion-subtitle">
            Focused preparation based on the JD{' and resume gaps' if resume_uploaded else ''}
          </div>
        </div>
      </div>
      <span class="result-accordion-toggle"></span>
    </summary>
    <div class="result-accordion-content result-study-plan result-markdown">
      {study_plan_html}
    </div>
  </details>

</section>
"""

    st.html(accordion_html)

    full_report = build_report(result, match_score, skill_gap)

    st.html(
        """
<div class="result-download-head">
  <strong>Your personalized preparation is ready.</strong>
  <span>Save the complete report when you are ready to study offline.</span>
</div>
"""
    )

    d1, d2 = st.columns(2)

    with d1:
        st.download_button(
            "↓ Download Markdown",
            data=full_report,
            file_name="interview_prep_report.md",
            mime="text/markdown",
            use_container_width=True,
        )

    with d2:
        try:
            pdf_bytes = report_to_pdf(full_report)
            st.download_button(
                "PDF · Download Report",
                data=pdf_bytes,
                file_name="interview_prep_report.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except ImportError:
            st.button(
                "PDF · Download Report",
                disabled=True,
                use_container_width=True,
                help="Install fpdf2 to enable PDF export.",
            )
        except Exception as exc:
            st.error(f"PDF export failed: {exc}")


# ============================================================
# WORKSPACE
# ============================================================

def show_workspace() -> None:
    st.html(
        """
<div class="section-free workspace-clean-head">
  <div class="section-head">
    <div class="kicker">Preparation workspace</div>

    <div class="section-title">
      Build your interview <span>preparation.</span>
    </div>

    <div class="section-copy">
      Paste your job description below. Use the + button if you want to
      attach a resume or upload the job description as a file.
    </div>
  </div>
</div>
"""
    )

    left_label, center_label, plus_label, right_label = st.columns(
        [2.2, 6.2, 0.5, 2.2],
        vertical_alignment="center",
    )

    with center_label:
        st.html(
            """
<div class="workspace-input-label centered">
  <span>Job Description</span>
</div>
"""
        )

    left_box, center_box, plus_box, right_box = st.columns(
        [2.2, 6.2, 0.5, 2.2],
        vertical_alignment="top",
    )

    with center_box:
        job_description = st.text_area(
            "Job description",
            key="jd_text",
            placeholder=(
                "Paste the job description here...\n"
                "Example: Python Developer / Data Analyst / AI Engineer..."
            ),
            height=72,
            max_chars=12000,
            label_visibility="collapsed",
        )

    with plus_box:
        st.markdown("<div class='plus-align-space'></div>", unsafe_allow_html=True)
        with st.popover("＋", use_container_width=True):
            st.markdown("**Add files**")

            st.file_uploader(
                "Resume · PDF / DOCX",
                type=["pdf", "docx"],
                key="resume_file",
            )

            st.file_uploader(
                "Job Description · PDF / DOCX / TXT",
                type=["pdf", "docx", "txt"],
                key="jd_file",
            )

    attachments = []

    if st.session_state.get("resume_file") is not None:
        attachments.append(
            f"Resume: {html.escape(st.session_state.resume_file.name)}"
        )

    if st.session_state.get("jd_file") is not None:
        attachments.append(
            f"JD: {html.escape(st.session_state.jd_file.name)}"
        )

    cap_left, cap_center, cap_right = st.columns([2.2, 6.7, 2.7])

    with cap_center:
        if attachments:
            st.caption(" · ".join(attachments))
        else:
            st.caption(
                f"{len(job_description)} / 12000 characters · "
                "Use ＋ to add Resume or JD file."
            )

    b1, b2, b3 = st.columns([1.5, 2.0, 1.5])

    with b2:
        generate = st.button(
            "✦ Generate Interview Preparation",
            key="generate_interview_prep",
            type="primary",
            use_container_width=True,
        )

    if generate:
        jd_text = ""

        jd_file = st.session_state.get("jd_file")
        resume_file = st.session_state.get("resume_file")

        if jd_file is not None:
            try:
                jd_text = read_jd_file(jd_file)
            except Exception as exc:
                st.error(f"Couldn't read the job description file: {exc}")

        if not jd_text.strip():
            jd_text = job_description

        if not jd_text.strip():
            st.warning("Please paste or upload a job description first.")
            return

        match_score = None
        skill_gap = None

        if resume_file is not None:
            with st.spinner("Reading resume and computing match score..."):
                try:
                    resume_file.seek(0)
                    resume_text = extract_resume_text(resume_file)
                    match_score = compute_match_score(resume_text, jd_text)
                    skill_gap = analyze_skill_gap(resume_text, jd_text)
                except Exception as exc:
                    st.error(
                        f"Resume analysis failed, but interview generation will continue: {exc}"
                    )

        try:
            with st.spinner(
                "Interview Prep Agent is analyzing the role and building your preparation..."
            ):
                focus_context = ""
                if skill_gap is not None:
                    missing_for_focus = _as_skill_list(
                        getattr(skill_gap, "missing_skills", [])
                    )
                    if missing_for_focus:
                        focus_context = (
                            "Candidate skill gaps to prioritize where relevant: "
                            + ", ".join(missing_for_focus)
                        )

                result = run_graph_pipeline(
                    jd_text,
                    focus_context=focus_context,
                )
        except RuntimeError as exc:
            st.error(str(exc))
            return
        except Exception as exc:
            st.error(f"AI generation failed: {exc}")
            return

        st.session_state.result = result
        st.session_state.match_score = match_score
        st.session_state.skill_gap = skill_gap
        st.session_state.last_jd = jd_text

        st.success("Your interview preparation is ready.")

    show_results()


# ============================================================
# FOOTER
# ============================================================

def show_footer() -> None:
    st.html(
        """
<div class="site-footer">
  <div class="feedback-row">
    <span class="feedback-label">Found something off?</span>
    <a class="footer-link"
       href="https://github.com/pallavivhalgade/interview-prep-agent/issues/new"
       target="_blank">🐞 Report a bug</a>
    <a class="footer-link"
       href="https://github.com/pallavivhalgade/interview-prep-agent/issues/new"
       target="_blank">💡 Share an idea</a>
  </div>

  <div class="github-footer">
    ⭐ Like Interview Prep Agent?
    &nbsp; <strong>Star the project on GitHub</strong>
    &nbsp; · &nbsp;
    <a href="https://github.com/pallavivhalgade/interview-prep-agent"
       target="_blank">View source ↗</a>
  </div>

  <div class="project-year">
    © 2026 Interview Prep Agent
  </div>
</div>
"""
    )


# ============================================================
# ROUTER — ONLY ONE MAIN VIEW AT A TIME
# ============================================================

view = st.session_state.view

if view == "home":
    show_home()
elif view == "features":
    show_features()
elif view == "workflow":
    show_workflow()
elif view == "faq":
    show_faq()
elif view == "workspace":
    show_workspace()
else:
    st.session_state.view = "home"
    show_home()

show_footer()
