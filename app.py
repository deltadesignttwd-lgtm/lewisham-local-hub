import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import feedparser
import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

# 1. 頁面基礎設定
st.set_page_config(page_title="Lewisham Local Hub", page_icon="🦁", layout="wide")

LONDON = ZoneInfo("Europe/London")
REQUEST_TIMEOUT = 10  # 秒；避免任何一個網站卡住整個頁面
# Reddit 等網站會封鎖偽裝成瀏覽器的爬蟲，官方建議使用可辨識的 User-Agent
HEADERS = {"User-Agent": "LewishamLocalHub/1.0 (community news aggregator)"}
ITEMS_PER_SOURCE = 8
MAX_EVENTS = 12

RSS_FEEDS = {
    "Reddit (r/lewisham)": "https://www.reddit.com/r/lewisham/new/.rss",
    "Lewisham Loop Newsletter": "https://lewisham-loop.beehiiv.com/feed",
    "Lewisham Council News": "https://lewisham.gov.uk/news/rss",
}
COUNCIL_SOURCE = "Lewisham Council News"
COUNCIL_NEWS_PAGE = "https://lewisham.gov.uk/news"
EVENTS_SOURCE = "We Are Lewisham"
EVENTS_URL = "https://www.wearelewisham.com/events/"

# 2. 社區分類關鍵字
# 「Lewisham」幾乎出現在每一則標題裡（例如 "Lewisham Council"），所以放在最後比對，
# 讓較具體的社區名稱優先。
NEIGHBOURHOODS = [
    "Brockley", "Catford", "Deptford", "New Cross", "Sydenham", "Blackheath",
    "Forest Hill", "Ladywell", "Hither Green", "Lee", "Honor Oak", "Crofton Park",
    "Bellingham", "Downham", "Grove Park", "Lewisham",
]
BOROUGH_WIDE = "Borough-Wide"
# 使用單字邊界，避免 "Lee" 誤判 "Leeds"、"sleep" 等字
_AREA_PATTERNS = [(area, re.compile(rf"\b{re.escape(area)}\b", re.IGNORECASE)) for area in NEIGHBOURHOODS]


def categorize_title(title):
    text = str(title)
    for area, pattern in _AREA_PATTERNS:
        if area == "Lewisham":
            # 只有明確指 Lewisham 市中心時才歸類為 Lewisham，其餘視為全區消息
            if re.search(r"\bLewisham (town centre|high street|station|market|shopping centre)\b", text, re.IGNORECASE):
                return area
            continue
        if pattern.search(text):
            return area
    return BOROUGH_WIDE


def make_item(title, link, published, source, item_type):
    return {
        "Title": title,
        "Link": link,
        "Published": published,  # timezone-aware datetime 或 None
        "Source": source,
        "Area": categorize_title(title),
        "Type": item_type,
    }


def _http_get(url):
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response


def _entry_datetime(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc).astimezone(LONDON)


# 3. 抓取 RSS 來源 (Reddit, Beehiiv, Council)
# 注意：失敗時直接拋出例外。st.cache_data 不會快取例外，
# 所以某個網站暫時掛掉時，下次重新整理就會再試，而不是空白 30 分鐘。
@st.cache_data(ttl=1800, show_spinner=False)  # 每 30 分鐘自動更新一次
def fetch_rss_source(source_name, url):
    # feedparser 本身沒有 timeout 且不會拋出網路錯誤，所以先用 requests 下載
    feed = feedparser.parse(_http_get(url).content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"無法解析 RSS：{feed.get('bozo_exception')}")

    items = []
    for entry in feed.entries[:ITEMS_PER_SOURCE]:
        title = entry.get("title", "").strip()
        link = entry.get("link", "")
        if title and link:
            items.append(make_item(title, link, _entry_datetime(entry), source_name, "新聞 / 討論"))
    return items


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_council_news_page():
    """議會 RSS 失效時的備案：直接解析新聞頁面上的新聞連結。"""
    soup = BeautifulSoup(_http_get(COUNCIL_NEWS_PAGE).text, "html.parser")
    items, seen = [], set()
    for a in soup.find_all("a", href=True):
        link = urljoin(COUNCIL_NEWS_PAGE, a["href"])
        title = a.get_text(" ", strip=True)
        path = link.split("lewisham.gov.uk", 1)[-1].rstrip("/")
        if "/news/" not in path or path.endswith("/news") or link in seen or len(title) < 15:
            continue
        seen.add(link)
        items.append(make_item(title, link, None, COUNCIL_SOURCE, "新聞 / 討論"))
        if len(items) >= ITEMS_PER_SOURCE:
            break
    if not items:
        raise ValueError("新聞頁面上找不到任何新聞連結")
    return items


# 4. 抓取 We Are Lewisham 文化活動 (網頁爬蟲)
def _parse_event_date(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LONDON)
    return dt.astimezone(LONDON)


