# -*- coding: utf-8 -*-
"""
海外債換券比較試算 — 舊券 A 贖回，換入零息債＋配息基金（基本款）或自組標的
比較「維持原券」與「換新券」在兩個時點的現金流與總值，並試算實現虧損的稅務扣抵
資料來源：Supabase bond_price_history（每日報價檔經龍蝦Bot /bond-upload 寫入）
僅供內部教育訓練／試算參考
"""
import math
from datetime import date

import altair as alt
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="海外債換券比較試算", page_icon="🔄", layout="wide")

NAVY, GOLD, BLUE, ORANGE = "#0B2A5B", "#C9A227", "#3E6A8A", "#E08A3C"

# 配息基金清單與預設配息率（沿用金開心Pro；配息率為假設、可修改）
FUNDS = {
    "AV04駿利亨德森平衡基金": 8.5,
    "PIMCO收益增長": 9.25,
    "PIMCO多元收益": 8.5,
    "富達全球動能多元基金": 10.0,
    "貝萊德全球智慧數據股票入息基金": 8.0,
    "貝萊德環球資產配置基金": 6.6,
    "聯博全球多元": 8.24,
    "聯博美國收益EA穩定月配": 7.81,
    "聯博-優化波動股票基金": 8.85,
    "聯博-新興市場多元收益基金": 5.51,
    "施羅德環球收益成長基金": 10.0,
    "施羅德環球收息債券": 9.38,
    "富蘭克林穩定月收益A(acc)": 8.21,
    "富達全球優質債券基金": 8.49,
    "富達永續發展全球存股優勢基金": 8.19,
    "安聯智慧城市收益": 9.0,
    "富邦台美雙星多重": 9.04,
    "群益潛力收益多重": 7.0,
    "富邦雙核心A台幣": 6.0,
}

# 預設配息組合（基金, 比例%, 年配息率%）；配息率為假設、可修改
PORTFOLIOS = {
    "333配息組合（各 1/3）": [("PIMCO收益增長", 33.3, 9.25), ("富達全球動能多元基金", 33.3, 10.0),
                         ("貝萊德全球智慧數據股票入息基金", 33.4, 8.0)],
}

# ───────────────────────── 樣式＋浮水印 ─────────────────────────
st.markdown(f"""
<style>
.stApp {{ background:#F7F8FB; }}
.block-container {{ max-width:1450px; }}
h1, h2, h3 {{ color:{NAVY}; }}
.tag {{ display:inline-block; background:{GOLD}; color:#fff; padding:2px 10px; border-radius:12px; font-size:0.8rem; }}
.muted {{ color:#6B7280; font-size:0.85rem; }}
.card {{ background:#fff; border:1px solid #E3E7EF; border-left:5px solid {NAVY}; border-radius:10px;
         padding:12px 16px; margin:6px 0; }}
.big {{ font-size:1.6rem; font-weight:700; color:{NAVY}; }}
.dash-title {{ background:{NAVY}; color:#fff; text-align:center; font-size:1.35rem; font-weight:800;
               padding:10px; border-radius:8px; margin:6px 0 12px; }}
.tbl {{ overflow-x:auto; }}
.tbl table {{ width:100%; border-collapse:collapse; font-size:0.82rem; background:#fff; }}
.tbl th {{ background:#EEF2F8; color:{NAVY}; font-weight:700; padding:6px 5px; border:1px solid #E3E7EF;
          text-align:center; line-height:1.25; }}
.tbl td {{ padding:6px 5px; border:1px solid #E3E7EF; }}
.tbl td.num {{ text-align:right; white-space:nowrap; }}
.tbl tr.tot td {{ background:#FFF8E6; font-weight:700; }}
.tbl td.pos {{ color:#1E7F4C; font-weight:700; }}
.tbl td.neg {{ color:#C0392B; font-weight:700; }}
</style>
""", unsafe_allow_html=True)

_WM = "僅供內部教育訓練使用"
st.markdown(
    '<div class="wm">' + "".join(f"<span>{_WM}</span>" for _ in range(60)) + "</div>"
    + """
<style>
.wm { position:fixed; inset:-30vh -30vw; z-index:999999; pointer-events:none; user-select:none;
      display:grid; grid-template-columns:repeat(6, 1fr); gap:90px 40px;
      transform:rotate(-30deg); align-content:center; justify-items:center; }
.wm span { font-size:22px; font-weight:700; color:rgba(11,42,91,0.05); white-space:nowrap; }
@media print {
  .wm { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  .wm span { color:rgba(11,42,91,0.10); }
}
</style>""", unsafe_allow_html=True)


