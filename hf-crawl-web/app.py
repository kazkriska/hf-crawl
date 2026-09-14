import streamlit as st
import requests
import pandas as pd
import os

st.set_page_config(page_title="HF Crawl Dashboard", page_icon="🤗", layout="wide")

# --- Config ---
API_URL = os.environ.get("API_URL", "http://localhost:8001")

# --- Sidebar ---
st.sidebar.title("🤗 HF Crawl")
page = st.sidebar.radio("Page", ["Overview", "Models by Pipeline", "Model Search", "Model Info", "Model Cards", "Raw SQL"])

# --- API Helper ---
def api_get(path, params=None, timeout=30):
    resp = requests.get(f"{API_URL}{path}", params=params, timeout=timeout)
    return resp.json()

def api_post(path, json_data=None, timeout=30):
    resp = requests.post(f"{API_URL}{path}", json=json_data, timeout=timeout)
    return resp.json()

# --- Main ---
try:
    health = api_get("/health")
    if health.get("status") != "ok":
        st.error(f"API unhealthy")
        st.stop()
except Exception as e:
    st.error(f"Cannot connect to API at {API_URL}: {e}")
    st.stop()

if page == "Overview":
    st.title("📊 Database Overview")
    
    stats = api_get("/stats")
    progress = api_post("/sql", {"query": "SELECT COUNT(*) as cnt FROM models_list WHERE created_at > datetime '2024-01-01'"}).get("rows", [[0]])
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Models Listed", f"{stats.get('models_list', 0):,}")
    col2.metric("Info Fetched", f"{stats.get('model_info', 0):,}")
    col3.metric("Cards Fetched", f"{stats.get('model_card', 0):,}")
    
    # Top downloads
    st.subheader("Top 20 Models by Downloads")
    top = api_post("/sql", {"query": "SELECT model_id, downloads, pipeline_tag FROM models_list ORDER BY downloads DESC LIMIT 20"}).get("rows", [])
    if top:
        df = pd.DataFrame(top)
        st.dataframe(df, use_container_width=True, hide_index=True)

elif page == "Models by Pipeline":
    st.title("📦 Models by Pipeline Tag")
    
    tag_data = api_post("/sql", {"query": "SELECT pipeline_tag, COUNT(*) as cnt FROM models_list GROUP BY pipeline_tag ORDER BY cnt DESC"}).get("rows", [])
    if tag_data:
        df = pd.DataFrame(tag_data)
        
        # Show bar chart
        st.bar_chart(df.set_index("pipeline_tag")["cnt"])
        
        # Show models per tag
        for _, row in df.iterrows():
            tag = row["pipeline_tag"]
            count = row["cnt"]
            with st.expander(f"**{tag}** ({count:,} models)"):
                models = api_post("/sql", {"query": f"SELECT model_id, downloads FROM models_list WHERE pipeline_tag = '{tag}' ORDER BY downloads DESC LIMIT 100"}).get("rows", [])
                if models:
                    mdf = pd.DataFrame(models)
                    st.dataframe(mdf, use_container_width=True, hide_index=True)

elif page == "Model Search":
    st.title("🔍 Model Search")
    
    col1, col2 = st.columns(2)
    with col1:
        search = st.text_input("Search model ID", "")
    with col2:
        tag_filter = st.selectbox("Filter by pipeline tag", ["All"] + [r["pipeline_tag"] for r in api_post("/sql", {"query": "SELECT DISTINCT pipeline_tag FROM models_list WHERE pipeline_tag IS NOT NULL ORDER BY pipeline_tag"}).get("rows", [])])
    
    limit = st.slider("Results per page", 50, 500, 100)
    
    query = "SELECT model_id, author, downloads, likes, pipeline_tag, created_at FROM models_list WHERE 1=1"
    params = []
    if search:
        query += " AND model_id LIKE ?"
        params.append(f"%{search}%")
    if tag_filter != "All":
        query += " AND pipeline_tag = ?"
        params.append(tag_filter)
    query += f" ORDER BY downloads DESC LIMIT {limit}"
    
    if params:
        models = api_post("/sql", {"query": query}).get("rows", [])
    else:
        models = api_post("/sql", {"query": query}).get("rows", [])
    
    if models:
        df = pd.DataFrame(models)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No models found")

elif page == "Model Info":
    st.title("ℹ️ Model Info")
    model_id = st.text_input("Enter model ID", "albert/albert-base-v2")
    if model_id:
        resp = api_get(f"/model/{model_id}")
        if "error" not in resp:
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("Basic Info")
                st.write(f"**ID:** {resp.get('model_id')}")
                st.write(f"**SHA:** {resp.get('sha')}")
                st.write(f"**Gated:** {resp.get('gated')}")
                st.write(f"**Disabled:** {resp.get('disabled')}")
                st.write(f"**Storage:** {resp.get('used_storage', 0):,} bytes")
            with col2:
                st.subheader("Card Data")
                st.json(resp.get("card_data", {}))
            st.subheader("Config")
            st.json(resp.get("config", {}))
        else:
            st.warning(f"No info found for {model_id}")

elif page == "Model Cards":
    st.title("📝 Model Cards")
    model_id = st.text_input("Enter model ID", "albert/albert-base-v2")
    if model_id:
        resp = api_get(f"/cards/{model_id}")
        if "error" not in resp:
            tab1, tab2 = st.tabs(["README", "YAML Metadata"])
            with tab1:
                st.markdown(resp.get("readme_raw", ""))
            with tab2:
                st.json(resp.get("yaml_metadata", {}))
        else:
            st.warning(f"No card found for {model_id}")

elif page == "Raw SQL":
    st.title("🗄️ Raw SQL Query")
    query = st.text_area("SQL", "SELECT model_id, downloads FROM models_list ORDER BY downloads DESC LIMIT 10", height=150)
    if st.button("Run"):
        resp = api_post("/sql", {"query": query})
        if resp.get('error'):
            st.error(resp['error'])
        else:
            df = pd.DataFrame(resp.get('rows', []), columns=resp.get('columns', []))
            st.dataframe(df, use_container_width=True)
