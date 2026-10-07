---
doc_id: RB-PAY-001
title: Runbook: Payment gateway failover and degraded mode
department: payments
document_type: runbook
access_level: internal
created_date: '2025-01-20'
---

# Payment gateway failover

## When to use
Authorisation error rate above 5% for 5 minutes, or processor latency p99 above 8 seconds.

## Steps
1. Check the processor status page and the `payments-gateway` Grafana dashboard.
2. Set the flag `payments.processor.route=secondary` in the feature-flag console.
3. Confirm error rate falls below 2% within 5 minutes.
4. Page the Payments on-call lead and open an incident per POL-002.

## Rollback
Reset the flag to `primary` once the processor confirms recovery for 30 minutes.
