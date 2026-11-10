#!/usr/bin/env python3
"""Pull watermark jobs from the YID PLUS control site, render, upload.
The logs of this public repo are public: print counts only (no URLs, ids, captions or names)."""
import json, os, subprocess, sys, time, urllib.request, shutil

BASE = (os.environ.get("CONTROL_URL") or "https://control.yidplus.com").rstrip("/")
KEY = os.environ.get("WM_KEY") or ""
if not KEY:
    print("WM_KEY secret missing"); sys.exit(0)
H = {"x-wm-key": KEY, "user-agent": "yidplus-watermark/1"}

def req(method, path, data=None, headers=None, timeout=120):
    h = dict(H); h.update(headers or {})
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.status, resp.read()

def get_jobs():
    try:
        st, body = req("GET", "/api/wm/jobs")
        return json.loads(body)
    except Exception as e:
        print("control site not reachable:", type(e).__name__)
        return {}

# Keep looking for ~4 minutes (every 20 s) so a video waits seconds, not until the next scheduled run.
deadline = time.time() + 240
j = get_jobs(); jobs = j.get("jobs") or []
while not jobs and time.time() < deadline:
    time.sleep(20)
    j = get_jobs(); jobs = j.get("jobs") or []
print("jobs:", len(jobs))
if not jobs:
    sys.exit(0)
wm = j.get("wm") or {}
try:
    if not shutil.which("ffmpeg"):
        subprocess.run(["sudo", "apt-get", "update", "-qq"], check=False)
        subprocess.run(["sudo", "apt-get", "install", "-y", "-qq", "ffmpeg"], check=True)
    st, logo = req("GET", "/api/wm/logo")
except Exception as e:
    print("setup failed:", type(e).__name__)
    for job in jobs:
        try: req("POST", "/api/wm/fail?id=" + job["id"], data=json.dumps({"error": "render setup failed"}).encode(), headers={"content-type": "application/json"})
        except Exception: pass
    sys.exit(0)
open("logo.png", "wb").write(logo)

size = max(5, min(40, int(wm.get("size") or 11)))
opa = max(0.2, min(1.0, (int(wm.get("opacity") or 90)) / 100.0))
margin = max(0, min(15, int(wm.get("margin") or 3)))
corner = wm.get("corner") or "br"

for job in jobs:
    jid = job["id"]
    t0 = time.time()
    try:
        rq = urllib.request.Request(job["src"], headers={"user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36", "referer": "https://yidstatus.com/"})
        with urllib.request.urlopen(rq, timeout=180) as resp, open("in.mp4", "wb") as fo:
            shutil.copyfileobj(resp, fo)
        pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", "in.mp4"], capture_output=True, text=True, check=True)
        s = json.loads(pr.stdout)["streams"][0]
        W, Hh = int(s["width"]), int(s["height"])
        base = min(W, Hh) if Hh > W else W          # portrait: size is % of the width; same for landscape
        lw = max(40, int(base * size / 100)) // 2 * 2
        m = int(base * margin / 100)
        x = f"{m}" if corner[1] == "l" else f"W-w-{m}"
        y = f"{m}" if corner[0] == "t" else f"H-h-{m}"
        flt = f"[1:v]scale={lw}:-1,format=rgba,colorchannelmixer=aa={opa:.2f}[wm];[0:v][wm]overlay={x}:{y}:format=auto,format=yuv420p[v]"
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", "in.mp4", "-i", "logo.png", "-filter_complex", flt, "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "copy", "-movflags", "+faststart", "out.mp4"]
        subprocess.run(cmd, check=True, timeout=600)
        data = open("out.mp4", "rb").read()
        st, _ = req("PUT", "/api/wm/done?id=" + jid, data=data, headers={"content-type": "video/mp4"}, timeout=300)
        print(f"rendered 1 video in {time.time()-t0:.0f}s")
    except Exception as e:
        print("1 video failed:", type(e).__name__)
        try: req("POST", "/api/wm/fail?id=" + jid, data=json.dumps({"error": str(e)[:200]}).encode(), headers={"content-type": "application/json"})
        except Exception: pass
    for f in ("in.mp4", "out.mp4"):
        try: os.remove(f)
        except Exception: pass
