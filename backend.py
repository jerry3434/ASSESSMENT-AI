import os
import re
import sqlite3
import json
import base64
import time
from typing import List, Dict
from dotenv import load_dotenv
import groq
import pandas as pd

# Load API Key
load_dotenv("API.env")
api_key = os.getenv("GROQ_API_KEY")

from langchain_groq import ChatGroq
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import pdfplumber
import docx

# Excel File Path for Credentials
EXCEL_USER_FILE = "users.xlsx"

# Primary LLM
llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0.2,
    api_key=api_key
)

# Backup LLM for Rate Limit failover
fallback_llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0.2,
    api_key=api_key
)

# Exponential Backoff Wrapper catching Rate Limits
@retry(
    wait=wait_exponential(min=2, max=10),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(groq.RateLimitError),
    reraise=False
)
def safe_llm_invoke(prompt):
    try:
        return llm.invoke(prompt)
    except groq.RateLimitError:
        return fallback_llm.invoke(prompt)

# ==========================================
# 1. DATABASE SETUP & MIGRATIONS
# ==========================================
def init_db():
    conn = sqlite3.connect("evaluations.db")
    cursor = conn.cursor()
    
    # Main Evaluations Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS student_evaluations (
            student_id TEXT PRIMARY KEY,
            student_name TEXT,
            essay_text TEXT,
            overall_score REAL,
            grammar_score REAL,
            thesis_score REAL,
            evidence_score REAL,
            structure_score REAL,
            grade TEXT,
            status TEXT,
            feedback TEXT,
            anomaly_flag TEXT
        )
    """)
    
    # Auto-migrate missing columns for existing databases
    cursor.execute("PRAGMA table_info(student_evaluations)")
    columns = [col[1] for col in cursor.fetchall()]
    missing_columns = {
        "student_name": "TEXT",
        "grade": "TEXT",
        "status": "TEXT"
    }
    for col_name, col_type in missing_columns.items():
        if col_name not in columns:
            cursor.execute(f"ALTER TABLE student_evaluations ADD COLUMN {col_name} {col_type}")
    
    conn.commit()
    conn.close()

def clear_db():
    conn = sqlite3.connect("evaluations.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM student_evaluations")
    conn.commit()
    conn.close()

init_db()

# ==========================================
# 2. EXCEL-BASED AUTHENTICATION
# ==========================================
def verify_user_from_excel(username_input: str, password_input: str) -> bool:
    """Verifies credentials directly against users.xlsx."""
    if not os.path.exists(EXCEL_USER_FILE):
        return False
        
    try:
        df = pd.read_excel(EXCEL_USER_FILE)
        df.columns = df.columns.str.strip().str.lower()
        
        match = df[(df['username'].astype(str).str.strip() == username_input.strip()) & 
                   (df['password'].astype(str).str.strip() == password_input.strip())]
        
        return not match.empty
    except Exception as e:
        print(f"Error reading Excel file: {e}")
        return False

# ==========================================
# 3. HELPER: GRADE & STATUS CALCULATOR
# ==========================================
def calculate_grade_and_status(percentage: float):
    if percentage >= 91:
        return "S", "Pass"
    elif percentage >= 81:
        return "A", "Pass"
    elif percentage >= 71:
        return "B", "Pass"
    elif percentage >= 61:
        return "C", "Pass"
    elif percentage >= 51:
        return "D", "Pass"
    elif percentage >= 41:
        return "E", "Pass"
    else:
        return "F", "Fail"

# ==========================================
# 4. DYNAMIC QUESTION-BASED RUBRIC GENERATOR
# ==========================================
def suggest_dynamic_rubric(question_text: str) -> Dict[str, int]:
    """Analyzes question text and outputs recommended rubric weights summing to 100."""
    if not question_text.strip():
        return {"grammar": 25, "thesis": 25, "evidence": 25, "structure": 25}

    prompt = f"""
    You are an academic curriculum designer. Analyze the following question/prompt and decide the optimal weight distribution across these 4 rubric components so that the sum is EXACTLY 100:

    1. Grammar / Syntax / Precision (Weight 0 if pure math/coding/formula problem)
    2. Thesis / Problem Approach / Core Logic
    3. Evidence / Steps / Calculation / Proof
    4. Structure / Clarity / Solution Organization

    QUESTION / PROMPT:
    "{question_text}"

    OUTPUT INSTRUCTIONS:
    Respond STRICTLY with a JSON object. Ensure grammar + thesis + evidence + structure = 100.
    Example JSON:
    {{
        "grammar": 0,
        "thesis": 30,
        "evidence": 50,
        "structure": 20
    }}
    """
    try:
        response = safe_llm_invoke(prompt).content
        clean_json = response[response.find("{"):response.rfind("}")+1]
        weights = json.loads(clean_json)
        
        g = int(weights.get("grammar", 25))
        t = int(weights.get("thesis", 25))
        e = int(weights.get("evidence", 25))
        s = int(weights.get("structure", 25))
        
        # Ensure exact 100 sum
        total = g + t + e + s
        if total != 100 and total > 0:
            diff = 100 - total
            e += diff # Adjust evidence category by remainder
            
        return {"grammar": g, "thesis": t, "evidence": e, "structure": s}
    except Exception:
        return {"grammar": 25, "thesis": 25, "evidence": 25, "structure": 25}

# ==========================================
# 5. FILE PARSERS (PDF, DOCX, TXT, IMAGE)
# ==========================================
def extract_text_from_file(uploaded_file) -> str:
    filename = uploaded_file.name.lower()
    
    if filename.endswith(".txt"):
        return uploaded_file.read().decode("utf-8", errors="ignore")
        
    elif filename.endswith(".pdf"):
        text = ""
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
        return text

    elif filename.endswith(".docx"):
        doc = docx.Document(uploaded_file)
        return "\n".join([para.text for para in doc.paragraphs])

    elif filename.endswith((".png", ".jpg", ".jpeg")):
        image_bytes = uploaded_file.read()
        base64_image = base64.b64encode(image_bytes).decode("utf-8")
        
        msg = fallback_llm.invoke([
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe all written text from this image accurately. Output only raw text."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }
        ])
        return msg.content

    return ""

def parse_class_text_to_batch(raw_text: str) -> List[Dict[str, str]]:
    student_pattern = re.compile(r'(?i)^(student[\s_-]*\w+|name\s*:\s*\w+)', re.MULTILINE)
    matches = list(student_pattern.finditer(raw_text))
    
    batch = []
    if matches:
        for i in range(len(matches)):
            start_idx = matches[i].start()
            end_idx = matches[i+1].start() if i + 1 < len(matches) else len(raw_text)
            
            match_header = matches[i].group(0).strip()
            block_content = raw_text[start_idx:end_idx].strip()
            
            s_identifier = match_header.split("\n")[0].replace(":", "").strip()
            essay_body = block_content[len(match_header):].strip()
            if not essay_body:
                essay_body = block_content
                
            batch.append({
                "student_id": f"ID_{s_identifier}",
                "student_name": s_identifier,
                "essay": essay_body
            })
    else:
        blocks = [b.strip() for b in raw_text.split("\n\n") if len(b.strip()) > 20]
        for idx, block in enumerate(blocks, start=1):
            batch.append({
                "student_id": f"ID_{idx:03d}",
                "student_name": f"Student {idx}",
                "essay": block
            })

    return batch if batch else [{
        "student_id": "ID_001",
        "student_name": "Student 1",
        "essay": raw_text.strip()
    }]

# ==========================================
# 6. SINGLE-PASS AGENT EVALUATION ENGINE
# ==========================================
def evaluate_single_submission(student_id: str, student_name: str, submission: str, weights: Dict[str, int]) -> Dict:
    prompt = f"""
    You are an expert educational grading assistant. Evaluate the following student submission based on the provided rubric weights (out of 100 total points).

    RUBRIC WEIGHT DISTRIBUTION:
    - Grammar / Syntax: {weights.get('grammar', 25)} points max
    - Thesis / Logic / Approach: {weights.get('thesis', 25)} points max
    - Evidence / Steps / Calculation: {weights.get('evidence', 25)} points max
    - Structure / Clarity: {weights.get('structure', 25)} points max

    STUDENT NAME: {student_name} (ID: {student_id})
    SUBMISSION:
    {submission[:2000]}

    OUTPUT INSTRUCTIONS:
    Respond strictly with a valid JSON object matching this exact schema:
    {{
        "grammar_score": <number 0-{weights.get('grammar', 25)}>,
        "thesis_score": <number 0-{weights.get('thesis', 25)}>,
        "evidence_score": <number 0-{weights.get('evidence', 25)}>,
        "structure_score": <number 0-{weights.get('structure', 25)}>,
        "feedback": "<2-3 concise constructive sentences>",
        "anomaly_flag": "<'Clean' OR 'Flagged: reason for blank/gibberish/off-topic text'>"
    }}
    """
    
    try:
        response = safe_llm_invoke(prompt).content
        clean_json = response[response.find("{"):response.rfind("}")+1]
        data = json.loads(clean_json)
    except Exception:
        data = {
            "grammar_score": round(weights.get('grammar', 25) * 0.5, 1),
            "thesis_score": round(weights.get('thesis', 25) * 0.5, 1),
            "evidence_score": round(weights.get('evidence', 25) * 0.5, 1),
            "structure_score": round(weights.get('structure', 25) * 0.5, 1),
            "feedback": "Evaluation completed with default scores.",
            "anomaly_flag": "Clean"
        }

    g_score = float(data.get("grammar_score", 0))
    t_score = float(data.get("thesis_score", 0))
    e_score = float(data.get("evidence_score", 0))
    s_score = float(data.get("structure_score", 0))
    overall_percentage = round(g_score + t_score + e_score + s_score, 1)

    grade, status = calculate_grade_and_status(overall_percentage)

    # Store evaluation in SQLite
    conn = sqlite3.connect("evaluations.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO student_evaluations 
        (student_id, student_name, essay_text, overall_score, grammar_score, thesis_score, evidence_score, structure_score, grade, status, feedback, anomaly_flag)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        student_id, student_name, submission,
        overall_percentage, g_score, t_score, e_score, s_score,
        grade, status,
        str(data.get("feedback", "")),
        str(data.get("anomaly_flag", "Clean"))
    ))
    conn.commit()
    conn.close()

    return {
        "parsed_scores": {
            "grammar_score": g_score,
            "thesis_score": t_score,
            "evidence_score": e_score,
            "structure_score": s_score,
            "overall_score": overall_percentage
        },
        "grade": grade,
        "status": status,
        "feedback": data.get("feedback", ""),
        "anomaly_flag": data.get("anomaly_flag", "Clean")
    }

def process_entire_class_with_progress(batch_data: List[Dict[str, str]], weights: Dict[str, int], progress_bar, status_text) -> List[Dict]:
    results = []
    total = len(batch_data)
    for idx, item in enumerate(batch_data, start=1):
        status_text.text(f"Evaluating {item['student_name']} ({idx}/{total})...")
        res = evaluate_single_submission(
            student_id=item['student_id'],
            student_name=item['student_name'],
            submission=item['essay'],
            weights=weights
        )
        results.append(res)
        progress_bar.progress(idx / total)
        time.sleep(0.5)
    status_text.text("Processing complete!")
    return results

# ==========================================
# 7. SIMILARITY & PLAGIARISM DETECTOR
# ==========================================
def detect_suspicious_similarity(threshold=0.70):
    conn = sqlite3.connect("evaluations.db")
    cursor = conn.cursor()
    cursor.execute("SELECT student_id, student_name, essay_text FROM student_evaluations")
    rows = cursor.fetchall()
    conn.close()

    if len(rows) < 2:
        return []

    ids = [f"{r[1]} ({r[0]})" for r in rows]
    texts = [r[2] for r in rows]

    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform(texts)
    sim_matrix = cosine_similarity(tfidf_matrix)

    flagged_pairs = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            score = sim_matrix[i][j]
            if score >= threshold:
                flagged_pairs.append({
                    "student_1": ids[i],
                    "student_2": ids[j],
                    "similarity_pct": round(float(score) * 100, 1)
                })
    return flagged_pairs

# ==========================================
# 8. TEACHER CHATBOT
# ==========================================
def teacher_chatbot(user_query: str) -> str:
    conn = sqlite3.connect("evaluations.db")
    cursor = conn.cursor()
    cursor.execute("SELECT student_id, student_name, overall_score, grade, status, anomaly_flag FROM student_evaluations")
    all_records = cursor.fetchall()
    conn.close()

    sims = detect_suspicious_similarity(threshold=0.70)
    sim_text = json.dumps(sims) if sims else "None detected."

    context = "Class Summary:\n" + "\n".join([
        f"ID:{r[0]}|Name:{r[1]}|Score:{r[2]}/100|Grade:{r[3]}|Status:{r[4]}|Anomaly:{r[5]}" 
        for r in all_records[:50]
    ])

    prompt = f"""
    You are an AI teaching assistant. Answer concisely using this database summary and plagiarism report.

    CLASS DATASET:
    {context}

    SUSPICIOUS SIMILARITY & PLAGIARISM REPORT:
    {sim_text}

    TEACHER QUESTION: {user_query}
    """
    try:
        return safe_llm_invoke(prompt).content
    except Exception:
        return "⚠️ Rate limit reached on the primary model. Auto-recovering. Please try again in a moment."