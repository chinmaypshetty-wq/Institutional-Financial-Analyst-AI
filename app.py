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

try:
    genai.configure(api_key=user_api_key)
except Exception as e:
    st.error(f"Invalid API Key: {e}")
    st.stop()

# ==========================================
# 2. ENGINE: GOOGLE NEWS RSS (Reliable)
# ==========================================
def get_google_news_rss(query):
    """Fetches news from Google News RSS. Never blocked."""
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
            
        return "\n".join(headlines) if headlines else "No news found via RSS."
    except:
        return "News unavailable."

# ==========================================
# 3. ENGINE: BRUTE FORCE TICKER RESOLVER
# ==========================================
@st.cache_resource
def get_active_model():
    return "gemini-1.5-flash"

ACTIVE_MODEL_NAME = get_active_model()

def check_ticker_live(ticker):
    """Returns True if ticker exists on Yahoo, False otherwise."""
    try:
        # fast_info is the quickest, least-blocked way to check
        price = yf.Ticker(ticker).fast_info.last_price
        return price is not None and price > 0
    except:
        return False

@st.cache_data(ttl=3600) 
def resolve_ticker(user_input):
    """
    1. Ask AI for ticker.
    2. If valid, return.
    3. If invalid, try appending suffixes (.AX, .NS) automatically.
    """
    clean_input = user_input.strip().upper()
    
    # Quick Check: Did user type a valid ticker directly? (e.g. "EAX")
    if check_ticker_live(clean_input): return clean_input
    if check_ticker_live(clean_input + ".AX"): return clean_input + ".AX"
    if check_ticker_live(clean_input + ".NS"): return clean_input + ".NS"

    # AI Attempt
    try:
        model = genai.GenerativeModel(ACTIVE_MODEL_NAME)
        prompt = (
            f"What is the exact Yahoo Finance ticker for '{user_input}'? "
            "Examples: 'Netflix'->NFLX, 'Tata Steel'->TATASTEEL.NS, 'Energy Action'->EAX.AX. "
            "Return ONLY the text of the ticker."
        )
        response = model.generate_content(prompt)
        ai_ticker = response.text.strip().upper().replace(" ", "").replace("`", "")
        
        # Verify AI's guess
        if check_ticker_live(ai_ticker): return ai_ticker
        
        # Verify AI's guess with suffixes (AI might forget .NS)
        if check_ticker_live(ai_ticker + ".AX"): return ai_ticker + ".AX"
        if check_ticker_live(ai_ticker + ".NS"): return ai_ticker + ".NS"
        
    except: pass

    return clean_input # Fallback to user input if all else fails

# ==========================================
# 4. DATA ENGINE: STEALTH MODE
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
    
    # 1. PRICE & CAP (Using fast_info to bypass 'info' block)
    current_price = 0
    mcap = 0
    currency = "USD"
    
    try:
        current_price = stock.fast_info.last_price
        mcap = stock.fast_info.market_cap
        currency = stock.fast_info.currency
    except:
        return {"error": f"Yahoo Finance blocked or Ticker '{ticker_symbol}' invalid."}

    # 2. FINANCIALS
    try:
        financials = stock.financials
        cashflow = stock.cashflow
        balance_sheet = stock.balance_sheet
        fin_T = financials.T if not financials.empty else pd.DataFrame()
        if not fin_T.empty: fin_T.sort_index(ascending=False, inplace=True)
    except:
        return {"error": "Critical: Could not load financial statements."}

    # 3. INFO (Lazy Load)
    info = {}
    try: info = stock.info
    except: pass 

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
        "sector": info.get('sector', 'Unknown'),
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
# 6. MAIN INTERFACE
# ==========================================
st.title("Institutional Financial Analyst AI")

with st.form(key='analysis_form'):
    col1, col2 = st.columns([3, 1])
    with col1:
        user_input = st.text_input("Enter Company or Ticker", placeholder="e.g., Netflix, Tata Steel").strip()
    with col2:
        st.write("")
        st.write("")
        submit_btn = st.form_submit_button("🚀 Run Analysis", type="primary", use_container_width=True)

if submit_btn:
    if not user_input:
        st.warning("Please enter a company name or ticker.")
    else:
        # 1. RESOLVE & VERIFY TICKER
        with st.spinner(f"🔍 Resolving ticker for '{user_input}'..."):
            resolved_ticker = resolve_ticker(user_input)
            
            # Final check before passing to engine
            if not check_ticker_live(resolved_ticker):
                st.error(f"❌ Could not find valid data for '{resolved_ticker}'.")
                st.caption("Try adding the country suffix manualy (e.g. .AX for Australia, .NS for India).")
            else:
                st.success(f"✅ Analysis Target: **{resolved_ticker}**")
        
                # 2. FETCH DATA
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
