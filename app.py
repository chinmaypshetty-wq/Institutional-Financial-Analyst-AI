import streamlit as st
import google.generativeai as genai
import yfinance as yf
import pandas as pd
import warnings
import re
import time
from duckduckgo_search import DDGS

# Suppress warnings
warnings.filterwarnings('ignore')

st.set_page_config(page_title="Institutional AI Analyst", page_icon="🦅", layout="wide")

st.markdown("""
<style>
div[data-testid="stMetricValue"] { font-size: 1.2rem; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 1. SIDEBAR CONFIGURATION (User Input)
# ==========================================
with st.sidebar:
    st.title("🦅 Controls")
    # THE MAGICAL TEXT BOX
    user_api_key = st.text_input("Enter Google API Key", type="password", help="Get a free key from Google AI Studio")
    st.markdown("---")
    st.info("System Status: Waiting for Key...")

# STOP THE APP IF NO KEY IS ENTERED
if not user_api_key:
    st.warning("⬅️ Please enter a Google API Key in the sidebar to start.")
    st.stop() # Stops the code here until key is entered

# Configure with the user's key
try:
    genai.configure(api_key=user_api_key)
except Exception as e:
    st.error(f"Invalid API Key: {e}")
    st.stop()

# ==========================================
# 2. CORE UTILITY: FIND WORKING MODEL
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

# Detect model AFTER key is configured
ACTIVE_MODEL_NAME = find_working_model()
with st.sidebar:
    st.success(f"Connected: {ACTIVE_MODEL_NAME}")

# ==========================================
# 3. HELPER: SMART RESOLVER
# ==========================================
@st.cache_data(ttl=3600) 
def resolve_ticker(user_input):
    """Aggressively converts names to Yahoo Tickers."""
    if "." in user_input and len(user_input) < 12: return user_input.upper()

    try:
        model = genai.GenerativeModel(ACTIVE_MODEL_NAME)
        prompt = (
            f"What is the exact Yahoo Finance ticker for '{user_input}'? "
            "Rules: 1. Australian -> add .AX. 2. Indian -> add .NS. 3. US -> symbol only. "
            "Return ONLY the symbol. No text."
        )
        response = model.generate_content(prompt)
        ticker = response.text.strip().upper()
        ticker = re.sub(r'\*|\`', '', ticker)
        
        if " " in ticker or len(ticker) > 15: return user_input.upper()
        return ticker
    except:
        return user_input.upper()

def get_company_news(ticker):
    """Fetches news headlines."""
    try:
        clean_ticker = ticker.replace(".NS", "").replace(".AX", "")
        results = DDGS().news(keywords=f"{clean_ticker} stock news", max_results=5)
        if results:
            return "\n".join([f"- {r['title']} ({r['source']})" for r in results])
        return "No major recent news found."
    except:
        return "News fetch failed."

# ==========================================
# 4. DATA ENGINE (With Repair Kit)
# ==========================================
def calculate_cagr(series, years):
    try:
        if len(series) < years + 1: return None
        current, past = series.iloc[0], series.iloc[years]
        if past <= 0: return "N/A (Neg Base)"
        if current <= 0: return "N/A (Neg Current)"
        return round(((current / past)**(1/years) - 1) * 100, 2)
    except: return None

def manual_metric_repair(stock, info, financials, balance_sheet):
    """Repairs missing Yahoo Finance data."""
    repaired = {}
    try:
        # 1. Repair ROE
        if info.get('returnOnEquity') is None:
            try:
                net_income = financials.loc['Net Income'].iloc[0] if 'Net Income' in financials.index else None
                equity = balance_sheet.loc['Stockholders Equity'].iloc[0] if 'Stockholders Equity' in balance_sheet.index else None
                if net_income and equity: repaired['roe'] = round(net_income / equity, 4)
                else: repaired['roe'] = "N/A"
            except: repaired['roe'] = "N/A"
        else: repaired['roe'] = info.get('returnOnEquity')

        # 2. Repair Debt/Equity
        if info.get('debtToEquity') is None:
            try:
                total_debt = balance_sheet.loc['Total Debt'].iloc[0] if 'Total Debt' in balance_sheet.index else None
                equity = balance_sheet.loc['Stockholders Equity'].iloc[0] if 'Stockholders Equity' in balance_sheet.index else None
                if total_debt and equity: repaired['debt_to_equity'] = round((total_debt / equity) * 100, 2)
                else: repaired['debt_to_equity'] = "N/A"
            except: repaired['debt_to_equity'] = "N/A"
        else: repaired['debt_to_equity'] = info.get('debtToEquity')

        # 3. Repair PEG
        if info.get('pegRatio') is None:
            pe = info.get('trailingPE')
            repaired['peg_ratio'] = "N/A (Calc Failed)"
            repaired['pe_ratio'] = round(pe, 2) if pe else "N/A"
        else:
            repaired['peg_ratio'] = info.get('pegRatio')
            repaired['pe_ratio'] = info.get('trailingPE')

    except Exception: pass
    return repaired

@st.cache_data(ttl=3600) 
def get_garp_data(ticker_symbol):
    stock = yf.Ticker(ticker_symbol)
    try:
        info = stock.info
        current_price = info.get('currentPrice', info.get('regularMarketPrice', 0))
        if current_price == 0: return {"error": f"Ticker '{ticker_symbol}' not found."}
        
        financials = stock.financials
        cashflow = stock.cashflow
        balance_sheet = stock.balance_sheet
        
        # Growth Calculations
        growth_data = {}
        fin_T = financials.T 
        fin_T.sort_index(ascending=False, inplace=True)
        
        rev_col = next((c for c in fin_T.columns if 'Total Revenue' in c), None)
        eps_col = next((c for c in fin_T.columns if 'Basic EPS' in c or 'Net Income' in c), None)
        
        for yr in [3, 5, 7]:
            growth_data[f'sales_cagr_{yr}y'] = calculate_cagr(fin_T[rev_col], yr) if rev_col else "N/A"
            growth_data[f'eps_cagr_{yr}y'] = calculate_cagr(fin_T[eps_col], yr) if eps_col else "N/A"

        # Quality Check
        earnings_quality_msg = "Unknown"
        try:
            cf_T = cashflow.T
            cf_T.sort_index(ascending=False, inplace=True)
            ocf_col = next((c for c in cf_T.columns if 'Operating' in c and 'Cash' in c), None)
            ni_col = next((c for c in fin_T.columns if 'Net Income' in c), None)
            
            if ocf_col and ni_col and not cf_T.empty and not fin_T.empty:
                latest_ocf = cf_T.iloc[0][ocf_col]
                latest_ni = fin_T.iloc[0][ni_col]
                earnings_quality_msg = "High (Cash > Profit)" if latest_ocf > latest_ni else "Low (Profit > Cash) ⚠️"
        except: pass

        # Trend Check
        trend_msg = "Unknown"
        try:
            hist = stock.history(period="1y")
            if not hist.empty and len(hist) > 200:
                sma_200 = hist['Close'].rolling(window=200).mean().iloc[-1]
                trend_msg = "Bullish (Above 200DMA) 🟢" if current_price > sma_200 else "Bearish (Below 200DMA) 🔴"
        except: pass

        repaired_metrics = manual_metric_repair(stock, info, financials, balance_sheet)

        return {
            "ticker": ticker_symbol.upper(),
            "sector": info.get('sector', 'Unknown'),
            "price": current_price,
            "currency": info.get('currency', 'USD'),
            "market_cap_millions": round(info.get('marketCap', 0) / 1_000_000, 2),
            "peg_ratio": repaired_metrics.get('peg_ratio', "N/A"),
            "pe_ratio": repaired_metrics.get('pe_ratio', "N/A"),
            "debt_to_equity": repaired_metrics.get('debt_to_equity', "N/A"),
            "roe": repaired_metrics.get('roe', "N/A"),
            "earnings_quality": earnings_quality_msg,
            "technical_trend": trend_msg,
            "recent_news": get_company_news(ticker_symbol),
            **growth_data
        }
    except Exception as e:
        return {"error": f"Data Pipeline Error: {e}"}

# ==========================================
# 5. SYSTEM PROMPT
# ==========================================
sys_instruction = """
### ROLE
Senior Portfolio Manager. Skeptical, data-driven, focused on **risk-adjusted returns**.

### STRATEGY (GARP + QUALITY + MOMENTUM + NEWS)
1. Growth: 3Y/5Y/7Y CAGR > 20% (EPS) & > 15% (Sales).
2. Valuation: PEG < 1.0 (Strict) or < 1.5 (if ROE > 20%).
3. Health: Debt/Equity < 1.0 (Ignore for Banks).
4. Quality: Cash Flow > Net Income.
5. Trend: Prefer "Bullish".
6. Sentiment: Analyze 'recent_news' for lawsuits/fraud/scandals.

### OUTPUT FORMAT (Markdown)
## Institutional Memo: {Ticker}
**Sector:** {Sector} | **Trend:** {Trend}
**Verdict:** [STRONG BUY | WATCHLIST | HARD PASS]

### 1. Executive Thesis
(State the core argument clearly. Mention News Sentiment.)

### 2. Quantitative Scorecard
| Metric | Value | Target | Status |
| :--- | :--- | :--- | :--- |
| **EPS Growth (3Y/5Y/7Y)** | {vals}% | > 20% | [PASS/FAIL] |
| **Sales Growth (3Y/5Y/7Y)** | {vals}% | > 15% | [PASS/FAIL] |
| **PEG Ratio** | {val} | < 1.0 | [PASS/FAIL] |
| **Debt/Equity** | {val} | < 1.0 | [PASS/FAIL/SKIP] |
| **ROE** | {val} | > 15% | [PASS/FAIL] |
| **Earnings Quality** | {val} | High | [PASS/FAIL] |

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
        user_input = st.text_input("Enter Company or Ticker", placeholder="e.g., Commonwealth Bank, Tata Steel").strip()
    with col2:
        st.write("")
        st.write("")
        submit_btn = st.form_submit_button("🚀 Run Analysis", type="primary", use_container_width=True)

if submit_btn:
    if not user_input:
        st.warning("Please enter a company name or ticker.")
    else:
        resolved_ticker = resolve_ticker(user_input)
        
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
