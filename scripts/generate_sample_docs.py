"""Generate mock enterprise documents (markdown + YAML front-matter) into data/docs/."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "docs"
OUT.mkdir(parents=True, exist_ok=True)


def write(doc_id: str, title: str, dept: str, dtype: str, level: str, date: str, body: str, **extra):
    extras = "".join(f"{k}: {json.dumps(v)}\n" for k, v in extra.items())
    fm = (f"---\ndoc_id: {doc_id}\ntitle: {json.dumps(title)}\ndepartment: {dept}\ndocument_type: {dtype}\n"
          f"access_level: {level}\ncreated_date: '{date}'\n{extras}---\n\n")
    (OUT / f"{doc_id}.md").write_text(fm + body.strip() + "\n")


# ------------------------------------------------------------------ incidents
INCIDENTS = [
    # id, date, service, sev, minutes, root cause, level, trigger, resolution, action
    ("INC-2025-003", "2025-02-11", "payment-gateway", "SEV1", 95, "database connection pool exhaustion", "internal",
     "A promotional campaign tripled card-payment traffic. The gateway's PostgreSQL pool (max 50) saturated and requests queued until clients timed out.",
     "On-call raised pool size to 150 and restarted two gateway pods; traffic drained within 20 minutes.",
     "Add pool saturation alerting at 70% and load-test before campaigns."),
    ("INC-2025-009", "2025-03-27", "card-authorization", "SEV2", 42, "third-party processor timeout", "internal",
     "The external card processor (AcquirerX) responded in over 12s for 18% of authorisations; our 10s client timeout failed them as declines.",
     "Traffic was shifted to the secondary processor via the routing flag payments.processor.route.",
     "Introduce circuit breaker with automatic failover; negotiate processor latency SLA."),
    ("INC-2025-014", "2025-05-06", "payment-gateway", "SEV1", 128, "database connection pool exhaustion", "confidential",
     "A long-running reconciliation query held connections open during peak hour. Pool exhaustion caused 31% of payment attempts to fail; an estimated 14,200 customers were affected.",
     "Reconciliation job was killed, connections were recycled, and the job was moved to a read replica.",
     "Enforce statement timeouts (30s) and separate pools for batch and online workloads."),
    ("INC-2025-018", "2025-05-29", "mobile-banking-app", "SEV3", 25, "CDN cache misconfiguration", "internal",
     "A stale CDN rule served an outdated login bundle to some Android users, causing blank screens.",
     "Cache was purged and the rule corrected.", "Add synthetic login check per release."),
    ("INC-2025-021", "2025-06-19", "payments-api", "SEV2", 55, "expired TLS certificate", "internal",
     "The mutual-TLS certificate to the payments partner network expired; all partner payment calls failed handshake.",
     "A renewed certificate was deployed from the secrets vault.", "Automate renewal and alert 30 days before expiry."),
    ("INC-2025-027", "2025-08-02", "card-authorization", "SEV1", 77, "third-party processor timeout", "internal",
     "AcquirerX suffered a regional outage; authorisations timed out and our failover did not trigger because it was still manual.",
     "Engineers manually enabled the secondary processor route.", "Automate processor failover (carry-over action from INC-2025-009)."),
    ("INC-2025-033", "2025-09-15", "payment-gateway", "SEV2", 38, "faulty deployment (config regression)", "internal",
     "Release 4.12 shipped a wrong retry-count config, causing duplicate payment submissions that were rejected by idempotency checks.",
     "Release was rolled back through the pipeline.", "Add config diff validation to the release gate."),
    ("INC-2025-036", "2025-10-01", "notification-service", "SEV3", 20, "email provider rate limiting", "internal",
     "SMS/email payment confirmations were delayed because the email provider throttled our burst sending.",
     "Sending was batched and rate-limited.", "Move to queue-based sending with backoff."),
    ("INC-2025-041", "2025-11-04", "payments-api", "SEV1", 110, "database connection pool exhaustion", "internal",
     "Month-end salary-day load exhausted the payments-api connection pool again; the pool limit increase from INC-2025-003 had not been applied to this service.",
     "Pool limits were raised and autoscaling thresholds adjusted.", "Standardise pool configuration across all payment services via shared Helm values."),
    ("INC-2024-052", "2024-10-22", "payment-gateway", "SEV2", 63, "message queue backlog", "internal",
     "A consumer bug stalled the payment-events queue, delaying settlement notifications.",
     "Consumer was patched and backlog replayed.", "Add queue-depth alerting."),
]
for (i, d, svc, sev, mins, cause, lvl, trigger, fix, action) in INCIDENTS:
    write(i, f"Incident report {i}: {svc} - {cause}", "payments" if "pay" in svc or "card" in svc else "platform",
          "incident", lvl, d, f"""