def _jsonld_events(soup):
    """許多活動網站會在頁面中嵌入 schema.org 的 Event 資料，比猜 CSS class 可靠得多。"""
    found = []

    def walk(node):
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif isinstance(node, dict):
            node_type = node.get("@type")
            types = node_type if isinstance(node_type, list) else [node_type]
            if any(isinstance(t, str) and t.endswith("Event") for t in types):
                found.append(node)
            for key in ("@graph", "itemListElement", "item"):
                if key in node:
                    walk(node[key])

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            walk(json.loads(script.string or ""))
        except (json.JSONDecodeError, TypeError):
            continue
    return found


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_we_are_lewisham_events():
    soup = BeautifulSoup(_http_get(EVENTS_URL).text, "html.parser")
    events, seen = [], set()

    def add(title, link, start):
        link = urljoin(EVENTS_URL, link)
        if not title or link in seen or link.rstrip("/") == EVENTS_URL.rstrip("/"):
            return
        seen.add(link)
        events.append(make_item(title, link, start, EVENTS_SOURCE, "文化活動"))

    for event in _jsonld_events(soup):
        add(str(event.get("name", "")).strip(), event.get("url") or "", _parse_event_date(event.get("startDate")))

    if not events:
        # 備案：尋找 class 含 "event" 的卡片。只取最外層卡片，避免巢狀元素重複計算。
        cards = soup.find_all(["article", "li", "div"], class_=lambda c: c and "event" in c.lower())
        cards = [c for c in cards if not any(p in cards for p in c.parents)] or cards
        for card in cards:
            title_tag = card.find(["h2", "h3", "h4"]) or card.find("a", href=True)
            link_tag = (title_tag if title_tag and title_tag.name == "a" else None) or card.find("a", href=True)
            if title_tag and link_tag:
                time_tag = card.find("time")
                start = _parse_event_date(time_tag.get("datetime")) if time_tag else None
                add(title_tag.get_text(" ", strip=True), link_tag["href"], start)

    if not events:
        raise ValueError("找不到活動資料（網站結構可能已變更）")
    return events[:MAX_EVENTS]


# 5. 整合所有數據（每個來源獨立處理，一個失敗不影響其他）
def load_all_sources():
    items, errors = [], {}
    for source_name, url in RSS_FEEDS.items():
        try:
            items += fetch_rss_source(source_name, url)
        except Exception as e:
            if source_name == COUNCIL_SOURCE:
                try:
                    items += fetch_council_news_page()
                    continue
                except Exception as fallback_error:
                    e = fallback_error
            errors[source_name] = str(e)
    try:
        items += fetch_we_are_lewisham_events()
    except Exception as e:
        errors[EVENTS_SOURCE] = str(e)
    return items, errors


def md_escape(text):
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~])", r"\\\1", str(text))


def format_published(value):
    if value is None or pd.isna(value):
        return "日期未提供"
    return value.strftime("%Y-%m-%d %H:%M")


# 6. UI
st.title("🦁 Lewisham 綜合在地資訊網")
st.caption("一站式匯集社群討論、在地電子報、區議會公告與文化活動")

st.sidebar.header("🔍 篩選條件")
if st.sidebar.button("🔄 重新整理資料"):
    st.cache_data.clear()

with st.spinner("正在為您同步 Lewisham 最新在地資訊..."):
    items, errors = load_all_sources()

all_sources = list(RSS_FEEDS) + [EVENTS_SOURCE]
columns = ["Title", "Link", "Published", "Source", "Area", "Type"]
all_data = pd.DataFrame(items, columns=columns)
all_data["Published"] = pd.to_datetime(all_data["Published"], utc=True).dt.tz_convert(LONDON)
all_data = all_data.drop_duplicates(subset="Link")
all_data = all_data.sort_values("Published", ascending=False, na_position="last")

for source_name, message in errors.items():
    st.sidebar.warning(f"無法讀取 {source_name}：{message}", icon="⚠️")

selected_source = st.sidebar.multiselect("選擇資訊來源", options=all_sources, default=all_sources)
selected_area = st.sidebar.selectbox("選擇社區區域", ["All Areas"] + NEIGHBOURHOODS + [BOROUGH_WIDE])
keyword = st.sidebar.text_input("關鍵字搜尋", placeholder="例如：market, library")

st.sidebar.caption(f"最後更新：{datetime.now(LONDON):%Y-%m-%d %H:%M}（倫敦時間）")

# 過濾資料
filtered_df = all_data[all_data["Source"].isin(selected_source)]
if selected_area != "All Areas":
    filtered_df = filtered_df[filtered_df["Area"] == selected_area]
if keyword.strip():
    filtered_df = filtered_df[filtered_df["Title"].str.contains(keyword.strip(), case=False, regex=False)]

st.subheader(f"最新消息與活動 ({len(filtered_df)} 筆)")

if all_data.empty:
    st.error("目前無法從任何來源取得資料，請稍後再試或按左側「重新整理資料」。")
elif filtered_df.empty:
    st.info("沒有符合篩選條件的項目，請調整左側的篩選條件。")

for row in filtered_df.itertuples(index=False):
    with st.container():
        col1, col2 = st.columns([4, 1])
        with col1:
            prefix = "🎉 [活動] " if row.Type == "文化活動" else ""
            safe_link = row.Link.replace("(", "%28").replace(")", "%29").replace(" ", "%20")
            st.markdown(f"### [{prefix}{md_escape(row.Title)}]({safe_link})")
            st.caption(
                f"📍 **區域:** {row.Area} | 📰 **來源:** {row.Source} | 🕒 {format_published(row.Published)}"
            )
        with col2:
            st.link_button("查看詳情 ↗️", row.Link)
        st.divider()
