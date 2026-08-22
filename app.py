import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from engine import GoatedEngine

# PAGE CONFIG
st.set_page_config(page_title="Goated Algo Suite", layout="wide", page_icon="🚀")

# PULL SECRETS FROM STREAMLIT SETTINGS
# Ensure you put these in the Streamlit Cloud Sidebar under "Secrets"
try:
    API_KEY = st.secrets["ALPACA_KEY"]
    API_SECRET = st.secrets["ALPACA_SECRET"]
except:
    st.error("⚠️ API Keys missing! Go to Streamlit Cloud Settings > Secrets and add ALPACA_KEY and ALPACA_SECRET.")
    st.stop()
