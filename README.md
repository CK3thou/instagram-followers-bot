# Instagram follow report

Read-only local report from an official Instagram information export. It compares follower and following lists and does not log in, follow, or unfollow anyone.

It reads the usual export shapes:

- JSON: `followers_1.json` (and `followers_2.json`, …) plus `following.json`
- HTML: `followers_1.html` plus `following.html`
- The export `.zip` (files under `connections/followers_and_following` or `followers_and_following`)

The report includes:

- Accounts you follow who do not follow you back
- Accounts who follow you whom you do not follow
- Mutual follows
- Follow-back percentages for both your following and follower lists
- Following-to-follower ratio and the difference between the two counts
- The 50 newest non-mutual follows with dates, when timestamps are included in the export

## Usage

```
python web_app.py
```

Or run `launch_report.bat` on Windows.

Open `http://127.0.0.1:8765/`. Upload the export ZIP, or select the follower and following JSON/HTML files. Files are parsed in memory and are not saved.

Profile links open Instagram in your browser so you can review accounts yourself.

Press `Ctrl+C` in the terminal to stop the server.

Requires Python 3.7 or newer. No extra packages.
