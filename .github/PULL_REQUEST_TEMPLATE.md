## Summary

<!-- What does this PR do? One or two sentences. -->

Closes #<!-- issue number -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] New connector
- [ ] Refactor (no behavior change)
- [ ] Documentation

## Testing

- [ ] `pytest tests/ -v` passes with no errors
- [ ] `docker compose up --build` starts cleanly
- [ ] Manually tested the affected flow end-to-end

<!-- Describe what you tested and how -->

## Checklist

- [ ] My changes follow the style guide in CONTRIBUTING.md
- [ ] I have added tests for new behavior
- [ ] I have updated documentation / README where needed
- [ ] No secrets or `.env` values are included in this PR
- [ ] Database changes use safe DDL only (`ADD COLUMN IF NOT EXISTS`, never `DROP`)
