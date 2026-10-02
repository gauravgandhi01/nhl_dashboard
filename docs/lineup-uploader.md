# Laptop-to-Render lineup uploads

The laptop fetches Daily Faceoff using the existing parser and uploads parsed
team lineups to `POST /api/admin/lineups`. Render serves the snapshots through
the existing matchup API and Lines UI. No frontend changes or per-update
deployments are needed. This includes forward lines, defense pairs, power-play
units, and the goalies listed on team lineup pages. The separate daily
starting-goalie confirmation feed is not part of this upload.

## One-time setup

Run these commands from `nhl_dashboard/`, using its existing virtual environment.

1. Deploy the backend changes to Render through the normal GitHub deployment.
2. Create the laptop configuration (already prepared on this laptop):

   ```sh
   .venv/bin/python -m backend.collect_lineups init --site https://nhl-dashboard-g8h2.onrender.com
   ```

   This creates `data/lineup-upload.json` with a generated secret and file mode
   `0600`. It refuses to overwrite an existing file. `data/` is gitignored;
   never commit this file. The URL must be the origin without `/?date=...`.

3. In the Render service's **Environment** settings, set:

   ```text
   NHL_DFO_LINEUP_MODE=uploaded
   NHL_LINEUP_UPLOAD_TOKEN=<token value from data/lineup-upload.json>
   ```

   To copy the token on macOS without printing it into terminal output:

   ```sh
   .venv/bin/python -c 'import json; print(json.load(open("data/lineup-upload.json"))["token"], end="")' | pbcopy
   ```

   Save the environment settings and let Render finish deploying.

4. Verify the endpoint and perform the first upload:

   ```sh
   .venv/bin/python -m backend.collect_lineups status
   .venv/bin/python -m backend.collect_lineups run
   ```

   Status should show `"mode": "uploaded"`. After the first successful run,
   it lists the uploaded teams with source retrieval times and freshness.
   Reopen or refresh a matchup's Lines tab to see the uploaded lineup.

5. Activate the macOS schedule:

   ```sh
   .venv/bin/python -m backend.collect_lineups install-schedule
   ```

   The installer verifies server access, installs a LaunchAgent, and starts an
   upload immediately. It runs every five minutes while the user is logged in
   and the laptop is awake. It also starts on subsequent logins. It does not
   keep the laptop awake. Moving this repository or replacing its virtual
   environment requires rerunning the installer.

   `install-schedule --write-only` prepares the plist without activating it.
   The prepared plist is `~/Library/LaunchAgents/com.nhl-dashboard.lineup-collector.plist`.

## Freshness, failures, and storage

- Each run collects all 32 teams sequentially with a one-second pause between
  teams. The existing two-minute source cache and robots checks still apply.
- Only successfully fetched and validated lineups are uploaded. A failed team
  leaves that team's server snapshot unchanged. Partial runs upload successes
  and exit with status 1 so failures remain visible in the logs.
- `retrieved_at` is the laptop's actual source fetch time, not the upload time.
  Daily Faceoff's published `updated_at` is preserved separately; a fresh fetch
  does not mean Daily Faceoff has published a new lineup.
- Snapshots become stale after 20 minutes without a source refresh. The Lines
  UI uses its existing warning. After 24 hours the lineup is withheld and the
  roster-only fallback is used. Sleeping or offline laptops therefore cannot
  silently keep old assignments looking fresh.
- Uploads require a bearer token of at least 32 characters, have a 256 KiB body
  limit, and validate team names, timestamps, and lineup structure. Older or
  identical snapshots cannot overwrite newer ones. Validation is atomic for
  each batch. Redirects are not followed by the uploader.
- In uploaded mode, lineup reads never contact Daily Faceoff, even if no
  snapshot exists. In the default `direct` mode, existing fetching is unchanged.
- Snapshots live in the database selected by `NHL_DASHBOARD_DB`. With the default
  `/tmp/dashboard.sqlite3`, a restart or redeploy can empty them. The next
  collector run repopulates them if the laptop is online. For persistence,
  attach a Render disk at `/var/data` and set
  `NHL_DASHBOARD_DB=/var/data/dashboard.sqlite3`. Changing only the variable
  without mounting a disk does not provide persistence. See
  [Render persistent disks](https://render.com/docs/disks).

## Troubleshooting and maintenance

Test source access without contacting Render or needing the upload token:

```sh
.venv/bin/python -m backend.collect_lineups run --dry-run --teams NYR TOR
```

Inspect the authenticated server status or upload selected teams:

```sh
.venv/bin/python -m backend.collect_lineups status
.venv/bin/python -m backend.collect_lineups run --teams NYR TOR
```

The private config path can be overridden **before** the subcommand:

```sh
.venv/bin/python -m backend.collect_lineups --config /private/path/upload.json status
```

Logs are in `data/lineup-collector-logs/stdout.log` and `stderr.log`. These logs
are appended by launchd; clear or rotate them periodically if needed. Inspect
the scheduler with:

```sh
launchctl print gui/$(id -u)/com.nhl-dashboard.lineup-collector
```

- HTTP 404: the new endpoint has not deployed, or the site URL is incorrect.
- HTTP 401: the laptop and Render tokens differ.
- HTTP 503: the token is missing/too short, or the Render service is unavailable.
- HTTP 422: invalid data or an incorrect laptop clock. Keep automatic date/time
  enabled; uploaded timestamps allow at most 60 seconds of future clock skew.
- `mode` is `direct`: set `NHL_DFO_LINEUP_MODE=uploaded` on Render and redeploy.
- Collector source errors: check local network access to Daily Faceoff. Cached
  failures are never relabeled as newly collected lineups.

To stop scheduled uploads:

```sh
launchctl bootout gui/$(id -u)/com.nhl-dashboard.lineup-collector
rm ~/Library/LaunchAgents/com.nhl-dashboard.lineup-collector.plist
```

To restore direct server fetching, set `NHL_DFO_LINEUP_MODE=direct` on Render.
To disable uploads, remove `NHL_LINEUP_UPLOAD_TOKEN`. For token rotation,
replace the token in the private JSON and Render with the same newly generated
secret; the scheduled process reads the config on every run.
