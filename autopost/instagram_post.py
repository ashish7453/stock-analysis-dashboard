"""Make the dashboard's charts as Instagram images and post them automatically.

Run by GitHub Actions (.github/workflows/instagram.yml) on a schedule:

  india-daily  trading days ~7:45 PM IST  bar charts: NSE sectoral, NSE thematic,
                                          Nifty 50 stocks, NSE sector 30/60/90-day
                                          strongest & weakest (one carousel)
  us-daily     Tue-Sat ~7:30 AM IST       bar charts: USA sectors, USA themes for the
                                          US session that just closed
  weekly       Saturday ~9:00 AM IST      the Mon-Fri week as bar charts: NSE sectoral,
                                          NSE thematic, Nifty 50, USA sectors, USA
                                          themes, NSE sector rankings
  global-daily Tue-Sat ~8:00 AM IST       world indices and commodities for the day that
                                          just closed, world indices 30/60/90-day
                                          strongest & weakest
  global-weekly Saturday ~9:30 AM IST     world indices and commodities for the week,
                                          currencies vs USD over one month, world
                                          indices 30/60/90-day strongest

Safety checks: nothing is posted on market holidays (the data must be dated the
expected day), and each post is made only once (posted.json on the
social-posts branch remembers what went out).

Run by hand:
  python autopost/instagram_post.py --mode india-daily --dry-run   # images only
  python autopost/instagram_post.py --mode weekly                  # make + post

Environment (GitHub secrets): IG_ACCESS_TOKEN, optional IG_USER_ID and GH_PAT
(lets the script save the refreshed Instagram token back into the secret).
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock-chart-app-main"))
import app as core      # noqa: E402  (the dashboard's calculation module)
import charts           # noqa: E402

IST, NY = ZoneInfo("Asia/Kolkata"), ZoneInfo("America/New_York")
W, H = charts.SOCIAL_SIZES["Instagram portrait (1080×1350)"]
FOOTER = "rscreener.com"
# Two kinds of Instagram token work:
#  - Instagram Login token ("IG..."), 60 days, refreshed on each run -> graph.instagram.com
#  - Meta Unified/Facebook Login system-user token ("EAA..."), never expires -> graph.facebook.com
#    (needs IG_USER_ID = the Instagram business account ID)
GRAPH_IG = "https://graph.instagram.com/v23.0"
GRAPH_FB = "https://graph.facebook.com/v23.0"
BRANCH = "social-posts"        # branch that holds the images Instagram downloads
DISCLAIMER = "For education only, not investment advice."
TAGS_IN = "#Nifty #Nifty50 #NSE #SectorRotation #IndianStockMarket #StockMarketIndia #SwingTrading"
TAGS_US = "#StockMarket #SP500 #Nasdaq #SectorRotation #ETF #USStocks #Investing"
TAGS_GLOBAL = "#GlobalMarkets #WorldIndices #StockMarket #Commodities #Gold #CrudeOil #Nifty #Investing"


class Skip(Exception):
    """Data is not there for the expected day (holiday, or not published yet)."""


# ------------------------------------------------------------------ helpers
def log(*a):
    print(*a, flush=True)


def short_nse(df):
    """'Nifty PSU Bank' -> 'PSU Bank' (same as the dashboard's charts)."""
    d = df.copy()
    d["Name"] = d["Name"].str.replace(r"^Nifty\s*", "", regex=True, case=False).str.strip().replace("", "Nifty")
    return d


def check_fresh(df, ok, what):
    """Keep rows whose Last Date passes `ok`; skip the chart if most rows fail
    (the market was shut, or the day's data is not out yet)."""
    d = df.dropna(subset=["Gain (%)"])
    good = d[d["Last Date"].map(lambda x: ok(pd.Timestamp(x).date()))]
    if len(good) < 0.7 * max(1, len(d)):
        last = max((pd.Timestamp(x).date() for x in d["Last Date"]), default=None)
        raise Skip(f"{what}: latest data is {last}, not the expected day")
    return good.reset_index(drop=True)


def movers(df, n=3, name="Name"):
    d = df.dropna(subset=["Gain (%)"]).sort_values("Gain (%)", ascending=False)
    fmt = lambda r: f"{r[name]} {r['Gain (%)']:+.2f}%"
    return ", ".join(map(fmt, d.head(n).to_dict("records"))), \
        ", ".join(map(fmt, d.tail(n).iloc[::-1].to_dict("records")))


def save(fig, path):
    """Instagram portrait JPEG (1080x1350), same look as the app's Instagram size."""
    fig = charts.social_layout(fig, W, H, footer=FOOTER, sideways_min=2)   # every bar list sideways
    png = path.with_suffix(".png")
    fig.write_image(png, width=W // 2, height=H // 2, scale=2)
    Image.open(png).convert("RGB").save(path, "JPEG", quality=92, optimize=True)
    png.unlink()
    log("  saved", path.name)


def day_label(d):
    return f"{d:%a %d %b %Y}"


def week_label(a, b):
    return f"{a:%d %b} to {b:%d %b %Y}"


# ------------------------------------------------------------------- charts
def nse_bars(start, end, ok, label):
    """Ranked bars of NSE sectoral and thematic indices (one chart each)."""
    df, info = core.nse_index_stats(str(start), str(end), ex="NSE")
    df = short_nse(check_fresh(df[df["Category"].isin(["Sectoral", "Thematic"])], ok, "NSE indices"))
    figs = [(charts.ranked_bars(df[df["Category"] == c], f"NSE {c} Indices: {label}"), f"nse-{c.lower()}")
            for c in ("Sectoral", "Thematic") if (df["Category"] == c).any()]
    top, bottom = movers(df[df["Category"] == "Sectoral"])
    return figs, f"🇮🇳 NSE sectors {label}\n🟢 {top}\n🔴 {bottom}"


def nifty50_bars(start, end, ok, label):
    cons, _ = core.load_constituents("nifty50", refresh=False)
    names = dict(zip(cons["Yahoo"], cons["Symbol"]))
    df = check_fresh(core.range_stats(names, str(start), str(end)), ok, "Nifty 50")
    top, bottom = movers(df)
    return charts.ranked_bars(df, f"Nifty 50 Stocks: {label}"), f"📈 Nifty 50 stocks\n🟢 {top}\n🔴 {bottom}"


def nse_rankings(ref, ok, which_list=("strongest", "weakest"), n=5):
    raw, info = core.nse_index_returns(str(ref), ex="NSE")
    if not ok(pd.Timestamp(info["last_day"]).date()):
        raise Skip(f"NSE rankings: latest data is {info['last_day']}")
    df = short_nse(core.rank_returns(raw[raw["Category"] == "Sectoral"]))
    asof = pd.Timestamp(info["last_day"])
    figs = [charts.window_bars(df, w, n=n, title_prefix=f"NSE Sector Rankings ({asof:%d %b %Y}): ")
            for w in which_list]
    best = ", ".join(df.sort_values("Sum of Ranks")["Name"].head(3))
    return [f for f in figs if f is not None], f"🏆 Strongest NSE sectors over 30/60/90 days: {best}"


def us_bars(start, end, ok, label):
    """Ranked bars of USA sector indices and thematic indices/ETFs (one chart each)."""
    names = {s: n for s, (n, _) in core.US_INDICES.items()}
    cat = {s: c for s, (_, c) in core.US_INDICES.items()}
    df = core.range_stats(names, str(start), str(end))
    df.insert(1, "Category", df["Symbol"].map(cat))
    df = check_fresh(df[df["Category"].isin(["Sectoral", "Thematic"])], ok, "USA indices")
    figs = [(charts.ranked_bars(df[df["Category"] == c], f"USA {t}: {label}"), f"us-{c.lower()}")
            for c, t in (("Sectoral", "Sectors"), ("Thematic", "Themes"))
            if (df["Category"] == c).any()]
    top, bottom = movers(df)
    return figs, f"🇺🇸 USA sectors & themes {label}\n🟢 {top}\n🔴 {bottom}"


def range_bars(names, start, end, ok, title, what, emoji, n=3):
    """Ranked bars for a {symbol: name} list over a date range (world indices,
    commodities, currencies); rows not dated the expected day are left out."""
    df = check_fresh(core.range_stats(names, str(start), str(end)), ok, what)
    top, bottom = movers(df, n)
    return charts.ranked_bars(df, title), f"{emoji} {what}\n🟢 {top}\n🔴 {bottom}"


def world_rankings(ref, ok, which_list=("strongest", "weakest"), n=5):
    """World indices ranked on 30/60/90-day returns (the World Indices tool)."""
    df = core.compute_index_returns(core.WORLD_INDICES, reference_date=str(ref))
    last = max(pd.Timestamp(x).date() for x in df["Last Date"].dropna())
    if not ok(last):
        raise Skip(f"World rankings: latest data is {last}")
    figs = [charts.window_bars(df, w, n=n, title_prefix=f"World Indices ({last:%d %b %Y}): ")
            for w in which_list]
    best = ", ".join(df.dropna(subset=["Sum of Ranks"]).sort_values("Sum of Ranks")["Name"].head(3))
    return [f for f in figs if f is not None], f"🏆 Strongest world indices over 30/60/90 days: {best}"


# -------------------------------------------------------------------- posts
def build(mode, out):
    """Make the images for `mode` in `out`. Returns (key, caption, [jpg paths])."""
    now_ist = dt.datetime.now(IST)
    parts, files = [], []

    def add(fig, name):
        p = out / f"{len(files) + 1:02d}-{name}.jpg"
        save(fig, p)
        files.append(p)

    def attempt(label, fn):
        try:
            fn()
        except Skip as e:
            log("  skipped:", e)
        except Exception as e:                      # one failing chart shouldn't stop the rest
            log(f"  {label} failed: {type(e).__name__}: {e}")

    if mode == "india-daily":
        day = now_ist.date()
        if day.weekday() >= 5:
            raise Skip("weekend")
        key, lab, ok = f"india-daily:{day}", day_label(day), (lambda d: d == day)

        def a():
            figs, txt = nse_bars(day, day, ok, lab)
            for f, nm in figs:
                add(f, nm)
            parts.append(txt)

        def b():
            fig, txt = nifty50_bars(day, day, ok, lab); add(fig, "nifty50"); parts.append(txt)

        def c():
            figs, txt = nse_rankings(day, ok)
            for f, w in zip(figs, ("strongest", "weakest")):
                add(f, f"nse-rank-{w}")
            parts.append(txt)
        for lbl, fn in (("NSE indices", a), ("Nifty 50", b), ("NSE rankings", c)):
            attempt(lbl, fn)
        head = f"📊 Indian market today, {lab}"
        tags = TAGS_IN
    elif mode == "us-daily":
        day = dt.datetime.now(NY).date()               # the US session that just closed
        if day.weekday() >= 5:
            raise Skip("weekend in New York")
        key, lab, ok = f"us-daily:{day}", day_label(day), (lambda d: d == day)

        def u():
            figs, txt = us_bars(day, day, ok, lab)
            for f, nm in figs:
                add(f, nm)
            parts.append(txt)
        attempt("USA indices", u)
        head = f"📊 US market, {lab}"
        tags = TAGS_US
    elif mode == "weekly":
        friday = now_ist.date() - dt.timedelta(days=(now_ist.weekday() - 4) % 7)
        monday = friday - dt.timedelta(days=4)
        key, lab = f"weekly:{monday}", week_label(monday, friday)
        ok = lambda d: monday <= d <= friday              # last trading day of the week

        def a():
            figs, txt = nse_bars(monday, friday, ok, lab)
            for f, nm in figs:
                add(f, nm + "-week")
            parts.append(txt)

        def b():
            fig, txt = nifty50_bars(monday, friday, ok, lab); add(fig, "nifty50-week"); parts.append(txt)

        def u():
            figs, txt = us_bars(monday, friday, ok, lab)
            for f, nm in figs:
                add(f, nm + "-week")
            parts.append(txt)

        def c():
            figs, txt = nse_rankings(friday, ok, which_list=("strongest",))
            for f in figs:
                add(f, "nse-rank-strongest")
            parts.append(txt)
        for lbl, fn in (("NSE week", a), ("Nifty 50 week", b), ("USA week", u), ("NSE rankings", c)):
            attempt(lbl, fn)
        head = f"🗓️ Week in markets, {lab}"
        tags = "#WeeklyRecap #Nifty #NSE #IndianStockMarket #SP500 #StockMarket #SectorRotation #SwingTrading"
    elif mode in ("global-daily", "global-weekly"):
        if mode == "global-daily":
            end = dt.datetime.now(NY).date()           # the session that just closed in New York
            if end.weekday() >= 5:
                raise Skip("weekend in New York")
            start, key, lab = end, f"global-daily:{end}", day_label(end)
            ok = lambda d, e=end: d == e
            head, extra = f"🌍 Global markets, {lab}", []
        else:
            end = now_ist.date() - dt.timedelta(days=(now_ist.weekday() - 4) % 7)   # last Friday
            start = end - dt.timedelta(days=4)
            key, lab = f"global-weekly:{start}", week_label(start, end)
            ok = lambda d, a=start, b=end: a <= d <= b
            head = f"🌍 Global markets this week, {lab}"
            # Currencies: one month to Friday (base = close one month earlier)
            m0 = (pd.Timestamp(end) - pd.DateOffset(months=1) + pd.Timedelta(days=1)).date()
            extra = [("Currencies vs USD", core.CURRENCIES, m0,
                      f"Currencies vs USD, 1 month: {m0 - dt.timedelta(days=1):%d %b} to {end:%d %b %Y}",
                      "Currencies vs USD (1 month)", "💱", "currencies-1m")]

        def g():
            fig, txt = range_bars(core.WORLD_INDICES, start, end, ok, f"World Indices: {lab}",
                                  "World indices", "🌍")
            add(fig, "world-indices"); parts.append(txt)

        def m():
            fig, txt = range_bars(core.COMMODITIES, start, end, ok, f"Commodities: {lab}",
                                  "Commodities", "🛢️")
            add(fig, "commodities"); parts.append(txt)

        def fx():
            for _, names, s0, title, what, emo, nm in extra:
                fig, txt = range_bars(names, s0, end, ok, title, what, emo)
                add(fig, nm); parts.append(txt)

        def r():
            which = ("strongest", "weakest") if mode == "global-daily" else ("strongest",)
            figs, txt = world_rankings(end, ok, which)
            for f, w in zip(figs, which):
                add(f, f"world-rank-{w}")
            parts.append(txt)
        for lbl, fn in (("World indices", g), ("Commodities", m), ("Currencies", fx), ("World rankings", r)):
            attempt(lbl, fn)
        tags = TAGS_GLOBAL + (" #Forex #WeeklyRecap" if mode == "global-weekly" else "")
    else:
        raise SystemExit(f"unknown mode {mode}")

    swipe = "\n\nSwipe ➡️ for all charts." if len(files) > 1 else ""
    caption = (f"{head}\n\n" + "\n\n".join(parts) + swipe +
               f"\n\nMore free tools: {FOOTER}\n{DISCLAIMER}\n\n{tags}")
    return key, caption[:2150], files


# ------------------------------------------------------- hosting (GitHub)
def git(*args, cwd=ROOT, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


class Host:
    """Images live on the `social-posts` branch (one commit, replaced each run),
    so Instagram can download them from raw.githubusercontent.com. That branch
    also keeps posted.json, the list of posts already made."""

    def __init__(self):
        self.repo = os.environ.get("GITHUB_REPOSITORY") or self._repo_from_remote()
        self.dir = Path(tempfile.mkdtemp(prefix="social-"))
        have = git("ls-remote", "--heads", "origin", BRANCH)
        if have:
            git("fetch", "-q", "origin", f"{BRANCH}:refs/remotes/origin/{BRANCH}")
            git("worktree", "add", "-q", "--detach", str(self.dir), f"origin/{BRANCH}")
        else:
            git("worktree", "add", "-q", "--detach", str(self.dir), "HEAD")
        git("checkout", "-q", "--orphan", f"tmp-{os.getpid()}", cwd=self.dir)
        p = self.dir / "posted.json"
        self.posted = json.loads(p.read_text()) if have and p.exists() else {}
        git("rm", "-rq", "--cached", ".", cwd=self.dir, check=False)
        for f in self.dir.iterdir():
            if f.name != ".git":
                shutil.rmtree(f) if f.is_dir() else f.unlink()

    @staticmethod
    def _repo_from_remote():
        url = git("remote", "get-url", "origin")
        return re.sub(r"(\.git)?$", "", url.split("github.com")[-1].lstrip("/:"))

    def publish(self, files, message):
        """Commit files + posted.json as the branch's only commit; return raw URLs."""
        (self.dir / "posted.json").write_text(json.dumps(self.posted, indent=1, sort_keys=True))
        names = []
        if files:
            (self.dir / "img").mkdir(exist_ok=True)
            for f in files:
                shutil.copy(f, self.dir / "img" / f.name)
                names.append(f"img/{f.name}")
        git("add", "-A", cwd=self.dir)
        git("-c", "user.name=github-actions[bot]",
            "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "commit", "-qm", message, cwd=self.dir)
        git("push", "-qf", "origin", f"HEAD:refs/heads/{BRANCH}", cwd=self.dir)
        sha = git("rev-parse", "HEAD", cwd=self.dir)
        urls = [f"https://raw.githubusercontent.com/{self.repo}/{sha}/{n}" for n in names]
        for u in urls:                                     # wait until GitHub serves them
            for _ in range(20):
                if requests.head(u, timeout=20).status_code == 200:
                    break
                time.sleep(3)
            else:
                raise RuntimeError(f"image not reachable: {u}")
        return urls

    def close(self):
        git("worktree", "remove", "--force", str(self.dir), check=False)


# ---------------------------------------------------------------- Instagram
class Instagram:
    def __init__(self):
        self.token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
        if not self.token:
            raise SystemExit("IG_ACCESS_TOKEN is not set: add it under the repo's Settings -> "
                             "Secrets and variables -> Actions (see autopost/README.md).")
        self.facebook = not self.token.startswith("IG")
        self.graph = GRAPH_FB if self.facebook else GRAPH_IG
        self.uid = os.environ.get("IG_USER_ID", "").strip()
        if not self.uid:
            if self.facebook:
                raise SystemExit("IG_USER_ID is not set: a Meta system-user token needs the "
                                 "Instagram business account ID (see autopost/README.md).")
            self.uid = "me"

    def call(self, method, path, **params):
        r = requests.request(method, f"{self.graph}/{path}",
                             params={**params, "access_token": self.token}, timeout=60)
        try:
            data = r.json()
        except ValueError:
            data = {"error": {"message": r.text[:300]}}
        if r.status_code >= 400 or "error" in data:
            raise RuntimeError(f"Instagram {path}: {data.get('error', data)}")
        return data

    def refresh_token(self):
        """Long-lived tokens last 60 days; refreshing on every run keeps them alive.
        If a GH_PAT secret is set, a changed token is saved back to the secret.
        System-user tokens never expire, so they are left alone."""
        if self.facebook:
            return
        try:
            r = requests.get("https://graph.instagram.com/refresh_access_token",
                             params={"grant_type": "ig_refresh_token", "access_token": self.token},
                             timeout=30).json()
        except Exception as e:
            log("  token refresh failed (continuing):", e)
            return
        new = r.get("access_token")
        if not new:
            log("  token refresh skipped:", r.get("error", {}).get("message", r))
            return
        print(f"::add-mask::{new}")
        days = int(r.get("expires_in", 0)) // 86400
        log(f"  Instagram token refreshed, valid {days} more days")
        if new != self.token:
            self.token = new
            if os.environ.get("GH_PAT"):
                subprocess.run(["gh", "secret", "set", "IG_ACCESS_TOKEN", "--body", new,
                                "--repo", os.environ.get("GITHUB_REPOSITORY", "")],
                               env={**os.environ, "GH_TOKEN": os.environ["GH_PAT"]}, check=False)
                log("  new token saved to the IG_ACCESS_TOKEN secret")
            else:
                log("::warning::Instagram gave a new token but GH_PAT is not set, so it "
                    "could not be saved. Update the IG_ACCESS_TOKEN secret within 60 days.")

    def wait(self, cid):
        for _ in range(40):
            s = self.call("GET", cid, fields="status_code")["status_code"]
            if s == "FINISHED":
                return
            if s in ("ERROR", "EXPIRED"):
                raise RuntimeError(f"Instagram could not process media {cid}: {s}")
            time.sleep(5)
        raise RuntimeError(f"Instagram media {cid} not ready after 200 s")

    def post(self, urls, caption):
        if len(urls) == 1:
            cid = self.call("POST", f"{self.uid}/media", image_url=urls[0], caption=caption)["id"]
        else:
            kids = []
            for u in urls[:10]:
                kid = self.call("POST", f"{self.uid}/media", image_url=u, is_carousel_item="true")["id"]
                self.wait(kid)
                kids.append(kid)
            cid = self.call("POST", f"{self.uid}/media", media_type="CAROUSEL",
                            children=",".join(kids), caption=caption)["id"]
        self.wait(cid)
        return self.call("POST", f"{self.uid}/media_publish", creation_id=cid)["id"]


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", required=True, choices=["india-daily", "us-daily", "weekly", "global-daily", "global-weekly"])
    ap.add_argument("--dry-run", action="store_true", help="make the images and caption only")
    ap.add_argument("--force", action="store_true", help="post even if this post was already made")
    ap.add_argument("--out", default=str(ROOT / "social-out"))
    a = ap.parse_args()

    out = Path(a.out)
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    log(f"== {a.mode} ({dt.datetime.now(IST):%Y-%m-%d %H:%M} IST)")
    try:
        key, caption, files = build(a.mode, out)
    except Skip as e:
        log("Nothing to post:", e)
        return
    (out / "caption.txt").write_text(caption, encoding="utf-8")
    log(f"\n--- caption ({len(caption)} chars) ---\n{caption}\n---")
    if not files:
        log("Nothing to post: no chart had data for the expected day (market holiday?)")
        return
    if a.dry_run:
        log(f"Dry run: {len(files)} image(s) in {out}, nothing posted.")
        return

    host = Host()
    try:
        if key in host.posted and not a.force:
            log(f"Already posted {key} on {host.posted[key]['at']}; skipping.")
            return
        ig = Instagram()
        ig.refresh_token()
        urls = host.publish(files, f"images for {key}")
        media = ig.post(urls, caption)
        host.posted[key] = {"at": dt.datetime.now(IST).isoformat(timespec="minutes"),
                            "media_id": media, "images": len(urls)}
        host.publish([], f"posted {key}")                  # record it; drop the images
        log(f"Posted {key}: Instagram media {media}")
    finally:
        host.close()


if __name__ == "__main__":
    main()
