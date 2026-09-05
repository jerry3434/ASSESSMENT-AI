import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
from backend import (
    evaluate_single_submission,
    process_entire_class_with_progress,
    extract_text_from_file,
    parse_class_text_to_batch,
    detect_suspicious_similarity,
    teacher_chatbot,
    suggest_dynamic_rubric,
    clear_db
)

def render_rubric_input_fields(key_prefix: str):
    st.markdown("##### 📝 Question Prompt & Dynamic Rubric")
    
    question_text = st.text_input(
        "Question / Assessment Prompt",
        placeholder="e.g., 'Solve dy/dx = 2x + 5 given y(0)=1' OR 'Write an essay analyzing Hamlet'",
        key=f"{key_prefix}_q_input"
    )
    
    for cat in ['grammar', 'thesis', 'evidence', 'structure']:
        w_key = f"{key_prefix}_{cat}"
        if w_key not in st.session_state:
            st.session_state[w_key] = 25

    use_ai_rubric = st.checkbox(
        "🤖 Auto-Detect Rubric Weights from Question", 
        key=f"{key_prefix}_ai_rubric"
    )

    if use_ai_rubric:
        if question_text.strip():
            if st.button("⚡ Calculate & Apply AI Rubric", key=f"{key_prefix}_btn_calc"):
                with st.spinner("Analyzing question content..."):
                    weights_suggested = suggest_dynamic_rubric(question_text)
                    
                    # Explicit integer casting to avoid hidden floating point sum issues
                    st.session_state[f"{key_prefix}_grammar"] = int(round(float(weights_suggested["grammar"])))
                    st.session_state[f"{key_prefix}_thesis"] = int(round(float(weights_suggested["thesis"])))
                    st.session_state[f"{key_prefix}_evidence"] = int(round(float(weights_suggested["evidence"])))
                    st.session_state[f"{key_prefix}_structure"] = int(round(float(weights_suggested["structure"])))
                st.success("Rubric updated successfully!")
                st.rerun()
        else:
            st.warning("⚠️ Enter a question/prompt above to calculate weights.")

    st.markdown("##### 📏 Weightage Distribution")
    r_col1, r_col2, r_col3, r_col4 = st.columns(4)

    g_weight = int(r_col1.number_input("Grammar (%)", min_value=0, max_value=100, step=5, key=f"{key_prefix}_grammar"))
    t_weight = int(r_col2.number_input("Thesis/Logic (%)", min_value=0, max_value=100, step=5, key=f"{key_prefix}_thesis"))
    e_weight = int(r_col3.number_input("Steps/Evidence (%)", min_value=0, max_value=100, step=5, key=f"{key_prefix}_evidence"))
    s_weight = int(r_col4.number_input("Structure (%)", min_value=0, max_value=100, step=5, key=f"{key_prefix}_structure"))

    total_weight = g_weight + t_weight + e_weight + s_weight
    is_valid = round(total_weight) == 100
    
    if is_valid:
        st.caption(f"🟢 **Total:** {total_weight}%")
    else:
        st.error(f"⚠️ **Total:** {total_weight}% (Must sum to 100%)")

    return {
        "grammar": g_weight,
        "thesis": t_weight,
        "evidence": e_weight,
        "structure": s_weight
    }, is_valid


