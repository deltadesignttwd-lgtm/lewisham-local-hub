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

# 1. Page set-up
st.set_page_config(page_title="Lewisham Local Hub", page_icon="🦁", layout="wide")

LONDON = ZoneInfo("Europe/London")
REQUEST_TIMEOUT = 10  # seconds; stops one slow site from holding up the whole page
# Sites such as Reddit block scrapers pretending to be browsers; they ask for an identifiable User-Agent
HEADERS = {"User-Agent": "LewishamLocalHub/1.0 (community news aggregator)"}
ITEMS_PER_SOURCE = 8
MAX_EVENTS = 12

# Each source can list several candidate URLs; they are tried in order and the first that works is used
RSS_FEEDS = {
    "Reddit (r/lewisham)": [
        "https://www.reddit.com/r/lewisham/new/.rss",
        "https://old.reddit.com/r/lewisham/new/.rss",
    ],
    # The original lewisham-loop.beehiiv.com/feed returned 404 (no such newsletter), so The Lewisham Letter is used instead
    "The Lewisham Letter": [
        "https://thelewishamletter.substack.com/feed",
    ],
    "Lewisham Council News": [
        "https://lewisham.gov.uk/news/rss",
        "https://lewisham.gov.uk/news/rss.xml",
        # Fallback: Google News results for lewisham.gov.uk, which is a reliable RSS feed
        "https://news.google.com/rss/search?q=site:lewisham.gov.uk&hl=en-GB&gl=GB&ceid=GB:en",
    ],
}
COUNCIL_SOURCE = "Lewisham Council News"
COUNCIL_NEWS_PAGE = "https://lewisham.gov.uk/news"
EVENTS_SOURCE = "We Are Lewisham"
EVENTS_URL = "https://www.wearelewisham.com/events/"
# List view is usually plain server-rendered HTML, which is easier to parse than the default page
EVENTS_PAGES = [EVENTS_URL + "?display=list", EVENTS_URL]

# 2. Neighbourhood keywords
# "Lewisham" appears in almost every title (e.g. "Lewisham Council"), so it is checked last
# to let the more specific neighbourhood names take priority.
NEIGHBOURHOODS = [
    "Brockley", "Catford", "Deptford", "New Cross", "Sydenham", "Blackheath",
    "Forest Hill", "Ladywell", "Hither Green", "Lee", "Honor Oak", "Crofton Park",
    "Bellingham", "Downham", "Grove Park", "Lewisham",
]
BOROUGH_WIDE = "Borough-wide"
# Whole-word matching, so "Lee" does not match "Leeds" or "sleep"
_AREA_PATTERNS = [(area, re.compile(rf"\b{re.escape(area)}\b", re.IGNORECASE)) for area in NEIGHBOURHOODS]


def categorise_title(title):
    text = str(title)
    for area, pattern in _AREA_PATTERNS:
        if area == "Lewisham":
            # Only tag as Lewisham when it clearly means the town centre; otherwise treat it as borough-wide news
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
        "Published": published,  # timezone-aware datetime or None
        "Source": source,
        "Area": categorise_title(title),
        "Type": item_type,
    }


def _http_get(url):
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response


def _page_diagnostics(response, soup):
    """Describe what was actually fetched when scraping fails, to help diagnose the site's structure."""
    title = soup.title.get_text(strip=True) if soup.title else "(no title)"
    hrefs = [a["href"] for a in soup.find_all("a", href=True)]
    sample = ", ".join(hrefs[:15]) or "(none)"
    return (
        f"final URL {response.url}, HTTP {response.status_code}, page title \"{title[:80]}\", "
        f"{len(response.text)} characters of HTML, {len(hrefs)} links, e.g. {sample}"
    )


def _entry_datetime(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc).astimezone(LONDON)


# 3. RSS sources (Reddit, The Lewisham Letter, Council)
# Note: failures raise an exception. st.cache_data does not cache exceptions,
# so if a site is briefly down it is retried on the next refresh rather than staying empty for 30 minutes.
def _try_each(urls, fetch_one):
    """Try each URL in turn and return the first success; if all fail, raise a combined error."""
    failures = []
    for url in urls:
        try:
            return fetch_one(url)
        except Exception as e:
            failures.append(f"{url} → {e}")
    raise RuntimeError("; ".join(failures))


@st.cache_data(ttl=1800, show_spinner=False)  # refresh automatically every 30 minutes
def fetch_rss_source(source_name, urls):
    return _try_each(urls, lambda url: _fetch_one_feed(source_name, url))


