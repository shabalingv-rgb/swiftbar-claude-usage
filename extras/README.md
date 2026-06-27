# Extras: Weekly History Collector (Optional)

These files are **not required** for the main plugin. The main `claude-usage.1m.sh` (v5.0) tracks weekly usage directly via the OAuth endpoint.

Use these extras only if you want:
- Historical `$ spent per day` breakdown
- Long-term weekly usage trends stored locally

## Files

| File | Purpose |
|------|---------|
| `collect.py` | Hourly collector: calls `ccusage daily` and writes to `state.json` |
| `com.claude.usage.calibrate.plist.template` | launchd job template (runs collect.py hourly) |

## Requirements

- [ccusage](https://github.com/ryanoasis/ccusage) npm package: `npm install -g ccusage`
- Node.js (via Homebrew: `brew install node`)

## Setup

```bash
# 1. Create folder
mkdir -p ~/.claude-usage-calibrate

# 2. Copy collect.py (replace YOUR_USERNAME)
sed "s/YOUR_USERNAME/$USER/g" collect.py > ~/.claude-usage-calibrate/collect.py

# 3. Copy and edit the launchd plist
sed "s/YOUR_USERNAME/$USER/g" com.claude.usage.calibrate.plist.template \
  > ~/Library/LaunchAgents/com.claude.usage.calibrate.plist

# 4. Load the job
launchctl load ~/Library/LaunchAgents/com.claude.usage.calibrate.plist
```

The script will now run hourly while you're using Claude Code, writing weekly summaries to:
`~/Library/Caches/com.swiftbar.claude-usage/state.json`
