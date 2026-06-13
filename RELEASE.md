# Ragarium Release Checklist

This project uses local tags and GitHub releases for distribution. Do not run
the remote steps unless you intentionally want to publish.

## Local Verification

```bash
python -m pip install -e ".[dev]"
python -m pytest tests/test_api.py tests/test_eval_presets.py tests/test_workflow.py
python -m pytest
cd frontend
npm ci
npm run build
```

If URL ingestion will be tested manually, install Chromium once:

```bash
python -m playwright install chromium
```

## Version Bump

1. Update `version` in `pyproject.toml`.
2. Update release notes with the notable API, packaging, and frontend changes.
3. Re-run the local verification commands above.

## Tag And Release

Remote publication is intentionally separate from local verification.

```bash
git status --short
git tag -a v0.4.0 -m "v0.4.0"
git push origin v0.4.0
gh release create v0.4.0 --title "Ragarium v0.4.0" --notes-file RELEASE_NOTES_v0.4.0.md --prerelease
```

## Rollback Notes

- If the package install is broken, delete the local tag before pushing:
  `git tag -d v0.4.0`.
- If a pushed prerelease is wrong, create a patch release instead of moving the
  published tag.
- The local runtime state under `var/` and Chroma data are not release
  artifacts.
