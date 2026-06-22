from __future__ import annotations

import json
import math
import statistics
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


REPORT_PATH = Path("daily-brief.md")
TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class Instrument:
    label: str
    symbol: str
    source: str = "Yahoo Finance"


@dataclass(frozen=True)
class Snapshot:
    label: str
    symbol: str
    price: float | None
    day_change: float | None
    month_change: float | None
    ma20_gap: float | None
    ma60_gap: float | None
    date: str
    source: str
    error: str | None = None


TRACKED = [
    Instrument("上证指数", "000001.SS"),
    Instrument("沪深300", "000300.SS"),
    Instrument("创业板指", "399006.SZ"),
    Instrument("恒生指数", "^HSI"),
    Instrument("日经225", "^N225"),
    Instrument("纳斯达克100", "^NDX"),
    Instrument("纳斯达克综合", "^IXIC"),
    Instrument("标普500", "^GSPC"),
    Instrument("纳指期货", "NQ=F"),
    Instrument("标普期货", "ES=F"),
    Instrument("10年美债收益率", "^TNX"),
    Instrument("美元指数", "DX-Y.NYB"),
    Instrument("美元/离岸人民币", "CNH=X"),
    Instrument("铜期货", "HG=F"),
    Instrument("铝期货", "ALI=F"),
    Instrument("黄金期货", "GC=F"),
    Instrument("WTI原油", "CL=F"),
    Instrument("锂电池ETF代理", "LIT"),
    Instrument("英伟达", "NVDA"),
    Instrument("微软", "MSFT"),
    Instrument("苹果", "AAPL"),
    Instrument("博通", "AVGO"),
    Instrument("亚马逊", "AMZN"),
    Instrument("Meta", "META"),
    Instrument("特斯拉", "TSLA"),
    Instrument("中际旭创", "300308.SZ"),
    Instrument("新易盛", "300502.SZ"),
    Instrument("天孚通信", "300394.SZ"),
    Instrument("工业富联", "601138.SS"),
    Instrument("中芯国际A", "688981.SS"),
    Instrument("北方华创", "002371.SZ"),
    Instrument("绿色电力ETF代理", "562550.SS"),
    Instrument("阳光电源", "300274.SZ"),
    Instrument("宁德时代", "300750.SZ"),
    Instrument("紫金矿业A", "601899.SS"),
]


SECTION_ASSETS = {
    "半导体": ["中芯国际A", "北方华创"],
    "CPO": ["中际旭创", "新易盛", "天孚通信"],
    "AI通信映射": ["工业富联", "中际旭创", "新易盛"],
    "绿色电力": ["绿色电力ETF代理", "阳光电源", "沪深300"],
    "中证电池": ["宁德时代", "锂电池ETF代理"],
    "有色金属": ["紫金矿业A", "铜期货", "铝期货"],
    "纳斯达克": ["纳斯达克100", "纳指期货", "英伟达", "微软", "博通", "苹果"],
    "亚太和全球精选股票": ["恒生指数", "日经225", "标普500", "纳斯达克100"],
    "防守资产": ["沪深300", "10年美债收益率", "黄金期货", "美元/离岸人民币"],
}


HOLDING_MAP = [
    ("半导体", "中欧半导体产业股票", "进攻分组"),
    ("CPO", "嘉实信息产业股票C", "进攻分组；本报告按 CPO / 光通信 / 光模块 / 海外AI资本开支映射理解"),
    ("AI通信映射", "富国中证通信设备", "进攻分组；通信外壳下的光通信/IDC互联/交换机/运营商混合篮子"),
    ("纳斯达克", "建信纳斯达克100 + 大成纳斯达克100 + 景顺长城纳斯达克科技市值加权", "进攻分组"),
    ("卫星分组", "南方亚太精选ETF + 广发全球精选股票", "全球/亚太权益敞口"),
    ("防守资产", "博时恒乐债券C + 华安黄金ETF联接I + 中金沪深300指数", "防守分组稳定器 + 防守权益底盘"),
    ("绿色电力", "华夏中证绿色电力ETF", "防守分组中的主题防守资产 / 稳健权益资产"),
]


