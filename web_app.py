import html
import io
import posixpath
import re
import zipfile
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import quote, unquote

HOST = "127.0.0.1"
PORT = 8765
MAX_REQUEST_SIZE = 50 * 1024 * 1024
MAX_FILE_SIZE = 10 * 1024 * 1024
PROFILE_HREF_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:_u/)?([A-Za-z0-9._]+)/?",
    re.IGNORECASE,
)
FOLLOWERS_NAME_RE = re.compile(r"^followers(?:_\d+)?\.(json|html|htm)$", re.IGNORECASE)
FOLLOWING_NAME_RE = re.compile(r"^following\.(json|html|htm)$", re.IGNORECASE)
HTML_DATE_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}, \d{4}"
    r"(?: \d{1,2}:\d{2}(?::\d{2})? ?(?:AM|PM|am|pm))?",
)
SKIP_USERNAMES = {
    "accounts",
    "direct",
    "explore",
    "p",
    "reel",
    "reels",
    "stories",
    "about",
    "legal",
}


def render_page(message="", report=None, status=200):
    sections = ""
    if report is not None:
        if report["recent_not_following_back"]:
            recent_dates_note = (
                f'<p class="meta">Dates are available for '
                f'{report["dated_not_following_back_count"]:,} of '
                f'{report["not_following_back_count"]:,} non-mutual follows overall; '
                "showing up to 50.</p>"
            )
        else:
            recent_dates_note = '<p class="meta">No follow dates were included in this export.</p>'
        sections = f"""
        <section class="summary">
          <div><strong>{report["followers_count"]:,}</strong><span>Followers</span></div>
          <div><strong>{report["following_count"]:,}</strong><span>Following</span></div>
          <div><strong>{report["mutual_count"]:,}</strong><span>Mutual follows</span></div>
          <div><strong>{report["not_following_back_count"]:,}</strong><span>Not following you back ({report["not_following_back_percent"]})</span></div>
          <div><strong>{report["not_followed_back_count"]:,}</strong><span>You don't follow back ({report["not_followed_back_percent"]})</span></div>
          <div><strong>{report["reciprocity_percent"]}</strong><span>Of your following follow you back</span></div>
          <div><strong>{report["followers_you_follow_percent"]}</strong><span>Of your followers you follow back</span></div>
          <div><strong>{report["follow_ratio"]}</strong><span>Following / followers</span></div>
          <div><strong>{report["following_difference"]:+,}</strong><span>Following minus followers</span></div>
        </section>
        <p class="notice">{html.escape(report["insight"])}</p>
        <section class="columns">
          <div>
            <h2>You follow them; they don't follow you ({report["not_following_back_count"]})</h2>
            {render_account_list(report["not_following_back"])}
          </div>
          <div>
            <h2>They follow you; you don't follow them ({report["not_followed_back_count"]})</h2>
            {render_account_list(report["not_followed_back"])}
          </div>
        </section>
        <section class="columns">
          <div>
            <h2>Mutual follows ({report["mutual_count"]})</h2>
            {render_account_list(report["mutuals"])}
          </div>
          <div>
            <h2>Latest follows with no follow-back (up to 50)</h2>
            {recent_dates_note}
            {render_account_list(report["recent_not_following_back"])}
          </div>
        </section>
        """

    message_html = f'<p class="message">{html.escape(message)}</p>' if message else ""
    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Instagram follow report</title>
  <style>
    :root {{ color-scheme: light; font-family: system-ui, sans-serif; color: #202124; background: #f5f6fa; }}
    body {{ max-width: 1100px; margin: 3rem auto; padding: 0 1.25rem; }}
    main {{ background: white; border-radius: 14px; padding: 2rem; box-shadow: 0 8px 30px #18223012; }}
    h1 {{ margin-top: 0; }}
    p {{ line-height: 1.5; }}
    form {{ display: grid; gap: .75rem; max-width: 36rem; }}
    label {{ font-weight: 600; }}
    input, button {{ font: inherit; padding: .7rem .8rem; border: 1px solid #c7cbd1; border-radius: 8px; }}
    button {{ background: #3445b4; border-color: #3445b4; color: white; cursor: pointer; }}
    .action-link {{ display: inline-block; margin: .2rem 0; padding: .35rem .55rem; border-radius: 6px; background: #3445b4; color: white; text-decoration: none; }}
    .message {{ color: #9b2226; }}
    .summary {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; margin-top: 1.5rem; }}
    .columns {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; margin-top: 1.5rem; }}
    .summary div, .columns div {{ border: 1px solid #e1e4e8; border-radius: 10px; padding: 1rem; }}
    .summary strong, .summary span {{ display: block; }}
    .summary strong {{ font-size: 1.5rem; }}
    ul {{ padding-left: 1.25rem; max-height: 28rem; overflow: auto; }}
    li {{ margin: .35rem 0; }}
    .meta {{ color: #5f6368; font-size: .9rem; }}
    .notice {{ padding: .8rem 1rem; background: #eef2ff; border-radius: 8px; }}
    @media (max-width: 800px) {{ .columns, .summary {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <h1>Instagram follow report</h1>
    <p>This local app only reads an official Instagram information export. It does not log in to Instagram or follow or unfollow anyone.</p>
    <p>Request a download of your information as JSON or HTML. Upload the export <code>.zip</code>, or the files from <code>connections/followers_and_following</code> (or <code>followers_and_following</code>): <code>followers_1.json</code> / <code>followers_1.html</code> (and <code>followers_2</code>, …) plus <code>following.json</code> / <code>following.html</code>.</p>
    <form method="post" action="/report" enctype="multipart/form-data">
      <label for="exports">Export ZIP or follower/following files</label>
      <input id="exports" name="exports" type="file" accept=".json,.html,.htm,.zip,application/json,text/html,application/zip" multiple required>
      <button type="submit">Build report</button>
    </form>
    {message_html}
    {sections}
  </main>
</body>
</html>"""
    return status, body.encode("utf-8")


def render_account_list(accounts):
    if not accounts:
        return "<p>None</p>"
    items = []
    for account in accounts:
        username = html.escape(account["username"])
        profile_url = "https://www.instagram.com/" + quote(account["username"], safe="") + "/"
        date_html = ""
        if account.get("date"):
            date_html = f' <span class="meta">({html.escape(account["date"])})</span>'
        items.append(
            f"<li>{username}{date_html} "
            f'<a class="action-link" href="{html.escape(profile_url, quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">Open profile</a></li>'
        )
    return f"<ul>{''.join(items)}</ul>"


def format_timestamp(timestamp):
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or timestamp <= 0:
        return ""
    try:
        return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).strftime("%Y-%m-%d")
    except (OSError, OverflowError, ValueError):
        return ""


def normalize_username(value):
    if not isinstance(value, str):
        return ""
    username = unquote(value).strip().lstrip("@")
    if "/" in username:
        username = username.rstrip("/").rsplit("/", 1)[-1]
    username = username.strip()
    if not username or username.casefold() in SKIP_USERNAMES:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9._]+", username):
        return ""
    return username


def username_from_href(href):
    if not isinstance(href, str):
        return ""
    match = PROFILE_HREF_RE.search(href)
    if not match:
        return ""
    return normalize_username(match.group(1))


def parse_timestamp(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def parse_html_date(text):
    match = HTML_DATE_RE.search(text or "")
    if not match:
        return None
    raw = re.sub(r"\s+", " ", match.group(0)).strip()
    for fmt in ("%b %d, %Y %I:%M:%S %p", "%b %d, %Y %I:%M %p", "%b %d, %Y"):
        try:
            parsed = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            return int(parsed.timestamp())
        except ValueError:
            continue
    return None


def username_from_label_values(entry):
    values = entry.get("label_values")
    if not isinstance(values, list):
        return ""
    for item in values:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).casefold()
        if label in {"username", "user name"}:
            return normalize_username(item.get("value", ""))
        if label in {"url", "profile url", "href"}:
            username = username_from_href(item.get("value", ""))
            if username:
                return username
    return ""


def account_from_entry(entry):
    if not isinstance(entry, dict):
        return None
    string_data = entry.get("string_list_data", [])
    username = ""
    timestamp = None
    href = ""
    if isinstance(string_data, list) and string_data and isinstance(string_data[0], dict):
        first = string_data[0]
        username = normalize_username(first.get("value", ""))
        href = first.get("href", "") if isinstance(first.get("href"), str) else ""
        timestamp = parse_timestamp(first.get("timestamp"))
    if not username:
        username = normalize_username(entry.get("title", ""))
    if not username:
        username = username_from_href(href)
    if not username:
        username = username_from_label_values(entry)
    if not username:
        return None
    return {
        "username": username,
        "timestamp": timestamp,
        "date": format_timestamp(timestamp) if timestamp else "",
    }


def relationship_entries(data, kind):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return None
    preferred = (
        ("relationships_followers", "followers")
        if kind == "followers"
        else ("relationships_following", "following")
    )
    for key in preferred:
        if isinstance(data.get(key), list):
            return data[key]
    list_values = [value for value in data.values() if isinstance(value, list)]
    if len(list_values) == 1:
        return list_values[0]
    return None


def extract_accounts(data, kind):
    entries = relationship_entries(data, kind)
    if not isinstance(entries, list):
        raise ValueError(f"The {kind} JSON has an unexpected structure.")
    accounts = []
    for entry in entries:
        account = account_from_entry(entry)
        if account:
            accounts.append(account)
    return accounts


def looks_like_html(content):
    sample = content.lstrip()[:200].lower()
    return sample.startswith(b"<!doctype html") or sample.startswith(b"<html") or b"<a " in sample[:1000]


def decode_text(content):
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("The export file is not valid text.")


def parse_html_export(content):
    text = decode_text(content)
    accounts = []
    for match in PROFILE_HREF_RE.finditer(text):
        username = normalize_username(match.group(1))
        if not username:
            continue
        nearby = text[match.end() : match.end() + 400]
        timestamp = parse_html_date(nearby)
        accounts.append(
            {
                "username": username,
                "timestamp": timestamp,
                "date": format_timestamp(timestamp) if timestamp else "",
            }
        )
    if not accounts:
        raise ValueError("No Instagram profile links were found in the HTML export.")
    return accounts


def parse_json_export(content, kind):
    if not content:
        raise ValueError(f"The {kind} JSON file is empty.")
    try:
        data = json.loads(decode_text(content))
    except json.JSONDecodeError as exc:
        raise ValueError(f"The {kind} file is not valid JSON.") from exc
    return extract_accounts(data, kind)


def parse_named_file(filename, content, kind_hint=None):
    if not content or len(content) > MAX_FILE_SIZE:
        raise ValueError(f"{filename or 'File'} is empty or too large.")
    kind = classify_kind(filename) or kind_hint
    lower_name = basename(filename).casefold()
    try_html = lower_name.endswith((".html", ".htm")) or looks_like_html(content)
    if try_html and not lower_name.endswith(".json"):
        if kind is None:
            raise ValueError(f"Unrecognized export file: {filename}")
        return kind, "html", parse_html_export(content)
    try:
        if kind is None:
            data = json.loads(decode_text(content))
            if relationship_entries(data, "following") is not None and relationship_entries(data, "followers") is None:
                kind = "following"
            elif relationship_entries(data, "followers") is not None:
                kind = "followers"
            else:
                raise ValueError(f"Unrecognized export file: {filename}")
            return kind, "json", extract_accounts(data, kind)
        return kind, "json", parse_json_export(content, kind)
    except ValueError:
        if looks_like_html(content):
            if kind is None:
                raise
            return kind, "html", parse_html_export(content)
        raise


def basename(path):
    return posixpath.basename((path or "").replace("\\", "/"))


def classify_kind(filename):
    name = basename(filename)
    if FOLLOWERS_NAME_RE.fullmatch(name):
        return "followers"
    if FOLLOWING_NAME_RE.fullmatch(name):
        return "following"
    return None


def parse_zip_export(content):
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ValueError("The ZIP file is not a valid Instagram export archive.") from exc
    files = []
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            kind = classify_kind(info.filename)
            if kind is None:
                continue
            if info.file_size > MAX_FILE_SIZE:
                raise ValueError(f"{basename(info.filename)} in the ZIP is too large.")
            files.append((info.filename, archive.read(info)))
    if not files:
        raise ValueError(
            "The ZIP did not contain followers or following files. "
            "Look in connections/followers_and_following."
        )
    return files


def unique_accounts(accounts):
    by_key = {}
    order = []
    for account in accounts:
        key = account["username"].casefold()
        if key not in by_key:
            by_key[key] = account
            order.append(key)
            continue
        current = by_key[key]
        if current.get("timestamp") is None and account.get("timestamp") is not None:
            by_key[key] = account
    return [by_key[key] for key in order]


def sort_accounts(accounts, newest_first=False):
    if newest_first:
        return sorted(
            accounts,
            key=lambda account: (
                account.get("timestamp") is None,
                -(account.get("timestamp") or 0),
                account["username"].casefold(),
            ),
        )
    return sorted(accounts, key=lambda account: account["username"].casefold())


def build_report(followers, followings):
    followers = unique_accounts(followers)
    followings = unique_accounts(followings)
    follower_set = {account["username"].casefold() for account in followers}
    following_set = {account["username"].casefold() for account in followings}

    not_following_back = [
        account for account in followings if account["username"].casefold() not in follower_set
    ]
    not_followed_back = [
        account for account in followers if account["username"].casefold() not in following_set
    ]
    mutuals = [
        account for account in followings if account["username"].casefold() in follower_set
    ]

    following_count = len(followings)
    reciprocity = (
        f"{round(len(mutuals) / following_count * 100)}%"
        if following_count
        else "n/a"
    )
    follow_ratio = (
        f"{len(followings) / len(followers):.2f}"
        if followers
        else "n/a"
    )
    mutual_phrase = (
        f"{len(mutuals):,} follow is mutual"
        if len(mutuals) == 1
        else f"{len(mutuals):,} follows are mutual"
    )
    insight = (
        f"You follow {len(followings):,} accounts and {len(followers):,} accounts follow you. "
        f"{mutual_phrase} ({reciprocity} of accounts you follow). "
        f"Follow ratio (following / followers) is {follow_ratio}."
    )

    return {
        "followers_count": len(followers),
        "following_count": len(followings),
        "mutual_count": len(mutuals),
        "not_following_back_count": len(not_following_back),
        "not_followed_back_count": len(not_followed_back),
        "reciprocity_percent": reciprocity,
        "not_following_back_percent": (
            f"{round(len(not_following_back) / following_count * 100)}%"
            if following_count
            else "n/a"
        ),
        "not_followed_back_percent": (
            f"{round(len(not_followed_back) / len(followers) * 100)}%"
            if followers
            else "n/a"
        ),
        "followers_you_follow_percent": (
            f"{round(len(mutuals) / len(followers) * 100)}%"
            if followers
            else "n/a"
        ),
        "follow_ratio": follow_ratio,
        "following_difference": following_count - len(followers),
        "insight": insight,
        "not_following_back": sort_accounts(not_following_back),
        "not_followed_back": sort_accounts(not_followed_back),
        "mutuals": sort_accounts(mutuals),
        "dated_not_following_back_count": sum(
            1 for account in not_following_back if account.get("timestamp") is not None
        ),
        "recent_not_following_back": sort_accounts(
            [
                account
                for account in not_following_back
                if account.get("timestamp") is not None
            ],
            newest_first=True,
        )[:50],
    }


def add_parsed_file(collected, filename, content, kind_hint=None):
    if basename(filename).casefold().endswith(".zip") or content.startswith(b"PK"):
        for zip_name, zip_content in parse_zip_export(content):
            add_parsed_file(collected, zip_name, zip_content)
        return
    kind, fmt, accounts = parse_named_file(filename, content, kind_hint)
    collected[kind][fmt].extend(accounts)


def parse_upload(content_type, body):
    if len(body) > MAX_REQUEST_SIZE:
        raise ValueError("The upload is too large. Upload the ZIP or only the follower/following files.")
    headers = (
        f"Content-Type: {content_type}\r\n"
        "MIME-Version: 1.0\r\n"
        "\r\n"
    ).encode("ascii", "strict")
    message = BytesParser(policy=policy.default).parsebytes(headers + body)
    if not message.is_multipart():
        raise ValueError("Submit the export files using the upload form.")

    collected = {
        "followers": {"json": [], "html": []},
        "following": {"json": [], "html": []},
    }
    found_any = False
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if name not in ("exports", "followers", "following"):
            continue
        payload = part.get_payload(decode=True) or b""
        filename = part.get_filename() or name
        if len(payload) > MAX_REQUEST_SIZE:
            raise ValueError(f"{filename} is too large.")
        found_any = True
        kind_hint = name if name in ("followers", "following") else None
        add_parsed_file(collected, filename, payload, kind_hint)

    if not found_any:
        raise ValueError("Select the export ZIP or the follower and following files.")

    followers = collected["followers"]["json"] or collected["followers"]["html"]
    followings = collected["following"]["json"] or collected["following"]["html"]
    if not followers:
        raise ValueError("No follower list was found. Include followers_1.json or followers_1.html.")
    if not followings:
        raise ValueError("No following list was found. Include following.json or following.html.")
    return build_report(followers, followings)


class ReportHandler(BaseHTTPRequestHandler):
    def _send_page(self, message="", report=None, status=200):
        status, content = render_page(message, report, status)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'",
        )
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if self.path not in ("/", "/report"):
            self.send_error(404)
            return
        self._send_page()

    def do_POST(self):
        if self.path != "/report":
            self.send_error(404)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "Invalid request length")
            return
        if content_length <= 0 or content_length > MAX_REQUEST_SIZE:
            self.send_error(413, "Request is empty or too large")
            return

        body = self.rfile.read(content_length)
        try:
            content_type = self.headers.get("Content-Type", "")
            report = parse_upload(content_type, body)
        except (ValueError, UnicodeEncodeError) as exc:
            self._send_page(str(exc), status=400)
            return
        finally:
            body = b""

        self._send_page("Report loaded successfully.", report=report)

    def log_message(self, format_string, *args):
        print(f"{self.address_string()} - {format_string % args}")


def main():
    server = ThreadingHTTPServer((HOST, PORT), ReportHandler)
    print(f"Follow report UI running at http://{HOST}:{PORT}/")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping the local report UI.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
