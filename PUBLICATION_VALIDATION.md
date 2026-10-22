# Publication review — 2026-10-22

Selected project: CDIS — Career Decision Intelligence System, version 2.0.0.

## Source and version selection

Source: `hackathon/AI resume/CDIS_MVP_v2.0 (3)/CDIS_MVP_v2.0/cdis`.

Compared both extracted project folders and all three CDIS ZIP archives. The selected folder contains the most complete available implementation: database migrations, production configuration, audit/research documents and ML-related artifacts beyond the latest ZIP. All 37 Python files passed syntax checks. No divergent versions were merged.

The GitHub duplicate check covered 22 accessible repositories. The portfolio repository already hosts `dist/assets/evidence/cdis-architecture.md`, an exact copy of the architecture document, but has no matching CDIS implementation. This publication supplies the complete project rather than another copy of the portfolio website.

## Validation

```text
python -m ruff check app tests
All checks passed!

SIMULATE_LLM_DOWN=1 python -m pytest
37 passed
```

Tests use an isolated in-memory SQLite database. The optional LLM was disabled for the local publication check; external provider performance and production deployment were not validated. Historical research, commercial and model-quality claims in the supplied documents are preserved as author-provided material rather than independently verified results.

## Publication preparation

- Excluded the local database, production environment file and generated caches.
- Replaced personal details in test fixtures with generic example data.
- Applied import/whitespace/line-wrap lint fixes without changing scoring behavior.
- Corrected invalid shell redirection on a Dockerfile `COPY` instruction; both migration paths exist and are copied explicitly.
- Removed the Git ignore exception that would have allowed a production environment file to be committed.
- Preserved the supplied application, architecture and research documents. No license file was supplied in the selected source.
