import streamlit as st
import google.generativeai as genai
import yfinance as yf
import pandas as pd
import altair as alt
import warnings
import re
import requests
import xml.etree.ElementTree as ET
import time
import numpy as np

# Suppress warnings
warnings.filterwarnings('ignore')

st.set_page_config(page_title="Institutional AI Analyst", layout="wide")

st.markdown("""
<style>
    /* 1. TERMINAL BACKGROUND */
    .stApp {
        background-color: #0E1117;
        font-family: 'SF Mono', 'Roboto Mono', monospace;
    }

    /* 2. BUTTONS - FORCE BLUE */
    button {
        background-color: #3399FF !important;
        border: 1px solid #3399FF !important;
        color: white !important;
        font-weight: bold !important;
        transition: all 0.2s ease !important;
    }
    div.stButton > button:hover {
        background-color: #2678CC !important;
        border-color: #2678CC !important;
        box-shadow: 0 0 12px rgba(51, 153, 255, 0.5) !important;
    }
    div.stButton > button:active {
        background-color: #1A528A !important;
    }

    /* 3. INPUT BOX - NUCLEAR FIX FOR RED BORDER */
    /* Target the internal wrapper that holds the border */
    div[data-baseweb="base-input"] {
        background-color: #0D1117 !important;
        border: 1px solid #30363D !important;
        border-radius: 4px !important;
    }
    /* FOCUS STATE - Force Blue Border & Blue Glow */
    div[data-baseweb="base-input"]:focus-within {
        border: 1px solid #3399FF !important;
        box-shadow: 0 0 0 1px #3399FF !important;
    }
    /* Text Color */
    div[data-testid="stTextInput"] input {
        color: #E6EDF3 !important;
        caret-color: #3399FF !important;
    }

    /* 4. ALERTS - KILL GREEN BACKGROUND */
    /* Force "System Online" box to be Dark */
    div[data-testid="stAlert"] {
        background-color: #0D1117 !important;
        border: 1px solid #30363D !important;
        color: #E6EDF3 !important;
    }
    /* Specific override for the 'success' green variant */
    div[data-testid="stAlert"][data-variant="success"] {
        background-color: #0D1117 !important; /* Kills Green Bg */
        border-left: 4px solid #3399FF !important; /* Blue Stripe */
        color: #E6EDF3 !important;
    }
    /* Force Icon to be Blue */
    div[data-testid="stAlert"] svg {
        fill: #3399FF !important;
    }

    /* 5. METRIC CARDS */
    div[data-testid="stMetric"] {
        background-color: #161B22 !important;
        border: 1px solid #30363D !important;
        padding: 15px !important;
        border-radius: 6px !important;
    }
    div[data-testid="stMetricValue"] {
        color: #3399FF !important;
        font-size: 28px !important;
    }
    div[data-testid="stMetricLabel"] {
        color: #8B949E !important;
    }

    /* 6. SIDEBAR */
    section[data-testid="stSidebar"] {
        background-color: #010409 !important;
        border-right: 1px solid #30363D !important;
    }
</style>
""", unsafe_allow_html=True)
# ==========================================
# 1. API KEY ROTATION SYSTEM (Secure & Auto-Switch)
# ==========================================

try:
    API_KEYS = st.secrets["gemini"]["api_keys"]
except Exception:
    # Fallback for local testing if secrets.toml isn't set up
    st.error("❌ No API Keys found in Secrets. Please set them up in Streamlit Cloud > Settings > Secrets.")
    st.stop()

@st.cache_resource
def configure_valid_key(keys):
    """
    Tries each key in the list. Returns the first one that works.
    This prevents the app from crashing if one key hits a quota limit.
    """
    for key in keys:
        try:
            genai.configure(api_key=key)
            # Test the key by listing models (Lightweight call)
            list(genai.list_models())
            return key
        except Exception as e:
            print(f"Key failed: {e}") # Log it internally but don't crash
            continue # If key fails, loop to the next one
    return None

# Initialize API
active_key = configure_valid_key(API_KEYS)

if not active_key:
    st.error("❌ Critical Error: All API keys failed or quota exceeded. Please generate NEW keys.")
    st.stop()
# ==========================================
# 2. CORE UTILITY: DYNAMIC MODEL FINDER
# ==========================================
@st.cache_resource
def get_valid_model_name():
    try:
        available_models = list(genai.list_models())
        text_models = [m.name for m in available_models if 'generateContent' in m.supported_generation_methods]
        for m in text_models:
            if 'gemini-1.5-flash' in m: return m
        for m in text_models:
            if 'gemini-1.5-pro' in m: return m
        return text_models[0] if text_models else "models/gemini-pro"
    except:
        return "models/gemini-pro"

