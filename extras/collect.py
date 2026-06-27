#!/usr/bin/env python3
"""
claude-usage-collect.py
Собирает точку данных: внутренние метрики + % из claude.ai (авто или вручную).
Сохраняет в data.jsonl рядом со скриптом.

Запускается автоматически через launchd каждый час с 11 до 20.
Молча выходит, если нет активной сессии Claude Code.
Через 7 дней показывает напоминание поделиться данными с Клодом.

Авто-чтение из браузера (опционально):
  Safari: включите Safari → Разработка → Разрешить JavaScript из событий Apple
  Chrome: работает без настроек, если вкладка claude.ai открыта.
"""

import json, os, glob, subprocess, sys, re
from datetime import datetime, timezone, timedelta, date as _date

HERE             = os.path.dirname(os.path.abspath(__file__))
DATA_FILE        = os.path.join(HERE, "data.jsonl")
REMINDER_FLAG    = os.path.join(HERE, ".week_reminder_shown")
CCUSAGE          = "/opt/homebrew/bin/ccusage"
JSONL_GLOB       = os.path.expanduser("~/.claude/projects/*/*.jsonl")
WEEK_DAYS        = 7
STATE_DIR        = os.path.expanduser("~/Library/Caches/com.swiftbar.claude-usage")
STATE_FILE       = os.path.join(STATE_DIR, "state.json")

PRICING = {
    "opus":   {"in": 5.0, "out": 25.0, "cw5": 6.25, "cw1h": 10.0, "cr": 0.50},
    "sonnet": {"in": 3.0, "out": 15.0, "cw5": 3.75, "cw1h":  6.0, "cr": 0.30},
    "haiku":  {"in": 1.0, "out":  5.0, "cw5": 1.25, "cw1h":  2.0, "cr": 0.10},
}

def family(m):
    m = (m or "").lower()
    for f in ("opus", "sonnet", "haiku"):
        if f in m: return f
    return "sonnet"

def block_non_cr(b):
    dom = family(b.get("models", ["opus"])[0]) if b.get("models") else "opus"
    cr_tok = b.get("tokenCounts", {}).get("cacheReadInputTokens", 0)
    return max(b.get("costUSD", 0) - cr_tok * PRICING[dom]["cr"] / 1_000_000, 0.0)

def notify(title, message, subtitle=""):
    sub = f' subtitle "{subtitle}"' if subtitle else ""
    subprocess.run(["osascript", "-e",
        f'display notification "{message}" with title "{title}"{sub}'],
        capture_output=True)

def dialog(prompt, default="", title="Claude Usage Calibration"):
    r = subprocess.run(["osascript", "-e",
        f'tell app "System Events" to display dialog "{prompt}" '
        f'default answer "{default}" with title "{title}"'],
        capture_output=True, text=True)
    if r.returncode != 0:
        return None
    m = re.search(r"text returned:(.+)", r.stdout)
    return m.group(1).strip() if m else None

# ── Проверяем, прошла ли неделя ──────────────────────────────────────
def check_week_reminder():
    if os.path.exists(REMINDER_FLAG):
        return False
    if not os.path.exists(DATA_FILE):
        return False
    try:
        with open(DATA_FILE) as f:
            first_line = f.readline()
        if not first_line:
            return False
        first_entry = json.loads(first_line)
        first_ts = datetime.fromisoformat(first_entry["timestamp"])
        if (datetime.now(timezone.utc) - first_ts).days >= WEEK_DAYS:
            return True
    except Exception:
        pass
    return False

if check_week_reminder():
    n = sum(1 for _ in open(DATA_FILE)) if os.path.exists(DATA_FILE) else 0
    r = subprocess.run(["osascript", "-e",
        f'tell app "System Events" to display dialog '
        f'"📊 Неделя сбора данных завершена!\n\n'
        f'Собрано точек: {n}\nФайл: ~/.claude-usage-calibrate/data.jsonl\n\n'
        f'Попросите Клода проанализировать записи и обновить формулу плагина." '
        f'with title "Claude Usage — анализ готов" '
        f'buttons {{"Напомнить позже", "Понятно"}} default button "Понятно"'],
        capture_output=True, text=True)
    if "Понятно" in r.stdout:
        open(REMINDER_FLAG, "w").close()  # больше не показываем
    # продолжаем сбор данных

# ── 0. Загрузка / сохранение state.json ──────────────────────────────
def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(st):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(st, f)

