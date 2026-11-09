# Contributing & Branching Workflow Policy

To maintain institutional code quality, auditability, and strict credential hygiene, **all ongoing changes must go through a Feature Branch and Pull Request (PR) before merging into `master`**.

---

## Mandatory Development Workflow

### 1. Create a Feature or Fix Branch from `master`
Never commit directly to `master`. Always branch off the latest `master`:
```bash
git checkout master
git pull origin master
git checkout -b feat/<short-description>
# or for bug fixes:
git checkout -b fix/<short-description>
```

### 2. Run Pre-Commit Security & Secret Verification
Before staging or pushing any commit, verify that:
- Zero API keys, Upstox JWT tokens, DhanHQ access tokens, Telegram bot tokens, or chat IDs are present in any tracked file or `.md` document.
- Local runtime files (`config/broker_config.json`, `config/settings.json`, `data/telegram_config.json`, `data/upstox_token.json`, `data/*.sqlite3`) remain untracked in `.gitignore`.
- No personal OS file paths (e.g. `C:\Users\...`) are hardcoded in source files or documentation.

### 3. Push the Branch & Raise a Pull Request
Push your branch to GitHub and open a Pull Request targeting `master`:
```bash
git push -u origin feat/<short-description>
gh pr create --base master --head feat/<short-description> --fill
```

### 4. Review & Merge to `master`
Once the PR diff is verified clean and passes all checks, merge it into `master` via GitHub PR merge:
```bash
gh pr merge --merge --delete-branch
git checkout master
git pull origin master
```
