 AI assistant for a commercial bank ("Meridian Commercial Bank"): multi-agent LangGraph orchestration, hybrid RAG (Pinecone dense + BM25), a Recursive Language Model (RLM) research agent, RBAC-gated tools incl. an MCP server, guardrails against prompt injection, LangSmith tracing, and a Streamlit UI that shows the agent working in real time.

Quick start

cp .env.example .env                 # add GEMINI_KEY, PINECONE_API_KEY, LANGSMITH_API_KEY
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python scripts/generate_sample_docs.py   # 19 mock docs (already committed in data/docs)
python -m app.retrieval.ingest           # chunk -> BM25 store -> embed -> Pinecone (namespace per document type)
uvicorn app.main:app --reload            # API  :8000
streamlit run ui/streamlit_app.py        # UI   :8501


How requirements map to the code
Requirement	Where
LangGraph, multiple agents	app/agents/graph.py - guard → supervisor → retrieval | research(RLM) → response → validation → memory
RLM	app/agents/research_agent.py, app/rlm/sandbox.py, app/rlm/map_reduce.py
Hybrid search + Pinecone	app/retrieval/hybrid.py, pinecone_store.py, bm25_index.py, ingest.py
Tools: knowledge search, MCP, Python analysis	app/tools/builtin.py, app/mcp_server/server.py
RBAC	app/permissions.py (policy), app/tools/registry.py (tool enforcement), hybrid.py (document ACL)
Prompt-injection / guardrails	app/security.py, app/agents/validation.py, guard_input node
Rate limiting	app/rate_limit.py + dependency in app/main.py (HTTP 429 + Retry-After)
Streaming + agent activity	app/context.py::emit → SSE in app/main.py → ui/streamlit_app.py
Memory	app/agents/memory.py + LangGraph checkpointer (below)






RLM (Recursive Language Model) - how it works here
For broad questions ("summarise all payment outages last year and find recurring root causes") the supervisor routes to the Research Agent, which never loads the corpus into one prompt:
1.	Explore / plan - the LLM writes a small Python search plan (search(...) calls with type/date filters).
2.	Safe execution - plan is validated by an AST allow-list (no imports/attributes/while/other calls), run with empty builtins, a search-call budget and a timeout. Invalid plan → logged, default plan used.
3.	Decompose - retrieved chunks are grouped by document and split into batches (RLM_BATCH_SIZE).
4.	Sub-agents - each batch analysed concurrently (semaphore-limited); a failed sub-agent degrades to an extractive result for that batch only.
5.	Recursive aggregation - partial findings are tree-reduced (RLM_FAN_IN) level by level, depth-capped (RLM_MAX_DEPTH); invented evidence ids are stripped at every level.
6.	Analysis - python_analysis counts recurring root causes over the examined documents (analyst/admin only), then the Response Agent writes the cited summary.
Memory design
Session memory lives inside the persisted LangGraph state, keyed by thread_id = user:session_id (MemorySaver):
•	messages - raw conversation; the last MEMORY_WINDOW are replayed to the supervisor (to resolve follow-ups into standalone queries) and the response agent.
•	memory - compact structured memory updated by memory_update with no extra LLM call: previous questions, topics/filters used, user context (role/department), last cited documents, turn count.
•	Blocked (injection) messages are never written to memory, so an attack can't poison later turns.
•	Session ids are bound to the owning user (cross-user session access → 403). Trade-off: in-process MemorySaver is lost on restart and single-instance. Long-term memory = swap in PostgresSaver/a store keyed by user (see "Next steps").
Security approach
Defence in depth; the LLM is treated as untrusted:
1.	Input validation (length, control chars, Pydantic schemas) and heuristic screening for instruction override, data exfiltration and tool-abuse attempts (guard_input, refuse + trace, never reaches an LLM).
2.	Indirect injection: retrieved text is sanitised (instruction-like lines removed), wrapped in <document> tags, and the prompts state documents are data.
3.	Authorisation in code: document ACL (access_level ≤ role ceiling) is injected in the retriever/Pinecone filter from the verified user; agent filters can only narrow. Tools are reachable only through ToolRegistry (default-deny, validated args, timeout). Identity is set from the JWT in a context variable, never from model output; the role is re-derived server-side.
4.	Output guardrails: hallucinated citation removal (every [doc#n] must exist in this turn's evidence), secret/PAN redaction (Luhn), brand-safety blocklist, empty-response fallback.

Error handling / graceful degradation
Failure	Behaviour
LLM down / malformed JSON	2 SDK retries → 1 repair retry → supervisor uses heuristic routing; response agent returns an extractive cited answer; RLM sub-agents degrade per batch
Pinecone / embeddings down	dense leg dropped, BM25-only results, degraded flag surfaced in UI and prompt
MCP server down / tool timeout	registry returns error/timeout result; the answer states the limitation
Invalid request / tool args	422 structured error / invalid_args tool result
Any node exception	agent_node wrapper contains it, records state.errors, applies fallback patch - downstream nodes adapt (limits the butterfly effect)
Rate limit	429 + Retry-After, shown in UI
Assumptions & trade-offs
See assumption.docx (all adopted). Notable trade-offs:
•	Hybrid fusion: score-level fusion (min-max normalise, 0.6 dense + 0.4 BM25) is simple and tunable; RRF or a learned reranker would be more robust. BM25 runs locally over the persisted chunk store (not Pinecone sparse vectors) to keep the POC dependency-light - fine for thousands of docs, not millions.
•	Namespaces per document type allow scoped search and cheap filtering; ACL/department/date are metadata filters.
•	LLM: OpenAI (gpt-4o-mini) - reliable JSON mode + tool use at low latency/cost for a multi-call agent graph; all calls go through app/llm.py, so swapping to Anthropic/Gemini touches one file. Quality could improve with a larger model for the response/aggregation steps.
•	Streaming vs validation: tokens stream as a draft; the validated answer replaces it on the final event (so hallucinated citations never persist).
•	Hard-coded users (Option A) and in-memory rate limiting/sessions - POC scope.
•	Human-in-the-loop approval and long-term memory are not implemented 

