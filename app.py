import streamlit as st
import google.generativeai as genai
import yfinance as yf
import pandas as pd
import warnings
import re
import requests
import xml.etree.ElementTree as ET

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

try:
    genai.configure(api_key=user_api_key)
except Exception as e:
    st.error(f"Invalid API Key: {e}")
    st.stop()

# ==========================================
# 2. CORE UTILITY: MODEL AUTO-DETECT
# ==========================================
@st.cache_resource
def find_working_model():
    """Finds a valid model to prevent 404 errors."""
    try:
        all_models = list(genai.list_models())
        valid_models = [m.name for m in all_models if 'generateContent' in m.supported_generation_methods]
        for m in valid_models:
            if 'gemini-1.5-flash' in m: return m
        for m in valid_models:
            if 'gemini-1.5-pro' in m: return m
        return valid_models[0] if valid_models else "gemini-pro"
    except:
        return "gemini-pro"

ACTIVE_MODEL_NAME = find_working_model()
with st.sidebar:
    st.success(f"Connected: {ACTIVE_MODEL_NAME}")

# ==========================================
# 3. ENGINE: GOOGLE NEWS RSS (Reliable)
# ==========================================
def get_google_news_rss(query):
    """Fetches news from Google News RSS. Always works."""
    try:
        clean_query = query.replace(".NS", " stock").replace(".AX", " stock")
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
# 4. ENGINE: SMART TICKER RESOLVER (STRICT CLEANING)
# ==========================================
@st.cache_data(ttl=3600) 
def resolve_ticker(user_input):
    """
    Resolves ticker and performs NUCLEAR CLEANING to remove hidden characters.
    """
    clean_input = user_input.strip()
    
    # If user provides a ticker directly (contains dot or is short caps), use it
    if "." in clean_input or (clean_input.isupper() and len(clean_input) < 6):
        return re.sub(r'[^A-Z0-9.]', '', clean_input) # NUCLEAR CLEAN

    try:
        model = genai.GenerativeModel(ACTIVE_MODEL_NAME)
        prompt = (
            f"What is the exact Yahoo Finance ticker symbol for '{clean_input}'?\n"
            "STRICT RULES:\n"
            "1. USA: Symbol ONLY (e.g., 'Netflix' -> NFLX).\n"
            "2. INDIA: Must end in .NS (e.g., 'National Aluminium' -> NATIONALUM.NS).\n"
            "3. AUSTRALIA: Must end in .AX (e.g., 'Golden Deeps' -> GDE.AX).\n"
            "4. RETURN ONLY THE SYMBOL."
        )
        response = model.generate_content(prompt)
        ticker = response.text.strip().upper()
        
        # NUCLEAR CLEAN: Remove everything that isn't a Letter, Number, or Dot
        # This removes hidden spaces, newlines, asterisks, everything.
        ticker = re.sub(r'[^A-Z0-9.]', '', ticker)
        
        return ticker
    except:
        return clean_input.upper()