# ───────────────────────── 密碼 ─────────────────────────
def check_password():
    pw = st.secrets.get("APP_PASSWORD", "")
    if not pw or st.session_state.get("auth_ok"):
        return True
    st.title("🔄 海外債換券比較試算")
    st.markdown('<span class="tag">僅供內部教育訓練使用・請勿外流</span>', unsafe_allow_html=True)
    v = st.text_input("請輸入密碼", type="password")
    if v:
        if v == pw:
            st.session_state["auth_ok"] = True
            st.rerun()
        st.error("密碼錯誤")
    return False


if not check_password():
    st.stop()


# ───────────────────────── 資料 ─────────────────────────
@st.cache_data(ttl=600, show_spinner="讀取最新報價…")
def load_quotes():
    url = st.secrets["SUPABASE_URL"].rstrip("/")
    key = st.secrets["SUPABASE_KEY"]
    h = {"apikey": key}
    if key.startswith("eyJ"):
        h["Authorization"] = f"Bearer {key}"
    api = f"{url}/rest/v1/bond_price_history"
    r = requests.get(api, params={"select": "snap_date", "order": "snap_date.desc", "limit": 1},
                     headers=h, timeout=20)
    r.raise_for_status()
    snap = r.json()[0]["snap_date"]
    r = requests.get(api, params={"select": "*", "snap_date": f"eq.{snap}", "limit": 5000},
                     headers={**h, "Range": "0-4999"}, timeout=30)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    if "prod_code" not in df.columns:
        df["prod_code"] = None
    for c in ["offer", "bid", "ytm", "ltv", "coupon", "min_amt"]:
        if c not in df.columns:
            df[c] = None
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["offer"] > 0].copy()
    df["ccy"] = df["ccy"].fillna("USD").astype(str).str.strip().str.upper()
    df = df[df["ccy"] == "USD"].copy()                 # 換券以美元計算
    df["maturity"] = pd.to_datetime(df["maturity"], errors="coerce")
    df = df.dropna(subset=["maturity"])
    code = df["prod_code"].fillna("").astype(str).str.strip()
    df["code_show"] = code.where(code != "", df["isin"].astype(str))
    df["sort_key"] = code.str.extract(r"(\d+)$")[0].fillna("0").astype("int64")
    df["label"] = (df["code_show"] + "｜" + df["bond_name"].astype(str) + "｜到期 "
                   + df["maturity"].dt.strftime("%Y-%m-%d"))
    df = (df.sort_values(["sort_key", "code_show"], ascending=[False, False])
            .drop_duplicates("isin").drop_duplicates("label").set_index("label"))
    return snap, df


@st.cache_data(ttl=3600, show_spinner=False)
def usd_twd():
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
        return float(r.json()["rates"]["TWD"])
    except Exception:
        return 32.0


try:
    snap_date, quotes = load_quotes()
except Exception as e:
    st.error(f"讀取報價失敗，請稍後再試或聯絡管理者。（{e}）")
    st.stop()

TODAY = date.today()


# ───────────────────────── 工具函式 ─────────────────────────
def fmt(v, d=0):
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:,.{d}f}"


def show_table(df, fmts=None, total=None, signed=()):
    fmts = fmts or {}

    def cell(c, v):
        if v is None or (isinstance(v, float) and math.isnan(v)) or v == "":
            return "—" if c in fmts else ""
        return fmts[c].format(v) if c in fmts else str(v)

    def cls(c, v):
        k = "num" if c in fmts else ""
        if c in signed and isinstance(v, (int, float)) and not math.isnan(v):
            k += " pos" if v > 0 else " neg" if v < 0 else ""
        return k

    head = "".join(f"<th>{c}</th>" for c in df.columns)
    rows = ""
    for _, r in df.iterrows():
        rows += "<tr>" + "".join(f'<td class="{cls(c, r[c])}">{cell(c, r[c])}</td>' for c in df.columns) + "</tr>"
    if total:
        rows += '<tr class="tot">' + "".join(
            f'<td class="{"num" if c in fmts else ""}">{total.get(c, "")}</td>' for c in df.columns) + "</tr>"
    st.markdown(f'<div class="tbl"><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>',
                unsafe_allow_html=True)


