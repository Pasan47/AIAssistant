---
doc_id: ARCH-002
title: "Architecture: Fraud detection engine"
department: risk
document_type: architecture
access_level: confidential
created_date: '2025-04-12'
---

# Fraud detection engine

Real-time scoring consumes `payment-events`, enriches with device and velocity features, and calls the model service
(gradient-boosted trees, p99 latency 35 ms). Transactions scoring above 0.92 are blocked; 0.75-0.92 trigger step-up
authentication. Rules thresholds are confidential and reviewed monthly by the Risk committee.
