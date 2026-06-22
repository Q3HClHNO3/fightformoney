from __future__ import annotations

import json
import math
import statistics
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


REPORT_PATH = Path("daily-brief.md")
TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class Asset:
    name: str
    symbol: str
    group: str


ASSETS = [
    Asset("S&P 500 ETF", "SPY", "US equities"),
    Asset("Nasdaq 100 ETF", "QQQ", "US equities"),
    Asset("Dow Jones ETF", "DIA", "US equities"),
    Asset("US 20Y+ Treasury ETF", "TLT", "Rates"),
    Asset("Gold ETF", "GLD", "Commodities"),
    Asset("Oil ETF", "USO", "Commodities"),
    Asset("China A-shares ETF", "ASHR", "China"),
    Asset("China Internet ETF", "KWEB", "China"),
]


def fetch_text(url: str, timeout: int = 20) -> str:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 daily-investment-report/1.0"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 + attempt)
    raise RuntimeError(f"request failed after retries: {last_error}")


def fetch_yahoo_history(symbol: str) -> list[dict[str, object]]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=3mo&interval=1d"
    data = json.loads(fetch_text(url))
    result = data.get("chart", {}).get("result") or []
    if not result:
        raise RuntimeError("no chart result returned")

    chart = result[0]
    timestamps = chart.get("timestamp") or []
    quote = (chart.get("indicators", {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    rows: list[dict[str, object]] = []
    for timestamp, close in zip(timestamps, closes):
        if close is None:
            continue
        rows.append(
            {
                "Date": datetime.fromtimestamp(int(timestamp), TZ).strftime("%Y-%m-%d"),
                "Close": float(close),
            }
        )
    if len(rows) < 2:
        raise RuntimeError("not enough price rows returned")
    return rows


def pct(current: float, previous: float) -> float:
    if previous == 0:
        return math.nan
    return (current / previous - 1) * 100


def moving_average(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return statistics.fmean(values[-window:])


def summarize_asset(asset: Asset) -> dict[str, object]:
    rows = fetch_yahoo_history(asset.symbol)
    closes = [float(row["Close"]) for row in rows]
    latest = rows[-1]
    close = closes[-1]
    previous = closes[-2] if len(closes) >= 2 else close
    ma20 = moving_average(closes, 20)
    ma60 = moving_average(closes, 60)
    return {
        "name": asset.name,
        "symbol": asset.symbol,
        "group": asset.group,
        "date": latest["Date"],
        "close": close,
        "day_change": pct(close, previous),
        "month_change": pct(close, closes[-22]) if len(closes) >= 22 else math.nan,
        "ma20_gap": pct(close, ma20) if ma20 else math.nan,
        "ma60_gap": pct(close, ma60) if ma60 else math.nan,
    }


def fetch_crypto() -> dict[str, object] | None:
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true"
    )
    try:
        data = json.loads(fetch_text(url))
    except Exception:
        return None
    return data


def fmt_pct(value: object) -> str:
    if not isinstance(value, (int, float)) or math.isnan(value):
        return "n/a"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def fmt_price(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{value:,.2f}"


def market_tone(rows: list[dict[str, object]]) -> str:
    risk_assets = [row for row in rows if row["symbol"] in {"SPY", "QQQ", "KWEB", "ASHR"}]
    positive = sum(1 for row in risk_assets if isinstance(row["day_change"], float) and row["day_change"] > 0)
    above_ma20 = sum(1 for row in risk_assets if isinstance(row["ma20_gap"], float) and row["ma20_gap"] > 0)
    if positive >= 3 and above_ma20 >= 3:
        return "风险偏好偏积极：多数跟踪的权益资产上涨并站上20日均线。"
    if positive <= 1 and above_ma20 <= 1:
        return "风险偏好偏防御：多数跟踪的权益资产走弱并低于20日均线。"
    return "风险偏好分化：跟踪资产之间的强弱表现不一致。"


def build_report() -> str:
    now = datetime.now(TZ)
    rows: list[dict[str, object]] = []
    errors: list[str] = []
    for asset in ASSETS:
        try:
            rows.append(summarize_asset(asset))
        except Exception as exc:
            errors.append(f"- {asset.name} ({asset.symbol}): {exc}")

    crypto = fetch_crypto()
    latest_dates = sorted({str(row["date"]) for row in rows})
    data_date = latest_dates[-1] if latest_dates else "n/a"

    lines = [
        f"# 每日投资分析报告 - {now:%Y-%m-%d}",
        "",
        "自动生成于 GitHub Actions。数据来自公开行情接口，可能存在延迟；仅供研究参考，不构成投资建议。",
        "",
        "## 市场总览",
        "",
        f"- 报告生成时间：{now:%Y-%m-%d %H:%M:%S} 北京时间",
        f"- 最新行情日期：{data_date}",
    ]
    if rows:
        lines.append(f"- 市场状态：{market_tone(rows)}")
    lines.extend(["", "## 主要资产跟踪", ""])
    lines.append("| 资产 | 收盘价 | 日涨跌 | 近1个月 | 距20日均线 | 距60日均线 |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for row in rows:
        lines.append(
            "| {name} | {close} | {day} | {month} | {ma20} | {ma60} |".format(
                name=row["name"],
                close=fmt_price(row["close"]),
                day=fmt_pct(row["day_change"]),
                month=fmt_pct(row["month_change"]),
                ma20=fmt_pct(row["ma20_gap"]),
                ma60=fmt_pct(row["ma60_gap"]),
            )
        )

    lines.extend(["", "## 结构性观察", ""])
    if rows:
        strongest = max(rows, key=lambda row: row["day_change"] if isinstance(row["day_change"], float) else -999)
        weakest = min(rows, key=lambda row: row["day_change"] if isinstance(row["day_change"], float) else 999)
        lines.append(f"- 当日相对强势：{strongest['name']}，日涨跌 {fmt_pct(strongest['day_change'])}。")
        lines.append(f"- 当日相对弱势：{weakest['name']}，日涨跌 {fmt_pct(weakest['day_change'])}。")
        lines.append("- 观察重点：权益资产与长债、黄金的相对表现，可用于判断风险偏好是否扩散或收缩。")
    else:
        lines.append("- 今日未能取得行情数据，请查看 GitHub Actions 日志。")

    lines.extend(["", "## 加密资产", ""])
    if crypto:
        for coin_id, label in (("bitcoin", "Bitcoin"), ("ethereum", "Ethereum")):
            coin = crypto.get(coin_id, {})
            lines.append(
                f"- {label}: ${fmt_price(coin.get('usd'))}, 24h {fmt_pct(coin.get('usd_24h_change'))}"
            )
    else:
        lines.append("- 加密资产数据暂时不可用。")

    lines.extend(["", "## 明日关注", ""])
    lines.append("- 关注主要股指是否继续站上短期均线。")
    lines.append("- 关注长债和黄金是否同步走强；若同步走强，通常意味着避险需求升温。")
    lines.append("- 关注中国相关 ETF 是否延续相对强弱变化。")

    if errors:
        lines.extend(["", "## 数据异常", ""])
        lines.extend(errors)

    return "\n".join(lines).strip() + "\n"


def main() -> None:
    REPORT_PATH.write_text(build_report(), encoding="utf-8")
    print(f"Generated investment report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
