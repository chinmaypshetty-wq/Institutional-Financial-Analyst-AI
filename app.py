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
# 2. ENGINE: GOOGLE NEWS RSS (Reliable)
# ==========================================
def get_google_news_rss(query):
    """
    Fetches news from Google News RSS. 
    Why? Yahoo News is empty for many intl stocks. Google News always has something.
    """
    try:
        # Clean query for URL
        clean_query = query.replace(".NS", " stock").replace(".AX", " stock")
        url = f"https://news.google.com/rss/search?q={clean_query}&hl=en-US&gl=US&ceid=US:en"
        
        response = requests.get(url, timeout=5)
        root = ET.fromstring(response.content)
        
        headlines = []
        # Parse XML for top 5 items
        for item in root.findall('./channel/item')[:5]:
            title = item.find('title').text
            pubDate = item.find('pubDate').text
            headlines.append(f"- {title} ({pubDate})")
            
        if not headlines:
            return "No news found via RSS."
            
        return "\n".join(headlines)
    except Exception as e:
        return f"News unavailable (Error: {str(e)})"

# ==========================================
# 3. ENGINE: SMART TICKER RESOLVER
# ==========================================
@st.cache_resource
def get_active_model():
    return "gemini-1.5-flash" # Force Flash for speed/reliability

ACTIVE_MODEL_NAME = get_active_model()

@st.cache_data(ttl=3600) 
def resolve_ticker(user_input):
    """
    Forces AI to find the YAHOO FINANCE specific ticker.
    Example: 'National Aluminium' -> 'NATIONALUM.NS' (not NALCO.NS)
    """
    # If user types a valid-looking ticker, trust it but clean it
    if "." in user_input and len(user_input) < 12: 
        return user_input.upper().replace(" ", "")

    try:
        model = genai.GenerativeModel(ACTIVE_MODEL_NAME)
        prompt = (
            f"Identify the exact **Yahoo Finance** ticker symbol for '{user_input}'.\n"
            "CRITICAL RULES:\n"
            "1. Search your knowledge base for the specific symbol Yahoo Finance uses.\n"
            "2. For India (NSE/BSE), it usually ends in .NS or .BO (e.g., Reliance -> RELIANCE.NS, National Aluminium -> NATIONALUM.NS).\n"
            "3. For Australia, it ends in .AX (e.g., BHP -> BHP.AX).\n"
            "4. For USA, it is just the code (e.g., General Motors -> GM, Tesla -> TSLA).\n"
            "5. Return ONLY the ticker. No text."
        )
        response = model.generate_content(prompt)
        ticker = response.text.strip().upper()
        ticker = re.sub(r'\*|\`', '', ticker)
        return ticker
    except:
        return user_input.upper()

