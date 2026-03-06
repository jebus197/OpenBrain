# Open Brain Keyboard Shortcuts & Quick Commands

## Shell Aliases

Add these to your `~/.zshrc` or `~/.bashrc` for quick access:

```bash
# Open Brain CLI shortcuts
alias ob="python3 -m open_brain.cli"
alias obst="ob status"
alias obc="ob capture"
alias obs="ob search"
alias obl="ob list-recent --limit 10"
alias obp="ob pending-tasks"
alias obctx="ob session-context"

# IM shortcuts (set OB_PROJECT to your default project)
export OB_PROJECT="my_project"
alias im="python3 /path/to/OpenBrain/tools/im_service.py --project $OB_PROJECT"
alias imr="im read"
alias imp="im post"
alias imrs="im r"

# Bridge management (macOS launchd)
alias obd="launchctl list | grep openbrain"
alias oblog="tail -30 /path/to/OpenBrain/logs/ob_bridge.log"
alias obstart="launchctl load ~/Library/LaunchAgents/com.openbrain.bridge.plist"
alias obstop="launchctl unload ~/Library/LaunchAgents/com.openbrain.bridge.plist"
alias obrestart="launchctl stop com.openbrain.bridge"
```

After adding, reload your shell:
```bash
source ~/.zshrc
```

## Common Workflows

### Agent startup
```bash
obst                   # Check OB status
obctx --agent myagent  # Get session context
imr                    # Read IM
```

### Post a memory + notify
```bash
obc "Completed API refactor" --agent myagent --type insight --area backend
imp otheragent "myagent: API refactor complete. 5 new tests."
```

### Search for context
```bash
obs "authentication pipeline"     # Semantic search
obl --limit 20 --agent myagent   # Recent memories from an agent
obp --agent myagent              # My pending tasks
```

### Bridge management
```bash
obd          # Is bridge running?
oblog        # Recent bridge activity
obrestart    # Restart (auto-recovers in 10s)
```

### Drop a memory file (for sandboxed agents)
```bash
cat > /path/to/outbox/my_note.json << 'EOF'
{
  "agent": "myagent",
  "type": "insight",
  "area": "backend",
  "text": "Refactored API endpoints to use async handlers."
}
EOF
# Bridge picks it up within 60 seconds
```

## Valid Memory Types

| Type | Use for |
|------|---------|
| `session_summary` | End-of-session state capture |
| `insight` | Technical or architectural insight |
| `decision` | Design decision or conclusion |
| `task` | Action item (supports status tracking) |
| `blocker` | Something preventing progress |
| `review` | Code review or assessment |
| `handoff` | Context transfer between agents |

## Default Areas

`general`, `backend`, `frontend`, `api`, `database`, `infra`, `testing`,
`security`, `devops`, `ux`, `docs`, `ops`

Areas are configurable — add your own in `~/.openbrain/config.json`:
```json
{
  "areas": ["general", "backend", "frontend", "ml", "data", "infra"]
}
```

## Agents

Configured per project in `~/.openbrain/projects.json`. Example identifiers:
- `cc` — Claude Code
- `cx` — OpenAI Codex
- `copilot` — GitHub Copilot
- Any alphanumeric identifier your workflow requires