SOURCE_LINKS = {
    "Yahoo Finance": "https://finance.yahoo.com/",
    "CoinGecko": "https://www.coingecko.com/",
}


def fetch_text(url: str, timeout: int = 10) -> str:
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 investment-brief/2.0"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except Exception as exc:
            last_error = exc
            if attempt < 1:
                time.sleep(1.0)
    raise RuntimeError(f"request failed after retries: {last_error}")


def fetch_chart(symbol: str) -> list[dict[str, object]]:
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=3mo&interval=1d"
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
        rows.append({"date": datetime.fromtimestamp(int(timestamp), TZ).strftime("%Y-%m-%d"), "close": float(close)})
    if len(rows) < 2:
        raise RuntimeError("not enough price rows returned")
    return rows


def pct(current: float, previous: float) -> float:
    if previous == 0:
        return math.nan
    return (current / previous - 1) * 100


def ma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return statistics.fmean(values[-window:])


def snapshot(inst: Instrument) -> Snapshot:
    try:
        rows = fetch_chart(inst.symbol)
        closes = [float(row["close"]) for row in rows]
        latest = rows[-1]
        close = closes[-1]
        ma20 = ma(closes, 20)
        ma60 = ma(closes, 60)
        return Snapshot(
            label=inst.label,
            symbol=inst.symbol,
            price=close,
            day_change=pct(close, closes[-2]),
            month_change=pct(close, closes[-22]) if len(closes) >= 22 else None,
            ma20_gap=pct(close, ma20) if ma20 else None,
            ma60_gap=pct(close, ma60) if ma60 else None,
            date=str(latest["date"]),
            source=inst.source,
        )
    except Exception as exc:
        return Snapshot(inst.label, inst.symbol, None, None, None, None, None, "n/a", inst.source, str(exc))


def fetch_crypto() -> dict[str, dict[str, float]]:
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true"
    )
    try:
        return json.loads(fetch_text(url))
    except Exception:
        return {}


def fmt_pct(value: float | None) -> str:
    if value is None or math.isnan(value):
        return "n/a"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def fmt_num(value: float | None) -> str:
    if value is None or math.isnan(value):
        return "n/a"
    return f"{value:,.2f}"


def row(s: Snapshot) -> str:
    return f"{s.label}({s.symbol}) {fmt_num(s.price)} / 日涨跌 {fmt_pct(s.day_change)} / 近1月 {fmt_pct(s.month_change)} / 日期 {s.date}"


def avg(values: list[float | None]) -> float | None:
    clean = [v for v in values if isinstance(v, float) and not math.isnan(v)]
    if not clean:
        return None
    return statistics.fmean(clean)


def by_label(snaps: list[Snapshot]) -> dict[str, Snapshot]:
    return {s.label: s for s in snaps}


def section_signal(name: str, data: dict[str, Snapshot]) -> tuple[str, str, str]:
    assets = [data[label] for label in SECTION_ASSETS[name] if label in data]
    valid = [s for s in assets if s.price is not None]
    if len(valid) < max(1, math.ceil(len(assets) / 2)):
        return "🟡", "继续观望/等待确认", "核心代理数据不足，不能给出激进信号"
    day = avg([s.day_change for s in valid])
    month = avg([s.month_change for s in valid])
    ma20 = avg([s.ma20_gap for s in valid])
    if day is not None and day >= 1.2 and ma20 is not None and ma20 > 0:
        return "🟢", "强烈建议加仓", "趋势与当日动量同时转强"
    if ma20 is not None and ma20 > 0 and (day is None or day > -1.0):
        return "🟩", "分批参与/逢低加仓", "价格保持在20日均线附近或上方"
    if day is not None and day <= -2.0 and ma20 is not None and ma20 < -2.0:
        return "🟠", "阶段减持/降低仓位", "短线跌幅和趋势位置同时走弱"
    if month is not None and month < -8 and ma20 is not None and ma20 < -4:
        return "🔴", "强烈减仓/回避", "中短期趋势破坏明显"
    return "🟡", "继续观望/等待确认", "信号分化，缺少高胜率确认"


