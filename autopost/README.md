# Automatic Instagram posts

GitHub Actions makes the dashboard's charts as Instagram images (1080×1350
bar charts) and posts them to your Instagram account on a schedule. No
computer of yours needs to be on.

| Post | When (IST) | Slides |
|---|---|---|
| India daily | Mon–Fri ~7:45 PM | NSE sectoral, NSE thematic, Nifty 50 stocks, NSE sector 30/60/90-day strongest 5, weakest 5 |
| USA daily | Tue–Sat ~7:30 AM | USA sectors, USA themes (the US session that closed overnight) |
| Weekly recap | Saturday ~9:00 AM | Mon–Fri week: NSE sectoral, NSE thematic, Nifty 50, USA sectors, USA themes, NSE sector rankings |
| Global daily | Tue–Sat ~8:00 AM | World indices and commodities for the day that just closed, world indices 30/60/90-day strongest 5 and weakest 5 |
| Global weekly | Saturday ~9:30 AM | World indices and commodities for the week, currencies vs USD over one month, world indices 30/60/90-day strongest 5 |

Each post gets a caption with the top 3 and bottom 3, a note pointing to
rscreener.com, a "not investment advice" line and hashtags.

**Safety checks**
- Nothing is posted on market holidays. Each chart's data must be dated the
  expected day; a chart without fresh data is left out, and if none has
  data, nothing is posted.
- Each post goes out only once. The `social-posts` branch keeps
  `posted.json`, a list of what was posted.
- GitHub often starts scheduled runs 10–30 minutes late. That is normal.

---

## One-time setup (about 20 minutes)

### 1. Make your Instagram account a professional account

In the Instagram app, go to **Settings → Account type and tools → Switch to
professional account**. Choose **Creator** or **Business**; either works,
and it's free. Instagram only allows automatic posting for professional
accounts.

### 2. Create a Meta app and get an access token

1. Go to <https://developers.facebook.com/apps> and log in. Accept the
   developer terms if asked.
2. **Create app**. For the use case, pick **Manage messaging & content on
   Instagram** (Instagram API). Give it any name, e.g. *rscreener poster*.
3. In the app, open **Instagram → API setup with Instagram business login**.
4. Under **Generate access tokens**, click **Add account** and log in with
   your Instagram account. Allow the permissions it asks for. The ones this
   needs are `instagram_business_basic` and
   `instagram_business_content_publish`.
5. Click **Generate token** next to your account and copy the token. This
   is a long-lived token, valid for 60 days; the workflow refreshes it on
   every run.
6. Optional: copy the numeric **Instagram user ID** shown next to the
   account.

You only post to your own account, so the app can stay in Development mode
and does not need Meta's App Review.

### 3. Add the secrets to GitHub

In the repo, go to **Settings → Secrets and variables → Actions → New
repository secret**:

| Name | Value |
|---|---|
| `IG_ACCESS_TOKEN` | the token from step 2.5 (required) |
| `IG_USER_ID` | the user ID from step 2.6 (optional; the token's own account is used if empty) |
| `GH_PAT` | optional, see below |

**`GH_PAT` (recommended):** if Instagram ever hands back a *new* token
string when refreshing, the workflow saves it into `IG_ACCESS_TOKEN`
automatically. Without `GH_PAT`, you get a warning in the run log and
must paste a fresh token within 60 days.

To create it: on GitHub, go to **Settings (your profile) → Developer
settings → Fine-grained tokens → Generate new token**. Set **Repository
access** to *Only select repositories → stock-analysis-dashboard*, and
under **Permissions → Secrets** choose *Read and write*. Copy the token
into a secret named `GH_PAT`.

### 4. Allow the workflow to push

Go to **Settings → Actions → General → Workflow permissions** and choose
**Read and write permissions**, then click **Save**. The workflow pushes
the images to the `social-posts` branch, because Instagram downloads each
image from a public link.

### 5. Test, then go live

1. Open the **Actions** tab, select **Instagram posts**, and click **Run
   workflow**.
2. Pick a post type and leave **Dry run** ticked. When the run finishes,
   download the images from **Artifacts** at the bottom of the run page.
   The caption is in `caption.txt`.
3. Run it again with **Dry run** unticked to post for real. If that post
   was already made today, tick **Force** to post it again.
4. From then on, the schedule runs by itself.

---

## Changing things

- **Times:** edit the `cron:` lines in `.github/workflows/instagram.yml`.
  Cron times are UTC; IST = UTC + 5:30. Keep the `case` lines below them in
  step with the cron lines.
- **Charts, captions, hashtags:** edit `autopost/instagram_post.py`. Look
  for `TAGS_IN`, `TAGS_US`, `FOOTER` and `DISCLAIMER` near the top.
- **Pause posting:** go to **Actions → Instagram posts → ⋯ → Disable
  workflow**.

GitHub turns off scheduled workflows in repos with no activity for 60 days.
If the Actions tab shows a banner about that, click **Enable workflow**.

## Troubleshooting

- **Run fails with an Instagram error about the token:** the token
  expired or was revoked. Generate a new one (step 2.5) and update
  `IG_ACCESS_TOKEN`.
- **A slide is missing from a post:** that chart had no data for the day.
  The run log says why, e.g. "skipped: NSE indices: latest data is …".
  NSE sometimes publishes its end-of-day file late; you can re-run that
  day's post by hand later, with **Force** ticked.
- **Instagram limit:** 50 automatic posts per day. This schedule uses at
  most 3.
