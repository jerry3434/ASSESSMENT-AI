import os
import streamlit as st
from backend import verify_user_from_excel
from agent1 import render_main_dashboard

st.set_page_config(
    page_title="Agentic Assessment Hub", 
    page_icon="🎓", 
    layout="wide"
)

def load_css(file_name="styles.css"):
    if os.path.exists(file_name):
        with open(file_name, "r") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

load_css("styles.css")

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "username" not in st.session_state:
    st.session_state.username = ""

# LOGIN VIEW
if not st.session_state.authenticated:
    st.markdown("<div style='height: 40px;'></div>", unsafe_allow_html=True)
    _, main_col, _ = st.columns([0.1, 0.8, 0.1])
    
    with main_col:
        col_hero, col_form = st.columns([1, 1], gap="large")

        with col_hero:
            st.markdown("""<div class="login-hero-card">
<div>
<div style="font-size: 20px; font-weight: 800; color: #A78BFA; letter-spacing: 1px;">λMU ASSESSMENT</div>
<div style="color: #64748B; font-size: 12px; margin-top: 2px;">Automated Evaluation Engine</div>
</div>

<div style="margin: 20px 0;">
<div style="color: #FFFFFF; font-size: 24px; font-weight: 700; line-height: 1.3;">Evaluating Logic,<br>Empowering Growth</div>

<div class="hero-feature-item">⚡ <b>Dynamic Rubrics:</b> AI auto-configures weightages</div>
<div class="hero-feature-item">📊 <b>Batch Processing:</b> Multi-file submission parsing</div>
<div class="hero-feature-item">🔍 <b>Similarity Checker:</b> Detects cluster anomalies</div>
</div>

<div style="color: #64748B; font-size: 12px;">© 2026 Academic Assessment Hub</div>
</div>""", unsafe_allow_html=True)

        with col_form:
            st.markdown("<h2 style='color: white; margin-bottom: 2px;'>Sign In</h2>", unsafe_allow_html=True)
            st.markdown("<p style='color: #9CA3AF; margin-bottom: 20px; font-size: 14px;'>Enter institutional credentials</p>", unsafe_allow_html=True)

            if not os.path.exists("users.xlsx"):
                st.warning("⚠️ `users.xlsx` not found in root directory.")

            with st.form("split_login_form"):
                username_input = st.text_input("Username / Email", placeholder="name@institution.edu")
                password_input = st.text_input("Password", type="password", placeholder="••••••••")
                
                st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
                submit_btn = st.form_submit_button("Sign In to Account", type="primary", use_container_width=True)

                if submit_btn:
                    if not username_input.strip() or not password_input.strip():
                        st.error("Please enter both username and password.")
                    else:
                        if verify_user_from_excel(username_input.strip(), password_input.strip()):
                            st.session_state.authenticated = True
                            st.session_state.username = username_input.strip()
                            st.rerun()
                        else:
                            st.error("Invalid credentials.")
else:
    render_main_dashboard() 