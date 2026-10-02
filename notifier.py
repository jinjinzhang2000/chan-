"""
A股内部交易监控工具 - 邮件推送模块
生成HTML报告并通过邮件发送
"""
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd

from config import (EMAIL_PASSWORD, EMAIL_RECEIVERS, EMAIL_SENDER,
                    EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, EMAIL_USE_SSL)

# HTML邮件模板
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{ font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif; margin: 20px; color: #333; background: #f5f5f5; }}
.container {{ max-width: 900px; margin: 0 auto; background: white; border-radius: 8px; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
h1 {{ color: #1a1a1a; font-size: 22px; border-bottom: 2px solid #e74c3c; padding-bottom: 10px; }}
h2 {{ color: #2c3e50; font-size: 17px; margin-top: 28px; padding: 8px 12px; background: #f8f9fa; border-left: 4px solid #3498db; }}
.portfolio-tag {{ display: inline-block; background: #e74c3c; color: white; font-size: 11px; padding: 1px 6px; border-radius: 3px; margin-left: 4px; }}
table {{ border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 13px; }}
th {{ background: #34495e; color: white; padding: 8px 10px; text-align: left; }}
td {{ padding: 7px 10px; border-bottom: 1px solid #eee; }}
tr:hover {{ background: #f8f9fa; }}
tr.portfolio {{ background: #fff5f5; }}
tr.portfolio:hover {{ background: #ffe8e8; }}
.score {{ font-weight: bold; }}
.score-high {{ color: #e74c3c; }}
.score-mid {{ color: #f39c12; }}
.score-low {{ color: #95a5a6; }}
.buy {{ color: #27ae60; font-weight: bold; }}
.sell {{ color: #e74c3c; font-weight: bold; }}
.summary {{ color: #7f8c8d; font-size: 13px; margin-top: 24px; padding-top: 12px; border-top: 1px solid #eee; }}
.empty {{ color: #95a5a6; font-style: italic; padding: 16px; }}
</style>
</head>
<body>
<div class="container">
<h1>A股+港股内部交易监控日报 - {date}</h1>
{content}
<div class="summary">
<p>数据来源：东方财富 / 港交所权益披露 / Webb-site Database | 生成时间：{timestamp}</p>
<p>★ 标记为持仓股票 | 评分范围：0-130（持仓股额外+30分）</p>
</div>
</div>
</body>
</html>
"""


def _is_missing(val) -> bool:
    if val is None:
        return True
    try:
        return bool(pd.isna(val))
    except (TypeError, ValueError):
        return False


def _format_amount(val) -> str:
    """格式化金额显示"""
    if _is_missing(val):
        return "-"
    try:
        val = float(val)
    except (TypeError, ValueError):
        return "-"
    abs_val = abs(val)
    if abs_val >= 1e8:
        return f"{val/1e8:.2f}亿"
    elif abs_val >= 1e4:
        return f"{val/1e4:.2f}万"
    else:
        return f"{val:.0f}"


def _format_pct(val, digits: int = 4) -> str:
    if _is_missing(val):
        return "-"
    try:
        return f"{float(val):.{digits}f}%"
    except (TypeError, ValueError):
        return "-"


def _score_class(score) -> str:
    try:
        s = int(score)
    except (TypeError, ValueError):
        return "score-low"
    if s >= 60:
        return "score-high"
    elif s >= 40:
        return "score-mid"
    return "score-low"


def _build_shareholder_table(df: pd.DataFrame) -> str:
    if df.empty:
        return '<p class="empty">无数据</p>'
    rows = []
    for _, r in df.iterrows():
        is_p = r.get("IS_PORTFOLIO", False)
        tr_cls = ' class="portfolio"' if is_p else ""
        tag = ' <span class="portfolio-tag">★持仓</span>' if is_p else ""
        direction_cls = "buy" if r.get("DIRECTION") == "增持" else "sell"
        rows.append(f"""<tr{tr_cls}>
<td>{r.get('SECURITY_CODE','')}{tag}</td>
<td>{r.get('SECURITY_NAME_ABBR','')}</td>
<td>{r.get('HOLDER_NAME','')}</td>
<td class="{direction_cls}">{r.get('DIRECTION','')}</td>
<td>{_format_amount(r.get('TRADE_AMOUNT'))}</td>
<td>{_format_pct(r.get('CHANGE_RATE'))}</td>
<td>{str(r.get('END_DATE',''))[:10]}</td>
<td class="score {_score_class(r.get('SCORE'))}">{r.get('SCORE','')}</td>
</tr>""")
    return f"""<table>
<tr><th>代码</th><th>名称</th><th>股东</th><th>方向</th><th>金额</th><th>占比</th><th>日期</th><th>评分</th></tr>
{''.join(rows)}
</table>"""


def _build_executive_table(df: pd.DataFrame) -> str:
    if df.empty:
        return '<p class="empty">无数据</p>'
    rows = []
    for _, r in df.iterrows():
        is_p = r.get("IS_PORTFOLIO", False)
        tr_cls = ' class="portfolio"' if is_p else ""
        tag = ' <span class="portfolio-tag">★持仓</span>' if is_p else ""
        amt = r.get("CHANGE_AMOUNT", 0)
        try:
            amt_val = float(amt) if not _is_missing(amt) else 0.0
        except (TypeError, ValueError):
            amt_val = 0.0
        direction_cls = "buy" if amt_val > 0 else "sell"
        direction = "增持" if amt_val > 0 else "减持"
        rows.append(f"""<tr{tr_cls}>
<td>{r.get('SECURITY_CODE','')}{tag}</td>
<td>{r.get('SECURITY_NAME','')}</td>
<td>{r.get('PERSON_NAME','')}</td>
<td>{r.get('POSITION_NAME','')}</td>
<td class="{direction_cls}">{direction}</td>
<td>{_format_amount(amt)}</td>
<td>{str(r.get('CHANGE_DATE',''))[:10]}</td>
<td class="score {_score_class(r.get('SCORE'))}">{r.get('SCORE','')}</td>
</tr>""")
    return f"""<table>
<tr><th>代码</th><th>名称</th><th>变动人</th><th>职务</th><th>方向</th><th>金额</th><th>日期</th><th>评分</th></tr>
{''.join(rows)}
</table>"""


def _build_buyback_table(df: pd.DataFrame) -> str:
    if df.empty:
        return '<p class="empty">无数据</p>'
    rows = []
    for _, r in df.iterrows():
        is_p = r.get("IS_PORTFOLIO", False)
        tr_cls = ' class="portfolio"' if is_p else ""
        tag = ' <span class="portfolio-tag">★持仓</span>' if is_p else ""
        rows.append(f"""<tr{tr_cls}>
<td>{r.get('DIM_SCODE','')}{tag}</td>
<td>{r.get('SECURITYSHORTNAME','')}</td>
<td>{_format_amount(r.get('REPURAMOUNTLIMIT'))}</td>
<td>{_format_amount(r.get('REPURAMOUNT'))}</td>
<td>{r.get('PROGRESS_TEXT', r.get('REPURPROGRESS',''))}</td>
<td>{str(r.get('UPDATEDATE',''))[:10]}</td>
<td class="score {_score_class(r.get('SCORE'))}">{r.get('SCORE','')}</td>
</tr>""")
    return f"""<table>
<tr><th>代码</th><th>名称</th><th>计划金额上限</th><th>已回购金额</th><th>进度</th><th>更新日期</th><th>评分</th></tr>
{''.join(rows)}
</table>"""


def _build_incentive_table(df: pd.DataFrame) -> str:
    if df.empty:
        return '<p class="empty">无数据</p>'
    rows = []
    for _, r in df.iterrows():
        is_p = r.get("IS_PORTFOLIO", False)
        tr_cls = ' class="portfolio"' if is_p else ""
        tag = ' <span class="portfolio-tag">★持仓</span>' if is_p else ""
        shares = r.get("INCENTIVE_SHARES", 0)
        try:
            shares_str = f"{float(shares):.0f}万股" if not _is_missing(shares) else "-"
        except (TypeError, ValueError):
            shares_str = "-"
        rows.append(f"""<tr{tr_cls}>
<td>{r.get('SECURITY_CODE','')}{tag}</td>
<td>{r.get('SECURITY_NAME_ABBR','')}</td>
<td>{r.get('PLAN_PROCESS','')}</td>
<td>{r.get('EI_TARGET','')}</td>
<td>{shares_str}</td>
<td>{r.get('EXERCISE_PRICE','')}</td>
<td>{str(r.get('LASTEST_NOTICE_DATE',''))[:10]}</td>
<td class="score {_score_class(r.get('SCORE'))}">{r.get('SCORE','')}</td>
</tr>""")
    return f"""<table>
<tr><th>代码</th><th>名称</th><th>进度</th><th>激励标的</th><th>股份数</th><th>行权价</th><th>公告日</th><th>评分</th></tr>
{''.join(rows)}
</table>"""


def _format_amount_hkd(val) -> str:
    """格式化港币金额显示"""
    if _is_missing(val):
        return "-"
    try:
        val = float(val)
    except (TypeError, ValueError):
        return "-"
    abs_val = abs(val)
    if abs_val >= 1e8:
        return f"HK${val/1e8:.2f}亿"
    elif abs_val >= 1e4:
        return f"HK${val/1e4:.2f}万"
    elif abs_val > 0:
        return f"HK${val:.0f}"
    return "-"


def _build_hk_insider_table(df: pd.DataFrame) -> str:
    """构建港股权益披露HTML表格"""
    if df.empty:
        return '<p class="empty">无数据</p>'
    rows = []
    for _, r in df.iterrows():
        is_p = r.get("IS_PORTFOLIO", False)
        tr_cls = ' class="portfolio"' if is_p else ""
        tag = ' <span class="portfolio-tag">★持仓</span>' if is_p else ""
        filer = r.get("FILER_TYPE", "")
        direction = str(r.get("DIRECTION", ""))
        direction_cls = "buy" if direction == "增持" or (not direction and "董事" in str(filer)) else "sell" if direction == "减持" else ""
        code = r.get("STOCK_CODE", "")
        corp_label = f"{code} " if code else ""
        rows.append(f"""<tr{tr_cls}>
<td>{corp_label}{r.get('CORP_NAME','')}{tag}</td>
<td>{r.get('PERSON_NAME','')}</td>
<td>{filer}</td>
<td>{r.get('REASON_TEXT','')}</td>
<td>{_format_amount_hkd(r.get('TRADE_AMOUNT'))}</td>
<td>{_format_pct(r.get('VOTING_PCT_L'), digits=2)}</td>
<td>{str(r.get('EVENT_DATE',''))[:10]}</td>
<td class="score {_score_class(r.get('SCORE'))}">{r.get('SCORE','')}</td>
</tr>""")
    return f"""<table>
<tr><th>公司</th><th>披露人</th><th>身份</th><th>原因</th><th>金额(HKD)</th><th>投票权%</th><th>日期</th><th>评分</th></tr>
{''.join(rows)}
</table>"""


def build_html_report(shareholder_df: pd.DataFrame, executive_df: pd.DataFrame,
                      buyback_df: pd.DataFrame, incentive_df: pd.DataFrame,
                      hk_insider_df: pd.DataFrame = None) -> str:
    """构建完整的HTML报告"""
    sections = []

    sections.append(f"<h2>一、大股东增减持（{len(shareholder_df)} 条）</h2>")
    sections.append(_build_shareholder_table(shareholder_df))

    sections.append(f"<h2>二、高管增减持（{len(executive_df)} 条）</h2>")
    sections.append(_build_executive_table(executive_df))

    sections.append(f"<h2>三、股票回购（{len(buyback_df)} 条）</h2>")
    sections.append(_build_buyback_table(buyback_df))

    sections.append(f"<h2>四、股权激励（{len(incentive_df)} 条）</h2>")
    sections.append(_build_incentive_table(incentive_df))

    if hk_insider_df is not None and not hk_insider_df.empty:
        src = ""
        if "DATA_SOURCE" in hk_insider_df.columns:
            sources = sorted({str(s) for s in hk_insider_df["DATA_SOURCE"].dropna().unique() if s})
            if sources:
                src = f"，来源：{' / '.join(sources)}"
        sections.append(f"<h2>五、港股权益披露（{len(hk_insider_df)} 条{src}）</h2>")
        sections.append(_build_hk_insider_table(hk_insider_df))

    return HTML_TEMPLATE.format(
        date=datetime.now().strftime("%Y-%m-%d"),
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        content="\n".join(sections),
    )


def send_email(html_content: str) -> bool:
    """发送HTML邮件"""
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        print("  ⚠️  邮件配置不完整，请设置 EMAIL_SENDER 和 EMAIL_PASSWORD 环境变量")
        return False
    receivers = [r.strip() for r in EMAIL_RECEIVERS if r.strip()]
    if not receivers:
        print("  ⚠️  未配置收件人，请设置 EMAIL_RECEIVERS 环境变量")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"A股+港股内部交易监控 - {datetime.now().strftime('%Y-%m-%d')}"
    msg["From"] = EMAIL_SENDER
    msg["To"] = ", ".join(receivers)
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        if EMAIL_USE_SSL:
            server = smtplib.SMTP_SSL(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT)
        else:
            server = smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT)
            server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, receivers, msg.as_string())
        server.quit()
        print(f"  ✅ 邮件已发送至 {', '.join(receivers)}")
        return True
    except Exception as e:
        print(f"  ❌ 邮件发送失败: {e}")
        return False
