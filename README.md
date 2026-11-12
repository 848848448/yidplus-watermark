# yidplus-watermark

Burns the YID PLUS logo onto videos sent by the YID PLUS control site (control.yidplus.com).

Every 5 minutes a GitHub Actions run asks the control site for waiting videos, renders them with ffmpeg and uploads the result. With nothing waiting it exits in seconds. Logo, corner, size and opacity are set in the control site (Watermark).

This repo is public on purpose: Actions minutes are free and unlimited for public repositories. It contains no secrets. The key lives in the repository secret `WM_KEY`, and the site address in the secret `CONTROL_URL`. The logs print counts only. A monthly keepalive commit stops GitHub from pausing the schedule after 60 quiet days.

## yidplus.com uploads (site.yml + site_watermark.py)

Every 5 minutes `site.yml` asks yidplus.com for uploads waiting for the "Yidplus.com" mark: every uploaded video (chat, status, shorts, posts, music videos) and any photo that arrived unmarked (the website marks photos itself; the Android app does not yet). It burns the mark in with ffmpeg (white bold text on a soft dark box, bottom-right, same look as the website's photo mark) and uploads the result, which replaces the file in place. Key: repository secret `SITE_WM_KEY` (= `WM_KEY` on the yidplus Pages project). Queue status: `GET https://yidplus.com/api/wm/status` with header `x-wm-key`.
