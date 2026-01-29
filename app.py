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

# 1. CONFIGURE PAGE & THEME
st.set_page_config(page_title="Institutional AI Analyst", page_icon="🦅", layout="wide")

# 2. "CYBERPUNK GOLD" STYLING (Based on your image)
st.markdown("""
<style>
    /* 1. DEEP SPACE BACKGROUND */
    .stApp {
        background: radial-gradient(circle at top left, #1B2838 0%, #0E1117 100%);
        font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    }

    /* 2. GOLDEN GLOW BUTTONS */
    div.stButton > button {
        background: linear-gradient(90deg, #FFD700 0%, #FFA500 100%) !important;
        border: none !important;
        color: #0E1117 !important; /* Dark text on gold */
        font-weight: 800 !important;
        text-transform: uppercase !important;
        letter-spacing: 1px !important;
        border-radius: 8px !important;
        box-shadow: 0 4px 15px rgba(255, 165, 0, 0.4) !important; /* Gold Glow */
        transition: all 0.3s ease !important;
    }
    div.stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(255, 165, 0, 0.6) !important;
        color: black !important;
    }
    div.stButton > button:active {
        transform: translateY(1px);
    }

    /* 3. INPUT BOX - NEON BLUE GLOW */
    div[data-baseweb="input"] {
        background-color: rgba(255, 255, 255, 0.05) !important; /* Glassy */
        border: 1px solid rgba(51, 153, 255, 0.3) !important;
        border-radius: 8px !important;
    }
    div[data-baseweb="base-input"] {
        background-color: transparent !important;
    }
    /* Focus State: Glowing Blue Border */
    div[data-baseweb="input"]:focus-within {
        border: 1px solid #3399FF !important;
        box-shadow: 0 0 15px rgba(51, 153, 255, 0.4) !important;
    }
    div[data-testid="stTextInput"] input {
        color: white !important;
        font-weight: 500 !important;
    }

    /* 4. SIDEBAR "SYSTEM ONLINE" - NEON PURPLE/BLUE GRADIENT */
    section[data-testid="stSidebar"] div[data-testid="stAlert"] {
        background: linear-gradient(90deg, #4b6cb7 0%, #182848 100%) !important;
        border: none !important;
        color: white !important;
        border-radius: 8px !important;
        box-shadow: 0 4px 10px rgba(75, 108, 183, 0.4) !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stAlert"] * {
        color: white !important;
        font-weight: 600 !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stAlert"] svg {
        fill: white !important;
    }

    /* 5. METRIC CARDS - GLASS & GOLD */
    div[data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.03) !important; /* Ultra-Subtle Glass */
        border: 1px solid rgba(255, 215, 0, 0.3) !important; /* Faint Gold Border */
        border-radius: 10px !important;
        padding: 15px !important;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.2) !important;
        transition: all 0.3s ease;
    }
    div[data-testid="stMetric"]:hover {
        border-color: #FFD700 !important;
        box-shadow: 0 0 15px rgba(255, 215, 0, 0.2) !important;
    }
    div[data-testid="stMetricLabel"] {
        color: #B0B0B0 !important; /* Silver Label */
        font-size: 0.9rem !important;
    }
    div[data-testid="stMetricValue"] {
        color: #FFD700 !important; /* GOLD NUMBERS */
        font-size: 1.8rem !important;
        font-weight: 700 !important;
        text-shadow: 0 0 10px rgba(255, 215, 0, 0.3);
    }

    /* 6. TARGET BOX (GREEN) */
    div[data-testid="stAlert"][data-variant="success"] {
        background: linear-gradient(90deg, #134E5E 0%, #71B280 100%) !important; /* Deep Green Gradient */
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
    st.error("❌ No API Keys found in Secrets. Please set them up in Streamlit Cloud > Settings > Secrets.")
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
    st.error("❌ Critical Error: All API keys failed or quota exceeded.")
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
    st.title("🦅 Controls")
    st.success(f"System Online")
    st.caption(f"Model: {ACTIVE_MODEL_NAME}")
    st.caption("API Status: Connected ✅")
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
        if s > 0 and e > 0: return round(((e / s)**(1/years) - 1) * 100, 2)
        if s < 0 and e > 0: return "TURNAROUND (Loss to Profit) 🚀"
        if s > 0 and e < 0: return "COLLAPSE (Profit to Loss) ⚠️"
        if s < 0 and e < 0 and e > s: return "IMPROVING (Losses Narrowing) 📈"
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

    # 2. FINANCIALS
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
        rev_c = find_col(fin, ['Total Revenue', 'Revenue'])
        eps_c = find_col(fin, ['Basic EPS', 'Diluted EPS'])
        ni_c  = find_col(fin, ['Net Income', 'Net Income Common'])
        
        raw_txt = "### 5-YEAR FINANCIAL TREND:\n"
        try:
            subset = fin.head(5)
            for d, row in subset.iterrows():
                d_str = d.strftime('%Y') if hasattr(d, 'strftime') else str(d)[:4]
                r = row.get(rev_c, 0)
                e = row.get(eps_c, 0)
                raw_txt += f"- {d_str}: Revenue {r:,.0f}, EPS {e:.2f}\n"
        except: pass

        if rev_c:
            kpis['sales_cagr_3y'] = safe_cagr(fin[rev_c].iloc[3], fin[rev_c].iloc[0], 3) if len(fin) > 3 else "N/A"
            kpis['sales_cagr_5y'] = safe_cagr(fin[rev_c].iloc[5], fin[rev_c].iloc[0], 5) if len(fin) > 5 else "N/A"
        if eps_c:
            kpis['eps_cagr_3y'] = safe_cagr(fin[eps_c].iloc[3], fin[eps_c].iloc[0], 3) if len(fin) > 3 else "N/A"
            kpis['eps_cagr_5y'] = safe_cagr(fin[eps_c].iloc[5], fin[eps_c].iloc[0], 5) if len(fin) > 5 else "N/A"

    # Valuation & Health
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
        kpis['peg'], kpis['pe'] = "N/A", "N/A"

    try:
        total_debt = bal.iloc[0][find_col(bal, ['Total Debt'])]
        total_equity = bal.iloc[0][find_col(bal, ['Stockholders Equity'])]
        net_income = fin.iloc[0][ni_c]
        kpis['debt_equity'] = round(total_debt / total_equity, 2)
        kpis['roe'] = round((net_income / total_equity) * 100, 2)
    except:
        kpis['debt_equity'], kpis['roe'] = "N/A", "N/A"

    try:
        ocf = cash.iloc[0][find_col(cash, ['Operating Cash Flow', 'Operating'])]
        ni = fin.iloc[0][ni_c]
        kpis['quality'] = "High (Cash > Profit) ✅" if ocf > ni else "Low (Profit > Cash) ⚠️"
    except:
        kpis['quality'] = "Unknown"

    # 4. CHART DATA
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
        kpis['trend'] = "Uptrend (Above 200DMA) 🟢" if current_price > sma200 else "Downtrend (Below 200DMA) 🔴"
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
# 6. SYSTEM PROMPT
# ==========================================
sys_instruction = """
### ROLE
Institutional Portfolio Manager. Prioritize Predictive Analysis.

### 1. FOUNDATIONAL KPIs (GARP)
* **Growth:** 3Y/5Y EPS & Sales > 15-20%. ("TURNAROUND" is POSITIVE).
* **Valuation:** PEG < 1.0 ideal.
* **Health:** Debt/Equity < 1.0.
* **Quality:** Cash Flow > Net Income.

### 2. PREDICTIVE SYNTHESIS
* Is momentum accelerating? 
* Are margins expanding?
* **Do not fail a stock just because one metric is N/A.** Use the trend.

### OUTPUT FORMAT
## 🦅 Institutional Verdict: {Ticker}
**Rating:** [STRONG BUY | BUY | WATCHLIST | SELL]
**Risk Level:** [Low/Medium/High]

### 1. Executive Thesis
(Explain the "Story" of the stock.)

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
* **Trend Analysis:** (Comment on Price vs 200DMA).
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
        # The CSS above targets this specific button to make it Blue
        submit_btn = st.form_submit_button("Run Analysis", type="primary", use_container_width=True)

if submit_btn:
    if not user_input:
        st.warning("Please enter a company name.")
    else:
        with st.spinner(f"🔍 Resolving '{user_input}'..."):
            ticker = resolve_ticker(user_input)
            
            if not check_ticker_live(ticker):
                st.error(f"❌ Could not find data for '{ticker}'.")
                st.caption("Try adding the suffix manually (e.g. .NS, .AX).")
            else:
                st.success(f"Target: {ticker}")
                
                with st.spinner("📡 Calculating KPIs & Predicting Trends..."):
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
                        
                        # 2. CHART (GOLDEN STYLE)
                        if data.get('chart_data') is not None:
                            # We create a layered chart for the glowing effect
                            base = alt.Chart(data['chart_data']).encode(
                                x=alt.X('Date:T', axis=alt.Axis(format='%b %Y', title=None, labelAngle=-45, grid=False)),
                                y=alt.Y('Close:Q', 
                                        axis=alt.Axis(title=None, format=",.0f"),
                                        scale=alt.Scale(zero=False))
                            )
                            
                            # The main Golden Line
                            line = base.mark_line(
                                color='#FFD700', 
                                strokeWidth=3
                            )
                            
                            # Gradient Fill under the line (Area Chart)
                            area = base.mark_area(
                                line={'color':'#FFD700'},
                                color=alt.Gradient(
                                    gradient='linear',
                                    stops=[alt.GradientStop(offset=0, color='#FFD700'),
                                           alt.GradientStop(offset=1, color='rgba(255, 215, 0, 0)')],
                                    x1=1, x2=1, y1=1, y2=0
                                ),
                                opacity=0.3
                            )
                            
                            final_chart = (area + line).properties(height=400).configure_view(stroke=None)
                            
                            st.altair_chart(final_chart, use_container_width=True)

                        # 3. AI ANALYSIS
                        try:
                            model = genai.GenerativeModel(ACTIVE_MODEL_NAME, system_instruction=sys_instruction)
                            prompt = f"Analyze {ticker}. Financials: {data['raw_history']}. KPIs: {data['kpis']}. News: {data['news']}"
                            response = model.generate_content(prompt)
                            st.markdown(response.text)
                        except Exception as e:
                            st.error(f"AI Synthesis Failed: {e}")
