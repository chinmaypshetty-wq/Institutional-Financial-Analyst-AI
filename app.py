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

# 1. CONFIGURE PAGE & THEME (NO EMOJIS)
st.set_page_config(page_title="Institutional AI Analyst", page_icon=None, layout="wide")

# 2. REFINED INSTITUTIONAL STYLING (METALLIC GOLD)
st.markdown("""
<style>
    /* 1. DEEP SPACE BACKGROUND */
    .stApp {
        background: radial-gradient(circle at top left, #1B2838 0%, #0E1117 100%);
        font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    }

    /* 2. REFINED METALLIC GOLD BUTTONS (No more neon yellow) */
    div.stButton > button {
        background: linear-gradient(135deg, #D4AF37 0%, #AA8C2C 100%) !important; /* Metallic Gold Gradient */
        border: 1px solid #8A6E18 !important;
        color: white !important; /* White text looks cleaner on dark gold */
        font-weight: 700 !important;
        text-transform: uppercase !important;
        letter-spacing: 1px !important;
        border-radius: 4px !important;
        box-shadow: 0 4px 10px rgba(212, 175, 55, 0.3) !important;
        transition: all 0.3s ease !important;
    }
    div.stButton > button:hover {
        transform: translateY(-2px);
        background: linear-gradient(135deg, #E5C566 0%, #B8962E 100%) !important; /* Lighter gold on hover */
        box-shadow: 0 6px 15px rgba(212, 175, 55, 0.5) !important;
        color: white !important;
    }
    div.stButton > button:active {
        transform: translateY(1px);
    }

    /* 3. INPUT BOX - GLASSY BLUE */
    div[data-baseweb="input"] {
        background-color: rgba(255, 255, 255, 0.05) !important;
        border: 1px solid rgba(51, 153, 255, 0.3) !important;
        border-radius: 4px !important;
    }
    div[data-baseweb="base-input"] {
        background-color: transparent !important;
    }
    div[data-baseweb="input"]:focus-within {
        border: 1px solid #3399FF !important;
        box-shadow: 0 0 15px rgba(51, 153, 255, 0.4) !important;
    }
    div[data-testid="stTextInput"] input {
        color: white !important;
        font-weight: 500 !important;
    }

    /* 4. SIDEBAR STATUS BOX */
    section[data-testid="stSidebar"] div[data-testid="stAlert"] {
        background: linear-gradient(90deg, #4b6cb7 0%, #182848 100%) !important;
        border: none !important;
        color: white !important;
        border-radius: 4px !important;
        box-shadow: 0 4px 10px rgba(75, 108, 183, 0.4) !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stAlert"] * {
        color: white !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stAlert"] svg {
        fill: white !important;
    }

    /* 5. METRIC CARDS - REFINED GOLD ACCENTS */
    div[data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.03) !important;
        border: 1px solid rgba(212, 175, 55, 0.2) !important; /* Subtle Gold Border */
        border-radius: 6px !important;
        padding: 15px !important;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.2) !important;
        transition: all 0.3s ease;
    }
    div[data-testid="stMetric"]:hover {
        border-color: #D4AF37 !important;
        box-shadow: 0 0 15px rgba(212, 175, 55, 0.15) !important;
    }
    div[data-testid="stMetricLabel"] {
        color: #B0B0B0 !important;
        font-size: 0.9rem !important;
    }
    div[data-testid="stMetricValue"] {
        color: #E5C566 !important; /* Soft Metallic Gold Text (Not Neon) */
        font-size: 1.8rem !important;
        font-weight: 700 !important;
        text-shadow: 0 0 10px rgba(212, 175, 55, 0.2);
    }

    /* 6. TARGET BOX */
    div[data-testid="stAlert"][data-variant="success"] {
        background: linear-gradient(90deg, #134E5E 0%, #71B280 100%) !important;
        border: none !important;
        color: white !important;
    }
    
    /* 7. SIDEBAR BACKGROUND */
    section[data-testid="stSidebar"] {
        background-color: #0B0E13 !important;
        border-right: 1px solid #1F2937 !important;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. API KEY ROTATION SYSTEM (Secure)
# ==========================================
try:
    API_KEYS = st.secrets["gemini"]["api_keys"]
except Exception:
    st.error("Error: No API Keys found. Please set them up in Streamlit Secrets.")
    st.stop()

@st.cache_resource
def configure_valid_key(keys):
    for key in keys:
        try:
            genai.configure(api_key=key)
            list(genai.list_models())
            return key
        except Exception as e:
            continue 
    return None

active_key = configure_valid_key(API_KEYS)
if not active_key:
    st.error("Critical Error: All API keys failed or quota exceeded.")
    st.stop()

# ==========================================
# 4. CORE UTILITY: DYNAMIC MODEL FINDER
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

# Sidebar Control
with st.sidebar:
    st.title("Controls")
    st.success(f"System Online")
    st.caption(f"Model: {ACTIVE_MODEL_NAME}")
    st.caption("API Status: Connected")
    st.markdown("---")

# ==========================================
# 5. ENGINES (News, Ticker, Data)
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
# 6. MATHEMATICAL ENGINE (7-YEAR ANALYSIS)
# ==========================================
def find_col(df, candidates):
    for c in candidates:
        matches = [col for col in df.columns if c in col]
        if matches: return matches[0]
    return None

def safe_cagr(start, end, years):
    if start is None or end is None or years == 0: return None
    try:
        s, e = float(start), float(end)
        if s == 0: return None
        if s > 0 and e > 0: 
            val = ((e / s)**(1/years) - 1) * 100
            return round(val, 2)
        if s < 0 and e > 0: return "TURNAROUND (Loss to Profit)"
        if s > 0 and e < 0: return "DETERIORATION (Profit to Loss)"
        if s < 0 and e < 0 and e > s: return "IMPROVING (Losses Narrowing)"
        return "N/A"
    except: return None

@st.cache_data(ttl=3600) 
def get_institutional_data(ticker_symbol):
    stock = yf.Ticker(ticker_symbol)
    
    # 1. PRICE
    try:
        current_price = stock.fast_info.last_price
        mcap = stock.fast_info.market_cap
        currency = stock.fast_info.currency
    except:
        return {"error": f"Could not find live data for '{ticker_symbol}'."}

    # 2. FINANCIAL STATEMENTS
    try:
        fin = stock.financials.T
        bal = stock.balance_sheet.T
        cash = stock.cashflow.T
        for df in [fin, bal, cash]:
            if not df.empty: df.sort_index(ascending=False, inplace=True)
    except:
        return {"error": "Financial statements unavailable."}

    # 3. KPI CALCULATOR
    kpis = {}
    raw_txt = "Financial Data Unavailable."
    
    if not fin.empty:
        # Identify Columns
        rev_c = find_col(fin, ['Total Revenue', 'Revenue'])
        eps_c = find_col(fin, ['Basic EPS', 'Diluted EPS'])
        ni_c  = find_col(fin, ['Net Income', 'Net Income Common'])
        
        # RAW HISTORY (7 Years where available)
        raw_txt = "### FINANCIAL HISTORY (Up to 7 Years):\n"
        try:
            subset = fin.head(8) # Fetch 8 to calculate 7Y growth
            for d, row in subset.iterrows():
                d_str = d.strftime('%Y') if hasattr(d, 'strftime') else str(d)[:4]
                r = row.get(rev_c, 0)
                e = row.get(eps_c, 0)
                n = row.get(ni_c, 0)
                raw_txt += f"- {d_str}: Revenue {r:,.0f}, Net Income {n:,.0f}, EPS {e:.2f}\n"
        except: pass

        # GROWTH METRICS (3Y, 5Y, 7Y)
        if rev_c:
            kpis['sales_cagr_3y'] = safe_cagr(fin[rev_c].iloc[3], fin[rev_c].iloc[0], 3) if len(fin) > 3 else "N/A"
            kpis['sales_cagr_5y'] = safe_cagr(fin[rev_c].iloc[5], fin[rev_c].iloc[0], 5) if len(fin) > 5 else "N/A"
            kpis['sales_cagr_7y'] = safe_cagr(fin[rev_c].iloc[7], fin[rev_c].iloc[0], 7) if len(fin) > 7 else "N/A (Data < 7Y)"

        if eps_c:
            kpis['eps_cagr_3y'] = safe_cagr(fin[eps_c].iloc[3], fin[eps_c].iloc[0], 3) if len(fin) > 3 else "N/A"
            kpis['eps_cagr_5y'] = safe_cagr(fin[eps_c].iloc[5], fin[eps_c].iloc[0], 5) if len(fin) > 5 else "N/A"
            kpis['eps_cagr_7y'] = safe_cagr(fin[eps_c].iloc[7], fin[eps_c].iloc[0], 7) if len(fin) > 7 else "N/A (Data < 7Y)"

    # VALUATION (PEG & PE)
    try:
        eps_ttm = fin.iloc[0][eps_c]
        pe = current_price / eps_ttm if eps_ttm > 0 else 0
        g = kpis.get('eps_cagr_3y')
        if isinstance(g, (int, float)) and g > 0 and pe > 0:
            kpis['peg'] = round(pe / g, 2)
        else:
            kpis['peg'] = "N/A"
        kpis['pe'] = round(pe, 2)
    except: 
        kpis['peg'], kpis['pe'] = "N/A", "N/A"

    # HEALTH (Debt/Equity & ROE)
    try:
        total_debt = bal.iloc[0][find_col(bal, ['Total Debt'])]
        total_equity = bal.iloc[0][find_col(bal, ['Stockholders Equity'])]
        net_income = fin.iloc[0][ni_c]
        kpis['debt_equity'] = round(total_debt / total_equity, 2)
        kpis['roe'] = round((net_income / total_equity) * 100, 2)
    except:
        kpis['debt_equity'], kpis['roe'] = "N/A", "N/A"

    # 4. CHART DATA
    chart_data = None
    try:
        hist = stock.history(period="2y")
        if not hist.empty:
            hist = hist.reset_index()
            chart_data = hist[['Date', 'Close', 'Volume']]
    except: pass

    # TECHNICAL TREND
    try:
        sma200 = hist['Close'].rolling(200).mean().iloc[-1]
        kpis['trend'] = "Uptrend" if current_price > sma200 else "Downtrend"
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
# 7. SYSTEM PROMPT (STRICT INSTITUTIONAL CRITERIA)
# ==========================================
sys_instruction = """
### ROLE
You are an Institutional Equity Analyst. You adhere to a STRICT Quantitative Strategy.
Your Output MUST BE FACT-BASED. No Emojis.

### 1. THE MANDATORY CRITERIA
You must evaluate the stock against these EXACT thresholds:
1. **EPS Growth:** > 20% for 3-Year, 5-Year, AND 7-Year periods.
2. **Sales Growth:** > 15% for 3-Year, 5-Year, AND 7-Year periods.
3. **PEG Ratio:** < 1.0.
4. **Debt to Equity:** < 1.0.
5. **P/E Ratio:** > 0.
6. **Market Cap:** > 5,000 (Currency adjusted).

### 2. ANALYSIS LOGIC
* **Strict Pass/Fail:** If 7-Year data is "N/A", state "Insufficient Data" but do not auto-fail if 5-Year is strong.
* **Turnarounds:** If growth states "TURNAROUND", treat this as a special positive case but note the risk.
* **Verdict:** Only give a "STRONG BUY" if almost all criteria are met.

### OUTPUT FORMAT
## Institutional Verdict: {Ticker}
**Rating:** [STRONG BUY | BUY | HOLD | SELL]
**Risk Profile:** [Low | Medium | High]

### 1. Executive Thesis
(Summary of the investment case based on the criteria.)

### 2. The Golden Rules Scorecard
| Metric | Value | Threshold | Verdict |
| :--- | :--- | :--- | :--- |
| **EPS Growth (3Y)** | {val} | > 20% | [Pass/Fail] |
| **EPS Growth (5Y)** | {val} | > 20% | [Pass/Fail] |
| **EPS Growth (7Y)** | {val} | > 20% | [Pass/Fail/No Data] |
| **Sales Growth (3Y)** | {val} | > 15% | [Pass/Fail] |
| **Sales Growth (5Y)** | {val} | > 15% | [Pass/Fail] |
| **Sales Growth (7Y)** | {val} | > 15% | [Pass/Fail/No Data] |
| **PEG Ratio** | {val} | < 1.0 | [Pass/Fail] |
| **Debt/Equity** | {val} | < 1.0 | [Pass/Fail] |

### 3. Institutional Quality & Risks
* **Market Cap:** {val} (Check > 5000)
* **Trend:** (200 SMA Status)
* **Key Risks:** (List specific failures from the scorecard)
"""

# ==========================================
# 8. MAIN INTERFACE
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
        with st.spinner(f"Resolving '{user_input}'..."):
            ticker = resolve_ticker(user_input)
            
            if not check_ticker_live(ticker):
                st.error(f"Could not find data for '{ticker}'.")
            else:
                st.success(f"Target: {ticker}")
                
                with st.spinner("Aggregating Financial Data & Computing KPIs..."):
                    data = get_institutional_data(ticker)
                    
                    if "error" in data:
                        st.error(data['error'])
                    else:
                        # 1. METRICS ROW
                        k = data['kpis']
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("Price", f"{data['currency']} {data['price']:,.2f}")
                        m2.metric("PEG Ratio", str(k.get('peg')))
                        m3.metric("ROE", f"{k.get('roe')}%")
                        m4.metric("Trend", k.get('trend'))
                        
                        # 2. CHART (REFINED METALLIC GOLD)
                        if data.get('chart_data') is not None:
                            base = alt.Chart(data['chart_data']).encode(
                                x=alt.X('Date:T', axis=alt.Axis(format='%b %Y', title=None, labelAngle=-45, grid=False)),
                                y=alt.Y('Close:Q', axis=alt.Axis(title=None, format=",.0f"), scale=alt.Scale(zero=False))
                            )
                            # Swapped #FFD700 (Neon) for #D4AF37 (Metallic)
                            line = base.mark_line(color='#D4AF37', strokeWidth=3)
                            area = base.mark_area(
                                line={'color':'#D4AF37'},
                                color=alt.Gradient(
                                    gradient='linear',
                                    stops=[alt.GradientStop(offset=0, color='#D4AF37'),
                                           alt.GradientStop(offset=1, color='rgba(212, 175, 55, 0)')],
                                    x1=1, x2=1, y1=1, y2=0
                                ),
                                opacity=0.3
                            )
                            final_chart = (area + line).properties(height=400).configure_view(stroke=None)
                            st.altair_chart(final_chart, use_container_width=True)

                        # 3. AI ANALYSIS
                        try:
                            model = genai.GenerativeModel(ACTIVE_MODEL_NAME, system_instruction=sys_instruction)
                            prompt = f"Analyze {ticker}. Financials: {data['raw_history']}. KPIs: {data['kpis']}. Market Cap: {data['mcap']}. News: {data['news']}"
                            response = model.generate_content(prompt)
                            st.markdown(response.text)
                        except Exception as e:
                            st.error(f"AI Synthesis Failed: {e}")
