#!/usr/bin/env python3
"""
Generate the evidence screenshots used in README.md (saved to screenshots/).

* Terminal shots: every command is EXECUTED for real (cwd = project root) and
  its genuine stdout/stderr is rendered as an image styled like the author's
  terminal (VS Code "Moonlight II" colours, Powerlevel10k two-line prompt,
  Menlo, exactly as the VS Code integrated terminal draws it).
* Browser shots: the real page is captured with headless Chromium, then shown
  under a simple address bar so the URL/port is visible.

Usage:   python3 tools/render_screenshots.py            # all shots
         python3 tools/render_screenshots.py 09 27      # only shots whose name starts with 09 / 27
Requires: the lab running (docker compose up -d --build) and Playwright's
          Chromium headless shell (npx playwright install chromium-headless-shell).
"""
import datetime
import html
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "screenshots"
SAMPLES = ROOT / "tools" / "samples"
TMP = Path(tempfile.mkdtemp(prefix="shots-"))
# Playwright's Chromium headless shell (npx playwright install chromium-headless-shell)
BROWSERS = sorted(Path.home().glob("Library/Caches/ms-playwright/chromium_headless_shell-*/"
                                   "chrome-mac*/headless_shell"), reverse=True)
BROWSER = str(BROWSERS[0]) if BROWSERS else None

# ---- terminal look (Moonlight II ANSI palette + p10k config) --------------
C = dict(bg="#1e2030", fg="#c8d3f5", c0="#444a73", red="#ff757f",
         green="#c3e88d", yellow="#ffc777", blue="#82aaff", cyan="#86e1fc")
FONT_PX, LINE_PX, PAD, WIDTH = 12, 16, 14, 1180     # VS Code terminal defaults (Menlo 12)
COLS = int((WIDTH - 2 * PAD) / (FONT_PX * 0.602)) - 1
CORNER, DOTS = "#000000", "#6e7399"
DIR = "~/Desktop/WEB404_Assignment4"
# The VS Code terminal uses Menlo, which has no Nerd Font glyphs, so every p10k
# icon shows up as an empty "tofu" box - reproduce that faithfully.
def box(color):
    return f"<span class='tofu' style='color:{color}'></span>"


def sh(cmd, timeout=180):
    p = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True,
                       timeout=timeout, executable="/bin/zsh")
    return p.returncode, (p.stdout + p.stderr).rstrip("\n")


def git_untracked():
    _, out = sh("git status --porcelain | grep -c '^??'")
    return out.strip() or "0"


def wait_waf():
    for _ in range(40):
        try:
            urllib.request.urlopen("http://localhost:8080/healthz", timeout=2)
            time.sleep(1)
            return
        except Exception:  # noqa: BLE001
            time.sleep(1)


def wrap(text):
    rows = []
    for line in text.split("\n"):
        line = line.expandtabs(8)
        while len(line) > COLS:
            rows.append(line[:COLS])
            line = line[COLS:]
        rows.append(line)
    return rows


def prompt(rc_prev):
    now = datetime.datetime.now().strftime("%I:%M:%S %p")
    status = (f"<span style='color:{C['red']}'>✘ {rc_prev} </span>" if rc_prev else "")
    return (
        f"<div class='row'><span class='corner'>╭─</span>"
        f"<span> {box(C['fg'])} </span>"
        f"<span style='color:{C['blue']}'>{box(C['blue'])} {DIR} </span>"
        f"<span style='color:{C['green']}'>{box(C['green'])} {box(C['green'])} main ?{git_untracked()} </span>"
        f"<span class='gap'>{'·' * 400}</span>"
        f"<span class='right'> {status}"
        f"<span style='color:{C['cyan']}'>{box(C['cyan'])} base </span>"
        f"<span style='color:{C['green']}'>{box(C['green'])} system </span>"
        f"<span style='color:{C['cyan']}'>{box(C['cyan'])} {now}</span></span></div>"
    )


def page_css():
    return f"""
html, body {{ margin:0; background:{C['bg']}; }}
.term {{ font-family: Menlo, monospace; font-size:{FONT_PX}px; line-height:{LINE_PX}px;
         color:{C['fg']}; padding:{PAD}px; width:{WIDTH - 2 * PAD}px; }}
.row {{ display:flex; white-space:pre; height:{LINE_PX}px; overflow:hidden; }}
.gap {{ flex:1; overflow:hidden; color:{DOTS}; }}
.corner {{ color:{CORNER}; font-weight:bold; }}
.tofu {{ display:inline-block; width:0.5em; height:0.95em; margin:0 0.05em; border:1.3px solid currentColor;
         border-radius:1px; vertical-align:-0.12em; box-sizing:border-box; }}
.cursor {{ display:inline-block; width:0.6em; height:1.1em; border:1.3px solid {C['blue']};
           vertical-align:-0.2em; box-sizing:border-box; }}
.right {{ white-space:pre; }}
.out {{ white-space:pre; height:{LINE_PX}px; }}
"""


