import streamlit as st
import google.generativeai as genai
import yfinance as yf
import pandas as pd
import warnings
import re
from duckduckgo_search import DDGS

# Suppress warnings
warnings.filterwarnings('ignore')

# ==========================================
# 1. CONFIGURATION
# ==========================================
MY_API_KEY = st.secrets["GOOGLE_API_KEY"]

try:
    genai.configure(api_key=MY_API_KEY)
except Exception as e:
    st.error(f"API Key Error: {e}")

st.set_page_config(page_title="Institutional AI Analyst", page_icon="🦅", layout="wide")

st.markdown("""
<style>
div[data-testid="stMetricValue"] { font-size: 1.2rem; }
</style>
""", unsafe_allow_html=True)

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

ACTIVE_MODEL_NAME = find_working_model()

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
    """
    If Yahoo 'info' is missing data, try to calculate it manually 
    from the Balance Sheet and Income Statement.
    """
    repaired = {}
    
    try:
        # 1. Repair ROE (Net Income / Total Equity)
        if info.get('returnOnEquity') is None:
            try:
                # Try finding Net Income
                net_income = None
                if 'Net Income' in financials.index:
                    net_income = financials.loc['Net Income'].iloc[0]
                elif 'Net Income Common Stockholders' in financials.index:
                    net_income = financials.loc['Net Income Common Stockholders'].iloc[0]
                
                # Try finding Equity
                equity = None
                if 'Stockholders Equity' in balance_sheet.index:
                    equity = balance_sheet.loc['Stockholders Equity'].iloc[0]
                elif 'Total Equity Gross Minority Interest' in balance_sheet.index:
                    equity = balance_sheet.loc['Total Equity Gross Minority Interest'].iloc[0]

                if net_income and equity and equity != 0:
                    repaired['roe'] = round(net_income / equity, 4)
                else: 
                    repaired['roe'] = "N/A"
            except: repaired['roe'] = "N/A"
        else:
            repaired['roe'] = info.get('returnOnEquity')

        # 2. Repair Debt/Equity (Total Debt / Total Equity)
        if info.get('debtToEquity') is None:
            try:
                total_debt = None
                if 'Total Debt' in balance_sheet.index:
                    total_debt = balance_sheet.loc['Total Debt'].iloc[0]
                
                # Reuse equity from above or fetch again
                equity = None
                if 'Stockholders Equity' in balance_sheet.index:
                    equity = balance_sheet.loc['Stockholders Equity'].iloc[0]

                if total_debt is not None and equity and equity != 0:
                    # Yahoo expects this as a percentage (e.g., 150 for 1.5)
                    repaired['debt_to_equity'] = round((total_debt / equity) * 100, 2)
                else: 
                    repaired['debt_to_equity'] = "N/A"
            except: repaired['debt_to_equity'] = "N/A"
        else:
            repaired['debt_to_equity'] = info.get('debtToEquity')

        # 3. Repair PEG (PE Ratio / Earnings Growth)
        if info.get('pegRatio') is None:
            # We need PE first
            pe = info.get('trailingPE')
            if pe is None:
                 # Try to calc PE: Price / EPS
                 try:
                     price = info.get('currentPrice', info.get('regularMarketPrice'))
                     eps = financials.loc['Basic EPS'].iloc[0] if 'Basic EPS' in financials.index else None
                     if price and eps:
                        pe = price / eps
                 except: pe = None
            
            repaired['peg_ratio'] = "N/A (Manual Calc Failed)"
            if pe:
                 repaired['pe_ratio'] = round(pe, 2)
                 # We simply return the PE here if PEG is missing, 
                 # letting the AI analyze it in context.
            else:
                 repaired['pe_ratio'] = "N/A"

        else:
            repaired['peg_ratio'] = info.get('pegRatio')
            repaired['pe_ratio'] = info.get('trailingPE')

    except Exception as e:
        print(f"Repair failed: {e}")
        
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
        
        # Sort DataFrames (Ensure most recent is first/column 0)
        # yfinance usually returns recent first, but we check to be safe
        # Note: yfinance dataframes usually have dates as columns. 
        
        # Growth Calculations
        growth_data = {}
        # We need the Transpose (.T) for calculating CAGR easily across rows
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
            # Need correct orientation
            cf_T = cashflow.T
            cf_T.sort_index(ascending=False, inplace=True)
            
            ocf_col = next((c for c in cf_T.columns if 'Operating' in c and 'Cash' in c), None)
            ni_col = next((c for c in fin_T.columns if 'Net Income' in c), None)
            
            if ocf_col and ni_col and not cf_T.empty and not fin_T.empty:
                latest_ocf = cf_T.iloc[0][ocf_col]
                latest_ni = fin_T.iloc[0][ni_col]
                if latest_ocf > latest_ni:
                    earnings_quality_msg = "High (Cash > Profit)"
                else:
                    earnings_quality_msg = "Low (Profit > Cash) ⚠️"
        except: pass

        # Trend Check
        trend_msg = "Unknown"
        try:
            hist = stock.history(period="1y")
            if not hist.empty and len(hist) > 200:
                sma_200 = hist['Close'].rolling(window=200).mean().iloc[-1]
                trend_msg = "Bullish (Above 200DMA) 🟢" if current_price > sma_200 else "Bearish (Below 200DMA) 🔴"
        except: pass

        # RUN THE REPAIR KIT (Pass untransposed DFs for easier key lookups)
        repaired_metrics = manual_metric_repair(stock, info, financials, balance_sheet)

        return {
            "ticker": ticker_symbol.upper(),
            "sector": info.get('sector', 'Unknown'),
            "price": current_price,
            "currency": info.get('currency', 'USD'),
            "market_cap_millions": round(info.get('marketCap', 0) / 1_000_000, 2),
            
            # Use Repaired Metrics
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

with st.sidebar:
    st.success(f"✅ AI Connected: {ACTIVE_MODEL_NAME}")
    st.info("System Ready")

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
        # Resolve Ticker
        resolved_ticker = resolve_ticker(user_input)
        
        with st.spinner(f"📡 Analyzing {resolved_ticker} (Financials + News)..."):
            data = get_garp_data(resolved_ticker)
            
            if "error" in data:
                st.error(f"❌ {data['error']} (Tried searching for: {resolved_ticker})")
            else:
                # Retry logic to handle "429 Too Many Requests"
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
                        
                        break # Success, exit retry loop
                        
                    except Exception as e:
                        if "429" in str(e): # Quota limit error
                            if attempt < max_retries - 1:
                                st.warning(f"⚠️ Quota limit hit. Retrying in 5 seconds... (Attempt {attempt+1}/{max_retries})")
                                import time
                                time.sleep(5)
                            else:
                                st.error("❌ Daily Quota Exceeded. Please try again tomorrow or switch to a paid API key.")
                        else:
                            st.error(f"AI Error: {e}")
                            break
