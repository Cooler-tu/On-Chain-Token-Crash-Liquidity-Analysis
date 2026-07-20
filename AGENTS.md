# AGENTS.md — On-Chain Token Crash Project

This file defines how I (Codex) should operate on this project. It's a self-discipline document to keep work focused, traceable, and efficient.

---

## 1. Research Workflow

When investigating a token or running analysis:

### 1.1 Before running analysis
- Check if the token has already been analyzed by looking at `output*/token_profile.json`
- Read `plan.md` to see if this is a planned research target
- Confirm the RPC endpoint is configured (`ETH_RPC_URL` or `--rpc-url`)
- Decide on a meaningful block window — don't default to the CLI's defaults blindly

### 1.2 While running analysis
- Log key findings in `README.md` under a "Recent Findings" section (English + Chinese)
- If the token reveals something unusual (new protocol, unusual risk pattern, suspicious holder behavior), document it in `research-notes/` as a markdown file
- Capture the output directory name and the command used

### 1.3 After analysis completes
- Run `python3 scripts/publish_site.py` to regenerate the public site
- Commit the output data and generated site together in one commit
- Update `plan.md` — move completed item to "✅ Completed" section
- Add a row to `README.md`'s analysis log table

---

## 2. Plan Management (`plan.md`)

Maintain a file at the project root called `plan.md`. Structure:

```markdown
# Plan

## ✅ Completed

- [token/feature] — what was done, output directory, date

## 🎯 Current

- What I'm working on now (max 1 item)

## 📋 Backlog (ordered by priority)

- Next thing
- Future thing

## 🚀 Final Goal

The ultimate vision for this project (keep it short).
```

Rules:
- Every time I finish a distinct piece of work, update `plan.md`
- Don't add every tiny subtask to the plan — only meaningful milestones
- The "Completed" section is append-only (keep history)
- If a backlog item has unclear requirements, write a brief description of what needs to be decided

---

## 3. Progress Tracking in `README.md`

`README.md` is the public-facing face of the project. Keep it tidy. For research progress specifically:

### English section — add a block like:

```markdown
### Analysis Log

| Token | Window | Pools | Holder | Risk | Date | Dir |
|-------|--------|-------|--------|------|------|-----|
| SPX   | 19000022–19000022 | 8 V2/V3 | 3 | 0.1944 LOW | 2026-07-18 | `output/` |
```

Add a new row for each completed analysis. Keep the table sorted by most recent first.

### Chinese section — same content, translated.

Don't let `README.md` become bloated. Keep the setup/pipeline/architecture docs concise. Research logs go in the table, not prose.

---

## 4. Resume Efficiency (No Full Scans)

Starting a new session costs tokens. Follow these rules to keep it cheap:

### 4.1 Don't scan the whole repo
- **DO NOT** run `find .`, `ls -R`, or `rg` across the entire project tree on resume
- **DO NOT** read every output file or every source file
- This wastes compute and is almost never needed

### 4.2 What to do instead on resume

1. **Read `AGENTS.md`** (this file) — refreshes context
2. **Read `plan.md`** — see where we are
3. **Read `README.md`** summary section — see the high-level state
4. **Read only the specific files needed** for the task at hand

### 4.3 If you need to understand recent state

- `git log --oneline -10` — see what happened recently
- `git diff --name-only HEAD~1` — what changed in the last commit
- Read the specific files from the diff, not the whole tree

### 4.4 Exception

If the task genuinely requires a broad scan (e.g. "find all tokens with high risk", "clean up all output directories"), you may scan — but state the scope explicitly before doing it.

---

## 5. Output & Data Conventions

- Each analysis run goes in its own `output-{purpose}/` directory
- `output/` is the default and is in `.gitignore` — don't commit it
- Named output dirs like `output-spx-demo/` are committed (they contain example data)
- Never commit `__pycache__/`, `.DS_Store`, `.env`, or binary artifacts
- When adding new output data to the public site, always regenerate the site

---

## 6. Public Site

- `site/` is the deployment source — always regenerate with `scripts/publish_site.py` after new analysis
- Don't edit `site/` files by hand; always regenerate
- After regeneration, check that the landing page lists the new token
- The site is served via GitHub Actions (`.github/workflows/deploy-pages.yml`) on push to `main`

---

## 7. Communication Style on This Project

- When doing research, keep commentary focused on what the data means — not just what you ran
- If a result is surprising (e.g. risk score much higher than expected), call it out
- Write findings bilingually (English + Chinese) in `README.md` updates
- Keep final answers structured but not rigid — let the shape match the results
- For analysis results, prefer tables over paragraphs when comparing multiple data points

---

## 8. Safety & Guardrails

- Never run `git reset --hard` or `git checkout -- .` on this project without explicitly confirming
- Don't delete output data unless the user asks for cleanup
- Don't modify `.gitignore` without explaining why
- If the analysis pipeline fails mid-way, preserve partial output — don't clean it up
- Before pushing to the public fork (`fork` remote), confirm with the user

---

## 9. Publication & Deployment

- Each new token analysis → regenerate site → commit → push
- Deployment is automatic via GitHub Actions; no need to manually configure Pages
- The live URL is `https://jelly577.github.io/On-Chain-Token-Crash-Liquidity-Analysis/`
- If the README analysis log grows beyond ~20 rows, suggest archiving old rows into a separate `HISTORY.md`

---

## 10. Quick Reference

```bash
# Full pipeline
python3 -m src.cli analyze <TOKEN> --from-block <N> --to-block <N> --output-dir output-<name>

# Regenerate dashboard only (from existing output)
python3 -m src.cli dashboard --output-dir output-<name>

# Build public site
python3 scripts/publish_site.py

# Preview public site
python3 scripts/publish_site.py --serve
```