def screenshot(url_or_file, out, w, h, budget=None):
    args = [BROWSER, "--disable-gpu", "--hide-scrollbars", "--allow-file-access-from-files",
            "--force-device-scale-factor=2", f"--window-size={w},{h}",
            f"--screenshot={out}"]
    if budget:
        args.append(f"--virtual-time-budget={budget}")
    subprocess.run(args + [url_or_file], capture_output=True, timeout=60)


def terminal(name, steps):
    """steps: list of shell commands; a command starting with '@' runs hidden
    (used only for waiting on the WAF to restart, never for producing output)."""
    body, rows, rc_prev = [], 0, 0
    for i, cmd in enumerate(steps):
        if cmd.startswith("@"):
            exec(cmd[1:])  # noqa: S102 - only internal helpers such as wait_waf()
            continue
        if body:
            body.append("<div class='out'> </div>")  # p10k: newline before prompt
            rows += 1
        body.append(prompt(rc_prev))
        first, rest = cmd[:COLS - 4], cmd[COLS - 4:]   # "╰─❯ " takes 4 columns
        body.append(f"<div class='row'><span class='corner'>╰─</span>"
                    f"<span style='color:{C['green']}'>❯ </span>"
                    f"<span>{html.escape(first)}</span></div>")
        rows += 2
        while rest:                                   # long commands wrap like a terminal
            body.append(f"<div class='out'>{html.escape(rest[:COLS])}</div>")
            rest, rows = rest[COLS:], rows + 1
        rc_prev, out = sh(cmd)
        if out:
            for r in wrap(out):
                body.append(f"<div class='out'>{html.escape(r) or ' '}</div>")
                rows += 1
    body.append("<div class='out'> </div>")
    body.append(prompt(rc_prev))
    body.append(f"<div class='row'><span class='corner'>╰─</span>"
                f"<span style='color:{C['green']}'>❯ </span><span class='cursor'></span></div>")
    rows += 3
    page = TMP / f"{name}.html"
    page.write_text(f"<!doctype html><meta charset='utf-8'><style>{page_css()}</style>"
                    f"<div class='term'>{''.join(body)}</div>", encoding="utf-8")
    screenshot(page.as_uri(), OUT / f"{name}.png", WIDTH, rows * LINE_PX + 2 * PAD)
    print("  terminal", name)


def browser(name, url, post=None, height=760):
    """Capture a real page; post={field: value} submits a form like a user would."""
    raw = TMP / f"{name}-raw.png"
    if post:
        inputs = "".join(f"<input name='{html.escape(k)}' value=\"{html.escape(v)}\">"
                         for k, v in post.items())
        form = TMP / f"{name}-form.html"
        form.write_text(f"<form id=f method=post action='{url}'>{inputs}</form>"
                        "<script>document.getElementById('f').submit()</script>")
        screenshot(form.as_uri(), raw, 1280, height, budget=4000)
    else:
        screenshot(url, raw, 1280, height, budget=2000)
    shown = urllib.parse.unquote(url.replace("http://", ""))
    try:
        data = urllib.parse.urlencode(post).encode() if post else None
        body = urllib.request.urlopen(url, data=data, timeout=5).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        body = ""
    title = (html.unescape(body.split("<title>")[1].split("</title>")[0])
             if "<title>" in body else shown)
    frame = TMP / f"{name}-frame.html"
    frame.write_text(f"""<!doctype html><meta charset='utf-8'><style>
body{{margin:0;background:#202124;font-family:-apple-system,Segoe UI,sans-serif}}
.tabs{{height:38px;display:flex;align-items:flex-end;padding-left:78px;position:relative}}
.dots{{position:absolute;left:14px;top:13px;display:flex;gap:8px}}
.dots i{{width:12px;height:12px;border-radius:50%;display:block}}
.tab{{background:#35363a;color:#e8eaed;font-size:12px;padding:9px 16px;border-radius:8px 8px 0 0;
      width:230px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.bar{{background:#35363a;height:40px;display:flex;align-items:center;padding:0 12px;gap:12px;color:#9aa0a6}}
.url{{flex:1;background:#202124;border-radius:16px;height:28px;display:flex;align-items:center;
      padding:0 14px;color:#e8eaed;font-size:13.5px;white-space:nowrap;overflow:hidden}}
.url b{{color:#9aa0a6;font-weight:normal;margin-right:8px}}
img{{display:block;width:1280px}}</style>
<div class=tabs><div class=dots><i style=background:#ff5f57></i><i style=background:#febc2e></i>
<i style=background:#28c840></i></div><div class=tab>{html.escape(title)}</div></div>
<div class=bar>&#8592; &#8594; &#8635;<div class=url><b>&#9432;</b>{html.escape(shown)}</div></div>
<img src='{raw.as_uri()}'>""", encoding="utf-8")
    screenshot(frame.as_uri(), OUT / f"{name}.png", 1280, height + 78)
    print("  browser ", name)


