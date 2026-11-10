# yidplus-watermark

Burns the YID PLUS logo onto videos sent by the YID PLUS control site (control.yidplus.com).

Every 5 minutes a GitHub Actions run asks the control site for waiting videos, renders them with ffmpeg and uploads the result. With nothing waiting it exits in seconds. Logo, corner, size and opacity are set in the control site (Watermark).

This repo is public on purpose: Actions minutes are free and unlimited for public repositories. It contains no secrets. The key lives in the repository secret `WM_KEY`, and the site address in the secret `CONTROL_URL`. The logs print counts only. A monthly keepalive commit stops GitHub from pausing the schedule after 60 quiet days.