def render_main_dashboard():
    top_col1, top_col2 = st.columns([4, 1])
    with top_col1:
        st.markdown("<h2 style='margin:0;'>🎓 Assessment & Analytics Hub</h2>", unsafe_allow_html=True)
        st.caption(f"Logged in as: **{st.session_state.username}**")
    with top_col2:
        if st.button("🚪 Logout", type="secondary"):
            st.session_state.authenticated = False
            st.session_state.username = ""
            st.rerun()

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs([
        "✍️ Single Evaluation", 
        "📁 Batch Evaluation", 
        "📊 Summary Analytics",
        "💬 AI Assistant Chat"
    ])

    # TAB 1: SINGLE EVALUATION
    with tab1:
        col1, col2 = st.columns([1, 1], gap="large")
        
        with col1:
            c_id, c_name = st.columns(2)
            with c_id:
                s_id = st.text_input("Student ID *", placeholder="STU101")
            with c_name:
                s_name = st.text_input("Student Name *", placeholder="John Doe")
                
            weights_single, is_valid_weight_single = render_rubric_input_fields("single")
            essay_single = st.text_area("Student Submission *", height=150, placeholder="Paste response here...")
            
            can_submit_single = bool(s_id.strip()) and bool(s_name.strip()) and bool(essay_single.strip()) and is_valid_weight_single
            btn_single = st.button("Evaluate Submission", type="primary", disabled=not can_submit_single)

        with col2:
            st.subheader("Evaluation Results")
            if btn_single and essay_single:
                with st.spinner("Evaluating..."):
                    res = evaluate_single_submission(
                        student_id=s_id.strip(),
                        student_name=s_name.strip(),
                        submission=essay_single.strip(),
                        weights=weights_single
                    )
                    
                    if "Flagged" in res["anomaly_flag"]:
                        st.error(f"⚠️ **Anomaly Flagged:** {res['anomaly_flag']}")
                    else:
                        st.success("✅ Submission verified.")

                    scores = res["parsed_scores"]
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Overall Score", f"{scores.get('overall_score', 0)}/100")
                    c2.metric("Grade", res["grade"])
                    c3.metric("Status", res["status"])
                    c4.metric("Grammar", f"{scores.get('grammar_score', 0)}/{weights_single['grammar']}")

                    st.markdown("<hr style='border-color: #2D2447; margin: 15px 0;'>", unsafe_allow_html=True)
                    c_t, c_e, c_s = st.columns(3)
                    c_t.metric("Logic/Thesis", f"{scores.get('thesis_score', 0)}/{weights_single['thesis']}")
                    c_e.metric("Steps/Evidence", f"{scores.get('evidence_score', 0)}/{weights_single['evidence']}")
                    c_s.metric("Structure", f"{scores.get('structure_score', 0)}/{weights_single['structure']}")

                    st.markdown("##### 📝 Detailed Feedback")
                    st.info(res["feedback"])
            else:
                st.caption("Submit an evaluation on the left panel to view metrics.")

    # TAB 2: BATCH UPLOAD
    with tab2:
        c_left, c_right = st.columns([3, 1])
        with c_right:
            if st.button("🗑️ Clear Database", type="secondary"):
                clear_db()
                st.success("Database cleared.")

        weights_batch, is_valid_weight_batch = render_rubric_input_fields("batch")
        uploaded_file = st.file_uploader("Upload Submissions File", type=["pdf", "docx", "txt", "png", "jpg"])

        if uploaded_file is not None:
            extracted_text = extract_text_from_file(uploaded_file)
            with st.expander("📄 View Extracted Text", expanded=False):
                st.text_area("Content", extracted_text, height=120)

            btn_batch = st.button("Run Batch Evaluation", type="primary", disabled=not is_valid_weight_batch)
            if btn_batch:
                batch = parse_class_text_to_batch(extracted_text)
                p_bar = st.progress(0)
                status = st.empty()
                process_entire_class_with_progress(batch, weights_batch, p_bar, status)
                st.success("Batch complete!")

        st.divider()
        st.subheader("📋 Student Evaluation Log")
        conn = sqlite3.connect("evaluations.db")
        df = pd.read_sql_query("SELECT student_id, student_name, overall_score, grade, status, grammar_score, thesis_score, evidence_score, structure_score, anomaly_flag FROM student_evaluations", conn)
        conn.close()
        
        if not df.empty:
            st.dataframe(df, use_container_width=True)
            sims = detect_suspicious_similarity()
            if sims:
                st.warning("⚠️ Suspicious Similarity Flagged:")
                st.json(sims)

    # TAB 3: SUMMARY ANALYTICS
    with tab3:
        st.subheader("📈 Performance Metrics")
        
        conn = sqlite3.connect("evaluations.db")
        df_summary = pd.read_sql_query("SELECT * FROM student_evaluations", conn)
        conn.close()

        if df_summary.empty:
            st.info("No evaluations found in database. Submit evaluations to generate summary charts.")
        else:
            total_students = len(df_summary)
            pass_count = len(df_summary[df_summary["status"] == "Pass"])
            fail_count = len(df_summary[df_summary["status"] == "Fail"])

            # Overview Metrics
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total Students", total_students)
            m2.metric("Pass Rate", f"{(pass_count/total_students)*100:.1f}%" if total_students > 0 else "0%")
            m3.metric("Passed", pass_count)
            m4.metric("Failed", fail_count)

            st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
            
            # Interactive Charts
            chart_col1, chart_col2 = st.columns([1, 1])
            
            with chart_col1:
                st.markdown("##### Pass / Fail Ratio")
                status_counts = pd.DataFrame({
                    "Status": ["Pass", "Fail"],
                    "Count": [pass_count, fail_count]
                })
                fig_pie = px.pie(
                    status_counts, 
                    names="Status", 
                    values="Count", 
                    color="Status",
                    color_discrete_map={"Pass": "#10B981", "Fail": "#EF4444"},
                    hole=0.4
                )
                fig_pie.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#F8FAFC"),
                    margin=dict(t=20, b=20, l=20, r=20)
                )
                st.plotly_chart(fig_pie, use_container_width=True)

            with chart_col2:
                st.markdown("##### Grade Distribution")
                if "grade" in df_summary.columns:
                    grade_counts = df_summary["grade"].value_counts().reset_index()
                    grade_counts.columns = ["Grade", "Count"]
                    fig_bar = px.bar(
                        grade_counts, 
                        x="Grade", 
                        y="Count", 
                        color="Grade",
                        color_discrete_sequence=px.colors.sequential.Purples
                    )
                    fig_bar.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#F8FAFC"),
                        xaxis=dict(showgrid=False),
                        yaxis=dict(showgrid=True, gridcolor="#2D2447"),
                        margin=dict(t=20, b=20, l=20, r=20)
                    )
                    st.plotly_chart(fig_bar, use_container_width=True)

    # TAB 4: CHATBOT
    with tab4:
        if "messages" not in st.session_state:
            st.session_state.messages = []

        chat_container = st.container(height=400)
        with chat_container:
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

        if user_query := st.chat_input("Ask a question about class performance..."):
            st.session_state.messages.append({"role": "user", "content": user_query})
            with chat_container:
                with st.chat_message("user"):
                    st.markdown(user_query)
                with st.chat_message("assistant"):
                    reply = teacher_chatbot(user_query)
                    st.markdown(reply)
            st.session_state.messages.append({"role": "assistant", "content": reply})
            st.rerun()