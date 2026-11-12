# Event trigger for the site watermark (plan, not live)

Today (since 2026-11-12 01:41 UTC) the runner only starts from GitHub's */5 schedule or a manual
"Run workflow". GitHub fires that schedule on this repo only every few hours, so a video can wait
hours for its mark. Uploads themselves are never affected.

The fast, clean fix: the website asks GitHub to start a run right after a file is queued.

## How it works
1. An upload queues a job in R2 (wmq/), exactly as now.
2. Right after, the site calls GitHub's "workflow_dispatch" for site.yml, at most once every
   2 minutes (one tiny R2 object, wmkick/last, remembers the last call; no database).
3. That run marks the queue, then keeps looking 150 s more (longer than the 2-min window, so an
   upload that skipped the call is still caught), then exits. Never more than 10 min.
4. GitHub keeps at most one waiting run per concurrency group, so extra calls collapse.
5. No token set = the site does nothing new. Any error is ignored; the schedule stays the backup.

## The code (ready, NOT merged or deployed)
- Watermark repo: branch `event-trigger` (site.yml: the 150 s look for dispatched runs).
- Website: `site-patch/_wm.js` (whole new file) and `site-patch/_wm.js.diff` on that branch,
  for functions/api/_wm.js in the site repo. Only wmEnqueue gains a debounced call (wmKick).
  Merge the branch here and deploy the site patch only after the token below is in place.

## Avrumy's steps (phone, about 5 minutes)
A. Make the GitHub key (only works on this one repo, only for starting runs)
1. In the phone browser open: https://github.com/settings/personal-access-tokens/new
   (sign in as 848848448 if asked).
2. Token name: yidplus-watermark-kick
3. Expiration: pick 1 year (write the date down; renew it then).
4. Repository access: "Only select repositories" -> choose 848848448/yidplus-watermark.
5. Permissions -> Repository permissions -> Actions -> "Read and write".
   (Metadata: Read-only is added by itself. Nothing else.)
6. Tap "Generate token" and copy it (it starts with github_pat_). It is shown only once.
   Do not send it to anyone, including Tab.

B. Put it in Cloudflare as a secret
7. Open https://dash.cloudflare.com and sign in to the account that has the yidplus site.
8. Workers & Pages -> yidplus -> Settings -> Variables and Secrets.
9. Production -> Add -> Type: Secret -> Variable name: GH_WM_TOKEN -> paste the token -> Save.
10. Tell Tab "the key is in". Tab then deploys the site patch (a secret only takes effect on the
    next deploy) and checks a test video gets its mark within a few minutes.

To turn it off later: delete GH_WM_TOKEN in Cloudflare (step 9) or delete the token on GitHub.
The schedule keeps working either way.

## Alternative (not recommended)
A separate free Cloudflare Worker with a 1-minute cron could check wmq/ and call the same
dispatch. It needs the same token, plus a new Worker to deploy and maintain. The upload hook is
simpler and only calls GitHub when something was actually uploaded.
