"""
Quick CLI test without Telegram.
Usage: python run.py [TICKER]
"""
import sys
from analyzer import analyze_ticker, format_result

if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(f"\n🔍 Analyzing {ticker.upper()}...\n")
    result = analyze_ticker(ticker.upper())
    print(format_result(result, verbose=True))
    print(f"\n⏱ Analysis complete.")
