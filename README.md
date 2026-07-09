<p align="center">
  <a href="README.zh.md">[CN] Chinese</a>
  |
  <a href="README.md">[EN] English</a>
</p>

# Trading Signal Bot

Telegram bot for US stock intraday signal analysis. Multi-dimensional scoring for entry timing assessment.

[GitHub](https://github.com/caozh502/trading-t-bot)

## Commands

| Command | Description |
|---------|-------------|
| `/t <ticker>` | Analyze a single stock |
| `/watchlist` | Scan all watchlist stocks |
| `/spy` | Market sentiment (SPY+QQQ) |
| `/help` | Help information |

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Bot Token
```bash
cp .env.example .env
# Edit .env, fill in your TG_BOT_TOKEN
```
Create a bot via [@BotFather](https://t.me/BotFather) to get a token.

### 3. Run
```bash
python bot.py
```

### 4. Local test (no Telegram needed)
```bash
python run.py AAPL
python run.py NVDA
```

## Scoring Dimensions

| Dimension | Weight | Description |
|-----------|--------|-------------|
| VWAP Position | 25% | Price relative to VWAP |
| Short-term Trend | 25% | 5EMA/20EMA bullish/bearish alignment |
| RSI(14) | 20% | Overbought/oversold |
| Volume | 15% | Volume confirmation |
| Price Level | 15% | Near support/resistance |

**Score range**: -1.0 ~ +1.0
- >= +0.5 -> Good entry
- +0.2 ~ +0.5 -> Cautious entry
- -0.2 ~ +0.2 -> Wait and see
- <= -0.5 -> Strongly avoid

## Customization

Edit `config.py`:
- `DEFAULT_WATCHLIST` - your watchlist
- `WEIGHTS` - dimension weights
- `SIGNAL_THRESHOLDS` - signal thresholds

---
_Trading Signal Bot - [GitHub](https://github.com/caozh502/trading-t-bot)_
