import streamlit as st
import requests
import pandas as pd
import os

st.set_page_config(page_title="HF Crawl Dashboard", page_icon="🤗", layout="wide")

# --- Config ---
API_URL = os.environ.get("API_URL", "http://localhost:8001")

# --- Sidebar ---
st.sidebar.title("🤗 HF Crawl")
page = st.sidebar.radio("Page", ["Overview", "Pipeline Tags", "Model Search", "Model Info", "Model Cards", "Raw SQL"])

# --- API Helper ---
@st.cache_data(ttl=30)
def get_stats():
    return requests.get(f"{API_URL}/stats", timeout=30).json()

@st.cache_data(ttl=30)
def get_pipeline_tags():
    return requests.post(f"{API_URL}/sql", json={
        "query": "SELECT COALESCE(pipeline_tag, 'NULL/Unset') as tag, COUNT(*) as cnt FROM models_list GROUP BY COALESCE(pipeline_tag, 'NULL/Unset') ORDER BY cnt DESC"
    }, timeout=30).json()

def is_classification_tag(tag):
    """Check if a tag indicates a classification type."""
    classification_tags = [
        'text-classification', 'image-classification', 'audio-classification',
        'video-classification', 'token-classification', 'sentence-similarity',
        'object-detection', 'image-segmentation', 'semantic-segmentation',
        'instance-segmentation', 'panoptic-segmentation', 'depth-estimation',
        'image-to-text', 'text-to-image', 'text-to-video', 'image-to-image',
        'text-generation', 'text2text-generation', 'translation', 'summarization',
        'conversational', 'question-answering', 'fill-mask', 'text-to-speech',
        'automatic-speech-recognition', 'audio-to-audio', 'voice-activity-detection',
        'tabular-classification', 'tabular-regression', 'time-series-forecasting',
        'reinforcement-learning', 'robotics'
    ]
    return tag in classification_tags

# --- Main ---
try:
    requests.get(f"{API_URL}/health", timeout=10).json()
except Exception as e:
    st.error(f"Cannot connect to API at {API_URL}: {e}")
    st.stop()

if page == "Overview":
    st.title("📊 Database Overview")
    stats = get_stats()
    col1, col2, col3 = st.columns(3)
    col1.metric("Models Listed", f"{stats.get('models_list', 0):,}")
    col2.metric("Info Fetched", f"{stats.get('model_info', 0):,}")
    col3.metric("Cards Fetched", f"{stats.get('model_card', 0):,}")
    
    # Null pipeline tags info
    tags_data = get_pipeline_tags()
    null_count = sum(r["cnt"] for r in tags_data.get("rows", []) if r["tag"] == "NULL/Unset")
    total = sum(r["cnt"] for r in tags_data.get("rows", []))
    if null_count > 0:
        st.warning(f"⚠️ {null_count:,} models ({null_count/total*100:.1f}%) have no pipeline_tag set (this is normal for many HF models)")
    
    st.subheader("Top 20 Models by Downloads")
    top = requests.post(f"{API_URL}/sql", json={"query": "SELECT model_id, downloads, pipeline_tag FROM models_list ORDER BY downloads DESC LIMIT 20"}, timeout=30).json()
    if top.get('rows'):
        st.dataframe(pd.DataFrame(top['rows']), use_container_width=True, hide_index=True)

elif page == "Pipeline Tags":
    st.title("📦 Models by Pipeline Tag")
    tags_data = get_pipeline_tags()
    rows = tags_data.get("rows", [])
    if rows:
        df = pd.DataFrame(rows)
        df.columns = ["Pipeline Tag", "Count"]
        st.bar_chart(df.set_index("Pipeline Tag")["Count"])
        
        st.subheader("Models by Tag")
        selected_tag = st.selectbox("Select a pipeline tag to view models:", [r["tag"] for r in rows])
        if selected_tag:
            with st.spinner(f"Loading models for {selected_tag}..."):
                if selected_tag == "NULL/Unset":
                    where_clause = "pipeline_tag IS NULL"
                else:
                    where_clause = f"pipeline_tag = '{selected_tag}'"
                models = requests.post(f"{API_URL}/sql", json={
                    "query": f"SELECT model_id, author, downloads, likes, created_at FROM models_list WHERE {where_clause} ORDER BY downloads DESC LIMIT 200"
                }, timeout=30).json()
                if models.get('rows'):
                    mdf = pd.DataFrame(models['rows'])
                    st.dataframe(mdf, use_container_width=True, hide_index=True)

elif page == "Model Search":
    st.title("🔍 Model Search")
    search = st.text_input("Search model ID", "")
    limit = st.slider("Results per page", 50, 500, 100)
    
    query = "SELECT model_id, author, downloads, likes, pipeline_tag, created_at FROM models_list WHERE 1=1"
    if search:
        query += f" AND model_id LIKE '%{search}%'"
    query += f" ORDER BY downloads DESC LIMIT {limit}"
    
    with st.spinner("Searching..."):
        models = requests.post(f"{API_URL}/sql", json={"query": query}, timeout=30).json()
    
    if models.get('rows'):
        df = pd.DataFrame(models['rows'])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No models found")

elif page == "Model Info":
    st.title("ℹ️ Model Info")
    model_id = st.text_input("Enter model ID", "albert/albert-base-v2")
    if model_id:
        resp = requests.get(f"{API_URL}/model/{model_id}", timeout=10).json()
        if "error" not in resp:
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**ID:** {resp.get('model_id')}")
                st.write(f"**SHA:** {resp.get('sha')}")
                st.write(f"**Gated:** {resp.get('gated')}")
                st.write(f"**Disabled:** {resp.get('disabled')}")
            with col2:
                st.write(f"**Storage:** {resp.get('used_storage', 0):,} bytes")
                st.write(f"**Fetched:** {resp.get('fetched_at')}")
            st.subheader("Card Data")
            st.json(resp.get("card_data", {}))
        else:
            st.warning(f"No info found for {model_id}")

elif page == "Model Cards":
    st.title("📝 Model Cards")
    model_id = st.text_input("Enter model ID", "albert/albert-base-v2")
    if model_id:
        resp = requests.get(f"{API_URL}/cards/{model_id}", timeout=10).json()
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
        resp = requests.post(f"{API_URL}/sql", json={"query": query}, timeout=30).json()
        if resp.get('error'):
            st.error(resp['error'])
        else:
            df = pd.DataFrame(resp.get('rows', []), columns=resp.get('columns', []))
            st.dataframe(df, use_container_width=True, hide_index=True)
