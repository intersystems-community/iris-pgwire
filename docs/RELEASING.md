# Release Guide: Publishing to PyPI and GitHub

This guide outlines the standard workflow for creating a new release of `iris-pgwire`.

## 1. Finalize Version and Changelog

1.  **Update Version**: Increment the version in `src/iris_pgwire/__init__.py`.
    ```python
    __version__ = "1.0.7"
    ```
2.  **Update Changelog**: Ensure `CHANGELOG.md` is updated with all changes for the new version.
3.  **Verify Tests**: Run the full suite to ensure no regressions.
    ```bash
    pytest tests/
    ```

## 2. Merge and Push to Remotes

Merge your feature branch into `main` and push to both the development and community remotes.

```bash
git checkout main
git merge feature-branch-name
git push origin main
git push community main
```

## 3. Create a Git Tag

Create a semantic version tag on the `main` branch and push it to the `community` remote.

```bash
git tag -a v1.0.7 -m "Release version 1.0.7"
git push community v1.0.7
```

## 4. Build and Publish to PyPI

We use `hatch` (via `uv` or directly) to build the package.

### Build the Package
```bash
# Clean previous builds
rm -rf dist/

# Build source distribution and wheel
uv build
```

### Verify Package Contents
```bash
tar -tzf dist/*.tar.gz
```

### Upload to PyPI
You will need your PyPI API token configured.

```bash
# Test upload (optional but recommended)
twine upload --repository testpypi dist/*

# Production upload
twine upload dist/*
```

## 5. Post-Release

1.  **Verify on PyPI**: Check [pypi.org/project/iris-pgwire/](https://pypi.org/project/iris-pgwire/).
2.  **GitHub Release**: Go to the `community` repository on GitHub and create a new release from the tag, pasting the changelog notes.
3.  **Update AGENTS.md**: Run the context update script to keep agent instructions in sync.
    ```bash
    bash .specify/scripts/bash/update-agent-context.sh
    ```
