# Sample Apps for Platform Agent Evaluation

These sample agent applications are used to test the Design Advisor and Code Review
skills. Each app is intentionally designed with specific characteristics:

| App | Design Quality | Expected Rating | Key Characteristics |
|-----|---------------|----------------|---------------------|
| `good-weather-agent/` | ✅ Well-designed | READY | Dockerfile, env vars, health check, proper error handling |
| `bad-secrets-agent/` | ❌ Poor | NOT READY | Hardcoded secrets, no Dockerfile, no pyproject.toml, bare exceptions |
| `needs-refactor-agent/` | ⚠️ Partial | NEEDS WORK | Has Dockerfile but local file storage, missing health check |
