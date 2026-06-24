from __future__ import annotations

import html
import base64
import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo


REQUIRED_ENV = ("SMTP_USER", "SMTP_PASSWORD", "MAIL_TO")


def get_required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def read_brief() -> tuple[str, str]:
    brief_file = Path(os.environ.get("BRIEF_FILE", "daily-brief.md")).expanduser()
    if brief_file.exists() and brief_file.is_file():
        content = brief_file.read_text(encoding="utf-8").strip()
        if content:
            return brief_file.as_posix(), content

    run_url = os.environ.get("GITHUB_RUN_URL", "").strip()
    lines = [
        "Daily Brief Email is configured and running.",
        "",
        "No non-empty brief file was found yet, so this message confirms that the QQ email delivery path works.",
    ]
    if run_url:
        lines.extend(["", f"GitHub Actions run: {run_url}"])
    return brief_file.as_posix(), "\n".join(lines)


def plain_to_html(text: str) -> str:
    escaped = html.escape(text)
    return (
        "<!doctype html><html><body>"
        "<pre style=\"font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
        "white-space:pre-wrap;line-height:1.5\">"
        f"{escaped}"
        "</pre></body></html>"
    )


def scheduled_marker(today: str) -> str:
    return f".sent/daily-brief-{today}.txt"


def should_use_send_marker() -> bool:
    return os.environ.get("GITHUB_EVENT_NAME") in {"schedule", "push"}


def github_api_request(url: str, token: str, method: str = "GET", payload: dict | None = None) -> bytes:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "daily-brief-email-action",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def scheduled_marker_exists(today: str) -> bool:
    if not should_use_send_marker():
        return False

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not token or not repository:
        return False

    marker_path = scheduled_marker(today)
    url = f"https://api.github.com/repos/{repository}/contents/{marker_path}"
    try:
        github_api_request(url, token)
        print(f"Scheduled email already sent today; marker exists: {marker_path}.")
        return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise


def write_scheduled_marker(today: str, subject: str) -> None:
    if not should_use_send_marker():
        return

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not token or not repository:
        print("No GitHub token/repository available; cannot write scheduled send marker.")
        return

    marker_path = scheduled_marker(today)
    run_url = os.environ.get("GITHUB_RUN_URL", "").strip()
    content = f"sent_at={datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}\nsubject={subject}\nrun={run_url}\n"
    payload = {
        "message": f"Mark daily brief sent for {today}",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    url = f"https://api.github.com/repos/{repository}/contents/{marker_path}"
    github_api_request(url, token, method="PUT", payload=payload)
    print(f"Wrote scheduled send marker: {marker_path}.")


def main() -> None:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError(
            "Missing required GitHub Actions secrets: "
            + ", ".join(missing)
            + ". Expected secrets are QQ_SMTP_USER, QQ_SMTP_AUTH_CODE, QQ_MAIL_TO."
        )

    smtp_host = os.environ.get("SMTP_HOST", "smtp.qq.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "465"))
    smtp_user = get_required_env("SMTP_USER")
    smtp_password = get_required_env("SMTP_PASSWORD")
    mail_from = os.environ.get("MAIL_FROM", smtp_user).strip() or smtp_user
    mail_to = get_required_env("MAIL_TO")

    source_path, brief_text = read_brief()
    today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    subject = os.environ.get("MAIL_SUBJECT", "").strip() or f"今日投资简报 - {today} - 14点 - 加减仓信号"

    if scheduled_marker_exists(today):
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = mail_from
    message["To"] = mail_to
    message.set_content(brief_text)
    message.add_alternative(plain_to_html(brief_text), subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context, timeout=30) as smtp:
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(message)

    print(f"Sent daily brief from {source_path} to {mail_to}.")
    write_scheduled_marker(today, subject)


if __name__ == "__main__":
    main()