ACTIVE_MODEL_NAME = get_valid_model_name()

# Sidebar Control (Cleaned up)
with st.sidebar:
    st.title("Controls")
    st.success(f"System Online")
    st.caption(f"Model: {ACTIVE_MODEL_NAME}")
    st.caption("API Status: Connected")
    st.markdown("---")

# ==========================================
# 3. ENGINE: GOOGLE NEWS RSS (Reliable)
# ==========================================
def get_google_news_rss(query):
    try:
        clean_query = query.split('.')[0] + " stock news"
        url = f"https://news.google.com/rss/search?q={clean_query}&hl=en-US&gl=US&ceid=US:en"
        response = requests.get(url, timeout=5)
        root = ET.fromstring(response.content)
        headlines = []
        for item in root.findall('./channel/item')[:5]:
            title = item.find('title').text
            pubDate = item.find('pubDate').text
            headlines.append(f"- {title} ({pubDate})")
        return "\n".join(headlines) if headlines else "No news found."
    except:
        return "News unavailable."

# ==========================================
# 4. ENGINE: TICKER RESOLVER (AUTO-COMPLETE)
# ==========================================
def check_ticker_live(ticker):
    try:
        price = yf.Ticker(ticker).fast_info.last_price
        return price is not None and price > 0
    except:
        return False

def search_yahoo_ticker(query):
    try:
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=5)
        data = response.json()
        if 'quotes' in data and len(data['quotes']) > 0:
            return data['quotes'][0]['symbol']
    except: pass
    return None

COMMON_MAPPING = {
    "APPLE": "AAPL", "NETFLIX": "NFLX", "GOOGLE": "GOOGL", "AMAZON": "AMZN",
    "TESLA": "TSLA", "MICROSOFT": "MSFT", "META": "META", "NVIDIA": "NVDA",
    "GENERAL MOTORS": "GM", "FORD": "F", "LIC": "LICI.NS", "LICI": "LICI.NS",
    "TATA STEEL": "TATASTEEL.NS", "RELIANCE": "RELIANCE.NS",
    "HDFC": "HDFCBANK.NS", "INFOSYS": "INFY.NS", "NALCO": "NATIONALUM.NS", 
    "GOLDEN DEEPS": "GED.AX", "COMMBANK": "CBA.AX", "ANZ": "ANZ.AX"
}

@st.cache_data(ttl=3600) 
def resolve_ticker(user_input):
    clean_input = user_input.strip().upper()
    if clean_input in COMMON_MAPPING: return COMMON_MAPPING[clean_input]
    if check_ticker_live(clean_input): return clean_input
    if check_ticker_live(clean_input + ".AX"): return clean_input + ".AX"
    if check_ticker_live(clean_input + ".NS"): return clean_input + ".NS"
    
    search_result = search_yahoo_ticker(user_input)
    if search_result and check_ticker_live(search_result): return search_result

    try:
        model = genai.GenerativeModel(ACTIVE_MODEL_NAME)
        prompt = f"What is the exact Yahoo Finance ticker for '{user_input}'? Return ONLY the symbol."
        response = model.generate_content(prompt)
        ai_ticker = response.text.strip().upper().replace(" ", "").replace("`", "")
        if check_ticker_live(ai_ticker): return ai_ticker
    except: pass
    return clean_input

# ==========================================
# 5. DATA ENGINE: DEEP DIVE (MATH & PREDICTION)
# ==========================================
def find_col(df, candidates):
    for c in candidates:
        matches = [col for col in df.columns if c in col]
        if matches: return matches[0]
    return None

def safe_cagr(start, end, years):
    """Handles negative base values intelligently for authentic verdicts."""
    if start is None or end is None or years == 0: return None
    try:
        s, e = float(start), float(end)
        if s == 0: return None # Div by zero
        if s > 0 and e > 0: return round(((e / s)**(1/years) - 1) * 100, 2)
        if s < 0 and e > 0: return "TURNAROUND (Loss to Profit) "
        if s > 0 and e < 0: return "COLLAPSE (Profit to Loss) "
        if s < 0 and e < 0 and e > s: return "IMPROVING (Losses Narrowing) "
        return "N/A"
    except: return None

