# Cloud Demo Deployment

## Design intent

Deep Mastery Lab is a **single-user, local-first application**. All persistent state — course progress, SRS scheduling, settings — is stored on disk and tied to one user's machine. There is no authentication, no per-user isolation, and no multi-tenancy.

The Streamlit Community Cloud deployment is a **read-only demo** of the learning experience. It is not intended for real study. The three pre-loaded courses exist to demonstrate the UI and learning flow; nothing the user does is saved between sessions.

---

## How cloud mode is activated

Add the following to the app's **Secrets** in the Streamlit Cloud dashboard (Settings → Secrets):

```toml
IS_CLOUD = true
```

This single flag enables all restrictions below. Locally, without this secret, the app behaves normally.

---

## What is disabled in cloud mode

### Persistence — no writes to disk

| Manager | Normal behaviour | Cloud behaviour |
|---------|-----------------|-----------------|
| `ProgressManager` | Saves progress + metrics to `_progress.pkl` / `_metrics.pkl` | `save()` and `update_metrics()` are no-ops |
| `SettingsManager` | Saves provider/model/prompt settings to `settings.json` | `save()` is a no-op |
| `KeysManager` | Reads/writes API keys to `keys.json` | No disk I/O; keys live in session state only |
| SRS recording | `record_answers_batch()` in `learn_feedback_render.py` updates `srs.db` | Skipped entirely |

Session state still works normally within a session — navigation, answers, and in-memory progress are intact. Nothing persists after the browser tab closes.

### UI — disabled buttons

**Welcome screen**
- Review (SRS) button
- Manage Decks button
- AI Course Creator button (also gated by missing API key)

**Sidebar**
- Start Review button
- Manage Decks button

**Settings → Courses tab**
- Reset popover (Clear Progress / Clear Metrics)
- Delete popover (Confirm Purge)
- AI Course Generator button

**Settings → API tab**
- Clear Cache popover (Clear Cards / Clear Questions)

**Settings → Prompts tab**
- Apply to all content popover (Clear Cards / Clear Questions)

**Lesson card header**
- Regenerate content button (also gated by missing API adapter)

**Test header**
- Regenerate test questions popover (also gated by missing API adapter)

### Content mode default

Locally, the app starts in **raw mode** (source text visible, no AI card generation until requested). On cloud, it starts in **AI-generated mode** so the demo immediately showcases both content types — users can still toggle to raw mode via the switch button in the lesson header.

The local preference is saved to `settings.json` and restored on next launch. In cloud, the preference is never persisted (settings save is a no-op), so every session starts fresh in AI-generated mode.

### Content generation — no API

No API keys are configured in the cloud deployment. All lesson cards and question pools are pre-generated and committed to the repository. The app falls back gracefully when no adapter is present:

- Cached cards are served directly; if a card is missing, an info message is shown instead of crashing
- Cached question pools are loaded at test time; if a pool is missing, a warning is shown
- Prefetch pipeline exits immediately when adapter is `None`

---

## Pre-loaded courses

The following courses are committed to the repository and available in the demo:

- `Computer_Science_OpenStax`
- `Pharmacology__OpenStax_`
- `World_War_I_Wikipedia`

All other course data is excluded via `.gitignore`. The `data/srs_data/srs.db` file is also excluded.

---

## What demo users can do

- Browse pre-loaded courses from the welcome screen
- Work through the full learning flow: lesson card → question test → feedback → next lesson
- Use Custom Study (mastery mode) to review a range of lessons
- Switch between AI-generated content and raw source material
- Open Settings to inspect prompts and model configuration (read-only)

## What demo users cannot do

- Create new courses
- Regenerate cards or questions
- Save progress across sessions
- Use SRS review
- Clear or delete any course data
- Change settings persistently
