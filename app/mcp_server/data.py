"""Dummy enterprise data exposed through MCP."""
EMPLOYEES = [
    {"name": "Nimal Perera", "title": "Payments On-call Lead", "team": "payments", "email": "nimal.perera@meridian.example", "on_call": True},
    {"name": "Ayesha Fernando", "title": "Platform SRE Manager", "team": "platform", "email": "ayesha.fernando@meridian.example", "on_call": False},
    {"name": "Kasun Silva", "title": "Fraud Engineer", "team": "risk", "email": "kasun.silva@meridian.example", "on_call": False},
    {"name": "Dilini Jayawardena", "title": "Product Owner, Instant Transfer", "team": "retail", "email": "dilini.j@meridian.example", "on_call": False},
]
SERVICES = [
    {"name": "payment-gateway", "team": "payments", "tier": 1, "owner": "Nimal Perera", "runbook": "RB-PAY-001"},
    {"name": "payments-api", "team": "payments", "tier": 1, "owner": "Nimal Perera", "runbook": "RB-PAY-001"},
    {"name": "card-authorization", "team": "payments", "tier": 1, "owner": "Nimal Perera", "runbook": "RB-PAY-001"},
    {"name": "fraud-engine", "team": "risk", "tier": 1, "owner": "Kasun Silva", "runbook": None},
    {"name": "notification-service", "team": "platform", "tier": 2, "owner": "Ayesha Fernando", "runbook": None},
]
INCIDENTS = [
    {"id": "INC-2025-041", "service": "payments-api", "severity": "SEV1", "status": "closed", "opened": "2025-11-04"},
    {"id": "INC-2025-036", "service": "notification-service", "severity": "SEV3", "status": "closed", "opened": "2025-10-01"},
    {"id": "INC-2026-002", "service": "payment-gateway", "severity": "SEV2", "status": "open", "opened": "2026-01-14"},
]
