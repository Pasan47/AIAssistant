---
doc_id: ARCH-001
title: Architecture: Payments platform overview
department: payments
document_type: architecture
access_level: internal
created_date: '2025-02-01'
---

# Payments platform

The platform consists of the **payments-api** (public edge), the **payment-gateway** (orchestration and idempotency),
and **card-authorization** (processor integration with AcquirerX primary and AcquirerY secondary).
State is stored in PostgreSQL (primary + read replica); payment events flow through a Kafka topic `payment-events`.

## Resilience
Retries use idempotency keys. Processor calls use a 10 second timeout. Failover to the secondary processor is
currently controlled by a feature flag; automation is on the roadmap.
