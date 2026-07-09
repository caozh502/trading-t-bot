# 美股做T信号分析 Bot

Telegram Bot 用于快速判断美股是否适合日内做T入场。

## 功能

| 命令 | 说明 |
|------|------|
| `/t <代码>` | 分析单只股票 |
| `/watchlist` | 扫描所有自选股 |
| `/spy` | 大盘情绪 (SPY+QQQ) |
| `/help` | 帮助信息 |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 Bot Token

```bash
cp .env.example .env
# 编辑 .env，填入你的 TG_BOT_TOKEN
```

从 [@BotFather](https://t.me/BotFather) 创建 bot 获取 token。

### 3. 运行

```bash
python bot.py
```

### 4. 本地测试（不用 Telegram）

```bash
python run.py AAPL
python run.py NVDA
```

## 评分维度

| 维度 | 权重 | 说明 |
|------|------|------|
| VWAP位置 | 25% | 价格相对VWAP的位置 |
| 短期趋势 | 25% | 5EMA/20EMA 多空排列 |
| RSI(14) | 20% | 超买超卖判断 |
| 成交量 | 15% | 放量/缩量确认 |
| 价位位置 | 15% | 支撑阻力附近 |

**评分逻辑**: -1.0 ~ +1.0
- ≥ +0.5 → ✅ 适合入场
- +0.2 ~ +0.5 → 🟡 谨慎入场
- -0.2 ~ +0.2 → ⚪ 观望
- ≤ -0.5 → 🔴 强烈回避

## 自定义

编辑 `config.py`:
- `DEFAULT_WATCHLIST` — 你的自选股
- `WEIGHTS` — 各维度权重
- `SIGNAL_THRESHOLDS` — 信号阈值