# ── 0b. Недельный кэш для плагина SwiftBar ────────────────────────────
# Вычисляет недельные данные через ccusage daily и пишет в state.json.
# Вызывается при каждом запуске launchd (раз в час), независимо от сессии.
def update_weekly_cache():
    print("обновляю недельный кэш...", flush=True)
    try:
        draw = subprocess.run([CCUSAGE, "daily", "--json", "--breakdown"],
                              capture_output=True, text=True)
        ddata = json.loads(draw.stdout)
    except Exception as e:
        print(f"weekly cache: ошибка ccusage daily: {e}", flush=True)
        return
    today = _date.today()
    # Неделя сбрасывается в пятницу (weekday=4).
    # Формула: days_since_reset = (weekday - 4) % 7
    WEEK_RESET_DOW = 4  # пятница
    days_since_reset = (today.weekday() - WEEK_RESET_DOW) % 7
    week_start = today - timedelta(days=days_since_reset)  # текущая пятница

    day_cost = {}
    for r in ddata.get("daily", []):
        try:
            dt = datetime.strptime(r.get("period", ""), "%Y-%m-%d").date()
        except Exception:
            continue
        for mb in r.get("modelBreakdowns", []):
            nm = mb.get("modelName", "")
            if "claude" not in nm:
                continue
            fam = family(nm)
            c = max((mb.get("cost", 0) or 0)
                    - (mb.get("cacheReadTokens", 0) or 0) * PRICING[fam]["cr"] / 1_000_000,
                    0.0)
            day_cost[dt] = day_cost.get(dt, 0.0) + c

    # Скользящие 7 суток
    week_cost = sum(day_cost.get(today - timedelta(days=k), 0.0) for k in range(7))

    # Текущая неделя (пт → сегодня, пт–чт цикл)
    cal_week_cost = sum(day_cost.get(week_start + timedelta(days=k), 0.0)
                        for k in range(days_since_reset + 1))
    days_done = days_since_reset + 1   # сколько дней прошло с пт (пт=1)
    days_left = 6 - days_since_reset   # дней до конца недели (до чт включительно)
    daily_avg = cal_week_cost / days_done if days_done else 0.0
    projected_eow = cal_week_cost + daily_avg * days_left

    # Исторический пик (для автолимита)
    hist_peak = 0.0
    if day_cost:
        end = today - timedelta(days=1)
        d = min(day_cost)
        while d <= end:
            s = sum(day_cost.get(d - timedelta(days=k), 0.0) for k in range(7))
            hist_peak = max(hist_peak, s)
            d += timedelta(days=1)

    state = load_state()
    state["peak_week_cost"]     = max(state.get("peak_week_cost", 0.0), hist_peak)
    state["week_cost"]          = week_cost
    state["cal_week_cost"]      = cal_week_cost
    state["cal_week_days_done"] = days_done
    state["cal_daily_avg"]      = daily_avg
    state["cal_projected_eow"]  = projected_eow
    state["week_updated"]       = datetime.now(timezone.utc).isoformat()
    save_state(state)
    print(f"недельный кэш обновлён: rolling=${week_cost:.2f}, "
          f"с пн=${cal_week_cost:.2f}, прогноз=${projected_eow:.2f}", flush=True)

update_weekly_cache()

# ── 1. ccusage ────────────────────────────────────────────────────────
print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}] запуск", flush=True)

raw = subprocess.run([CCUSAGE, "blocks", "--json"], capture_output=True, text=True)
try:
    data = json.loads(raw.stdout)
except Exception:
    print("нет ccusage/node", flush=True); sys.exit(0)

blocks = data.get("blocks", [])
active = next((b for b in blocks if b.get("isActive")), None)

if not active:
    print("нет активного блока — выход", flush=True); sys.exit(0)

block_start = datetime.fromisoformat(active["startTime"].replace("Z", "+00:00"))
block_elapsed_min = int((datetime.now(timezone.utc) - block_start).total_seconds() / 60)
tc = active.get("tokenCounts", {})
remaining_min_ccusage = (active.get("projection") or {}).get("remainingMinutes", 0)

metrics = {
    "timestamp":         datetime.now(timezone.utc).isoformat(),
    "block_start":       active["startTime"],
    "block_elapsed_min": block_elapsed_min,
    "ccusage_cost_usd":  active.get("costUSD", 0),
    "block_non_cr":      block_non_cr(active),
    "cr_tokens":         tc.get("cacheReadInputTokens", 0),
    "input_tokens":      tc.get("inputTokens", 0),
    "output_tokens":     tc.get("outputTokens", 0),
    "cw_tokens":         tc.get("cacheCreationInputTokens", 0),
    "block_models":      active.get("models", []),
}

# ── 2. JSONL: rolling 5h + block-window + счётчик сообщений ─────────
now_utc    = datetime.now(timezone.utc)
win5h      = now_utc - timedelta(hours=5)
hour_ago   = now_utc - timedelta(hours=1)

seen = set()
nc_block = nc_5h = nc_1h = cr_block = 0.0
msgs_block = msgs_5h = 0
by_fam = {}

