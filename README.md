# Institutional AI Equity Analyst

An automated, institutional-grade equity research agent powered by **Google Gemini 1.5 Pro**. This tool performs deep fundamental and technical analysis on global stocks using a strict **GARP (Growth at a Reasonable Price)** framework.

It acts as a force multiplier for financial analysts by automating data collection, ratio calculation, and qualitative risk assessment.

Link: https://institutional-financial-analyst-ai-chinmaypshetty.streamlit.app

## Key Features

* **Global Ticker Resolution:** Smartly identifies companies across exchanges (e.g., "Tata Steel" -> `TATASTEEL.NS`, "CommBank" -> `CBA.AX`).
* **Strict GARP Screening:** Automatically filters stocks based on:
    * **Growth:** 3/5/7-Year CAGR for Sales & EPS (>15-20%).
    * **Valuation:** PEG Ratio < 1.0 (or <1.5 for high ROE).
    * **Efficiency:** ROE > 15%.
* **Forensic "Quality" Checks:** detects "fake profits" by comparing **Operating Cash Flow vs. Net Income**.
* **Technical Trend Detection:** Warns against "falling knives" by checking price against the **200-Day Moving Average**.
* **Qualitative Risk Layer:** Scans live news headlines for fraud, lawsuits, or management scandals using **DuckDuckGo Search**.
* **Self-Healing Architecture:** Automatically handles API errors and selects the optimal AI model to ensure 99.9% uptime.

## Tech Stack

* **Frontend:** Streamlit (Python)
* **AI Logic:** Google Gemini 1.5 Pro & Flash (via Google Generative AI API)
* **Market Data:** Yahoo Finance (`yfinance`)
* **News Intelligence:** DuckDuckGo Search (`duckduckgo-search`)
* **Data Processing:** Pandas, NumPy

## How It Works

1.  **User Input:** Enter any company name (e.g., "Nvidia", "Reliance").
2.  **Smart Resolution:** The AI resolves the query to the correct ticker symbol.
3.  **Data Ingestion:** The engine pulls real-time financials, cash flow statements, and price history.
4.  **Metric Repair:** If data is missing (common with non-US stocks), the system manually calculates ratios like ROE and PEG from raw statements.
5.  **AI Synthesis:** The LLM acts as a "Senior Portfolio Manager," reviewing the quantitative scorecard and news sentiment to write a professional investment memo.

## Disclaimer

This tool is for **informational purposes only** and does not constitute financial advice. Always do your own due diligence before investing. The AI output is based on data available at the time of analysis.

---
*Built by Chinmay Shetty*
