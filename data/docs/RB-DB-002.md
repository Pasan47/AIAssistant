---
doc_id: RB-DB-002
title: Runbook: Database connection pool saturation
department: platform
document_type: runbook
access_level: internal
created_date: '2025-03-02'
---

# Connection pool saturation

## Symptoms
Rising request latency, `remaining connection slots` or `pool timeout` errors in service logs.

## Steps
1. Identify long-running queries: `SELECT pid, now()-query_start, query FROM pg_stat_activity ORDER BY 2 DESC;`
2. Terminate offending batch sessions after approval from the service owner.
3. Temporarily raise the pool size (max 150) via the Helm value `db.pool.max` and roll the pods.
4. File a follow-up to move batch workloads to a read replica.
