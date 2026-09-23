# Lewisham Local Hub

A Streamlit site that collects Lewisham local news, discussion and events from four sources:

| Source | Method |
| --- | --- |
| Reddit r/lewisham | RSS |
| The Lewisham Letter (Substack) | RSS |
| Lewisham Council news | RSS, falling back to reading the news page |
| We Are Lewisham events | Reads the web page (schema.org event data, then event cards, then links to `/events/<slug>/`) |

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy

On [Streamlit Community Cloud](https://streamlit.io/cloud), connect this repository and set the main file to `app.py`. Streamlit installs the packages in `requirements.txt` for you.

Feeds refresh every 30 minutes and events every hour. The **Refresh data** button in the sidebar forces an immediate refresh.

## Visitor counter (optional)

The sidebar shows a lasting visit count stored in [Supabase](https://supabase.com) (free plan). Without this set-up the counter is simply hidden.

1. Create a free Supabase project.
2. In **SQL Editor**, run the contents of `supabase_setup.sql`.
3. In **Project Settings → API Keys**, copy the project URL and the publishable (or `anon`) key.
4. In Streamlit Cloud, go to **Manage app → ⋮ → Settings → Secrets** and paste the lines from `.streamlit/secrets.toml.example` with your values filled in.