def years_to(d):
    d = pd.Timestamp(d).date()
    return max((d - TODAY).days / 365.25, 0.0)


def bond_price(y, cpn, t):
    """半年付息債券價格（每 100 面額）；y、cpn 為年利率（%），t 為剩餘年數"""
    if t <= 0:
        return 100.0
    i = y / 200
    n = t * 2
    c = cpn / 2
    if abs(i) < 1e-9:
        return c * n + 100
    return c * (1 - (1 + i) ** -n) / i + 100 * (1 + i) ** -n


def bond_yield(price, cpn, t):
    """由價格反推殖利率（%）"""
    if t <= 0 or price <= 0:
        return cpn
    lo, hi = -5.0, 60.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if bond_price(mid, cpn, t) > price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def bond_total(face, cpn, t_mat, y_now, H, dy, reinv):
    """持有到 H 年：累計配息＋H 時點價值（到期後本金以 reinv% 再投入領息）"""
    if H >= t_mat:
        return face * cpn / 100 * t_mat + face + face * reinv / 100 * (H - t_mat)
    p = bond_price(max(y_now + dy, -4.9), cpn, t_mat - H)
    return face * cpn / 100 * H + face * p / 100


# ───────────────────────── 標題 ─────────────────────────
st.title("🔄 海外債換券比較試算")
st.markdown(f'<span class="tag">僅供內部教育訓練使用・請勿外流</span> '
            f'<span class="muted">報價日期：{snap_date}（美元債 {len(quotes)} 檔）・以美元計算</span>',
            unsafe_allow_html=True)
st.caption("舊券（A 券）贖回後，換入「零息債打底＋配息基金」或自組標的，比較繼續持有與換券在兩個時點的結果。")

left, right = st.columns([1.45, 1], gap="medium")

# ───────────────────────── 左：A 券 ─────────────────────────
with left:
    st.header("① 目前持有的舊券（A 券）")
    st.caption("✏️ 直接在表格填寫，可新增多列（表格最下面一列點一下就能新增）")
    a_default = pd.DataFrame([{
        "名稱": "舊長債", "面額": 100000.0, "當初投入": 100000.0,
        "價格": 75.0, "票面%": 3.5, "到期日": date(TODAY.year + 18, TODAY.month, 1), "已領息": 15000.0,
    }])
    a_in = st.data_editor(
        st.session_state.get("a_saved", a_default), num_rows="dynamic", hide_index=True, width="stretch",
        key="a_ed",
        column_config={
            "名稱": st.column_config.TextColumn(required=True, width="small"),
            "面額": st.column_config.NumberColumn(min_value=0, step=1000, format="localized", width="small"),
            "當初投入": st.column_config.NumberColumn(min_value=0, step=1000, format="localized", width="small",
                                                    help="含溢價的實際投入（美元），用來算實現損益與稅務扣抵"),
            "價格": st.column_config.NumberColumn(min_value=0.01, max_value=200, step=0.01, format="%.2f", width="small", help="目前可贖回價格（每 100 面額）"),
            "票面%": st.column_config.NumberColumn(min_value=0, max_value=20, step=0.125, format="%.2f", width="small"),
            "到期日": st.column_config.DateColumn(min_value=TODAY, format="YYYY-MM-DD", width="small"),
            "已領息": st.column_config.NumberColumn(min_value=0, step=500, format="localized", width="small",
                                                 help="持有至今已領到的配息（美元，選填）；兩邊總值都會加上"),
        })
    a = a_in.dropna(subset=["面額", "價格", "到期日"]).copy()
    a["票面%"] = a["票面%"].fillna(0.0)          # 空白視為 0（零息債）
    a = a[a["面額"] > 0]
    if a.empty:
        st.info("請先填寫至少一檔 A 券。")
        st.stop()
    a["剩餘年期"] = a["到期日"].apply(years_to)
    a["贖回金額"] = a["面額"] * a["價格"] / 100
    a["殖利率(%)"] = [bond_yield(p, c, t) for p, c, t in zip(a["價格"], a["票面%"], a["剩餘年期"])]
    a["每年配息"] = a["面額"] * a["票面%"] / 100
    a["當初投入"] = a["當初投入"].fillna(a["面額"])
    a["實現損益"] = a["贖回金額"] - a["當初投入"]
    a["已領息"] = a["已領息"].fillna(0) if "已領息" in a else 0.0
    a["含息損益"] = a["實現損益"] + a["已領息"]
    R = a["贖回金額"].sum()
    RECEIVED = float(a["已領息"].sum())
    show_table(a[["名稱", "剩餘年期", "殖利率(%)", "贖回金額", "每年配息", "實現損益", "含息損益"]],
               {"剩餘年期": "{:.1f}", "殖利率(%)": "{:.2f}%", "贖回金額": "{:,.0f}", "每年配息": "{:,.0f}",
                "實現損益": "{:+,.0f}", "含息損益": "{:+,.0f}"},
               signed=("實現損益", "含息損益"),
               total=None if len(a) < 2 else {"名稱": "合計", "贖回金額": fmt(R),
                                              "每年配息": fmt(a["每年配息"].sum()),
                                              "實現損益": f'{a["實現損益"].sum():+,.0f}',
                                              "含息損益": f'{a["含息損益"].sum():+,.0f}'})
    c1, c2 = st.columns(2)
    c1.markdown(f'<div class="card">贖回可用資金（美元）<div class="big">{fmt(R)}</div></div>',
                unsafe_allow_html=True)
    c2.markdown(f'<div class="card">實現損益（美元）<div class="big">{a["實現損益"].sum():+,.0f}</div>'
                f'<span class="muted">加上已領配息 {fmt(RECEIVED)}，含息損益 '
                f'<b>{a["含息損益"].sum():+,.0f}</b></span></div>', unsafe_allow_html=True)