# ==========================================
# 4. DATA ENGINE: THE HEAVY LIFTER
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
    
    # --- 1. VALIDATION CHECK ---
    # We try to fetch 5 days of history. If this fails, the ticker is WRONG.
    try:
        hist = stock.history(period="5d")
        if hist.empty:
            return {"error": f"Ticker '{ticker_symbol}' returned no data. It might be delisted or misspelled."}
        current_price = hist['Close'].iloc[-1]
    except:
        return {"error": f"Yahoo Finance cannot find '{ticker_symbol}'. Please check the ticker manually."}

    # --- 2. ROBUST INFO FETCH ---
    # We prefer 'fast_info' because 'info' gets blocked often.
    info = {}
    try:
        info = stock.info # Try normal first
    except: pass # If it fails, ignore and rely on calculation
    
    # Fallbacks if info is empty/blocked
    currency = info.get('currency', 'USD')
    sector = info.get('sector', 'Unknown')
    
    # Market Cap Fallback
    mcap = info.get('marketCap', None)
    if mcap is None:
        try:
            mcap = stock.fast_info.market_cap
        except: mcap = "N/A"

    # --- 3. FINANCIALS (The Truth Source) ---
    try:
        financials = stock.financials
        cashflow = stock.cashflow
        balance_sheet = stock.balance_sheet
        fin_T = financials.T if not financials.empty else pd.DataFrame()
        if not fin_T.empty: fin_T.sort_index(ascending=False, inplace=True)
    except:
        return {"error": "Critical: Could not load financial statements."}

    # --- 4. CALCULATE METRICS (The "Quality" Fix) ---
    growth_data = {}
    
    # A. Growth (3/5/7 Years)
    if not fin_T.empty:
        # Smart Column Search
        rev_col = next((c for c in fin_T.columns if 'Total Revenue' in c or 'Revenue' in c), None)
        eps_col = next((c for c in fin_T.columns if 'Basic EPS' in c or 'Net Income' in c), None)
        
        for yr in [3, 5, 7]:
            growth_data[f'sales_cagr_{yr}y'] = calculate_cagr(fin_T[rev_col], yr) if rev_col else "N/A"
            growth_data[f'eps_cagr_{yr}y'] = calculate_cagr(fin_T[eps_col], yr) if eps_col else "N/A"

    # B. Earnings Quality
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

    # C. Trend
    trend_msg = "Unknown"
    try:
        hist_long = stock.history(period="1y")
        if len(hist_long) > 200:
            sma_200 = hist_long['Close'].rolling(200).mean().iloc[-1]
            trend_msg = "Bullish (Above 200DMA) 🟢" if current_price > sma_200 else "Bearish (Below 200DMA) 🔴"
    except: pass

    # --- 5. REPAIR KIT (Manual Ratio Calculation) ---
    repaired = {}
    
    # Manual ROE
    try:
        ni = fin_T.iloc[0][next(c for c in fin_T.columns if 'Net Income' in c)]
        eq_series = balance_sheet.loc['Stockholders Equity'] if 'Stockholders Equity' in balance_sheet.index else balance_sheet.iloc[0]
        eq = float(eq_series.iloc[0])
        repaired['roe'] = round((ni / eq) * 100, 2)
    except: repaired['roe'] = info.get('returnOnEquity', "N/A")

    # Manual Debt/Equity
    try:
        debt_series = balance_sheet.loc['Total Debt'] if 'Total Debt' in balance_sheet.index else None
        eq_series = balance_sheet.loc['Stockholders Equity']
        if debt_series is not None:
             repaired['debt_to_equity'] = round(float(debt_series.iloc[0]) / float(eq_series.iloc[0]), 2)
        else:
             repaired['debt_to_equity'] = "0.0 (No Debt Reported)"
    except: repaired['debt_to_equity'] = info.get('debtToEquity', "N/A")

    # Manual PE & PEG
    try:
        eps_val = float(fin_T.iloc[0][next(c for c in fin_T.columns if 'Basic EPS' in c)])
        pe = current_price / eps_val
        repaired['pe_ratio'] = round(pe, 2)
        
        # Approximate PEG using 3Y growth if available
        g_rate = growth_data.get('eps_cagr_3y')
        if isinstance(g_rate, (int, float)) and g_rate > 0:
            repaired['peg_ratio'] = round(pe / g_rate, 2)
        else:
            repaired['peg_ratio'] = info.get('pegRatio', "N/A")
    except: 
        repaired['pe_ratio'] = info.get('trailingPE', "N/A")
        repaired['peg_ratio'] = info.get('pegRatio', "N/A")

    # Format Market Cap
    mcap_formatted = f"{mcap / 1_000_000:,.2f} M" if isinstance(mcap, (int, float)) else "N/A"

    return {
        "ticker": ticker_symbol.upper(),
        "sector": sector,
        "price": round(current_price, 2),
        "currency": currency,
        "market_cap": mcap_formatted,
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
# 5. SYSTEM PROMPT
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

### INSTRUCTION
If data is "N/A", explicitly state "Data Unavailable" rather than making up a pass/fail.
If the stock fails the strict criteria but is close, mark it as "WATCHLIST".

### OUTPUT FORMAT (Markdown)
## Institutional Memo: {Ticker}
**Sector:** {Sector} | **Trend:** {Trend}
**Verdict:** [STRONG BUY | WATCHLIST | HARD PASS]

### 1. Executive Thesis
(Core argument. Address News Sentiment and Data Quality.)

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
# 6. MAIN INTERFACE
# ==========================================
st.title("Institutional Financial Analyst AI")

with st.form(key='analysis_form'):
    col1, col2 = st.columns([3, 1])
    with col1:
        user_input = st.text_input("Enter Company or Ticker", placeholder="e.g., General Motors, NALCO, Tesla").strip()
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
            st.success(f"✅ Analysis Target: **{resolved_ticker}**")
        
        with st.spinner(f"📡 Analyzing {resolved_ticker} (Financials + News)..."):
            data = get_garp_data(resolved_ticker)
            
            if "error" in data:
                st.error(f"❌ {data['error']}")
                st.caption("Tip: Try searching for the exact ticker (e.g., TSLA, NATIONALUM.NS).")
            else:
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        model = genai.GenerativeModel(ACTIVE_MODEL_NAME, system_instruction=sys_instruction)
                        response = model.generate_content(f"Analyze {resolved_ticker} using this data: {data}")
                        
                        st.markdown("---")
                        
                        # Top Metrics Bar
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