def catalyst_for(name: str) -> str:
    mapping = {
        "半导体": "国产算力、先进封装、设备国产替代和AI端侧芯片预期。",
        "CPO": "海外AI资本开支、800G/1.6T光模块、数据中心互联需求。",
        "AI通信映射": "IDC互联、交换机、运营商云网、光通信链条共同驱动；不是纯传统5G基站。",
        "绿色电力": "AI数据中心耗电增长、电力运营现金流、绿电交易与公用事业政策红利。",
        "中证电池": "储能、电动车需求、锂价边际变化和全球电池链风险偏好。",
        "有色金属": "铜铝供需、美元方向、全球制造业预期和通胀交易。",
        "纳斯达克": "美股AI核心权重、云资本开支、美债收益率和美元流动性。",
        "亚太和全球精选股票": "亚太股市风险偏好、美元流动性、港股/日股/美股联动。",
        "防守资产": "债券久期、黄金避险、沪深300防守权益底盘和人民币波动。",
    }
    return mapping.get(name, "暂无明确催化，按价格和宏观信号跟踪。")


def macro_read(data: dict[str, Snapshot]) -> list[str]:
    tnx = data.get("10年美债收益率")
    dxy = data.get("美元指数")
    cnh = data.get("美元/离岸人民币")
    ndx = data.get("纳斯达克100")
    hs300 = data.get("沪深300")
    lines = []
    if tnx:
        lines.append(f"- 美债：{row(tnx)}；收益率上行通常压制成长股估值，下行利好纳斯达克和A股科技。")
    if dxy:
        lines.append(f"- 美元指数：{row(dxy)}；美元走强时，全球风险资产和人民币资产承压概率上升。")
    if cnh:
        lines.append(f"- 人民币：{row(cnh)}；美元/离岸人民币上行表示人民币偏弱。")
    if ndx and hs300:
        lines.append(f"- 股指对照：{row(ndx)}；{row(hs300)}。")
    return lines


def commodity_read(data: dict[str, Snapshot]) -> list[str]:
    labels = ["铜期货", "铝期货", "黄金期货", "WTI原油", "锂电池ETF代理"]
    lines = [f"- {row(data[label])}" for label in labels if label in data]
    lines.append("- 锂相关价格：若直接锂盐报价不可得，使用 LIT 锂电池ETF作为全球锂电链风险偏好代理，需谨慎解读。")
    return lines


def section_block(name: str, holding: str, data: dict[str, Snapshot]) -> list[str]:
    emoji, signal, reason = section_signal(name, data)
    assets = [data[label] for label in SECTION_ASSETS[name] if label in data]
    support = [row(s) for s in assets[:5]]
    if name == "CPO":
        logic = "嘉实信息产业股票C在本报告中按CPO/光通信/光模块/海外AI资本开支映射理解，不按泛信息产业、软件或信创处理。"
    elif name == "AI通信映射":
        logic = "富国中证通信设备不是纯CPO，也不是纯传统5G基站；按AI通信映射资产看，覆盖光通信、IDC互联、交换机、运营商等混合篮子。"
    elif name == "绿色电力":
        logic = "绿色电力归入防守分组中的主题防守资产，买入逻辑来自AI电力需求、政策红利和公用事业属性，不按高弹性进攻主线处理。"
    elif name == "防守资产":
        logic = "防守分组不是纯现金，而是非进攻、偏稳的账户压舱仓；余额宝等现金不写入基金分组分析。"
    else:
        logic = f"{holding}按本板块真实持仓逻辑分析。"
    return [
        f"### {emoji} {name}：{signal}",
        f"- 结论：{signal}。{reason}。",
        f"- 对应持仓：{holding}",
        f"- 操作建议：短线按信号执行，中期保留核心观察仓；不追单日急涨，优先等回踩或确认突破。",
        f"- 支撑数据/逻辑：{logic}",
        f"- 行业催化/新闻线索：{catalyst_for(name)}",
        *[f"  - {item}" for item in support],
        "- 触发加仓条件：板块代表资产收盘站上20日均线；海外AI链或A股核心标的放量走强；人民币和美债环境不继续恶化。",
        "- 触发减仓条件：代表资产跌破20日均线且连续弱于大盘；美债收益率/美元同步上行；板块利好兑现后放量滞涨。",
        "- 风险点：公开行情延迟；基金净值与板块代理资产存在偏差；单日14点信号可能被尾盘反转。",
        "",
    ]