# {i} - {svc} ({sev})

## Summary
Date: {d}. Service: {svc}. Severity: {sev}. Duration: {mins} minutes. Root cause: {cause}.

## What happened
{trigger} Customer-facing payment failures were observed during the window.

## Resolution
{fix}

## Follow-up actions
{action}

## Lessons learned
Detection came from customer-impact alerts rather than leading indicators; see the incident severity policy POL-002.
""", service=svc, severity=sev, duration_minutes=mins, root_cause=cause.replace(":", ""))

# ------------------------------------------------------------------ runbooks
write("RB-PAY-001", "Runbook: Payment gateway failover and degraded mode", "payments", "runbook", "internal", "2025-01-20", """
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
""")
write("RB-DB-002", "Runbook: Database connection pool saturation", "platform", "runbook", "internal", "2025-03-02", """
# Connection pool saturation

## Symptoms
Rising request latency, `remaining connection slots` or `pool timeout` errors in service logs.

## Steps
1. Identify long-running queries: `SELECT pid, now()-query_start, query FROM pg_stat_activity ORDER BY 2 DESC;`
2. Terminate offending batch sessions after approval from the service owner.
3. Temporarily raise the pool size (max 150) via the Helm value `db.pool.max` and roll the pods.
4. File a follow-up to move batch workloads to a read replica.
""")

# ------------------------------------------------------------------ architecture
write("ARCH-001", "Architecture: Payments platform overview", "payments", "architecture", "internal", "2025-02-01", """
# Payments platform

The platform consists of the **payments-api** (public edge), the **payment-gateway** (orchestration and idempotency),
and **card-authorization** (processor integration with AcquirerX primary and AcquirerY secondary).
State is stored in PostgreSQL (primary + read replica); payment events flow through a Kafka topic `payment-events`.

## Resilience
Retries use idempotency keys. Processor calls use a 10 second timeout. Failover to the secondary processor is
currently controlled by a feature flag; automation is on the roadmap.
""")
write("ARCH-002", "Architecture: Fraud detection engine", "risk", "architecture", "confidential", "2025-04-12", """
# Fraud detection engine

Real-time scoring consumes `payment-events`, enriches with device and velocity features, and calls the model service
(gradient-boosted trees, p99 latency 35 ms). Transactions scoring above 0.92 are blocked; 0.75-0.92 trigger step-up
authentication. Rules thresholds are confidential and reviewed monthly by the Risk committee.
""")

# ------------------------------------------------------------------ product / policy / meeting
write("PROD-001", "Product specification: Instant Transfer", "retail", "product_spec", "internal", "2025-07-08", """
# Instant Transfer

Customers can send up to 5,000 per transaction and 20,000 per day to registered payees with settlement under 10 seconds.
Transfers above 2,000 require step-up authentication. The feature depends on the payment-gateway and card-authorization services.
""")
write("POL-001", "Policy: Access control and data handling", "compliance", "policy", "internal", "2025-01-05", """
# Access control and data handling

Access follows least privilege. Customer data (PAN, account numbers) must never be pasted into chat tools or tickets.
Confidential documents are restricted to Analyst and Administrator roles. All access is logged and reviewed quarterly.
""")
write("POL-002", "Policy: Incident severity classification", "compliance", "policy", "public", "2025-01-05", """
# Incident severity

SEV1: customer-facing outage of a critical service or more than 10% payment failures. SEV2: partial degradation.
SEV3: minor impact. SEV1 requires a post-incident review within 5 business days.
""")
write("POL-003", "Policy: Board risk appetite statement", "compliance", "policy", "restricted", "2025-03-30", """
# Risk appetite

Maximum tolerated annual payment downtime is 4 hours. Breaches are reported directly to the Board Risk Committee.
""")
write("MTG-2025-10", "Meeting notes: Payments weekly sync (October 2025)", "payments", "meeting_notes", "internal", "2025-10-14", """
# Payments weekly sync

Attendees: Payments leads and platform SRE. Agenda: recurring connection pool incidents, processor failover automation.
Decision: prioritise automated processor failover in Q1; standardise pool configuration through shared Helm values.
Owner of failover automation: Nimal Perera. Owner of pool standardisation: Ayesha Fernando.
""")
print(f"Generated {len(list(OUT.glob('*.md')))} documents in {OUT}")
