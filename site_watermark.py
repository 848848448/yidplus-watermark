#!/usr/bin/env python3
"""Burn "Yidplus.com" into new uploads on yidplus.com (videos from every path, and photos that
arrived unmarked, e.g. from the Android app). Pulls jobs from https://yidplus.com/api/wm/*,
renders with ffmpeg, uploads the result, which replaces the file in place.
The logs of this public repo are public: print counts only (no keys, names, URLs or ids)."""
import json, os, subprocess, sys, time, urllib.request, shutil

BASE = (os.environ.get("SITE_URL") or "https://yidplus.com").rstrip("/")
KEY = os.environ.get("SITE_WM_KEY") or ""
if not KEY:
    print("SITE_WM_KEY secret missing"); sys.exit(0)
H = {"x-wm-key": KEY, "user-agent": "yidplus-watermark/2"}
TRAILER = b"YPWM1"          # a marked photo ends with these bytes (same as the website)
TAG = "Yidplus.com watermark"  # written into a marked video's metadata (comment)
MAX_OUT = 95 * 1024 * 1024    # the site takes at most ~100 MB in one request
FONT = None
for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
          "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
          "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
    if os.path.exists(f): FONT = f; break

def req(method, path, data=None, headers=None, timeout=120):
    h = dict(H); h.update(headers or {})
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.status, resp.read()

def get_jobs():
    try:
        st, body = req("GET", "/api/wm/jobs")
        return json.loads(body).get("jobs") or []
    except Exception as e:
        print("site not reachable:", type(e).__name__)
        return []

def fail(jid, err):
    try: req("POST", "/api/wm/fail?id=" + jid, data=json.dumps({"error": str(err)[:200]}).encode(), headers={"content-type": "application/json"})
    except Exception: pass

def mark_filter(w, h):
    # Same look as the website's photo mark: white bold "Yidplus.com" on a soft dark box,
    # bottom-right, sized from the picture's area (~4.8% of a 1600x1200 frame's height).
    fs = int(round((w * h) ** 0.5 * 0.035))
    fs = max(14, min(fs, int(h * 0.09), int(w * 0.07)))
    pad = max(4, int(fs * 0.3))
    m = int(fs * 0.55)
    font = ("fontfile=" + FONT + ":") if FONT else ""
    return ("drawtext=" + font + "text='Yidplus.com':fontsize=%d:fontcolor=white@0.92:"
            "box=1:boxcolor=black@0.38:boxborderw=%d:x=w-tw-%d:y=h-th-%d" % (fs, pad, m + pad, m + pad // 2))

def probe(path):
    pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                         "stream=width,height:stream_side_data=rotation:stream_tags=rotate:format_tags=comment",
                         "-of", "json", path], capture_output=True, text=True, timeout=60)
    j = json.loads(pr.stdout or "{}")
    s = (j.get("streams") or [{}])[0]
    w, h = int(s.get("width") or 0), int(s.get("height") or 0)
    rot = 0
    try: rot = int(float((s.get("tags") or {}).get("rotate") or 0))
    except Exception: pass
    for sd in s.get("side_data_list") or []:
        if "rotation" in sd:
            try: rot = int(float(sd["rotation"]))
            except Exception: pass
    if abs(rot) % 180 == 90: w, h = h, w      # ffmpeg auto-rotates, so the frame we draw on is turned
    comment = ((j.get("format") or {}).get("tags") or {}).get("comment") or ""
    return w, h, comment

def render_video(src, dst):
    w, h, comment = probe(src)
    if TAG in comment: return "skip"
    if not w or not h: raise RuntimeError("no video stream")
    for crf, cap in ((23, None), (28, 1280), (32, 854)):
        sw, sh = w, h
        vf = "scale=trunc(iw/2)*2:trunc(ih/2)*2,"
        if cap and max(w, h) > cap:
            sc = float(cap) / max(w, h)
            sw, sh = int(w * sc) // 2 * 2, int(h * sc) // 2 * 2
            vf = "scale=%d:%d," % (sw, sh)
        vf += mark_filter(sw, sh) + ",format=yuv420p"
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", vf, "-map", "0:v:0", "-map", "0:a:0?",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-c:a", "aac", "-b:a", "128k",
               "-movflags", "+faststart", "-metadata", "comment=" + TAG, dst]
        subprocess.run(cmd, check=True, timeout=900)
        if os.path.getsize(dst) <= MAX_OUT: return "video/mp4"
    raise RuntimeError("result too big")

def render_image(src, dst_base, ct):
    data = open(src, "rb").read()
    if data.endswith(TRAILER): return "skip", None
    pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                         "-of", "json", src], capture_output=True, text=True, timeout=60)
    s = (json.loads(pr.stdout or "{}").get("streams") or [{}])[0]
    w, h = int(s.get("width") or 0), int(s.get("height") or 0)
    if not w or not h: raise RuntimeError("not a readable picture")
    vf = ""
    if max(w, h) > 1600:
        sc = 1600.0 / max(w, h); w, h = int(w * sc) // 2 * 2, int(h * sc) // 2 * 2
        vf = "scale=%d:%d," % (w, h)
    vf += mark_filter(w, h)
    png = ct == "image/png"
    dst = dst_base + (".png" if png else ".jpg")
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", src, "-frames:v", "1", "-vf", vf] + ([] if png else ["-q:v", "3"]) + [dst]
    subprocess.run(cmd, check=True, timeout=120)
    with open(dst, "ab") as fo: fo.write(TRAILER)
    return ("image/png" if png else "image/jpeg"), dst

def main():
    if not shutil.which("ffmpeg"):
        subprocess.run(["sudo", "apt-get", "update", "-qq"], check=False)
        subprocess.run(["sudo", "apt-get", "install", "-y", "-qq", "ffmpeg"], check=True)
    # Keep looking for ~4 minutes (every 30 s), so a new upload waits seconds, not a whole schedule gap.
    deadline = time.time() + float(os.environ.get("WM_LOOK_SECONDS") or 240)
    done = failed = skipped = 0
    while True:
        jobs = get_jobs()
        for job in jobs:
            jid, kind, ct = job["id"], job.get("kind"), (job.get("ct") or "").lower()
            t0 = time.time()
            try:
                st, data = req("GET", "/api/wm/src?id=" + jid, timeout=300)
                open("in.bin", "wb").write(data); data = None
                if kind == "video":
                    r = render_video("in.bin", "out.mp4"); out = "out.mp4"
                else:
                    r, out = render_image("in.bin", "out", ct)
                if r == "skip":
                    req("POST", "/api/wm/skip?id=" + jid, data=b"{}", headers={"content-type": "application/json"})
                    skipped += 1
                else:
                    body = open(out, "rb").read()
                    req("PUT", "/api/wm/done?id=" + jid, data=body, headers={"content-type": r}, timeout=300)
                    done += 1
                    print("marked 1 %s in %ds" % (kind, time.time() - t0))
            except Exception as e:
                failed += 1
                print("1 %s failed: %s" % (kind, type(e).__name__))
                fail(jid, "%s: %s" % (type(e).__name__, e))
            for f in ("in.bin", "out.mp4", "out.jpg", "out.png"):
                try: os.remove(f)
                except Exception: pass
        if not jobs:
            if time.time() > deadline: break
            time.sleep(30)
    print("done:", done, "skipped:", skipped, "failed:", failed)

if __name__ == "__main__":
    main()
