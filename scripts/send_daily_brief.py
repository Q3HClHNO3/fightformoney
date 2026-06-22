from __future__ import annotations

import html
import os
import smtplib
import ssl
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


if __name__ == "__main__":
    main()
