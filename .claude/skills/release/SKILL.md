---
name: release
description: Run security scan, tag, and create GitHub release
argument-hint: "<version>"
user-invocable: true
allowed-tools: "Bash Read Write Edit Grep Glob"
---

# Release BMT AI OS

Run the full release pipeline for version `$ARGUMENTS`.

## Steps

1. **Security gate**: Run `./scripts/security-report.sh $ARGUMENTS`
2. **Verify tests**: `python3 -m pytest tests/unit/ tests/smoke/ -q`
3. **Update version**: Set `$ARGUMENTS` in VERSION, pyproject.toml, CHANGELOG.md
4. **Build Docker image**: `docker build -t bemindlab/bmt-ai-os:$ARGUMENTS .`
5. **Push Docker image**: `docker push bemindlab/bmt-ai-os:$ARGUMENTS`
6. **Create PR**: Commit all version changes, create PR, merge
7. **Tag release**: `git tag $ARGUMENTS && git push origin $ARGUMENTS`
8. **GitHub release**: `gh release create $ARGUMENTS --notes-file releases/$ARGUMENTS.md`

## Pre-checks

Current version: !`cat VERSION`
Git status: !`git status --short | head -5`
Last tag: !`git describe --tags --abbrev=0 2>/dev/null || echo "none"`