# ───────────────────────── 右：換入方式 ─────────────────────────
with right:
    st.header("② 換入標的")
    mode = st.radio("換入方式", ["基本款：零息債打底＋配息基金", "自己組"], horizontal=True, key="swap_mode")
    holds = []          # 換入部位：dict(type, name, face/amt, cpn, t, y, cost)
    reinv_default = 9.0

    if mode.startswith("基本款"):
        zeros = quotes[(quotes["coupon"].fillna(-1) == 0)].sort_values("maturity")
        if zeros.empty:
            st.warning("今日報價沒有美元零息債，請改用「自己組」。")
            st.stop()
        z_label = st.selectbox("零息債", list(zeros.index),
                               index=min(len(zeros) - 1, max(0, len(zeros) // 2)), key="z_sel")
        z = zeros.loc[z_label]
        z_t = years_to(z["maturity"])
        a_face = float(a["面額"].sum())
        max_face = math.floor(R / (z["offer"] / 100) / 1000) * 1000
        z_face = st.number_input("零息債面額（美元）", min_value=0.0, step=1000.0, format="%.0f",
                                 value=float(min(math.floor(a_face / 1000) * 1000, max_face)), key="z_face",
                                 help=f"預設＝A 券面額（鎖定 100% 面額）；目前資金最多可買 {fmt(max_face)}")
        z_cost = z_face * z["offer"] / 100
        if z_cost > R + 0.5:
            st.error(f"不夠買：零息債成本 {fmt(z_cost)} 超過贖回金額 {fmt(R)}，最多可買面額 {fmt(max_face)}。")
            st.stop()
        if not pd.isna(z["min_amt"]) and 0 < z_face < z["min_amt"]:
            st.warning(f"未達最低申購面額 {fmt(z['min_amt'])}。")
        f_amt = R - z_cost
        holds.append(dict(類型="零息債", 標的=z["bond_name"], 面額=z_face, 投入=z_cost, cpn=0.0, t=z_t,
                          y=float(z["ytm"]) if not pd.isna(z["ytm"]) else bond_yield(z["offer"], 0, z_t)))
        pf = st.radio("剩餘資金投入", list(PORTFOLIOS) + ["單一基金", "自建組合"], horizontal=True, key="pf_mode")
        if pf == "單一基金":
            fc1, fc2 = st.columns([3, 1])
            fund = fc1.selectbox("配息基金", list(FUNDS), key="fund_sel")
            f_y = fc2.number_input("年配息率(%)", 0.0, 20.0, float(FUNDS[fund]), 0.25, key=f"fy_{fund}")
            pf_rows = [(fund, 100.0, f_y)]
        else:
            base = PORTFOLIOS.get(pf, [("AV04駿利亨德森平衡基金", 100.0, FUNDS["AV04駿利亨德森平衡基金"])])
            st.caption("✏️ 基金名稱、比例、配息率都可以直接改；自建組合可在最下面一列新增基金"
                       if pf == "自建組合" else "✏️ 比例和配息率都可以直接改")
            pf_ed = st.data_editor(
                pd.DataFrame(base, columns=["基金", "比例(%)", "年配息率(%)"]),
                num_rows="dynamic" if pf == "自建組合" else "fixed", hide_index=True, width="stretch",
                key=f"pf_ed_{pf}",
                column_config={
                    "基金": st.column_config.TextColumn(required=True, disabled=(pf != "自建組合")),
                    "比例(%)": st.column_config.NumberColumn(min_value=0, max_value=100, step=5, format="%.1f",
                                                            required=True),
                    "年配息率(%)": st.column_config.NumberColumn(min_value=0, max_value=20, step=0.25,
                                                               format="%.2f", required=True)})
            pf_ed = pf_ed.dropna(subset=["基金", "比例(%)", "年配息率(%)"])
            pf_rows = [(r["基金"], float(r["比例(%)"]), float(r["年配息率(%)"])) for _, r in pf_ed.iterrows()
                       if str(r["基金"]).strip() and r["比例(%)"] > 0]
            w_sum = sum(w for _, w, _ in pf_rows)
            if pf_rows and abs(w_sum - 100) > 0.05:
                st.warning(f"比例合計為 {w_sum:.1f}%，已自動按比例換算成 100%。")
        if not pf_rows:
            st.info("請至少輸入一檔基金。")
            st.stop()
        w_sum = sum(w for _, w, _ in pf_rows)
        for nm, w, y_ in pf_rows:
            holds.append(dict(類型="基金", 標的=nm, 面額=None, 投入=f_amt * w / w_sum, fy=y_))
        reinv_default = round(sum(w * y_ for _, w, y_ in pf_rows) / w_sum, 2)
        if len(pf_rows) > 1:
            st.caption(f"組合加權年配息率 **{reinv_default:.2f}%**（配息率為假設、非保證）")
        st.caption(f"零息債 {z['bond_name']}：價格 {z['offer']:.2f}、到期 {z['maturity']:%Y-%m-%d}"
                   f"（剩 {z_t:.1f} 年）；投入 {fmt(z_cost)}，剩餘 {fmt(f_amt)}（{f_amt / R:.0%}）放基金組合。")
    else:
        fund_labels = [f"基金｜{n}" for n in FUNDS]
        picks = st.multiselect("選擇換入標的（債券或基金，可多選）", list(quotes.index) + fund_labels,
                               key="custom_sel", placeholder="輸入產品代號、債券名稱或基金名稱")
        if not picks:
            st.info("請選擇要換入的標的。")
            st.stop()
        amode = st.radio("投入金額分配方式", ["平均分配", "依比例分配", "自訂金額"], horizontal=True,
                         key="alloc_mode")
        pcts = st.session_state.setdefault("pcts", {})
        amts = st.session_state.setdefault("amts", {})
        n = len(picks)
        eq = math.floor(R / n / 100) * 100
        if amode == "平均分配":
            a_list = [float(eq)] * n
            st.caption("贖回資金平均分給每一檔，結果見下表")
        else:
            col = "比例(%)" if amode == "依比例分配" else "投入金額（美元）"
            if amode == "依比例分配":
                base = [round(100 / n, 1)] * n
                base[-1] = round(100 - sum(base[:-1]), 1)
                dflt = [float(pcts[p]) for p in picks] if all(p in pcts for p in picks) else base
            else:
                dflt = [float(amts.get(p, eq)) for p in picks]
            ed = st.data_editor(
                pd.DataFrame({"標的": [p.split("｜")[1] for p in picks], col: dflt}),
                hide_index=True, width="stretch", key=f"c_ed_{amode}_{len(picks)}_{hash(tuple(picks))}",
                column_config={"標的": st.column_config.TextColumn(disabled=True),
                               col: (st.column_config.NumberColumn(min_value=0, max_value=100, step=5, format="%.1f")
                                     if amode == "依比例分配" else
                                     st.column_config.NumberColumn(min_value=0, step=1000, format="localized"))})
            vals = ed[col].fillna(0).astype(float).tolist()
            if amode == "依比例分配":
                a_list = [math.floor(R * p / 100) for p in vals]
                for p, v in zip(picks, vals):
                    pcts[p] = v
                if abs(sum(vals) - 100) > 0.05:
                    st.warning(f"比例合計為 {sum(vals):.1f}%，{'超過' if sum(vals) > 100 else '未滿'} 100%。")
            else:
                a_list = vals
        for p, v in zip(picks, a_list):
            amts[p] = v
        fy_cols = [p for p in picks if p.startswith("基金｜")]
        if fy_cols:
            st.caption("基金年配息率（可修改）")
            cols = st.columns(min(len(fy_cols), 3))
        k = 0
        for p, alloc in zip(picks, a_list):
            if p.startswith("基金｜"):
                nm = p.split("｜", 1)[1]
                fy = cols[k % len(cols)].number_input(nm, 0.0, 20.0, float(FUNDS[nm]), 0.25, key=f"cfy_{nm}")
                k += 1
                holds.append(dict(類型="基金", 標的=nm, 面額=None, 投入=float(alloc), fy=fy))
            else:
                q = quotes.loc[p]
                face = math.floor(alloc / (q["offer"] / 100) / 1000) * 1000
                note = ""
                if not pd.isna(q["min_amt"]) and face < q["min_amt"]:
                    note, face = f"未達最低申購 {fmt(q['min_amt'])}", 0
                t = years_to(q["maturity"])
                cpn = 0.0 if pd.isna(q["coupon"]) else float(q["coupon"])
                y = float(q["ytm"]) if not pd.isna(q["ytm"]) else bond_yield(q["offer"], cpn, t)
                holds.append(dict(類型="零息債" if cpn == 0 else "債券", 標的=q["bond_name"], 面額=face,
                                  投入=face * q["offer"] / 100, cpn=cpn, t=t, y=y, 備註=note))
        fys = [h["fy"] for h in holds if h["類型"] == "基金" and h["投入"] > 0]
        reinv_default = round(sum(fys) / len(fys), 2) if fys else 5.0

    spent = sum(h["投入"] for h in holds)
    cash_left = R - spent
    if cash_left < -0.5:
        st.error(f"換入金額合計 {fmt(spent)} 超過贖回金額 {fmt(R)}，請調整。")
        st.stop()
    for h in holds:
        h["每年配息"] = (h["投入"] * h["fy"] / 100) if h["類型"] == "基金" else h["面額"] * h["cpn"] / 100
    hv = pd.DataFrame([{"類型": h["類型"], "標的": h["標的"], "面額": h["面額"], "投入": h["投入"],
                        "殖利率/配息率": h.get("fy", h.get("y")), "每年配息": h["每年配息"],
                        "到期": (f'{h["t"]:.1f} 年' if h["類型"] != "基金" else "—"), "備註": h.get("備註", "")}
                       for h in holds])
    show_table(hv, {"面額": "{:,.0f}", "投入": "{:,.0f}", "殖利率/配息率": "{:.2f}%", "每年配息": "{:,.0f}"},
               total={"標的": "合計", "投入": fmt(spent), "每年配息": fmt(hv["每年配息"].sum()),
                      "備註": f"剩餘現金 {fmt(cash_left)}" if cash_left > 0.5 else ""})

# ───────────────────────── ③ 情境設定 ─────────────────────────
st.header("③ 比較結果")
with st.expander("⚙️ 情境假設（可調整）", expanded=False):
    s1, s2, s3 = st.columns(3)
    dy = s1.slider("比較時點的利率變動（%）", -2.0, 2.0, 0.0, 0.25,
                   help="影響尚未到期債券在比較時點的估價；利率下降→舊券估價上升")
    nav = s2.slider("基金淨值變動（到比較時點）", -40, 20, 0, 5, format="%d%%",
                    help="基金配息可能來自本金，可模擬淨值被侵蝕的情況")
    reinv = s3.number_input("到期資金再投入年配息率（%）", 0.0, 20.0, float(reinv_default), 0.25,
                            help="債券先到期後，拿回的本金假設轉入配息標的繼續領息（兩邊相同處理）")

bond_holds = [h for h in holds if h["類型"] != "基金" and h["面額"] > 0]
H1 = max([h["t"] for h in bond_holds], default=max(a["剩餘年期"]))
H2 = float(a["剩餘年期"].max())
horizons = [("換入債券到期", H1), ("A 券到期", H2)] if abs(H1 - H2) > 0.05 else [("A 券到期", H2)]


def total_hold(H):
    return RECEIVED + sum(bond_total(f, c, t, y, H, dy, reinv)
               for f, c, t, y in zip(a["面額"], a["票面%"], a["剩餘年期"], a["殖利率(%)"]))


def total_swap(H):
    tot = cash_left + RECEIVED
    for h in holds:
        if h["類型"] == "基金":
            tot += h["投入"] * h["fy"] / 100 * H + h["投入"] * (1 + nav / 100)
        elif h["面額"] > 0:
            tot += bond_total(h["面額"], h["cpn"], h["t"], h["y"], H, dy, reinv)
    return tot


def ann(total, H):
    t = total - RECEIVED                      # 年化從贖回金額起算，不含已領配息
    return (t / R) ** (1 / H) - 1 if H > 0 and R > 0 and t > 0 else float("nan")


rows = []
for nm, H in horizons:
    th, ts = total_hold(H), total_swap(H)
    yr_h = (pd.Timestamp(TODAY) + pd.Timedelta(days=round(H * 365.25))).year
    rows.append(dict(比較時點=f"{nm}（{yr_h} 年，{H:.1f} 年後）", H=H, 維持A券=th, 換新券=ts,
                     換新券多出=ts - th, 年化_維持=ann(th, H), 年化_換新券=ann(ts, H)))
res = pd.DataFrame(rows)

cash_a = float(a["每年配息"].sum())
cash_s = float(hv["每年配息"].sum())

st.markdown('<div class="dash-title">換券效益比較－維持原券 vs 換新券</div>', unsafe_allow_html=True)
k1, k2, k3 = st.columns(3)
best = res.iloc[-1]
k1.markdown(f'<div class="card">每年現金流（美元）<br><span class="muted">維持原券 → 換新券</span>'
            f'<div class="big">{fmt(cash_a)} → {fmt(cash_s)}</div>'
            f'<span class="muted">每月約 {fmt(cash_a / 12)} → {fmt(cash_s / 12)}</span></div>', unsafe_allow_html=True)
for col, (_, r) in zip([k2, k3], res.iterrows()):
    color = "#1E7F4C" if r["換新券多出"] >= 0 else "#C0392B"
    col.markdown(f'<div class="card">放到{r["比較時點"].split("（")[0]}，換新券多出'
                 f'<div class="big" style="color:{color}">{r["換新券多出"]:+,.0f}</div>'
                 f'<span class="muted">{r["比較時點"]}</span></div>', unsafe_allow_html=True)

g1, g2 = st.columns(2)
with g1:
    st.markdown("**【到期總值】維持原券 vs 換新券**")
    gd = pd.concat([pd.DataFrame({"時點": res["比較時點"].str.split("（").str[0], "方案": "維持原券", "金額": res["維持A券"]}),
                    pd.DataFrame({"時點": res["比較時點"].str.split("（").str[0], "方案": "換新券", "金額": res["換新券"]})])
    ch = alt.Chart(gd).mark_bar().encode(
        x=alt.X("方案:N", title=None, axis=alt.Axis(labels=False, ticks=False)),
        y=alt.Y("金額:Q", axis=alt.Axis(format=",.0f", title=None)),
        color=alt.Color("方案:N", scale=alt.Scale(domain=["維持原券", "換新券"], range=[BLUE, ORANGE]),
                        legend=alt.Legend(orient="bottom", title=None)),
        column=alt.Column("時點:N", title=None, sort=list(res["比較時點"].str.split("（").str[0]), header=alt.Header(labelFontSize=13, labelFontWeight="bold")))
    st.altair_chart(ch.properties(width=170, height=260))
with g2:
    st.markdown("**【每年現金流】維持原券 vs 換新券**")
    cd = pd.DataFrame({"方案": ["維持原券", "換新券"], "每年配息": [cash_a, cash_s]})
    b = alt.Chart(cd).mark_bar(size=44).encode(
        y=alt.Y("方案:N", sort=["換新券", "維持原券"], title=None),
        x=alt.X("每年配息:Q", axis=alt.Axis(format=",.0f", title=None),
                scale=alt.Scale(domain=[0, max(cash_a, cash_s, 1) * 1.2])),
        color=alt.Color("方案:N", scale=alt.Scale(domain=["換新券", "維持原券"], range=[ORANGE, BLUE]), legend=None))
    t = b.mark_text(align="right", dx=-8, fontWeight="bold", fontSize=15).encode(
        text=alt.Text("每年配息:Q", format=",.0f"), color=alt.value("white"))
    st.altair_chart((b + t).properties(height=260), width="stretch")

show_table(res[["比較時點", "維持A券", "換新券", "換新券多出", "年化_維持", "年化_換新券"]].rename(
    columns={"維持A券": "維持原券合計", "換新券": "換新券合計", "年化_維持": "年化（維持原券）", "年化_換新券": "年化（換新券）"}),
    {"維持原券合計": "{:,.0f}", "換新券合計": "{:,.0f}", "換新券多出": "{:+,.0f}",
     "年化（維持原券）": "{:.2%}", "年化（換新券）": "{:.2%}"}, signed=("換新券多出",))
st.caption("合計＝已領配息＋未來累計配息＋比較時點的本金或估價（已到期債券以面額計，之後依「再投入配息率」續領息）；"
           "未到期債券以目前殖利率加計利率變動估價；基金本金依淨值變動假設計算。"
           "已領配息兩邊相同，不影響換新券多出；年化從贖回金額起算，不含已領配息。")

# 利率敏感度
st.subheader("利率變動對換新券多出的影響")
sens = []
for nm, H in horizons:
    row = {"比較時點": nm}
    for d in [1.0, 0.0, -1.0, -2.0]:
        old = dy
        dy = d
        row[f"利率{'升' if d > 0 else '降' if d < 0 else ''}{abs(d):.0f}%" if d else "利率不變"] = total_swap(H) - total_hold(H)
        dy = old
    sens.append(row)
sdf = pd.DataFrame(sens)
show_table(sdf, {c: "{:+,.0f}" for c in sdf.columns[1:]}, signed=tuple(sdf.columns[1:]))
st.caption("利率下降時，未到期的舊長債估價上升，換券優勢會縮小；零息債已到期的部分不受利率影響。")

# ───────────────────────── ④ 稅務 ─────────────────────────
st.header("④ 實現虧損可抵海外財產交易所得")
loss_usd = -min(0.0, float(a["實現損益"].sum()))
t1, t2 = st.columns([1, 1.4], gap="large")
with t1:
    redeem_day = st.date_input("預計贖回日", value=TODAY, key="redeem_day")
    fx = st.number_input("美元兌台幣匯率", 20.0, 40.0, float(round(usd_twd(), 2)), 0.01, format="%.2f")
    loss_twd = loss_usd * fx
    yr = redeem_day.year
    if loss_usd > 0:
        st.markdown(f'<div class="card">換券實現虧損（台幣）<div class="big">{fmt(loss_twd)}</div>'
                    f'<span class="muted">美元 {fmt(loss_usd)} × {fx:.2f}<br>'
                    f'可用來扣抵 <b>{yr} 年度</b>的海外財產交易所得（{yr + 1} 年 5 月申報）</span></div>',
                    unsafe_allow_html=True)
    else:
        st.info("A 券沒有實現虧損，不適用扣抵。")
with t2:
    st.markdown("""
<div class="card">
<b>✅ 可以抵</b>：同年度的<b>海外財產交易所得</b>，例如同一年賣出海外股票、ETF、境外基金的獲利<br>
<b>❌ 不能抵</b>：利息、配息等其他海外所得<br>
<b>⏳ 不能遞延</b>：當年扣不完的部分，不能留到以後年度<br>
<b>🧮 怎麼算</b>：成交價 － 原始成本（當初溢價也算成本），以台幣核實計算，要保留交易憑證<br>
<b>📅 看贖回日</b>：12 月贖回列入當年度，隔年 1 月贖回就列入下一個年度
</div>""", unsafe_allow_html=True)
st.caption("實際能少繳多少稅，要看客戶全戶的海外所得、股利、保險給付等完整申報內容，"
           "請客戶洽詢會計師或依國稅局認定為準。本段僅供教育訓練參考，非稅務建議。")

st.markdown("---")
st.caption("本試算僅供內部教育訓練與試算參考。基金配息率為假設、非保證，配息可能來自本金；"
           "零息債到期以發行機構不違約為前提；可提前買回的債券若被買回，持有到期試算將不適用。"
           "報價以實際交易為準。")
