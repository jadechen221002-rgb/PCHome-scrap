# -*- coding: utf-8 -*-
import time

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API_URL = "https://ecshweb.pchome.com.tw/search/v3.3/all/results"
PROD_URL = "https://24h.pchome.com.tw/prod/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

SORT_OPTIONS = {
    "熱銷程度": "sale/dc",
    "相關程度": "rnk/dc",
    "價格由低到高": "prc/ac",
    "價格由高到低": "prc/dc",
}

st.set_page_config(page_title="PChome 商品價格分析", page_icon="🛒", layout="wide")


@st.cache_data(ttl=600, show_spinner=False)
def fetch_page(keyword: str, page: int, sort: str) -> dict:
    """抓取單一頁的搜尋結果（快取 10 分鐘，避免重複請求）"""
    params = {"q": keyword, "page": page, "sort": sort}
    resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.json()


def crawl(keyword: str, pages: int, sort: str, delay: float) -> pd.DataFrame:
    """依序抓取多頁資料並合併成 DataFrame"""
    frames = []
    progress = st.progress(0.0, text="開始爬取...")
    for i in range(1, pages + 1):
        progress.progress((i - 1) / pages, text=f"正在抓取第 {i}/{pages} 頁...")
        data = fetch_page(keyword, i, sort)
        prods = data.get("prods") or []
        if not prods:
            break
        frames.append(pd.DataFrame(prods))
        total_page = data.get("totalPage") or pages
        if i >= total_page:
            break
        if i < pages and delay > 0:
            time.sleep(delay)  # 禮貌性延遲，避免被網站封鎖
    progress.empty()

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df = df.dropna(subset=["name", "price"]).reset_index(drop=True)
    df["序號"] = df.index + 1
    if "Id" in df.columns:
        df["連結"] = PROD_URL + df["Id"].astype(str)
    return df


def add_price_range(df: pd.DataFrame) -> pd.DataFrame:
    """新增價格區間欄位（圓餅圖 / 旭日圖使用）"""
    bins = [0, 500, 1000, 1500, 2000, 3000, 5000, float("inf")]
    labels = ["0-500", "501-1000", "1001-1500", "1501-2000",
              "2001-3000", "3001-5000", "5000以上"]
    out = df.copy()
    out["價格區間"] = pd.cut(out["price"], bins=bins, labels=labels, right=True)
    return out


def guess_brand(name: str) -> str:
    """以商品名稱第一個詞粗略推測品牌（僅供參考）"""
    name = str(name)
    for sep in ["【", "】", "｜", "|", "-", "/"]:
        name = name.replace(sep, " ")
    parts = name.split()
    return parts[0] if parts else "未知"


# ---------------------------------------------------------------- UI
st.title("🛒 PChome 商品價格查詢與視覺化")

with st.form("search_form"):
    c1, c2, c3 = st.columns([3, 1, 2])
    keyword = c1.text_input("商品關鍵字", value="行動電源")
    pages = c2.number_input("爬取頁數", min_value=1, max_value=20, value=2, step=1)
    sort_label = c3.selectbox("排序方式", list(SORT_OPTIONS.keys()))
    delay = st.slider("每頁間隔秒數（建議 ≥ 1 秒）", 0.0, 10.0, 1.0, 0.5)
    submitted = st.form_submit_button("🔍 開始查詢", use_container_width=True)

if submitted:
    if not keyword.strip():
        st.warning("請輸入商品關鍵字")
    else:
        try:
            result = crawl(keyword.strip(), int(pages), SORT_OPTIONS[sort_label], delay)
            if result.empty:
                st.session_state.pop("df", None)
                st.info("查無資料，請換個關鍵字試試。")
            else:
                st.session_state["df"] = result
                st.session_state["keyword"] = keyword.strip()
        except requests.exceptions.RequestException as e:
            st.error(f"網路請求失敗：{e}")
        except ValueError as e:
            st.error(f"回傳資料格式錯誤：{e}")

# 結果存在 session_state，切換圖表時不會重新爬取
if "df" in st.session_state:
    df: pd.DataFrame = st.session_state["df"]
    kw = st.session_state["keyword"]
    avg_price = df["price"].mean()

    st.subheader(f"「{kw}」查詢結果")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("商品數量", f"{len(df):,}")
    m2.metric("平均價格", f"NT$ {avg_price:,.0f}")
    m3.metric("最高價格", f"NT$ {df['price'].max():,.0f}")
    m4.metric("最低價格", f"NT$ {df['price'].min():,.0f}")

    chart_type = st.radio("圖表類型", ["折線圖", "圓餅圖", "旭日圖"], horizontal=True)

    if chart_type == "折線圖":
        fig = px.line(
            df, x="序號", y="price", markers=True,
            hover_data={"name": True, "序號": False},
            labels={"price": "價格 (NT$)", "序號": "商品序號"},
            title=f"PChome「{kw}」商品售價",
        )
        fig.add_hline(
            y=avg_price, line_dash="dash", line_color="red",
            annotation_text=f"平均 {avg_price:,.0f}",
            annotation_position="top left",
        )

    elif chart_type == "圓餅圖":
        pie_df = add_price_range(df)
        counts = (pie_df.groupby("價格區間", observed=True)
                  .size().reset_index(name="商品數"))
        fig = px.pie(counts, names="價格區間", values="商品數",
                     title=f"PChome「{kw}」價格區間分佈", hole=0.3)
        fig.update_traces(textinfo="label+percent")

    else:  # 旭日圖：價格區間 → 品牌（以名稱第一個詞推測）
        sun_df = add_price_range(df)
        sun_df["品牌(推測)"] = sun_df["name"].apply(guess_brand)
        top_brands = sun_df["品牌(推測)"].value_counts().head(12).index
        sun_df.loc[~sun_df["品牌(推測)"].isin(top_brands), "品牌(推測)"] = "其他"
        sun_df["價格區間"] = sun_df["價格區間"].astype(str)
        counts = (sun_df.groupby(["價格區間", "品牌(推測)"])
                  .size().reset_index(name="商品數"))
        fig = px.sunburst(counts, path=["價格區間", "品牌(推測)"], values="商品數",
                          title=f"PChome「{kw}」價格區間 × 品牌（品牌為名稱首字推測）")

    fig.update_layout(height=600, font=dict(size=14))
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("📋 查看原始資料", expanded=False):
        cols = [c for c in ["序號", "name", "price", "連結"] if c in df.columns]
        st.dataframe(
            df[cols], use_container_width=True, hide_index=True,
            column_config={
                "name": "商品名稱",
                "price": st.column_config.NumberColumn("價格", format="NT$ %d"),
                "連結": st.column_config.LinkColumn("商品連結", display_text="前往"),
            },
        )
        st.download_button(
            "⬇️ 下載 CSV",
            data=df.drop(columns=["序號"]).to_csv(index=False).encode("utf-8-sig"),
            file_name=f"PCHOME_{kw}.csv",
            mime="text/csv",
        )