def _fetch_one_feed(source_name, url):
    # feedparser has no timeout and does not raise network errors, so download with requests first
    feed = feedparser.parse(_http_get(url).content)
    if not feed.entries:
        # If the URL returns an ordinary web page rather than RSS, feedparser may not complain; it just finds 0 entries
        reason = feed.get("bozo_exception") or "the response is not RSS or has no entries"
        raise ValueError(f"could not parse RSS: {reason}")

    items = []
    for entry in feed.entries[:ITEMS_PER_SOURCE]:
        title = entry.get("title", "").strip()
        link = entry.get("link", "")
        if "news.google.com" in url:
            title = title.rsplit(" - ", 1)[0]  # strip the " - Source name" suffix Google News adds
        if title and link:
            items.append(make_item(title, link, _entry_datetime(entry), source_name, "News / discussion"))
    return items


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_council_news_page():
    """Fallback when the Council RSS fails: read the news links straight from the news page."""
    response = _http_get(COUNCIL_NEWS_PAGE)
    soup = BeautifulSoup(response.text, "html.parser")
    items, seen = [], set()
    for a in soup.find_all("a", href=True):
        link = urljoin(COUNCIL_NEWS_PAGE, a["href"])
        title = a.get_text(" ", strip=True)
        path = link.split("lewisham.gov.uk", 1)[-1].rstrip("/")
        if "/news/" not in path or path.endswith("/news") or link in seen or len(title) < 15:
            continue
        seen.add(link)
        items.append(make_item(title, link, None, COUNCIL_SOURCE, "News / discussion"))
        if len(items) >= ITEMS_PER_SOURCE:
            break
    if not items:
        raise ValueError(f"no news links found on the news page ({_page_diagnostics(response, soup)})")
    return items


# 4. We Are Lewisham cultural events (web scraping)
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
    """Many event sites embed schema.org Event data in the page, which is far more reliable than guessing CSS classes."""
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


# Event page URLs look like /events/<slug>/; filter links such as ?categories= are excluded
_EVENT_LINK = re.compile(r"^https?://(www\.)?wearelewisham\.com/events/[^/?#]+/?$")


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_we_are_lewisham_events():
    return _try_each(EVENTS_PAGES, _fetch_events_page)


def _fetch_events_page(page_url):
    response = _http_get(page_url)
    soup = BeautifulSoup(response.text, "html.parser")
    events, seen = [], set()

    def add(title, link, start):
        link = urljoin(page_url, link)
        if not title or link in seen or not _EVENT_LINK.match(link):
            return
        seen.add(link)
        events.append(make_item(title, link, start, EVENTS_SOURCE, "Event"))

    for event in _jsonld_events(soup):
        add(str(event.get("name", "")).strip(), event.get("url") or "", _parse_event_date(event.get("startDate")))

    if not events:
        # Fallback: look for cards whose class contains "event". Only the outermost cards are kept, so nested elements are not counted twice.
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
        # Last resort: collect every link on the page that points to a single event page
        for a in soup.find_all("a", href=True):
            title = a.get_text(" ", strip=True)
            if len(title) >= 4 and title.lower() not in {"read more", "more info", "book now", "view event"}:
                add(title, a["href"], None)

    if not events:
        raise ValueError(f"no event data found ({_page_diagnostics(response, soup)})")
    return events[:MAX_EVENTS]


# 5. Combine all data (each source is handled separately, so one failure does not affect the others)
def load_all_sources():
    """Return (all items, status of each source). A status is an item count (int) or an error message (str)."""
    items, status = [], {}
    for source_name, urls in RSS_FEEDS.items():
        try:
            found = fetch_rss_source(source_name, tuple(urls))
        except Exception as e:
            if source_name != COUNCIL_SOURCE:
                status[source_name] = str(e)
                continue
            try:
                found = fetch_council_news_page()
            except Exception as fallback_error:
                status[source_name] = f"RSS: {e}; news page: {fallback_error}"
                continue
        items += found
        status[source_name] = len(found)
    try:
        found = fetch_we_are_lewisham_events()
        items += found
        status[EVENTS_SOURCE] = len(found)
    except Exception as e:
        status[EVENTS_SOURCE] = str(e)
    return items, status


# 6. Visitor counter
# Streamlit Cloud wipes local files on every restart, so the count lives in Supabase.
# See supabase_setup.sql and the README for the one-off set-up.
def _supabase_config():
    """Return (url, key), or raise with a plain-English reason if the secrets are missing."""
    try:
        conf = st.secrets["supabase"]
    except Exception:
        raise RuntimeError("not set up: no [supabase] section in the app's Secrets") from None
    url, key = str(conf.get("url", "")).strip(), str(conf.get("key", "")).strip()
    if not url or not key:
        raise RuntimeError("the [supabase] Secrets need both a url and a key")
    # Accept the URL with or without a trailing slash or /rest/v1
    url = url.rstrip("/").removesuffix("/rest/v1").rstrip("/")
    return url, key


