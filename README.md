# Lewisham Local Hub

A Streamlit site that collects Lewisham local news, discussion and events from four sources:

| Source | Method |
| --- | --- |
| Reddit r/lewisham | RSS |
| Lewisham Loop newsletter (Beehiiv) | RSS |
| Lewisham Council news | RSS, falling back to reading the news page |
| We Are Lewisham events | Reads the web page (schema.org event data first, then event cards) |

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy

On [Streamlit Community Cloud](https://streamlit.io/cloud), connect this repository and set the main file to `app.py`. Streamlit installs the packages in `requirements.txt` for you.

Feeds refresh every 30 minutes and events every hour. The **重新整理資料** (refresh) button in the sidebar forces an immediate refresh.
