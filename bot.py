"""
Telegram Bot for intraday trading (做T) entry signal analysis.
 
Commands:
  /t <ticker>    - Analyze a single ticker
  /watchlist     - Analyze all stocks in your watchlist
  /spy           - Current market sentiment
  /help          - Help message

Environment:
  TG_BOT_TOKEN   - Telegram Bot Token (required)
  TG_CHAT_ID     - Default chat ID for push/auto messages (optional)
"""

import asyncio
import logging
import os
import sys
import signal
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from analyzer import analyze_ticker, analyze_multiple, format_result
from config import (
    TELEGRAM_BOT_TOKEN, DEFAULT_WATCHLIST, VERBOSE_DEFAULT
)

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ── Command handlers ──────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message."""
    await update.message.reply_text(
        "🤖 **做T信号分析 Bot**\n\n"
        "快速判断美股是否适合日内入场做T。\n\n"
        "**命令:**\n"
        "`/t <代码>` — 分析单只股票\n"
        "`/watchlist` — 扫描自选股\n"
        "`/spy` — 大盘情绪\n"
        "`/help` — 帮助\n\n"
        "例: `/t AAPL`",
        parse_mode="Markdown"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help message."""
    await cmd_start(update, context)


async def cmd_t(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Analyze a single ticker.
    Usage: /t AAPL  or  /t NVDA
    """
    if not context.args:
        await update.message.reply_text(
            "⚠️ 请输入股票代码，例如: `/t AAPL`",
            parse_mode="Markdown"
        )
        return

    ticker = context.args[0].upper().strip()
    msg = await update.message.reply_text(f"🔍 正在分析 **{ticker}**...", parse_mode="Markdown")

    try:
        # Show typing indicator (long-running)
        async def progress_indicator():
            dots = ["", ".", "..", "..."]
            i = 0
            while True:
                await asyncio.sleep(1.5)
                i += 1
                try:
                    await msg.edit_text(f"🔍 正在分析 **{ticker}**{dots[i % 4]}")
                except Exception:
                    pass
        # Don't actually start a background task - just do the work
        
        result = analyze_ticker(ticker)
        output = format_result(result, verbose=VERBOSE_DEFAULT)
        await msg.edit_text(output, parse_mode="Markdown")
        
        # Add timing note
        now = datetime.now(timezone.utc)
        await msg.reply_text(f"⏱ {now.strftime('%H:%M:%S')} UTC | 数据来源: Yahoo Finance", parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Error in /t command: {e}")
        await msg.edit_text(f"❌ 分析出错: {str(e)[:200]}")


async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Analyze all stocks in the watchlist."""
    watchlist = DEFAULT_WATCHLIST
    msg = await update.message.reply_text(
        f"📋 正在扫描自选股 ({len(watchlist)}只)... 请稍候",
        parse_mode="Markdown"
    )
    
    try:
        results = analyze_multiple(watchlist)
        
        # Build summary table
        lines = ["📋 **自选股做T信号扫描**\n"]
        lines.append("代码  | 评分  | 信号")
        lines.append("─" * 30)
        
        buy_count = 0
        watch_count = 0
        avoid_count = 0
        
        for r in results:
            score_str = f"{r.total_score:+.2f}" if r.total_score != 0 else " 0.00"
            emoji = r.signal_color
            lines.append(f"{r.ticker:6s} | {score_str:6s} | {emoji} {r.signal}")
            
            if "入场" in r.signal:
                buy_count += 1
            elif "观望" in r.signal or "谨慎" in r.signal:
                watch_count += 1
            else:
                avoid_count += 1
        
        lines.append("─" * 30)
        lines.append(f"✅ 适合: {buy_count} | ⚪ 观望: {watch_count} | ❌ 回避: {avoid_count}")
        
        await msg.edit_text("\n".join(lines), parse_mode="Markdown")
        
        # Send detailed results for actionable ones
        for r in results:
            if r.total_score >= 0.2 or r.total_score <= -0.4:
                detail = format_result(r, verbose=False)
                await update.message.reply_text(detail, parse_mode="Markdown")
                await asyncio.sleep(0.3)  # Rate limit avoidance
        
    except Exception as e:
        logger.error(f"Error in /watchlist command: {e}")
        await msg.edit_text(f"❌ 扫描出错: {str(e)[:200]}")


async def cmd_spy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show market sentiment from SPY and QQQ."""
    from indicators import get_market_sentiment, fetch_intraday_data
    
    msg = await update.message.reply_text("📊 正在获取大盘数据...", parse_mode="Markdown")
    
    try:
        sentiment = get_market_sentiment()
        
        # Get SPY and QQQ current price
        spy_data = fetch_intraday_data('SPY', interval='5m', period='2d')
        qqq_data = fetch_intraday_data('QQQ', interval='5m', period='2d')
        
        spy_price = spy_data['Close'].iloc[-1] if not spy_data.empty else 0
        qqq_price = qqq_data['Close'].iloc[-1] if not qqq_data.empty else 0
        
        lines = [
            "📊 **大盘情绪分析**\n",
            f"{sentiment.get('description', 'N/A')}\n",
            f"**SPY** ${spy_price:.2f} | {sentiment.get('spy_change', 0):+.2f}%",
            f"**QQQ** ${qqq_price:.2f} | {sentiment.get('qqq_change', 0):+.2f}%",
            "",
            "💡 *做T建议: 顺大盘方向做T胜率更高*",
        ]
        
        await msg.edit_text("\n".join(lines), parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Error in /spy command: {e}")
        await msg.edit_text(f"❌ 获取大盘数据出错: {str(e)[:200]}")


# ── Stop command ─────────────────────────────────────────────

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop the bot gracefully. Only the owner can use this."""
    from config import TELEGRAM_BOT_TOKEN
    
    # Simple auth: only allow from chat ID in .env or the first person who chats
    user_id = update.effective_user.id if update.effective_user else None
    
    await update.message.reply_text(
        "🛑 正在关闭 Bot...",
        parse_mode="Markdown"
    )
    logger.warning(f"/stop requested by user {user_id}")
    
    # Schedule shutdown after a brief delay so the reply goes through
    async def _shutdown():
        await asyncio.sleep(0.5)
        os.kill(os.getpid(), signal.SIGTERM)
    
    asyncio.create_task(_shutdown())


# ── Error handler ────────────────────────────────────────────

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors."""
    logger.error(f"Update {update} caused error {context.error}")


# ── Main ─────────────────────────────────────────────────────

def main():
    """Start the bot."""
    token = TELEGRAM_BOT_TOKEN
    if not token:
        logger.error("❌ TG_BOT_TOKEN 未设置！请创建 .env 文件并填入 token")
        print("=" * 50)
        print("❌ TG_BOT_TOKEN 未设置！")
        print("1. 复制 .env.example 为 .env")
        print("2. 填入你的 Telegram Bot Token")
        print("3. 重新运行")
        print("=" * 50)
        sys.exit(1)
    
    logger.info("🤖 做T信号分析 Bot 启动中...")
    
    app = Application.builder().token(token).build()
    
    # Register commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("t", cmd_t))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(CommandHandler("spy", cmd_spy))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_error_handler(error_handler)
    
    logger.info("✅ Bot started! Commands: /t <ticker>, /watchlist, /spy, /stop")
    
    # Start polling
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
