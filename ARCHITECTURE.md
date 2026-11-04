# Architecture guide — AI service

AI agents: read this file and [RULES.md](RULES.md) before changing code.

## Source of truth

- [System architecture](docs/architecture/10-de-xuat-kien-truc-va-repo.md)
- [Repository structure and decisions](docs/architecture/11-de-xuat-cau-truc-repo.md)
- [AI service structure](docs/architecture/11-de-xuat-cau-truc-repo.md#5-tripflix-ai)
- [Architecture document index and diagrams](docs/architecture/README.md)

## AI service rules

- Keep this service stateless; read and write business data only through Core API contracts.
- Version prompts instead of replacing prompts already in use.
- Read credentials from environment settings. Record usage costs through the agreed event contract.
- Treat `contracts/` as generated output; update its source and regenerate it.
- Follow `RULES.md` for ownership, evaluations, checks and branch workflow.