@st.cache_data(ttl=3600) 
def get_institutional_data(ticker_symbol):
    stock = yf.Ticker(ticker_symbol)
    
    # 1. CORE PRICE (Fast)
    try:
        current_price = stock.fast_info.last_price
        mcap = stock.fast_info.market_cap
        currency = stock.fast_info.currency
    except:
        return {"error": f"Could not find live data for '{ticker_symbol}'."}

    # 2. FINANCIAL STATEMENTS (The Truth)
    try:
        fin = stock.financials.T
        bal = stock.balance_sheet.T
        cash = stock.cashflow.T
        for df in [fin, bal, cash]:
            if not df.empty: df.sort_index(ascending=False, inplace=True)
    except:
        return {"error": "Financial statements unavailable."}

    # 3. KPI CALCULATOR (Math Engine)
    kpis = {}
    raw_txt = "Financial Data Unavailable."
    
    if not fin.empty:
        # Columns
        rev_c = find_col(fin, ['Total Revenue', 'Revenue'])
        eps_c = find_col(fin, ['Basic EPS', 'Diluted EPS'])
        ni_c  = find_col(fin, ['Net Income', 'Net Income Common'])
        
        # RAW HISTORY GENERATOR
        raw_txt = "### 5-YEAR FINANCIAL TREND:\n"
        try:
            subset = fin.head(5)
            for d, row in subset.iterrows():
                d_str = d.strftime('%Y') if hasattr(d, 'strftime') else str(d)[:4]
                r = row.get(rev_c, 0)
                e = row.get(eps_c, 0)
                raw_txt += f"- {d_str}: Revenue {r:,.0f}, EPS {e:.2f}\n"
        except: pass

        # CAGR CALCULATION
        if rev_c:
            kpis['sales_cagr_3y'] = safe_cagr(fin[rev_c].iloc[3], fin[rev_c].iloc[0], 3) if len(fin) > 3 else "N/A"
            kpis['sales_cagr_5y'] = safe_cagr(fin[rev_c].iloc[5], fin[rev_c].iloc[0], 5) if len(fin) > 5 else "N/A"
        
        if eps_c:
            kpis['eps_cagr_3y'] = safe_cagr(fin[eps_c].iloc[3], fin[eps_c].iloc[0], 3) if len(fin) > 3 else "N/A"
            kpis['eps_cagr_5y'] = safe_cagr(fin[eps_c].iloc[5], fin[eps_c].iloc[0], 5) if len(fin) > 5 else "N/A"

    # 4. VALUATION & HEALTH (Manual Calc)
    # PEG Ratio
    try:
        eps_ttm = fin.iloc[0][eps_c]
        pe = current_price / eps_ttm if eps_ttm > 0 else 0
        g = kpis.get('eps_cagr_3y')
        if isinstance(g, (int, float)) and g > 0:
            kpis['peg'] = round(pe / g, 2)
        else:
            kpis['peg'] = "N/A (No Growth/Losses)"
        kpis['pe'] = round(pe, 2)
    except: 
        kpis['peg'] = "N/A"
        kpis['pe'] = "N/A"

    # Debt/Equity & ROE
    try:
        total_debt = bal.iloc[0][find_col(bal, ['Total Debt'])]
        total_equity = bal.iloc[0][find_col(bal, ['Stockholders Equity'])]
        net_income = fin.iloc[0][ni_c]
        
        kpis['debt_equity'] = round(total_debt / total_equity, 2)
        kpis['roe'] = round((net_income / total_equity) * 100, 2)
    except:
        kpis['debt_equity'] = "N/A"
        kpis['roe'] = "N/A"

    # Earnings Quality (OCF vs NI)
    try:
        ocf = cash.iloc[0][find_col(cash, ['Operating Cash Flow', 'Operating'])]
        ni = fin.iloc[0][ni_c]
        kpis['quality'] = "High (Cash > Profit) " if ocf > ni else "Low (Profit > Cash) "
    except:
        kpis['quality'] = "Unknown"

    # 5. CHART DATA (Visual Superiority)
    chart_data = None
    try:
        hist = stock.history(period="2y")
        if not hist.empty:
            hist = hist.reset_index()
            chart_data = hist[['Date', 'Close', 'Volume']]
    except: pass

    # Trend
    try:
        sma200 = hist['Close'].rolling(200).mean().iloc[-1]
        kpis['trend'] = "Uptrend (Above 200DMA) " if current_price > sma200 else "Downtrend (Below 200DMA) "
    except: kpis['trend'] = "Neutral"

    return {
        "ticker": ticker_symbol.upper(),
        "price": current_price,
        "currency": currency,
        "mcap": mcap,
        "kpis": kpis,
        "raw_history": raw_txt,
        "chart_data": chart_data,
        "news": get_google_news_rss(ticker_symbol)
    }

