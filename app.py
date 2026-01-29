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

# 2. DEEP GOLD THEME (Fixed Indentation & Color)
st.markdown("""
<style>
    /* 1. DEEP SPACE BACKGROUND */
    .stApp {
        background: radial-gradient(circle at top left, #0f172a 0%, #000000 100%);
        font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    }

    /* 2. METRIC CARDS (Deep Gold Text) */
    div[data-testid="stMetric"] {
        background: rgba(20, 20, 20, 0.6) !important; /* Dark Glass */
        border: 1px solid #4a3b10 !important; /* Antique Gold Border */
        border-radius: 8px !important;
        padding: 15px !important;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3) !important;
    }
    div[data-testid="stMetricLabel"] {
        color: #a0a0a0 !important; /* Silver Label */
        font-size: 0.9rem !important;
    }
    div[data-testid="stMetricValue"] {
        color: #D4AF37 !important; /* <--- DEEP METALLIC GOLD */
        font-size: 1.6rem !important;
        font-weight: 700 !important;
        text-shadow: 0 2px 10px rgba(212, 175, 55, 0.2) !important;
    }

    /* 3. BUTTONS (Antique Gold Gradient) */
    div.stButton > button {
        background: linear-gradient(180deg, #D4AF37 0%, #AA8C2C 100%) !important;
        border: 1px solid #8A6E18 !important;
        color: white !important;
        font-weight: bold !important;
        text-transform: uppercase !important;
        letter-spacing: 1px !important;
        border-radius: 4px !important;
        box-shadow: 0 4px 10px rgba(212, 175, 55, 0.3) !important;
        transition: all 0.3s ease !important;
    }
    div.stButton > button:hover {
        transform: translateY(-2px);
        filter: brightness(1.1);
        box-shadow: 0 6px 15px rgba(212, 175, 55, 0.4) !important;
        color: white !important;
    }

    /* 4. INPUT BOX (Clean Blue Glow) */
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
    }

    /* 5. SIDEBAR STATUS (Blue/Black Gradient) */
    section[data-testid="stSidebar"] div[data-testid="stAlert"] {
        background: linear-gradient(90deg, #4b6cb7 0%, #182848 100%) !important;
        border: none !important;
        color: white !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stAlert"] svg {
        fill: white !important;
    }

    /* 6. TARGET BOX (Green Gradient) */
    div[data-testid="stAlert"][data-variant="success"] {
        background: linear-gradient(90deg, #134E5E 0%, #71B280 100%) !important;
        border: none !important;
        color: white !important;
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

# Sidebar Control (Clean - No Emoji)
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
# 6. MATHEMATICAL ENGINE (Statistical Accuracy)
# ==========================================
def find_col(df, candidates):
    for c in candidates:
        matches = [col for col in df.columns if c in col]
        if matches: return matches[0]
    return None

def safe_cagr(start, end, years):
    """
    Calculates Compound Annual Growth Rate with logic for negative baselines.
    Returns strings for specific turnaround scenarios to aid qualitative analysis.
    """
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
    
    # 1. PRICE DATA
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

    # 3. KPI & RATIO CALCULATOR
    kpis = {}
    raw_txt = "Financial Data Unavailable."
    
    if not fin.empty:
        # Identify Columns
        rev_c = find_col(fin, ['Total Revenue', 'Revenue'])
        eps_c = find_col(fin, ['Basic EPS', 'Diluted EPS'])
        ni_c  = find_col(fin, ['Net Income', 'Net Income Common'])
        op_inc_c = find_col(fin, ['Operating Income', 'Operating Profit'])
        
        # RAW HISTORY FOR AI CONTEXT
        raw_txt = "### 5-YEAR FINANCIAL HISTORY:\n"
        try:
            subset = fin.head(5)
            for d, row in subset.iterrows():
                d_str = d.strftime('%Y') if hasattr(d, 'strftime') else str(d)[:4]
                r = row.get(rev_c, 0)
                e = row.get(eps_c, 0)
                n = row.get(ni_c, 0)
                raw_txt += f"- {d_str}: Revenue {r:,.0f}, Net Income {n:,.0f}, EPS {e:.2f}\n"
        except: pass

        # GROWTH METRICS (CAGR)
        if rev_c:
            kpis['sales_cagr_3y'] = safe_cagr(fin[rev_c].iloc[3], fin[rev_c].iloc[0], 3) if len(fin) > 3 else "N/A"
            kpis['sales_cagr_5y'] = safe_cagr(fin[rev_c].iloc[5], fin[rev_c].iloc[0], 5) if len(fin) > 5 else "N/A"
        if eps_c:
            kpis['eps_cagr_3y'] = safe_cagr(fin[eps_c].iloc[3], fin[eps_c].iloc[0], 3) if len(fin) > 3 else "N/A"
            kpis['eps_cagr_5y'] = safe_cagr(fin[eps_c].iloc[5], fin[eps_c].iloc[0], 5) if len(fin) > 5 else "N/A"

        # PROFITABILITY METRICS (Margins) - NEW ADDITION
        try:
            latest = fin.iloc[0]
            revenue = latest.get(rev_c, 1)
            net_income = latest.get(ni_c, 0)
            op_income = latest.get(op_inc_c, 0)
            
            kpis['net_margin'] = round((net_income / revenue) * 100, 2)
            kpis['op_margin'] = round((op_income / revenue) * 100, 2)
        except:
            kpis['net_margin'] = "N/A"
            kpis['op_margin'] = "N/A"

    # VALUATION (PEG & PE)
    try:
        eps_ttm = fin.iloc[0][eps_c]
        pe = current_price / eps_ttm if eps_ttm > 0 else 0
        g = kpis.get('eps_cagr_3y')
        
        # PEG Logic: Only valid if Growth > 0 and PE > 0
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

    # QUALITY (FCF & OCF) - NEW ADDITION
    try:
        ocf = cash.iloc[0][find_col(cash, ['Operating Cash Flow', 'Operating'])]
        capex = cash.iloc[0][find_col(cash, ['Capital Expenditure', 'Purchase of PPE'])]
        
        # Free Cash Flow = OCF + CapEx (CapEx is usually negative in statements)
        # We ensure we handle the sign correctly.
        if capex > 0: capex = -capex 
        fcf = ocf + capex
        
        ni = fin.iloc[0][ni_c]
        
        kpis['fcf'] = fcf
        kpis['quality_verdict'] = "High Quality" if ocf > ni else "Low Quality (Accruals)"
    except:
        kpis['quality_verdict'] = "Unknown"
        kpis['fcf'] = "N/A"

    # 4. CHART DATA
    chart_data = None
    try:
        hist = stock.history(period="2y")
        if not hist.empty:
            hist = hist.reset_index()
            chart_data = hist[['Date', 'Close', 'Volume']]
    except: pass

    # TECHNICAL TREND (SMA 200)
    try:
        sma200 = hist['Close'].rolling(200).mean().iloc[-1]
        kpis['trend'] = "Uptrend (Price > 200 SMA)" if current_price > sma200 else "Downtrend (Price < 200 SMA)"
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
# 7. SYSTEM PROMPT (STRICT & FACT-BASED)
# ==========================================
sys_instruction = """
### ROLE
You are an Institutional Equity Analyst (CFA Level). Your job is to provide a rigorous, fact-based investment thesis. 
You DO NOT use emojis. You prioritize data over narrative.

### 1. ANALYSIS FRAMEWORK
* **Growth:** Analyze 3Y and 5Y CAGR for Revenue and EPS. Is growth accelerating or decelerating?
* **Profitability:** Look at Net Margins and Operating Margins. Are they expanding?
* **Valuation:** Assess PEG Ratio (Target < 1.0) and P/E relative to growth.
* **Health:** Check Debt/Equity (< 1.0 preferred) and ROE (> 15% preferred).
* **Quality:** Compare Operating Cash Flow vs Net Income. (OCF > NI indicates high quality).

### 2. STRICT OUTPUT RULES
* **NO EMOJIS:** Do not use any emojis in the output.
* **CITE DATA:** Every claim must be backed by a number from the provided context. (e.g., "Margins expanded because Net Margin is 15%").
* **VERDICT JUSTIFICATION:** The final rating must be mathematically justified by the KPIs.

### OUTPUT FORMAT
## Institutional Verdict: {Ticker}
**Rating:** [STRONG BUY | BUY | HOLD | SELL]
**Risk Profile:** [Low | Medium | High]

### 1. Executive Thesis
(A professional summary of the investment case, citing specific growth and valuation metrics.)

### 2. Quantitative Scorecard
| Metric | Value | Assessment |
| :--- | :--- | :--- |
| **EPS Growth (3Y)** | {val} | [Accretive/Dilutive] |
| **Revenue Growth (3Y)** | {val} | [Pass/Fail] |
| **Net Margin** | {val}% | [Efficient/Inefficient] |
| **PEG Ratio** | {val} | [Undervalued/Overvalued] |
| **ROE** | {val}% | [Value Creation] |
| **Debt/Equity** | {val} | [Leverage Status] |

### 3. Key Risks & Bear Case
(Specific financial risks based on the data provided.)

### 4. Technical & Trend Outlook
(Comment on the long-term trend based on the 200 SMA status provided.)
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
                        m4.metric("Trend", k.get('trend').split('(')[0].strip()) # Clean text
                        
                        # 2. CHART (GOLDEN STYLE)
                        if data.get('chart_data') is not None:
    # 1. Create the Base Chart
    base = alt.Chart(data['chart_data']).encode(
        x=alt.X('Date:T', axis=alt.Axis(format='%b %Y', title=None, labelAngle=-45, grid=False)),
        y=alt.Y('Close:Q', axis=alt.Axis(title=None, format=",.0f"), scale=alt.Scale(zero=False))
    )
    
    # 2. The Line (Metallic Gold)
    line = base.mark_line(
        color='#D4AF37',  # <--- Deep Gold Hex Code
        strokeWidth=3
    )
    
    # 3. The Fade Under the Line (Gradient)
    area = base.mark_area(
        line={'color':'#D4AF37'},
        color=alt.Gradient(
            gradient='linear',
            stops=[alt.GradientStop(offset=0, color='#D4AF37'),
                   alt.GradientStop(offset=1, color='rgba(212, 175, 55, 0)')], # Fades to transparent
            x1=1, x2=1, y1=1, y2=0
        ),
        opacity=0.2 # Kept low for elegance
    )
    
    # 4. Combine and Display
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
