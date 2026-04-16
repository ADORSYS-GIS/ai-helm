---
description: Reset working tree to specific state
---

Reset working tree for **$ARGUMENTS**:

Soft reset (keep changes):
- Run git reset --soft HEAD~1 (undo last commit, keep staged)
- Run git reset --mixed HEAD~1 (undo commit, keep unstaged)

Hard reset (discard changes):
- Run git reset --hard HEAD (discard all uncommitted)
- WARNING: This is destructive

Undo specific file:
- Run git checkout HEAD -- <file>
- Run git restore <file>

Report reset action and current state.