# ==========================================
# 6. SYSTEM PROMPT: THE HEDGE FUND MANAGER
# ==========================================
sys_instruction = """
### ROLE
Institutional Portfolio Manager. You prioritize **Predictive Analysis** over just reading past data.

### 1. FOUNDATIONAL KPIs (GARP)
Evaluate strictly but intelligently:
* **Growth:** 3Y/5Y EPS & Sales > 15-20%. (Note: If CAGR says "TURNAROUND", this is a POSITIVE signal).
* **Valuation:** PEG < 1.0 is ideal. If PE is high but Growth is massive, justify it.
* **Health:** Debt/Equity < 1.0. (Exceptions: Banks/Utilities).
* **Quality:** Cash Flow > Net Income.

### 2. PREDICTIVE SYNTHESIS (Crucial)
Look at the "Raw 5-Year Financial History". 
* Is the momentum accelerating or slowing? 
* Are margins expanding (EPS growing faster than Sales)?
* **Do not fail a stock just because one metric is N/A.** If the *trend* is good, approve it.

### OUTPUT FORMAT
## Institutional Verdict: {Ticker}
**Rating:** [STRONG BUY | BUY | WATCHLIST | SELL]
**Risk Level:** [Low/Medium/High]

### 1. Executive Thesis
(Synthesis of Growth, Value, and Momentum. Explain the "Story" of the stock.)

### 2. Quantitative Scorecard
| Metric | Value | Verdict |
| :--- | :--- | :--- |
| **EPS Growth (3Y/5Y)** | {vals} | [Pass/Fail/Turnaround] |
| **Sales Growth (3Y/5Y)** | {vals} | [Pass/Fail] |
| **PEG Ratio** | {val} | [Undervalued/Overvalued] |
| **ROE** | {val}% | [Efficient/Inefficient] |
| **Debt/Equity** | {val} | [Safe/Risky] |
| **Earnings Quality** | {val} | [High/Low] |

### 3. Predictive Outlook
* **Bull Case:** (What goes right?)
* **Bear Case:** (What goes wrong?)
* **Trend Analysis:** (Comment on the price vs 200DMA).
"""

# ==========================================
# 7. MAIN INTERFACE
# ==========================================
st.title("Institutional Financial Analyst AI")

with st.form(key='analysis_form'):
    col1, col2 = st.columns([3, 1])
    with col1:
        user_input = st.text_input("Enter Company or Ticker", placeholder="e.g., Netflix, Tata Steel, Golden Deeps").strip()
    with col2:
        st.write("")
        st.write("")
        submit_btn = st.form_submit_button("Run Analysis", type="primary", use_container_width=True)

if submit_btn:
    if not user_input:
        st.warning("Please enter a company name.")
    else:
        with st.spinner(f"🔍 Resolving '{user_input}'..."):
            ticker = resolve_ticker(user_input)
            
            if not check_ticker_live(ticker):
                st.error(f"Could not find data for '{ticker}'.")
                st.caption("Try adding the suffix manually (e.g. .NS, .AX).")
            else:
                st.success(f"Target: **{ticker}**")
                
                with st.spinner("Calculating KPIs & Predicting Trends..."):
                    data = get_institutional_data(ticker)
                    
                    if "error" in data:
                        st.error(data['error'])
                    else:
                        # 1. METRICS
                        k = data['kpis']
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("Price", f"{data['currency']} {data['price']:,.2f}")
                        m2.metric("PEG Ratio", str(k.get('peg')))
                        m3.metric("ROE", f"{k.get('roe')}%")
                        m4.metric("Trend", k.get('trend'))
                        
                        # 2. CHART (Visual Superiority)
                        if data.get('chart_data') is not None:
                            chart = alt.Chart(data['chart_data']).mark_line(
                                color='#3399FF',  
                                strokeWidth=2     
                            ).encode(
                                x=alt.X('Date:T', 
                                        axis=alt.Axis(format='%b %Y', title="Date", labelAngle=-45, grid=False)),
                                y=alt.Y('Close:Q', 
                                        axis=alt.Axis(title=f"Price ({data.get('currency', 'USD')})", format=",.2f"),
                                        scale=alt.Scale(zero=False)),
                                tooltip=[
                                    alt.Tooltip('Date:T', format='%b %d, %Y'), 
                                    alt.Tooltip('Close:Q', format=",.2f"),
                                    alt.Tooltip('Volume:Q', format=",.0f")
                                ]
                            ).properties(height=400).configure_view(strokeWidth=0) 
                            st.altair_chart(chart, use_container_width=True)

                        # 3. AI ANALYSIS
                        try:
                            model = genai.GenerativeModel(ACTIVE_MODEL_NAME, system_instruction=sys_instruction)
                            prompt = f"Analyze {ticker}. Financials: {data['raw_history']}. KPIs: {data['kpis']}. News: {data['news']}"
                            response = model.generate_content(prompt)
                            st.markdown(response.text)
                        except Exception as e:
                            st.error(f"AI Synthesis Failed: {e}")
