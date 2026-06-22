# fightformoney

This repository sends a daily brief to QQ Mail through GitHub Actions.

## Required GitHub Actions secrets

Add these repository secrets under `Settings -> Secrets and variables -> Actions`:

- `QQ_SMTP_USER`: your QQ email address, for example `123456@qq.com`
- `QQ_SMTP_AUTH_CODE`: the QQ Mail SMTP authorization code, not the mailbox login password
- `QQ_MAIL_TO`: the recipient QQ email address

## Schedule

`.github/workflows/daily-brief-email.yml` runs every day at 09:00 Asia/Shanghai, which is `01:00 UTC` in GitHub Actions cron.

You can also run it manually from `Actions -> Daily Brief Email -> Run workflow` to verify delivery immediately.