def _explain_counter_error(response):
    body = response.text[:200]
    if response.status_code in (401, 403):
        return f"Supabase rejected the key (HTTP {response.status_code}); use the publishable or anon key. {body}"
    if response.status_code == 404:
        return f"the increment_visits function was not found; run supabase_setup.sql in the SQL Editor. {body}"
    return f"HTTP {response.status_code}: {body}"


def record_visit():
    """Add one visit per browser session and return (total, error message)."""
    if "visit_count" not in st.session_state:
        # Set first, so a failure is not retried on every click in the same session
        st.session_state.visit_count, st.session_state.visit_error = None, None
        try:
            url, key = _supabase_config()
            response = requests.post(
                f"{url}/rest/v1/rpc/increment_visits",
                headers={"apikey": key, "Content-Type": "application/json"},
                json={},
                timeout=5,
            )
            if not response.ok:
                raise RuntimeError(_explain_counter_error(response))
            st.session_state.visit_count = int(response.json())
        except Exception as e:
            st.session_state.visit_error = str(e)
    return st.session_state.visit_count, st.session_state.visit_error


def md_escape(text):
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~])", r"\\\1", str(text))


def format_published(value):
    if value is None or pd.isna(value):
        return "Date not given"
    return value.strftime("%-d %b %Y, %H:%M")


# 7. UI
st.title("🦁 Lewisham Local Hub")
st.caption("Community discussion, local newsletters, Council news and cultural events, all in one place")

st.sidebar.header("🔍 Filters")
if st.sidebar.button("🔄 Refresh data"):
    st.cache_data.clear()

with st.spinner("Fetching the latest Lewisham news and events..."):
    items, source_status = load_all_sources()

all_sources = list(RSS_FEEDS) + [EVENTS_SOURCE]
columns = ["Title", "Link", "Published", "Source", "Area", "Type"]
all_data = pd.DataFrame(items, columns=columns)
all_data["Published"] = pd.to_datetime(all_data["Published"], utc=True).dt.tz_convert(LONDON)
all_data = all_data.drop_duplicates(subset="Link")
all_data = all_data.sort_values("Published", ascending=False, na_position="last")

visit_count, visit_error = record_visit()

with st.sidebar.expander(
    "📡 Source status", expanded=bool(visit_error) or any(isinstance(v, str) for v in source_status.values())
):
    for source_name, result in source_status.items():
        if isinstance(result, int):
            st.success(f"{source_name}: {result} {'item' if result == 1 else 'items'}", icon="✅")
        else:
            st.warning(f"Could not load {source_name}: {result}", icon="⚠️")
    if visit_error:
        st.warning(f"Visitor counter: {visit_error}", icon="⚠️")

selected_source = st.sidebar.multiselect("Sources", options=all_sources, default=all_sources)
selected_area = st.sidebar.selectbox("Neighbourhood", ["All Areas"] + NEIGHBOURHOODS + [BOROUGH_WIDE])
keyword = st.sidebar.text_input("Search by keyword", placeholder="e.g. market, library")

if visit_count is not None:
    st.sidebar.metric("👀 Visits", f"{visit_count:,}")

st.sidebar.caption(f"Last updated: {datetime.now(LONDON):%-d %b %Y, %H:%M} (UK time)")

# Apply filters
filtered_df = all_data[all_data["Source"].isin(selected_source)]
if selected_area != "All Areas":
    filtered_df = filtered_df[filtered_df["Area"] == selected_area]
if keyword.strip():
    filtered_df = filtered_df[filtered_df["Title"].str.contains(keyword.strip(), case=False, regex=False)]

st.subheader(f"Latest news and events ({len(filtered_df)})")

if all_data.empty:
    st.error("We couldn't load anything from any source just now. Please try again later or click \"Refresh data\" in the sidebar.")
elif filtered_df.empty:
    st.info("Nothing matches your filters. Try changing them in the sidebar.")

for row in filtered_df.itertuples(index=False):
    with st.container():
        col1, col2 = st.columns([4, 1])
        with col1:
            prefix = "🎉 [Event] " if row.Type == "Event" else ""
            safe_link = row.Link.replace("(", "%28").replace(")", "%29").replace(" ", "%20")
            st.markdown(f"### [{prefix}{md_escape(row.Title)}]({safe_link})")
            st.caption(
                f"📍 **Area:** {row.Area} | 📰 **Source:** {row.Source} | 🕒 {format_published(row.Published)}"
            )
        with col2:
            st.link_button("Read more ↗️", row.Link)
        st.divider()
