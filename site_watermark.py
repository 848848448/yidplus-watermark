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

def mark_png(w, h, path="mark.png"):
    # Same look as the website's photo mark: white bold "Yidplus.com" on a soft dark box,
    # bottom-right, sized from the picture's area (~48 px on a 1600x1200 frame).
    # Drawn with Pillow and laid over with ffmpeg's overlay (the static ffmpeg has no drawtext).
    from PIL import Image, ImageDraw, ImageFont
    fs = int(round((w * h) ** 0.5 * 0.035))
    fs = max(14, min(fs, int(h * 0.09), int(w * 0.07)))
    font = ImageFont.truetype(FONT, fs) if FONT else ImageFont.load_default()
    text = "Yidplus.com"
    l, t, r, b = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), text, font=font)
    tw, th = r - l, b - t
    pad = fs * 0.55
    bw, bh = int(tw + pad), int(fs + pad * 0.7)
    im = Image.new("RGBA", (bw, bh), (0, 0, 0, 97))            # rgba(0,0,0,.38)
    d = ImageDraw.Draw(im)
    d.text(((bw - tw) / 2 - l, (bh - th) / 2 - t), text, font=font, fill=(255, 255, 255, 235))  # .92
    im.save(path)
    margin_x = int(pad)          # box right edge ~ text end + pad, like the canvas version
    margin_y = int(pad * 0.3)
    return path, margin_x, margin_y

def mark_filter(w, h):
    path, mx, my = mark_png(w, h)
    return path, "overlay=W-w-%d:H-h-%d" % (mx, my)

def run(cmd, timeout):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg: " + (p.stderr or "").strip().replace("in.bin", "input")[-300:])

def media_info(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                        "-of", "json", path], capture_output=True, text=True, timeout=60)
    j = json.loads(p.stdout or "{}")
    types = [s.get("codec_type") for s in j.get("streams") or []]
    try: dur = float((j.get("format") or {}).get("duration") or 0)
    except Exception: dur = 0.0
    return dur, ("video" in types), ("audio" in types)

def verify_video(src, dst):
    # Only swap when the marked copy is sound: it decodes, has the same length (within 1 s or 3 %),
    # and has sound if the original had sound. Otherwise the original stays untouched.
    d0, v0, a0 = media_info(src)
    d1, v1, a1 = media_info(dst)
    if not v1: raise RuntimeError("marked video has no picture")
    if a0 and not a1: raise RuntimeError("marked video lost its sound")
    if d0 and abs(d1 - d0) > max(1.0, d0 * 0.03): raise RuntimeError("marked video length %.1fs != %.1fs" % (d1, d0))
    run(["ffmpeg", "-v", "error", "-i", dst, "-t", "4", "-f", "null", "-"], 120)   # it plays

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

MAX_SECONDS = 15 * 60   # longer videos are left as uploaded (logged as failed) to keep runs short

def render_video(src, dst):
    w, h, comment = probe(src)
    if TAG in comment: return "skip"
    dur, _, _ = media_info(src)
    if dur > MAX_SECONDS: raise RuntimeError("video longer than %d min, left as uploaded" % (MAX_SECONDS // 60))
    if not w or not h: raise RuntimeError("no video stream")
    for crf, cap in ((23, None), (28, 1280), (32, 854)):
        sw, sh = w // 2 * 2, h // 2 * 2
        if cap and max(w, h) > cap:
            sc = float(cap) / max(w, h)
            sw, sh = int(w * sc) // 2 * 2, int(h * sc) // 2 * 2
        mpath, ov = mark_filter(sw, sh)
        fc = "[0:v]scale=%d:%d,setsar=1[b];[b][1:v]%s,format=yuv420p[v]" % (sw, sh, ov)
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", src, "-i", mpath, "-filter_complex", fc, "-map", "[v]", "-map", "0:a:0?",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-c:a", "aac", "-b:a", "128k",
               "-movflags", "+faststart", "-metadata", "comment=" + TAG, dst]
        run(cmd, 1800)
        verify_video(src, dst)
        if os.path.getsize(dst) <= MAX_OUT: return "video/mp4"
    raise RuntimeError("result too big")

def render_image(src, dst_base, ct):
    # Photos are done with Pillow (it honours the phone's EXIF rotation, which ffmpeg ignores).
    from PIL import Image, ImageOps
    data = open(src, "rb").read()
    if data.endswith(TRAILER): return "skip", None
    im = Image.open(src)
    if getattr(im, "is_animated", False) and getattr(im, "n_frames", 1) > 1: return "skip", None   # keep animation
    im = ImageOps.exif_transpose(im)
    png = ct == "image/png"
    im = im.convert("RGBA" if png else "RGB")
    w, h = im.size
    if not w or not h: raise RuntimeError("not a readable picture")
    if max(w, h) > 1600:
        sc = 1600.0 / max(w, h); im = im.resize((max(1, int(w * sc)), max(1, int(h * sc))), Image.LANCZOS); w, h = im.size
    mpath, mx, my = mark_png(w, h)
    mk = Image.open(mpath).convert("RGBA")
    base = im.convert("RGBA")
    base.alpha_composite(mk, (w - mk.width - mx, h - mk.height - my))
    dst = dst_base + (".png" if png else ".jpg")
    if png: base.save(dst, "PNG", optimize=True)
    else: base.convert("RGB").save(dst, "JPEG", quality=85, optimize=True)
    with open(dst, "ab") as fo: fo.write(TRAILER)
    Image.open(dst).verify()
    return ("image/png" if png else "image/jpeg"), dst

def main():
    if not shutil.which("ffmpeg"):
        subprocess.run(["sudo", "apt-get", "update", "-qq"], check=False)
        subprocess.run(["sudo", "apt-get", "install", "-y", "-qq", "ffmpeg"], check=True)
    # Work the queue and exit as soon as it is empty (WM_LOOK_SECONDS = extra idle wait, 0 = none).
    # WM_MAX_SECONDS is a hard cap: no new job is started after it; the next run picks up the rest.
    start = time.time()
    deadline = start + float(os.environ.get("WM_LOOK_SECONDS") or 0)
    hard_stop = start + float(os.environ.get("WM_MAX_SECONDS") or 600)
    done = failed = skipped = 0
    tried = set()       # a job that failed is retried on a later run, not in a tight loop
    while True:
        jobs = [j for j in get_jobs() if j["id"] not in tried]
        for job in jobs:
            if time.time() > hard_stop: break
            tried.add(job["id"])
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
                print("1 %s failed: %s" % (kind, type(e).__name__))   # public log: no details
                fail(jid, "%s: %s" % (type(e).__name__, e))
            for f in ("in.bin", "out.mp4", "out.jpg", "out.png", "mark.png"):
                try: os.remove(f)
                except Exception: pass
        if time.time() > hard_stop:
            print("time cap reached, the rest waits for the next run"); break
        if not jobs:
            if time.time() >= deadline: break
            time.sleep(min(30, max(1, deadline - time.time())))
    print("done:", done, "skipped:", skipped, "failed:", failed)

if __name__ == "__main__":
    main()
