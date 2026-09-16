# JARVIS Memory Vault Index

This vault is the persistent memory for the JARVIS AI assistant system. It stores knowledge, daily session logs, project-specific context, and archived items.

## Structure

- **01 - Daily Notes/** — Automatic session logs, one file per day
- **02 - Knowledge/** — Persistent facts, preferences, and learned context
- **03 - Projects/** — Project-specific memory organized by project name
- **04 - Archive/** — Completed items, old logs, reference material

## Rules

1. **Never delete** — Archive instead. Everything in this vault is the system's memory.
2. **Timestamped entries** — Daily notes use ISO timestamps for every entry.
3. **Plain markdown** — No proprietary formats. Obsidian-compatible, readable anywhere.
4. **Profile first** — `02 - Knowledge/Profile.md` is read at every boot to orient the session.
5. **Append-only daily notes** — Never overwrite today's log; only append to it.
