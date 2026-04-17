---
description: Pull and integrate remote changes
---

Pull and integrate remote changes:

Before pulling:
- Run git status to check for local changes
- Run git fetch to see remote updates
- Run git log HEAD..@{u} --oneline to see incoming commits

Pull:
- Run git pull --rebase (preferred for cleaner history)
- Or run git pull if rebase not appropriate
- Run git status to verify

Resolve conflicts if any:
- List conflicted files
- Suggest resolution strategy

Report pull status and any conflicts.