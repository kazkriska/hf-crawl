import streamlit as st
import requests
import pandas as pd
import os

st.set_page_config(page_title="HF Crawl Dashboard", page_icon="🤗", layout="wide")

# --- Config ---
API_URL = os.environ.get("API_URL", "http://localhost:8001")

@st.cache_resource
def get_session():
    return requests.Session()

# --- Sidebar ---
st.sidebar.title("🤗 HF Crawl")
page = st.sidebar.radio("Page", ["Overview", "Models", "Model Info", "Model Cards", "Raw SQL"])

# --- Main ---
try:
    resp = requests.get(f"{API_URL}/health", timeout=5)
    if resp.status_code != 200:
        st.error(f"API unhealthy: {resp.status_code}")
        st.stop()
except Exception as e:
    st.error(f"Cannot connect to API at {API_URL}: {e}")
    st.stop()

if page == "Overview":
    st.title("📊 Database Overview")
    
    resp = requests.get(f"{API_URL}/stats", timeout=10).json()
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Models Listed", f"{resp.get('models_list', 0):,}")
    col2.metric("Info Fetched", f"{resp.get('model_info', 0):,}")
    col3.metric("Cards Fetched", f"{resp.get('model_card', 0):,}")
    
    st.subheader("Pipeline Tag Distribution")
    sql_resp = requests.post(f"{API_URL}/sql", json={"query": "SELECT pipeline_tag, COUNT(*) as cnt FROM models_list GROUP BY pipeline_tag ORDER BY cnt DESC LIMIT 20"}, timeout=10).json()
    if sql_resp.get('rows'):
        df = pd.DataFrame(sql_resp['rows'])
        if not df.empty and 'pipeline_tag' in df.columns:
            st.bar_chart(df.set_index('pipeline_tag')['cnt'])

if page == "Models":
    st.title("🔍 Models List")
    
    search = st.text_input("Search model ID", "")
    limit = st.slider("Results per page", 50, 1000, 100)
    
    params = {"limit": limit}
    if search:
        params["search"] = search
    
    models = requests.get(f"{API_URL}/models", params=params, timeout=10).json().get("models", [])
    
    if models:
        df = pd.DataFrame(models)
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No models found")

elif page == "Model Info":
    st.title("ℹ️ Model Info")
    model_id = st.text_input("Enter model ID", "albert/albert-base-v2")
    if model_id:
        resp = requests.get(f"{API_URL}/model/{model_id}", timeout=10)
        if resp.status_code == 200:
            info = resp.json()
            st.json(info)
        else:
            st.warning(f"No info found for {model_id}")

elif page == "Model Cards":
    st.title("📝 Model Cards")
    model_id = st.text_input("Enter model ID", "albert/albert-base-v2")
    if model_id:
        resp = requests.get(f"{API_URL}/cards/{model_id}", timeout=10)
        if resp.status_code == 200:
            card = resp.json()
            tab1, tab2 = st.tabs(["README", "YAML Metadata"])
            with tab1:
                st.markdown(card.get("readme_raw", ""))
            with tab2:
                st.json(card.get("yaml_metadata", {}))
        else:
            st.warning(f"No card found for {model_id}")

elif page == "Raw SQL":
    st.title("🗄️ Raw SQL Query")
    query = st.text_area("SQL", "SELECT model_id, downloads FROM models_list ORDER BY downloads DESC LIMIT 10", height=150)
    if st.button("Run"):
        resp = requests.post(f"{API_URL}/sql", json={"query": query}, timeout=10).json()
        if resp.get('error'):
            st.error(resp['error'])
        else:
            df = pd.DataFrame(resp.get('rows', []))
            st.dataframe(df, use_container_width=True)
