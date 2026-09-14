import streamlit as st
import duckdb
import pandas as pd
import os

st.set_page_config(page_title="HF Crawl Dashboard", page_icon="🤗", layout="wide")

# --- Config ---
DB_PATH = st.sidebar.text_input("Database path", value="../hf-crawl/data/dev/model_cards.duckdb")

@st.cache_resource
def get_conn(path):
    return duckdb.connect(path, read_only=True)

# --- Sidebar ---
st.sidebar.title("🤗 HF Crawl")
page = st.sidebar.radio("Page", ["Overview", "Models", "Model Info", "Model Cards", "Raw SQL"])

# --- Main ---
try:
    conn = get_conn(DB_PATH)
except Exception as e:
    st.error(f"Cannot connect to database: {e}")
    st.stop()

if page == "Overview":
    st.title("📊 Database Overview")
    
    col1, col2, col3, col4 = st.columns(4)
    list_count = conn.execute("SELECT COUNT(*) FROM models_list").fetchone()[0]
    info_count = conn.execute("SELECT COUNT(*) FROM model_info").fetchone()[0]
    card_count = conn.execute("SELECT COUNT(*) FROM model_card").fetchone()[0]
    db_size = os.path.getsize(DB_PATH) / (1024*1024) if os.path.exists(DB_PATH) else 0
    
    col1.metric("Models Listed", f"{list_count:,}")
    col2.metric("Info Fetched", f"{info_count:,}")
    col3.metric("Cards Fetched", f"{card_count:,}")
    col4.metric("DB Size", f"{db_size:.1f} MB")
    
    st.subheader("Pipeline Tag Distribution")
    tags = conn.execute("""
        SELECT pipeline_tag, COUNT(*) as count 
        FROM models_list 
        WHERE pipeline_tag IS NOT NULL
        GROUP BY pipeline_tag 
        ORDER BY count DESC
        LIMIT 20
    """).fetchdf()
    if not tags.empty:
        st.bar_chart(tags.set_index("pipeline_tag"))
    
    st.subheader("Top 20 by Downloads")
    top = conn.execute("""
        SELECT model_id, downloads, pipeline_tag 
        FROM models_list 
        ORDER BY downloads DESC 
        LIMIT 20
    """).fetchdf()
    st.dataframe(top, use_container_width=True)

elif page == "Models":
    st.title("🔍 Models List")
    
    search = st.text_input("Search model ID", "")
    tag_filter = st.selectbox("Filter by pipeline tag", ["All"] + [r[0] for r in conn.execute("SELECT DISTINCT pipeline_tag FROM models_list WHERE pipeline_tag IS NOT NULL ORDER BY pipeline_tag").fetchall()])
    
    query = "SELECT model_id, author, downloads, likes, pipeline_tag, library_name, created_at FROM models_list WHERE 1=1"
    params = []
    if search:
        query += " AND model_id LIKE ?"
        params.append(f"%{search}%")
    if tag_filter != "All":
        query += " AND pipeline_tag = ?"
        params.append(tag_filter)
    query += " ORDER BY downloads DESC LIMIT 1000"
    
    df = conn.execute(query, params).fetchdf()
    st.write(f"Showing {len(df)} rows")
    st.dataframe(df, use_container_width=True)

elif page == "Model Info":
    st.title("ℹ️ Model Info")
    
    model_id = st.text_input("Enter model ID", "albert/albert-base-v2")
    if model_id:
        info = conn.execute("SELECT * FROM model_info WHERE model_id = ?", [model_id]).fetchdf()
        if info.empty:
            st.warning(f"No info found for {model_id}")
        else:
            st.subheader(model_id)
            row = info.iloc[0]
            col1, col2, col3 = st.columns(3)
            col1.metric("SHA", str(row.get("sha", "N/A"))[:12])
            col2.metric("Gated", row.get("gated", "N/A"))
            col3.metric("Disabled", row.get("disabled", "N/A"))
            
            st.subheader("Card Data")
            st.json(row.get("card_data", {}))
            
            st.subheader("Config")
            st.json(row.get("config", {}))
            
            st.subheader("Siblings")
            st.json(row.get("siblings", []))

elif page == "Model Cards":
    st.title("📝 Model Cards")
    
    model_id = st.text_input("Enter model ID", "albert/albert-base-v2")
    if model_id:
        card = conn.execute("SELECT * FROM model_card WHERE model_id = ?", [model_id]).fetchdf()
        if card.empty:
            st.warning(f"No card found for {model_id}")
        else:
            row = card.iloc[0]
            st.subheader(model_id)
            st.metric("README size", f"{row.get('readme_size', 0):,} bytes")
            
            tab1, tab2 = st.tabs(["README", "YAML Metadata"])
            with tab1:
                st.markdown(row.get("readme_raw", ""))
            with tab2:
                st.json(row.get("yaml_metadata", {}))

elif page == "Raw SQL":
    st.title("🗄️ Raw SQL Query")
    
    query = st.text_area("SQL", "SELECT model_id, downloads FROM models_list ORDER BY downloads DESC LIMIT 10", height=150)
    if st.button("Run"):
        try:
            result = conn.execute(query).fetchdf()
            st.dataframe(result, use_container_width=True)
        except Exception as e:
            st.error(str(e))

# --- Footer ---
st.sidebar.markdown("---")
st.sidebar.caption("HF Crawl Dashboard v1.0")