# --------------------------------------------------------------------------- #
D, W = "http://localhost:5001", "http://localhost:8080"
UNION = "/products?q=%27%20UNION%20SELECT%20username,password,1%20FROM%20users--"
PING = "/tools/ping?host=127.0.0.1;id"
TRAV = "/docs?file=../../../../etc/passwd"
SSRF = "/fetch?url=http://127.0.0.1:5000/internal/admin"
BYPASS = {"username": "admin'--", "password": "anything"}
FEEDBACK = ('--data-urlencode "name=Pema" --data-urlencode "message=Please select the best '
            "delivery option for me; I'd like to drop by your shop and update my order from "
            'last week."')
CODE = '-s -o /dev/null -w "HTTP %{http_code}\\n"'
RECREATE = "docker compose up -d --force-recreate waf"

SHOTS = [
    # A. setup
    ("01-project-structure", "t", ["tree -a -I '.git|logs|screenshots|__pycache__|.DS_Store' --dirsfirst"]),
    ("02-containers-running", "t", ['docker compose ps --format "table {{.Name}}\\t{{.Service}}\\t{{.Status}}\\t{{.Ports}}"']),
    ("03-waf-version", "t", ['docker compose logs waf | grep -E "libmodsecurity3 version|rules loaded" | tail -2',
                             "docker exec vulnshop-waf grep -m1 -o \"ver:'OWASP_CRS/[0-9.]*\" /etc/modsecurity.d/owasp-crs/crs-setup.conf"]),
    ("04-compose-config", "t", ["sed -n '/^  waf:/,$p' docker-compose.yml"]),
    ("05-custom-rules", "t", ["sed -n '/^# B4. Ping tool/,/t:none\"$/p' waf/rules/custom-before-crs.conf",
                              "grep -c '^SecRule\\|^SecAction' waf/rules/custom-*-crs.conf"]),
    ("06-nginx-hardening", "t", ["cat waf/nginx/custom-hardening.conf.template"]),
    # B. baseline - direct to the app
    ("07-app-home", "b", (D + "/",)),
    ("08-sqli-login-direct", "b", (D + "/login", BYPASS)),
    ("09-sqli-union-direct", "b", (D + UNION,)),
    ("10-cmdi-direct", "b", (D + PING,)),
    ("11-traversal-direct", "b", (D + TRAV,)),
    ("12-upload-direct", "t", ["cat tools/samples/shell.php",
                               f'curl {CODE} -F "file=@tools/samples/shell.php" {D}/upload',
                               f"curl -s {D}/uploads/shell.php"]),
    ("13-ssrf-direct", "b", (D + SSRF,)),
    ("14-env-leak-direct", "b", (D + "/.env",)),
    ("15-stacktrace-direct", "b", (D + "/report?year=abc",)),
    ("16-headers-direct", "t", [f"curl -sI {D}/"]),
    # C. same attacks through the WAF
    ("17-sqli-login-waf", "b", (W + "/login", BYPASS)),
    ("18-sqli-union-waf", "b", (W + UNION,)),
    ("19-cmdi-waf", "b", (W + PING,)),
    ("20-traversal-waf", "b", (W + TRAV,)),
    ("21-upload-waf", "t", [f'curl {CODE} -F "file=@tools/samples/shell.php" {W}/upload',
                            f'curl {CODE} -F "file=@tools/samples/shell.php;filename=shell.php.jpg" {W}/upload',
                            f'curl {CODE} -F "file=@tools/samples/shell.php;filename=photo.jpg" {W}/upload']),
    ("22-ssrf-waf", "b", (W + SSRF,)),
    ("23-env-leak-waf", "b", (W + "/.env",)),
    ("24-stacktrace-waf", "b", (W + "/report?year=abc",)),
    ("25-headers-waf", "t", [f"curl -sI {W}/"]),
    # D. which rule blocked what
    ("26-waf-error-log", "t", [f'curl {CODE} "{W}{UNION}"',
                               'docker compose logs waf | grep "Access denied" | tail -1']),
    ("27-audit-log-sqli", "t", [f'curl {CODE} "{W}{UNION}"', "python3 tools/waf_log.py -n 1"]),
    ("28-audit-log-custom-rule", "t", [f'curl {CODE} "{W}{PING}"', "python3 tools/waf_log.py -n 1"]),
    ("45-summary-direct-vs-waf", "t", [
        'printf "%-7s %-5s %s\\n" DIRECT WAF REQUEST; for u in "/products?q=laptop" '
        '"/products?q=%27%20UNION%20SELECT%20username,password,1%20FROM%20users--" '
        '"/product?id=1%20AND%201=1" "/tools/ping?host=127.0.0.1;id" "/docs?file=../../../../etc/passwd" '
        '"/fetch?url=http://127.0.0.1:5000/internal/admin" "/.env" "/backup/db_backup.sql" '
        '"/report?year=abc" "/docs?file=welcome.txt" "/tools/ping?host=127.0.0.1"; do '
        'printf "%-7s %-5s %s\\n" $(curl -s -o /dev/null -w "%{http_code}" "localhost:5001$u") '
        '$(curl -s -o /dev/null -w "%{http_code}" "localhost:8080$u") "$u"; done']),
    # E. custom rules in action
    ("29-legit-traffic-allowed", "b", (W + "/products?q=laptop",)),
    ("30-special-chars-allowed", "b", (W + "/products?q=Rock%20%26%20Roll",)),
    ("31-upload-legit", "t", ["file tools/samples/product.png",
                              f'curl {CODE} -F "file=@tools/samples/product.png" {W}/upload']),
    ("35-generic-error-page", "t", [f"curl -s -d \"username=alice&password=it's\" {D}/login | grep -A1 '<pre'",
                                    f"curl -s -d \"username=alice&password=it's\" {W}/login | grep -E '<h1>|<p>'"]),
    ("39-lmdb-collection-file", "t", ["docker exec vulnshop-waf ls -la /tmp"]),
    ("32-bruteforce-lockout", "t", [
        "@sh(RECREATE); wait_waf()",
        'for i in 1 2 3 4 5 6 7; do curl -s -o /dev/null -w "%{http_code} " '
        '-d "username=alice&password=wrong$i" localhost:8080/login; done; echo',
        f'curl {CODE} -d "username=alice&password=alice2026" localhost:8080/login']),
    ("33-bruteforce-audit", "t", ["python3 tools/waf_log.py -n 3"]),
    ("34-bruteforce-expiry", "t", [f'sleep 61 && curl {CODE} -d "username=alice&password=alice2026" localhost:8080/login']),
    # F. comparison and tuning
    ("36-crs-only-vs-custom", "t", [
        f"CUSTOM_RULES=none {RECREATE}", "@wait_waf()",
        f'curl -s "{W}/report?year=abc" | head -8',
        RECREATE, "@wait_waf()",
        f'curl {CODE} "{W}/report?year=abc"']),
    ("37-paranoia-level-2", "t", [
        f"CUSTOM_RULES=none PARANOIA=2 {RECREATE}", "@wait_waf()",
        f"curl {CODE} {FEEDBACK} {W}/feedback", "python3 tools/waf_log.py -n 1",
        f"PARANOIA=2 {RECREATE}", "@wait_waf()",
        f"curl {CODE} {FEEDBACK} {W}/feedback"]),
    ("38-detection-only", "t", [
        f"RULE_ENGINE=DetectionOnly {RECREATE}", "@wait_waf()",
        f'curl {CODE} "{W}{UNION}"',
        "python3 tools/waf_log.py -n 1",
        RECREATE, "@wait_waf()",
        f'curl {CODE} "{W}{UNION}"']),
]


def main():
    if not BROWSER:
        sys.exit("Run: npx playwright install chromium-headless-shell")
    OUT.mkdir(exist_ok=True)
    wanted = sys.argv[1:]
    sh(RECREATE)
    wait_waf()
    for name, kind, spec in SHOTS:
        if wanted and not any(name.startswith(w) for w in wanted):
            continue
        if kind == "t":
            terminal(name, spec)
        else:
            browser(name, *spec)
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"done -> {OUT}")


if __name__ == "__main__":
    main()
