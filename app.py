import streamlit as st
import google.generativeai as genai
import yfinance as yf
import pandas as pd
import warnings
import re
import requests
import xml.etree.ElementTree as ET
import time

# Suppress warnings
warnings.filterwarnings('ignore')

st.set_page_config(page_title="Institutional AI Analyst", page_icon="🦅", layout="wide")

st.markdown("""
<style>
div[data-testid="stMetricValue"] { font-size: 1.2rem; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 1. SIDEBAR: API KEY & CONTROLS
# ==========================================
with st.sidebar:
    st.title("🦅 Controls")
    user_api_key = st.text_input("Enter Google API Key", type="password", help="Get a free key from Google AI Studio")
    st.markdown("---")
    
if not user_api_key:
    st.info("System Status: Waiting for Key...")
    st.warning("⬅️ Please enter a Google API Key in the sidebar to start.")
    st.stop()

# Configure API immediately
try:
    genai.configure(api_key=user_api_key)
except Exception as e:
    st.error(f"Invalid API Key: {e}")
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
with st.sidebar:
    st.caption(f"🤖 Model: {ACTIVE_MODEL_NAME}")

# ==========================================
# 3. ENGINE: GOOGLE NEWS RSS (Targeted)
# ==========================================
def get_google_news_rss(query):
    try:
        # We keep the suffix (e.g. .NS) to ensure we get news for the RIGHT country
        clean_query = f"{query} stock news"
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
# 4. ENGINE: TICKER RESOLVER (HARDCODED MAP)
# ==========================================
def check_ticker_live(ticker):
    """Returns True if ticker exists on Yahoo, False otherwise."""
    try:
        price = yf.Ticker(ticker).fast_info.last_price
        return price is not None and price > 0
    except:
        return False

# THE "INSTANT FIX" DICTIONARY
COMMON_MAPPING = {
    # USA
    "APPLE": "AAPL", "NETFLIX": "NFLX", "GOOGLE": "GOOGL", "AMAZON": "AMZN",
    "TESLA": "TSLA", "MICROSOFT": "MSFT", "META": "META", "NVIDIA": "NVDA",
    "GENERAL MOTORS": "GM", "FORD": "F",
    
    # INDIA (Correcting Common Mistakes)
    "LIC": "LICI.NS", "LIC.NS": "LICI.NS", "LICI": "LICI.NS", # Fixes LIC issue
    "TATA STEEL": "TATASTEEL.NS", "RELIANCE": "RELIANCE.NS",
    "HDFC": "HDFCBANK.NS", "INFOSYS": "INFY.NS",
    "NALCO": "NATIONALUM.NS", "NATIONAL ALUMINIUM": "NATIONALUM.NS",
    "PG FOILS": "PGFOLS.NS", "PGFOILS": "PGFOLS.NS",
    
    # AUSTRALIA
    "GOLDEN DEEPS": "GED.AX", "GOLDEN DEEPS LTD": "GED.AX",
    "ENERGY ACTION": "EAX.AX", "EAX": "EAX.AX",
    "COMMBANK": "CBA.AX", "CBA": "CBA.AX",
    "ANZ": "ANZ.AX", "NAB": "NAB.AX", "BHP": "BHP.AX",
    "RIO": "RIO.AX", "TELSTRA": "TLS.AX", "WOOLWORTHS": "WOW.AX"
}

@st.cache_data(ttl=3600) 
def resolve_ticker(user_input):
    clean_input = user_input.strip().upper()
    
    # 1. HARDCODED MAP (Fastest)
    if clean_input in COMMON_MAPPING:
        return COMMON_MAPPING[clean_input]

    # 2. DIRECT CHECK (If user typed 'TSLA' or 'LICI.NS')
    if check_ticker_live(clean_input): return clean_input
    # Try adding country suffixes automatically
    if check_ticker_live(clean_input + ".AX"): return clean_input + ".AX"
    if check_ticker_live(clean_input + ".NS"): return clean_input + ".NS"

    # 3. AI GUESS (Fallback)
    try:
        model = genai.GenerativeModel(ACTIVE_MODEL_NAME)
        prompt = (
            f"What is the exact Yahoo Finance ticker for '{user_input}'? "
            "Examples: 'Netflix'->NFLX, 'Tata Steel'->TATASTEEL.NS, 'Energy Action'->EAX.AX. "
            "Return ONLY the ticker symbol. No text."
        )
        response = model.generate_content(prompt)
        ai_ticker = response.text.strip().upper().replace(" ", "").replace("`", "")
        
        if check_ticker_live(ai_ticker): return ai_ticker
        if check_ticker_live(ai_ticker + ".AX"): return ai_ticker + ".AX"
        if check_ticker_live(ai_ticker + ".NS"): return ai_ticker + ".NS"
    except: pass

    return clean_input

# ==========================================
# 5. DATA ENGINE: STEALTH MODE
# ==========================================
def calculate_cagr(series, years):
    try:
        if len(series) < years + 1: return None
        current = float(series.iloc[0])
        past = float(series.iloc[years])
        if past <= 0: return "N/A (Neg Base)"
        if current <= 0: return "N/A (Neg Current)"
        return round(((current / past)**(1/years) - 1) * 100, 2)
    except: return None

@st.cache_data(ttl=3600) 
def get_garp_data(ticker_symbol):
    stock = yf.Ticker(ticker_symbol)
    
    # 1. PRICE (Use fast_info to bypass 'info' block)
    current_price = 0
    mcap = 0
    currency = "USD"
    
    try:
        current_price = stock.fast_info.last_price
        mcap = stock.fast_info.market_cap
        currency = stock.fast_info.currency
    except:
        return {"error": f"Could not find live data for '{ticker_symbol}'. Is the ticker correct?"}

    # 2. FINANCIALS
    try:
        financials = stock.financials
        cashflow = stock.cashflow
        balance_sheet = stock.balance_sheet
        fin_T = financials.T if not financials.empty else pd.DataFrame()
        if not fin_T.empty: fin_T.sort_index(ascending=False, inplace=True)
    except:
        return {"error": "Financial statements unavailable."}

    # 3. INFO (Lazy Load)
    info = {}
    try: info = stock.info
    except: pass 
    sector = info.get('sector', 'Unknown')

    # 4. METRICS
    growth_data = {}
    if not fin_T.empty:
        rev_col = next((c for c in fin_T.columns if 'Total Revenue' in c or 'Revenue' in c), None)
        eps_col = next((c for c in fin_T.columns if 'Basic EPS' in c or 'Net Income' in c), None)
        
        for yr in [3, 5, 7]:
            growth_data[f'sales_cagr_{yr}y'] = calculate_cagr(fin_T[rev_col], yr) if rev_col else "N/A"
            growth_data[f'eps_cagr_{yr}y'] = calculate_cagr(fin_T[eps_col], yr) if eps_col else "N/A"

    # Earnings Quality
    earnings_quality_msg = "Unknown"
    try:
        cf_T = cashflow.T
        if not cf_T.empty:
            cf_T.sort_index(ascending=False, inplace=True)
            ocf = next((c for c in cf_T.columns if 'Operating' in c), None)
            ni = next((c for c in fin_T.columns if 'Net Income' in c), None)
            if ocf and ni:
                if float(cf_T.iloc[0][ocf]) > float(fin_T.iloc[0][ni]):
                    earnings_quality_msg = "High (Cash > Profit)"
                else:
                    earnings_quality_msg = "Low (Profit > Cash) ⚠️"
    except: pass

    # Trend
    trend_msg = "Unknown"
    try:
        hist_long = stock.history(period="1y")
        if len(hist_long) > 200:
            sma = hist_long['Close'].rolling(200).mean().iloc[-1]
            trend_msg = "Bullish (Above 200DMA) 🟢" if current_price > sma else "Bearish (Below 200DMA) 🔴"
    except: pass

    # 5. REPAIR KIT
    repaired = {}
    
    # ROE
    try:
        ni = fin_T.iloc[0][next(c for c in fin_T.columns if 'Net Income' in c)]
        eq = balance_sheet.loc['Stockholders Equity'].iloc[0]
        repaired['roe'] = round((float(ni) / float(eq)) * 100, 2)
    except: repaired['roe'] = info.get('returnOnEquity', "N/A")

    # Debt/Equity
    try:
        debt = balance_sheet.loc['Total Debt'].iloc[0]
        eq = balance_sheet.loc['Stockholders Equity'].iloc[0]
        repaired['debt_to_equity'] = round(float(debt) / float(eq), 2)
    except: repaired['debt_to_equity'] = info.get('debtToEquity', "N/A")

    # PE & PEG
    try:
        eps = fin_T.iloc[0][next(c for c in fin_T.columns if 'Basic EPS' in c)]
        pe = current_price / float(eps)
        repaired['pe_ratio'] = round(pe, 2)
        
        g = growth_data.get('eps_cagr_3y')
        if isinstance(g, (int, float)) and g > 0:
            repaired['peg_ratio'] = round(pe / g, 2)
        else:
            repaired['peg_ratio'] = info.get('pegRatio', "N/A")
    except: 
        repaired['pe_ratio'] = info.get('trailingPE', "N/A")
        repaired['peg_ratio'] = info.get('pegRatio', "N/A")

    mcap_fmt = f"{mcap / 1_000_000:,.2f} M" if isinstance(mcap, (int, float)) else "N/A"

    return {
        "ticker": ticker_symbol.upper(),
        "sector": sector,
        "price": round(current_price, 2),
        "currency": currency,
        "market_cap": mcap_fmt,
        "peg_ratio": repaired.get('peg_ratio'),
        "pe_ratio": repaired.get('pe_ratio'),
        "debt_to_equity": repaired.get('debt_to_equity'),
        "roe": repaired.get('roe'),
        "earnings_quality": earnings_quality_msg,
        "technical_trend": trend_msg,
        "recent_news": get_google_news_rss(ticker_symbol),
        **growth_data
    }

# ==========================================
# 6. SYSTEM PROMPT
# ==========================================
sys_instruction = """
### ROLE
Senior Portfolio Manager. Skeptical, data-driven, focused on **risk-adjusted returns**.

### STRATEGY (STRICT GARP CRITERIA)
1. **EPS Growth:** 3Y > 20% AND 5Y > 20% AND 7Y > 20%.
2. **Sales Growth:** 3Y > 15% AND 5Y > 15% AND 7Y > 15%.
3. **Valuation:** PEG Ratio < 1.0 (Strict).
4. **Health:** Debt/Equity < 1.0 (Strict).
5. **Profitability:** PE Ratio > 0.
6. **Size:** Market Capitalization > 5000 Million.
7. **Quality:** Cash Flow > Net Income.
8. **Trend:** Prefer "Bullish" (Above 200DMA).
9. **Sentiment:** Check 'recent_news' for red flags.

### OUTPUT FORMAT (Markdown)
## Institutional Memo: {Ticker}
**Sector:** {Sector} | **Trend:** {Trend}
**Verdict:** [STRONG BUY | WATCHLIST | HARD PASS]

### 1. Executive Thesis
(State the core argument clearly based on the 9 criteria above.)

### 2. Quantitative Scorecard
| Metric | Value | Target | Status |
| :--- | :--- | :--- | :--- |
| **EPS Growth (3Y/5Y/7Y)** | {vals}% | > 20% each | [PASS/FAIL] |
| **Sales Growth (3Y/5Y/7Y)** | {vals}% | > 15% each | [PASS/FAIL] |
| **PEG Ratio** | {val} | < 1.0 | [PASS/FAIL] |
| **Debt/Equity** | {val} | < 1.0 | [PASS/FAIL/SKIP] |
| **PE Ratio** | {val} | > 0 | [PASS/FAIL] |
| **Market Cap** | {val} | > 5000 M | [PASS/FAIL] |

### 3. Risk & Portfolio Fit
(Comment on Quality, Trend, and News. Why buy/avoid now?)
"""

# ==========================================
# 7. MAIN INTERFACE
# ==========================================
st.title("Institutional Financial Analyst AI")

with st.form(key='analysis_form'):
    col1, col2 = st.columns([3, 1])
    with col1:
        user_input = st.text_input("Enter Company or Ticker", placeholder="e.g., Netflix, LIC, Golden Deeps").strip()
    with col2:
        st.write("")
        st.write("")
        submit_btn = st.form_submit_button("🚀 Run Analysis", type="primary", use_container_width=True)

if submit_btn:
    if not user_input:
        st.warning("Please enter a company name or ticker.")
    else:
        with st.spinner(f"🔍 Resolving ticker for '{user_input}'..."):
            resolved_ticker = resolve_ticker(user_input)
            
            # Validation Step
            if not check_ticker_live(resolved_ticker):
                st.error(f"❌ Could not find data for '{resolved_ticker}'.")
                st.info(f"The AI could not resolve '{user_input}' to a valid symbol.")
                st.caption("Please try searching for the EXACT ticker symbol (e.g., NFLX, LICI.NS, GED.AX).")
            else:
                st.success(f"✅ Analysis Target: **{resolved_ticker}**")
        
                with st.spinner(f"📡 Analyzing {resolved_ticker} (Financials + News)..."):
                    data = get_garp_data(resolved_ticker)
                    
                    if "error" in data:
                        st.error(f"❌ {data['error']}")
                    else:
                        max_retries = 3
                        for attempt in range(max_retries):
                            try:
                                model = genai.GenerativeModel(ACTIVE_MODEL_NAME, system_instruction=sys_instruction)
                                response = model.generate_content(f"Analyze {resolved_ticker} using this data: {data}")
                                
                                st.markdown("---")
                                
                                m1, m2, m3, m4 = st.columns(4)
                                m1.metric("Price", f"{data.get('currency')} {data.get('price')}")
                                m2.metric("PEG Ratio", str(data.get('peg_ratio')))
                                m3.metric("Trend", data.get('technical_trend'))
                                m4.metric("Market Cap", str(data.get('market_cap')))
                                
                                st.markdown(response.text)
                                
                                with st.expander("📰 View News Source (Google RSS)"):
                                    st.write(data.get('recent_news'))
                                
                                break 
                                
                            except Exception as e:
                                if "429" in str(e):
                                    if attempt < max_retries - 1:
                                        time.sleep(5)
                                    else:
                                        st.error("❌ Google AI Quota Exceeded. Try again later.")
                                else:
                                    st.error(f"AI Error: {e}")
                                    break