for path in glob.glob(JSONL_GLOB):
    try:
        mtime = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)
        if mtime < block_start and mtime < win5h:
            continue
    except OSError:
        continue
    try:
        fh = open(path, "r", errors="ignore")
    except OSError:
        continue
    with fh:
        for line in fh:
            if '"usage"' not in line: continue
            try: e = json.loads(line)
            except: continue
            ts = e.get("timestamp")
            if not ts: continue
            try: t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except: continue
            msg = e.get("message") or {}
            u = msg.get("usage") or {}
            if not u: continue
            key = (msg.get("id"), e.get("requestId"))
            if key in seen: continue
            seen.add(key)

            fam = family(msg.get("model"))
            cc = u.get("cache_creation") or {}
            i   = u.get("input_tokens", 0)
            o   = u.get("output_tokens", 0)
            cr  = u.get("cache_read_input_tokens", 0)
            cw  = (cc.get("ephemeral_1h_input_tokens", 0)
                 + cc.get("ephemeral_5m_input_tokens", 0)
                 or u.get("cache_creation_input_tokens", 0))
            p = PRICING.get(fam, PRICING["sonnet"])
            c_ncr = (i*p["in"] + o*p["out"] + cw*p["cw5"]) / 1_000_000
            c_cr  = cr * p["cr"] / 1_000_000

            if t >= block_start:
                nc_block  += c_ncr
                cr_block  += c_cr
                msgs_block += 1
                by_fam[fam] = by_fam.get(fam, 0.0) + c_ncr
            if t >= win5h:
                nc_5h    += c_ncr
                msgs_5h  += 1
            if t >= hour_ago:
                nc_1h += c_ncr

metrics.update({
    "jlog_nc_block":   nc_block,
    "jlog_nc_5h":      nc_5h,
    "jlog_nc_1h":      nc_1h,
    "jlog_cr_block":   cr_block,
    "jlog_msgs_block": msgs_block,
    "jlog_msgs_5h":    msgs_5h,
    "jlog_by_fam":     by_fam,
})

# ── 3. Авто-чтение % из браузера ────────────────────────────────────
JS_SNIPPET = "(function(){var p=document.body.innerText.match(/[0-9]+%/g);return JSON.stringify({pcts:p,url:window.location.href});})()"

def try_browser(app, execute_fn):
    script = f'''
try
    tell application "{app}"
        repeat with w in windows
            repeat with t in tabs of w
                if URL of t contains "claude.ai" then
                    set r to {execute_fn.format(js=JS_SNIPPET)}
                    return r
                end if
            end repeat
        end repeat
    end tell
    return "no-tab"
on error e
    return "err:" & e
end try'''
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.stdout.strip()

ai_pct = None
browser_source = "manual"

for app, fn in [
    ("Safari",        'do JavaScript "{js}" in t'),
    ("Google Chrome", 'execute t javascript "{js}"'),
]:
    try:
        result = try_browser(app, fn)
        if result and not result.startswith(("no-tab", "err:", "no-claude")):
            parsed = json.loads(result)
            candidates = [int(p.rstrip("%")) for p in (parsed.get("pcts") or []) if 1 <= int(p.rstrip("%")) <= 99]
            if candidates:
                ai_pct = candidates[0]
                browser_source = app.lower().replace(" ", "_")
                break
    except Exception:
        pass

# ── 4. Диалог — запрос % и оставшегося времени ───────────────────────
hint_auto  = f" (авто из браузера: {ai_pct}%)" if ai_pct else ""
block_pct_hint = f"~{int(metrics['block_non_cr']/10*100)}% по плагину"

pct_str = dialog(
    f"% использования в claude.ai{hint_auto}\n"
    f"Откройте claude.ai/new#settings/usage\n({block_pct_hint})",
    default=str(ai_pct) if ai_pct else "",
    title="Claude Usage — точка данных"
)
if pct_str is None:
    sys.exit(0)

try:
    ai_pct_final = int(pct_str.rstrip("%"))
    if not (0 < ai_pct_final <= 100):
        raise ValueError
except Exception:
    notify("Claude Calibration", "Введён неверный %, пропускаю.")
    sys.exit(0)

if browser_source != "manual" and ai_pct_final != ai_pct:
    browser_source = "manual-override"

time_str = dialog(
    f"Минут до сброса сессии (claude.ai показывает):\n(ccusage даёт ≈{remaining_min_ccusage}м)",
    default=str(remaining_min_ccusage),
    title="Claude Usage — точка данных"
)
ai_remaining = None
if time_str:
    try: ai_remaining = int(time_str)
    except: pass

# ── 5. Сохраняем точку ───────────────────────────────────────────────
metrics["claude_ai_pct"]           = ai_pct_final
metrics["claude_ai_remaining_min"] = ai_remaining
metrics["browser_source"]          = browser_source

with open(DATA_FILE, "a") as f:
    f.write(json.dumps(metrics, ensure_ascii=False) + "\n")

n = sum(1 for _ in open(DATA_FILE))
days_left = WEEK_DAYS - (datetime.now(timezone.utc) - datetime.fromisoformat(
    json.loads(open(DATA_FILE).readline())["timestamp"]
)).days

notify(
    "Claude Usage Calibration",
    f"Точка {n} сохранена: claude.ai={ai_pct_final}%, блок=${metrics['block_non_cr']:.2f}",
    subtitle=f"Осталось дней до анализа: {max(days_left,0)}"
)
