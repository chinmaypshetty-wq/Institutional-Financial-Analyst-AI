import streamlit as st
import google.generativeai as genai
import yfinance as yf
import pandas as pd
import warnings
import re
import requests

# Suppress warnings
warnings.filterwarnings('ignore')

st.set_page_config(page_title="Institutional AI Analyst", page_icon="🦅", layout="wide")

st.markdown("""
<style>
div[data-testid="stMetricValue"] { font-size: 1.2rem; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 1. CONFIGURATION & SIDEBAR
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
        
        # Priority: Flash (Fast & Cheap) -> Pro (Smart) -> Fallback
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
# 3. HELPER: SMART RESOLVER (FIXED)
# ==========================================
@st.cache_data(ttl=3600) 
def resolve_ticker(user_input):
    """
    FIXED: No longer assumes short words are tickers. 
    Forces AI to resolve 'Tesla' -> 'TSLA' and 'General Motors' -> 'GM'.
    """
    # If it looks like a perfect ticker (e.g., "TSLA", "CBA.AX"), trust it.
    if user_input.isupper() and len(user_input) < 6 and "." not in user_input and " " not in user_input:
        # Ambiguous check: 'TESLA' is upper but wrong. 'GM' is upper and right.
        # Let's trust the AI more than the user for US stocks.
        pass 
    elif "." in user_input: 
        return user_input.upper() # Trust inputs with suffixes like .AX

    try:
        model = genai.GenerativeModel(ACTIVE_MODEL_NAME)
        prompt = (
            f"What is the exact Yahoo Finance ticker for '{user_input}'? "
            "Rules:\n"
            "1. Australian companies -> MUST end in .AX (e.g., 'Commonwealth Bank' -> 'CBA.AX')\n"
            "2. Indian companies -> MUST end in .NS (e.g., 'Reliance' -> 'RELIANCE.NS')\n"
            "3. US companies -> Symbol ONLY (e.g., 'General Motors' -> 'GM', 'Tesla' -> 'TSLA')\n"
            "4. Return ONLY the ticker symbol. No other text/markdown."
        )
        response = model.generate_content(prompt)
        ticker = response.text.strip().upper()
        ticker = re.sub(r'\*|\`', '', ticker) # Clean up markdown
        return ticker
    except:
        return user_input.upper()

# ==========================================
# 4. DATA ENGINE (HIGH QUALITY + ANTI-BLOCK)
# ==========================================
def get_yahoo_news(ticker):
    """Fetches news using yfinance Ticker object."""
    try:
        stock = yf.Ticker(ticker)
        news = stock.news
        if not news: return "No recent news found."
        
        headlines = []
        for n in news[:5]: # Top 5 stories
            title = n.get('title', 'No Title')
            pub = n.get('publisher', 'Unknown')
            headlines.append(f"- {title} ({pub})")
            
        return "\n".join(headlines)
    except:
        return "News unavailable."

def calculate_cagr(series, years):
    try:
        if len(series) < years + 1: return None
        current, past = series.iloc[0], series.iloc[years]
        if past <= 0: return "N/A (Neg Base)"
        if current <= 0: return "N/A (Neg Current)"
        return round(((current / past)**(1/years) - 1) * 100, 2)
    except: return None

@st.cache_data(ttl=3600) 
def get_garp_data(ticker_symbol):
    stock = yf.Ticker(ticker_symbol)
    
    # --- PHASE 1: HIGH QUALITY FETCH (With Browser Disguise) ---
    # We define a fallback dictionary in case info fails
    info = {}
    
    try:
        # Attempt to fetch full rich data
        info = stock.info
        current_price = info.get('currentPrice', info.get('regularMarketPrice', 0))
        currency = info.get('currency', 'USD')
        sector = info.get('sector', 'Unknown')
        mcap = info.get('marketCap', 0)
        
        # If regular fetch fails/returns 0, try fast_info
        if current_price == 0:
            raise ValueError("Price not found in info")
            
    except Exception:
        # FALLBACK: Fast Info (Reliable for Price/Cap)
        try:
            fast = stock.fast_info
            current_price = fast.last_price
            currency = fast.currency
            mcap = fast.market_cap
            sector = "Unknown (Data Restricted)"
            # Leave info empty so Repair Kit fills the gaps
        except:
            return {"error": f"Could not fetch data for '{ticker_symbol}'. Check spelling or try again."}

    # --- PHASE 2: FINANCIAL STATEMENTS ---
    try:
        financials = stock.financials
        cashflow = stock.cashflow
        balance_sheet = stock.balance_sheet
        fin_T = financials.T if not financials.empty else pd.DataFrame()
        if not fin_T.empty: fin_T.sort_index(ascending=False, inplace=True)
    except:
        return {"error": "Financial statements unavailable."}

    # --- PHASE 3: CALCULATE GROWTH (The Core Logic) ---
    growth_data = {}
    if not fin_T.empty:
        rev_col = next((c for c in fin_T.columns if 'Total Revenue' in c), None)
        eps_col = next((c for c in fin_T.columns if 'Basic EPS' in c or 'Net Income' in c), None)
        
        for yr in [3, 5, 7]:
            growth_data[f'sales_cagr_{yr}y'] = calculate_cagr(fin_T[rev_col], yr) if rev_col else "N/A"
            growth_data[f'eps_cagr_{yr}y'] = calculate_cagr(fin_T[eps_col], yr) if eps_col else "N/A"

    # --- PHASE 4: QUALITY CHECK ---
    earnings_quality_msg = "Unknown"
    try:
        cf_T = cashflow.T
        if not cf_T.empty:
            cf_T.sort_index(ascending=False, inplace=True)
            ocf = next((c for c in cf_T.columns if 'Operating' in c), None)
            ni = next((c for c in fin_T.columns if 'Net Income' in c), None)
            if ocf and ni:
                if cf_T.iloc[0][ocf] > fin_T.iloc[0][ni]: earnings_quality_msg = "High (Cash > Profit)"
                else: earnings_quality_msg = "Low (Profit > Cash) ⚠️"
    except: pass

    # --- PHASE 5: TREND CHECK ---
    trend_msg = "Unknown"
    try:
        hist = stock.history(period="1y")
        if not hist.empty and len(hist) > 200:
            sma = hist['Close'].rolling(200).mean().iloc[-1]
            trend_msg = "Bullish (Above 200DMA) 🟢" if current_price > sma else "Bearish (Below 200DMA) 🔴"
    except: pass

    # --- PHASE 6: REPAIR KIT (Fill gaps if 'info' failed) ---
    repaired = {}
    
    # ROE
    if info.get('returnOnEquity'): 
        repaired['roe'] = info.get('returnOnEquity')
    else:
        try:
            ni = financials.loc['Net Income'].iloc[0] if 'Net Income' in financials.index else 0
            eq = balance_sheet.loc['Stockholders Equity'].iloc[0] if 'Stockholders Equity' in balance_sheet.index else 1
            repaired['roe'] = round(ni / eq, 4) if eq != 0 else "N/A"
        except: repaired['roe'] = "N/A"

    # Debt/Equity
    if info.get('debtToEquity'):
        repaired['debt_to_equity'] = info.get('debtToEquity')
    else:
        try:
            debt = balance_sheet.loc['Total Debt'].iloc[0] if 'Total Debt' in balance_sheet.index else 0
            eq = balance_sheet.loc['Stockholders Equity'].iloc[0] if 'Stockholders Equity' in balance_sheet.index else 1
            repaired['debt_to_equity'] = round((debt / eq) * 100, 2)
        except: repaired['debt_to_equity'] = "N/A"

    # PEG Ratio
    if info.get('pegRatio'):
        repaired['peg_ratio'] = info.get('pegRatio')
    else:
        # PEG is hard to calc manually without forecast. We try to estimate or mark N/A
        repaired['peg_ratio'] = "N/A (Missing Forecast)"
        
    # PE Ratio
    if info.get('trailingPE'):
        repaired['pe_ratio'] = info.get('trailingPE')
    else:
        try:
            eps = financials.loc['Basic EPS'].iloc[0] if 'Basic EPS' in financials.index else None
            repaired['pe_ratio'] = round(current_price / eps, 2) if eps else "N/A"
        except: repaired['pe_ratio'] = "N/A"

    return {
        "ticker": ticker_symbol.upper(),
        "sector": sector,
        "price": current_price,
        "currency": currency,
        "market_cap_millions": round(mcap / 1_000_000, 2) if mcap else "N/A",
        "peg_ratio": repaired.get('peg_ratio'),
        "pe_ratio": repaired.get('pe_ratio'),
        "debt_to_equity": repaired.get('debt_to_equity'),
        "roe": repaired.get('roe'),
        "earnings_quality": earnings_quality_msg,
        "technical_trend": trend_msg,
        "recent_news": get_yahoo_news(ticker_symbol),
        **growth_data
    }

# ==========================================
# 5. SYSTEM PROMPT (STRICT & DETAILED)
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
(State the core argument clearly. **Explicitly comment on any Missing Data or N/A values.**)

### 2. Quantitative Scorecard
| Metric | Value | Target | Status |
| :--- | :--- | :--- | :--- |
| **EPS Growth (3Y/5Y/7Y)** | {vals}% | > 20% each | [PASS/FAIL] |
| **Sales Growth (3Y/5Y/7Y)** | {vals}% | > 15% each | [PASS/FAIL] |
| **PEG Ratio** | {val} | < 1.0 | [PASS/FAIL] |
| **Debt/Equity** | {val} | < 1.0 | [PASS/FAIL/SKIP] |
| **PE Ratio** | {val} | > 0 | [PASS/FAIL] |
| **Market Cap** | {val} M | > 5000 M | [PASS/FAIL] |

### 3. Risk & Portfolio Fit
(Comment on Quality, Trend, and News. Why buy/avoid now?)
"""

# ==========================================
# 6. MAIN INTERFACE
# ==========================================
st.title("Institutional Financial Analyst AI")

with st.form(key='analysis_form'):
    col1, col2 = st.columns([3, 1])
    with col1:
        user_input = st.text_input("Enter Company or Ticker", placeholder="e.g., General Motors, Tesla, Tata Steel").strip()
    with col2:
        st.write("")
        st.write("")
        submit_btn = st.form_submit_button("🚀 Run Analysis", type="primary", use_container_width=True)

if submit_btn:
    if not user_input:
        st.warning("Please enter a company name or ticker.")
    else:
        # Show what the AI is resolving to (Debugging transparency)
        with st.spinner(f"🔍 Resolving ticker for '{user_input}'..."):
            resolved_ticker = resolve_ticker(user_input)
            st.caption(f"✅ Resolved Ticker: **{resolved_ticker}**")
        
        with st.spinner(f"📡 Analyzing {resolved_ticker} (Financials + News)..."):
            data = get_garp_data(resolved_ticker)
            
            if "error" in data:
                st.error(f"❌ {data['error']} (Tried searching for: {resolved_ticker})")
            else:
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        model = genai.GenerativeModel(ACTIVE_MODEL_NAME, system_instruction=sys_instruction)
                        response = model.generate_content(f"Analyze {resolved_ticker} using this data: {data}")
                        
                        st.success(f"Analysis Complete (Ticker: {resolved_ticker})")
                        
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("Price", f"{data.get('currency')} {data.get('price')}")
                        c2.metric("PEG Ratio", data.get('peg_ratio'))
                        c3.metric("Trend", data.get('technical_trend'))
                        c4.metric("Quality", "High" if "High" in str(data.get('earnings_quality')) else "Low")
                        
                        st.markdown("---")
                        st.markdown(response.text)
                        
                        with st.expander("📰 Read Scanned Headlines"):
                            st.write(data.get('recent_news'))
                        
                        break 
                        
                    except Exception as e:
                        if "429" in str(e):
                            if attempt < max_retries - 1:
                                st.warning(f"⚠️ Quota limit hit. Retrying in 5 seconds... (Attempt {attempt+1}/{max_retries})")
                                time.sleep(5)
                            else:
                                st.error("❌ Daily Quota Exceeded. Please try again tomorrow or switch to a paid API key.")
                        else:
                            st.error(f"AI Error: {e}")
                            break
