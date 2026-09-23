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

## Local business ads (optional)

A "Local businesses" column lets businesses submit a free ad (name, description, neighbourhood, website, phone, contact email and an optional image). Ads only appear once you approve them.

**Set-up (once):** in Supabase, open **SQL Editor**, run the contents of `supabase_ads_setup.sql`. It uses the same Secrets as the visitor counter.

**Approving an ad:** in Supabase, open **Table Editor → business_ads**, tick `approved` on the row and save. It appears on the site within 5 minutes. Optionally set `expires_on` to a date after which the ad disappears. To remove an ad, untick `approved` or delete the row.

Contact emails are stored for you only and are never shown on the site.

**Email alerts for new ads (optional):** create a Gmail App Password (Google Account → Security → 2-Step Verification → App passwords) and add an `[email]` section to the Streamlit Secrets, as in `.streamlit/secrets.toml.example`. Each new submission then emails you its details and a link to approve it.