# ==========================================
# 5. DATA ENGINE: HEAVY LIFTER
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
    
    # --- 1. PRICE FETCH (The Validity Check) ---
    try:
        # We start with fast_info. If this works, the ticker is valid.
        current_price = stock.fast_info.last_price
        currency = stock.fast_info.currency
        mcap = stock.fast_info.market_cap
    except:
        # Fallback to history if fast_info fails
        try:
            hist = stock.history(period="5d")
            if hist.empty: return {"error": f"Ticker '{ticker_symbol}' not found. Try entering the code manually (e.g., GDE.AX)."}
            current_price = hist['Close'].iloc[-1]
            currency = "USD" 
            mcap = "N/A"
        except:
             return {"error": f"Yahoo Finance blocked or Ticker '{ticker_symbol}' invalid."}

    # --- 2. INFO FETCH (Lazy) ---
    info = {}
    try: info = stock.info
    except: pass 
    
    sector = info.get('sector', 'Unknown')
    
    # --- 3. FINANCIALS ---
    try:
        financials = stock.financials
        cashflow = stock.cashflow
        balance_sheet = stock.balance_sheet
        fin_T = financials.T if not financials.empty else pd.DataFrame()
        if not fin_T.empty: fin_T.sort_index(ascending=False, inplace=True)
    except:
        return {"error": "Critical: Could not load financial statements."}

    # --- 4. CALCULATE METRICS ---
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
                ocf_val = float(cf_T.iloc[0][ocf])
                ni_val = float(fin_T.iloc[0][ni])
                earnings_quality_msg = "High (Cash > Profit)" if ocf_val > ni_val else "Low (Profit > Cash) ⚠️"
    except: pass

    # Trend
    trend_msg = "Unknown"
    try:
        hist_long = stock.history(period="1y")
        if len(hist_long) > 200:
            sma_200 = hist_long['Close'].rolling(200).mean().iloc[-1]
            trend_msg = "Bullish (Above 200DMA) 🟢" if current_price > sma_200 else "Bearish (Below 200DMA) 🔴"
    except: pass

    # --- 5. REPAIR KIT (Manual Ratios) ---
    repaired = {}
    
    # ROE
    try:
        ni = fin_T.iloc[0][next(c for c in fin_T.columns if 'Net Income' in c)]
        eq_series = balance_sheet.loc['Stockholders Equity'] if 'Stockholders Equity' in balance_sheet.index else balance_sheet.iloc[0]
        eq = float(eq_series.iloc[0])
        repaired['roe'] = round((ni / eq) * 100, 2)
    except: repaired['roe'] = info.get('returnOnEquity', "N/A")

    # Debt/Equity
    try:
        debt_series = balance_sheet.loc['Total Debt'] if 'Total Debt' in balance_sheet.index else None
        eq_series = balance_sheet.loc['Stockholders Equity']
        if debt_series is not None:
             repaired['debt_to_equity'] = round(float(debt_series.iloc[0]) / float(eq_series.iloc[0]), 2)
        else:
             repaired['debt_to_equity'] = "0.0 (No Debt)"
    except: repaired['debt_to_equity'] = info.get('debtToEquity', "N/A")

    # PE & PEG
    try:
        eps_val = float(fin_T.iloc[0][next(c for c in fin_T.columns if 'Basic EPS' in c)])
        pe = current_price / eps_val
        repaired['pe_ratio'] = round(pe, 2)
        
        g_rate = growth_data.get('eps_cagr_3y')
        if isinstance(g_rate, (int, float)) and g_rate > 0:
            repaired['peg_ratio'] = round(pe / g_rate, 2)
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
(State the core argument. Integrate News Sentiment immediately here.)

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
(Why buy/avoid now?)
"""

# ==========================================
# 7. MAIN INTERFACE
# ==========================================
st.title("Institutional Financial Analyst AI")

with st.form(key='analysis_form'):
    col1, col2 = st.columns([3, 1])
    with col1:
        user_input = st.text_input("Enter Company or Ticker", placeholder="e.g., Golden Deeps, LIC, Netflix").strip()
    with col2:
        st.write("")
        st.write("")
        submit_btn = st.form_submit_button("🚀 Run Analysis", type="primary", use_container_width=True)

if submit_btn:
    if not user_input:
        st.warning("Please enter a company name or ticker.")
    else:
        # 1. RESOLVE
        with st.spinner(f"🔍 Resolving ticker for '{user_input}'..."):
            resolved_ticker = resolve_ticker(user_input)
            
        # 2. ANALYZE
        with st.spinner(f"📡 Analyzing {resolved_ticker} (Financials + News)..."):
            data = get_garp_data(resolved_ticker)
            
            if "error" in data:
                st.error(f"❌ {data['error']}")
                st.info(f"**Attempted Ticker:** `{resolved_ticker}`")
                st.caption("Tip: If the AI guessed wrong, enter the exact ticker (e.g., GDE.AX, PGFOLS.NS).")
            else:
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        model = genai.GenerativeModel(ACTIVE_MODEL_NAME, system_instruction=sys_instruction)
                        response = model.generate_content(f"Analyze {resolved_ticker} using this data: {data}")
                        
                        st.success(f"Analysis Complete: **{resolved_ticker}**")
                        
                        # News Section FIRST (Per your request to see it works)
                        with st.expander("📰 Latest News Headlines (Live)", expanded=True):
                            st.write(data.get('recent_news'))

                        st.markdown("---")
                        
                        # Top Metrics Bar
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("Price", f"{data.get('currency')} {data.get('price')}")
                        m2.metric("PEG Ratio", str(data.get('peg_ratio')))
                        m3.metric("Trend", data.get('technical_trend'))
                        m4.metric("Market Cap", str(data.get('market_cap')))
                        
                        st.markdown(response.text)
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
