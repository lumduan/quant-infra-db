# Lessons Learned

What worked, what didn't. Append; don't rewrite history.

## What Worked

- _Document your wins here. What shipped on schedule? What unexpected benefit came from a convention or tool choice? Be specific._

## What Didn't Work

- _Document your losses. What pattern caused bugs? What tool choice was regretted? What should have been done differently? Be specific._

## What's Still Unsettled

- _Open questions, unresolved trade-offs, decisions pending more data._
- Docker Compose stack is designed but not yet provisioned — `docker-compose.yml` and init scripts exist only as roadmap specifications. Actual file creation will validate assumptions.
- TimescaleDB hypertable chunk intervals: the roadmap uses defaults; real chunk sizing depends on data ingestion rate (TBD when strategy services connect).
- MongoDB authentication: roadmap starts with no auth for local dev; production auth strategy (SCRAM, X.509) is deferred.
- Backup frequency: roadmap recommends daily; actual cadence depends on trade volume and RPO requirements from strategy teams.

---

> **Append new lessons below. Date them. Be specific about the win or the loss.**