def build_report() -> str:
    now = datetime.now(TZ)
    snaps: list[Snapshot] = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(snapshot, inst): inst for inst in TRACKED}
        for future in as_completed(futures):
            snaps.append(future.result())
    data = by_label(snaps)
    crypto = fetch_crypto()
    errors = [s for s in snaps if s.error]
    latest_dates = sorted({s.date for s in snaps if s.date != "n/a"})
    data_time = latest_dates[-1] if latest_dates else "n/a"

    section_names = [
        ("半导体", "中欧半导体产业股票"),
        ("CPO", "嘉实信息产业股票C"),
        ("AI通信映射", "富国中证通信设备"),
        ("绿色电力", "华夏中证绿色电力ETF"),
        ("中证电池", "用户关注主题：中证电池"),
        ("有色金属", "用户关注主题：有色金属"),
        ("纳斯达克", "建信/大成/景顺长城纳指相关基金"),
        ("亚太和全球精选股票", "南方亚太精选ETF + 广发全球精选股票"),
        ("防守资产", "博时恒乐债券C + 华安黄金ETF联接I + 中金沪深300指数"),
    ]
    signals = [(name, *section_signal(name, data)) for name, _ in section_names]
    add_list = [f"{emoji} {name}：{signal}" for name, emoji, signal, _ in signals if emoji in {"🟢", "🟩"}]
    reduce_list = [f"{emoji} {name}：{signal}" for name, emoji, signal, _ in signals if emoji in {"🟠", "🔴"}]
    wait_list = [f"{emoji} {name}：{signal}" for name, emoji, signal, _ in signals if emoji == "🟡"]

    attack = [s for s in signals if s[0] in {"半导体", "CPO", "AI通信映射", "纳斯达克"}]
    defense = [s for s in signals if s[0] in {"绿色电力", "防守资产"}]
    satellite = [s for s in signals if s[0] == "亚太和全球精选股票"]

    lines = [
        f"# 每日14点A股科技与全球流动性投资简报 - {now:%Y-%m-%d}",
        "",
        f"> 数据时间戳：北京时间 {now:%Y-%m-%d %H:%M:%S}；行情多为最近可得交易日/过去24小时数据，A股盘中14点附近数据若接口不可得则使用最近可得数据谨慎推断。",
        "",
        "## 1）一句话总览",
        "",
        f"- 今日核心判断：进攻资产以AI链强弱为主线，防守资产继续承担压舱功能，卫星分组只做全球/亚太分散，不把它误写成A股科技。",
        f"- 今日最重要的执行点：{'; '.join(add_list[:3]) if add_list else '暂无明确加仓板块'}；{'; '.join(reduce_list[:2]) if reduce_list else '暂无强制减仓板块'}。",
        "",
        "## 2）今日加仓、减仓信号明确说明",
        "",
        "### 加仓/参与",
        *(f"- {item}" for item in (add_list or ["🟡 暂无强烈加仓信号：等待价格、成交量和全球流动性确认。"])),
        "",
        "### 观望/等待确认",
        *(f"- {item}" for item in (wait_list or ["无。"])),
        "",
        "### 减仓/回避",
        *(f"- {item}" for item in (reduce_list or ["🟡 暂无强烈减仓信号：若尾盘转弱或海外期货走低，再降低进攻仓。"])),
        "",
        "### 短线 vs 中期",
        "- 短线交易信号：看14点附近板块强弱、20日均线位置、海外期货和人民币方向。",
        "- 中期配置观点：AI算力链和纳斯达克仍是进攻核心；债券、黄金、沪深300、绿色电力是防守组压舱仓。",
        "- 仓位节奏：加仓只做分批；若同一天美元、美债、人民币同时不利，进攻分组不追高。",
        "",
        "## 3）与我持仓的对应关系速览",
        "",
        *(f"- {theme} = {fund}；{note}" for theme, fund, note in HOLDING_MAP),
        "",
        "## 4）三分组视角速览：进攻 / 防守 / 卫星",
        "",
        f"- 今天进攻分组该怎么做：{'; '.join(f'{e}{n}={sig}' for n, e, sig, _ in attack)}。优先处理半导体、CPO、AI通信映射、纳斯达克，不把嘉实信息产业C当泛信息产业写。",
        f"- 今天防守分组该怎么做：{'; '.join(f'{e}{n}={sig}' for n, e, sig, _ in defense)}。防守分组不是现金，现金/余额宝不纳入基金分组分析。",
        f"- 今天卫星分组该怎么做：{'; '.join(f'{e}{n}={sig}' for n, e, sig, _ in satellite)}。南方亚太精选ETF和广发全球精选股票按全球/亚太敞口看。",
        "",
        "## 5）全球流动性与宏观市场数据",
        "",
        *macro_read(data),
        f"- 纳斯达克关键权重：{'; '.join(row(data[x]) for x in ['英伟达', '微软', '苹果', '博通', '亚马逊', 'Meta', '特斯拉'] if x in data)}。",
        "",
        "## 6）大宗商品与汇率变化",
        "",
        *commodity_read(data),
    ]

    if crypto:
        lines.extend(
            [
                f"- Bitcoin：${fmt_num(crypto.get('bitcoin', {}).get('usd'))} / 24h {fmt_pct(crypto.get('bitcoin', {}).get('usd_24h_change'))}，来源 CoinGecko。",
                f"- Ethereum：${fmt_num(crypto.get('ethereum', {}).get('usd'))} / 24h {fmt_pct(crypto.get('ethereum', {}).get('usd_24h_change'))}，来源 CoinGecko。",
            ]
        )

    lines.extend(["", "## 7）逐板块分点分析", ""])
    for name, holding in section_names:
        lines.extend(section_block(name, holding, data))

    lines.extend(
        [
            "## 8）今日观察清单",
            "",
            "- 14点后A股科技是否继续放量，还是冲高回落。",
            "- CPO三只代理：中际旭创、新易盛、天孚通信是否同步强于创业板。",
            "- 半导体是否由个股行情扩散到设备、制造、材料。",
            "- 纳指期货和美债收益率是否同向不利：若纳指期货跌、美债收益率升，进攻仓不追。",
            "- 人民币是否继续走弱；若美元/离岸人民币明显上行，降低A股进攻加仓力度。",
            "- 铜、铝、黄金、原油是否给出通胀或避险信号。",
            "",
            "## 9）风险提示",
            "",
            "- 本报告是自动化研究简报，不构成投资建议。",
            "- 基金净值和实时板块代理资产不完全一致，尤其是QDII和跨市场基金有时差。",
            "- GitHub Actions 14点运行可能有几分钟延迟；公开行情接口可能延迟或缺失。",
            "- 盘中信号可能被尾盘、隔夜美股、政策消息反转。",
            "- 单日信号服务于仓位节奏，中期配置仍需结合你的总仓位、风险承受能力和现金安排。",
            "",
            "## 10）数据来源与时间戳",
            "",
            f"- 报告生成时间：北京时间 {now:%Y-%m-%d %H:%M:%S}",
            f"- 最近可得市场数据日期：{data_time}",
            f"- Yahoo Finance：{SOURCE_LINKS['Yahoo Finance']}",
            f"- CoinGecko：{SOURCE_LINKS['CoinGecko']}",
            "- 若某项实时数据不可得：报告会保留最近可得数据，并在下方列出异常。",
        ]
    )
    if errors:
        lines.extend(["", "### 数据异常/不可得项目", ""])
        lines.extend(f"- {s.label}({s.symbol})：{s.error}" for s in errors)
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    REPORT_PATH.write_text(build_report(), encoding="utf-8")
    print(f"Generated 14:00 investment report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
