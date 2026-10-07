"""Streamlit UI: chat (streaming) + live agent-activity panel + sources. Functionality over beauty."""
import json
import os

import httpx
import streamlit as st

API = os.getenv("API_URL", "http://localhost:8000")
st.set_page_config(page_title="Meridian Knowledge Assistant", layout="wide")

ss = st.session_state
for key, default in {"token": None, "role": None, "user": None, "messages": [], "session_id": None,
                     "activity": [], "sources": [], "last_run": None}.items():
    ss.setdefault(key, default)


# ---------------------------------------------------------------- activity formatting
def describe(ev: dict) -> str | None:
    t = ev.get("type")
    if t == "node_start":
        return f"▶️ **{ev['node']}** - {ev['label']}"
    if t == "node_end":
        return f"{'✅' if ev['status'] == 'ok' else '❌'} {ev['node']} finished ({ev['ms']} ms)"
    if t == "plan":
        return (f"🧭 **Plan**: intent=`{ev['intent']}` route=`{ev['route']}` tools={ev['tools']} filters={ev['filters']}\n\n"
                f"&nbsp;&nbsp;↳ query: _{ev['rewritten_query']}_")
    if t == "retrieval":
        if ev["status"] == "started":
            return f"🔎 Retrieval started (allowed levels: {ev['allowed_levels']}, filters: { {k: v for k, v in ev['filters'].items() if v} })"
        return (f"🔎 Retrieval done: {ev['hits']} chunks from {ev['documents']} "
                f"(dense={ev['dense_candidates']}, bm25={ev['sparse_candidates']}) {'⚠️ ' + str(ev['degraded']) if ev['degraded'] else ''}")
    if t == "tool_start":
        return f"🛠️ Tool call → `{ev['tool']}` {ev['args']}"
    if t == "tool_end":
        return f"🛠️ Tool `{ev['tool']}` → {ev['status']} ({ev['ms']} ms)"
    if t == "tool_denied":
        return f"⛔ Tool `{ev['tool']}` DENIED for role `{ev['role']}`"
    if t == "rlm":
        s = ev["stage"]
        detail = {k: v for k, v in ev.items() if k not in ("type", "ts", "stage", "code")}
        return f"🔁 RLM · **{s}** {detail}" + (f"\n```python\n{ev['code']}\n```" if s == "plan_generated" else "")
    if t == "memory":
        return f"🧠 Memory updated: turns={ev['turns']}, remembered questions={ev['remembered_questions']}, topics={ev['topics']}"
    if t == "validation":
        if ev["stage"] == "input":
            return f"🛡️ Input validation: {'passed' if ev['ok'] else 'BLOCKED (' + ev['category'] + ')'}"
        return f"🛡️ Output validation: ok={ev['ok']} problems={ev['problems']} citations={ev['valid_citations']}"
    if t == "degraded":
        return f"⚠️ Degraded mode ({ev['node']}): {ev['message']}"
    if t == "error":
        return f"❌ Error in {ev['node']}: {ev['message']}"
    if t == "final":
        return "🏁 Final response ready"
    return None


def login_sidebar():
    with st.sidebar:
        st.header("Sign in")
        if ss.token:
            st.success(f"{ss.user} ({ss.role})")
            if st.button("Sign out"):
                for k in ("token", "role", "user", "session_id"):
                    ss[k] = None
                ss.messages, ss.activity, ss.sources = [], [], []
                st.rerun()
            if st.button("New conversation"):
                ss.session_id, ss.messages, ss.activity, ss.sources = None, [], [], []
                st.rerun()
            st.caption(f"Session: {ss.session_id or 'new'}")
            return
        st.caption("Demo users: viewer/viewer123 · analyst/analyst123 · admin/admin123")
        u, p = st.text_input("Username"), st.text_input("Password", type="password")
        if st.button("Login"):
            r = httpx.post(f"{API}/auth/login", json={"username": u, "password": p}, timeout=10)
            if r.status_code == 200:
                d = r.json()
                ss.token, ss.role, ss.user = d["token"], d["role"], d["username"]
                st.rerun()
            st.error("Invalid credentials")


def send_feedback(score: int):
    httpx.post(f"{API}/feedback", json={"run_id": ss.last_run, "score": score},
               headers={"Authorization": f"Bearer {ss.token}"}, timeout=10)
    st.toast("Thanks for the feedback!")


login_sidebar()
st.title("🏦 Meridian Knowledge Assistant")
if not ss.token:
    st.info("Sign in from the sidebar to start.")
    st.stop()

chat_col, side_col = st.columns([3, 2])
with side_col:
    tab_act, tab_src = st.tabs(["🔬 Agent activity", "📚 Sources"])
    with tab_act:
        activity_box = st.container(height=560)
    with tab_src:
        sources_box = st.container(height=560)


def render_activity():
    activity_box.empty()
    with activity_box:
        for line in ss.activity:
            st.markdown(line)


def render_sources():
    sources_box.empty()
    with sources_box:
        if not ss.sources:
            st.caption("No sources cited yet.")
        for s in ss.sources:
            with st.expander(f"{s['chunk_id']} · {s['title']}"):
                st.caption(f"{s['document_type']} · {s['department']} · {s['access_level']} · {s['created_date']} · "
                           f"score {s['score']} (dense {s['dense_score']}, bm25 {s['sparse_score']})")
                st.write(s["snippet"])


with chat_col:
    for m in ss.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
    if ss.last_run and ss.messages and ss.messages[-1]["role"] == "assistant":
        c1, c2, _ = st.columns([1, 1, 6])
        c1.button("👍", on_click=send_feedback, args=(1,))
        c2.button("👎", on_click=send_feedback, args=(-1,))
render_activity()
render_sources()

if prompt := st.chat_input("Ask about policies, incidents, runbooks, architecture..."):
    ss.messages.append({"role": "user", "content": prompt})
    ss.activity, ss.sources = [], []
    with chat_col:
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            placeholder, answer = st.empty(), ""
            try:
                with httpx.Client(timeout=None) as client, client.stream(
                    "POST", f"{API}/chat/stream", json={"message": prompt, "session_id": ss.session_id},
                    headers={"Authorization": f"Bearer {ss.token}"},
                ) as r:
                    if r.status_code != 200:
                        r.read()
                        msg = r.json().get("error", {}).get("message") or r.json().get("detail") or "Request failed"
                        answer = f"⚠️ {msg} (HTTP {r.status_code})"
                        placeholder.markdown(answer)
                    else:
                        event = None
                        for line in r.iter_lines():
                            if line.startswith("event:"):
                                event = line[6:].strip()
                            elif line.startswith("data:"):
                                ev = json.loads(line[5:])
                                if event == "session":
                                    ss.session_id, ss.last_run = ev["session_id"], ev["run_id"]
                                elif event == "token":
                                    answer += ev["text"]
                                    placeholder.markdown(answer + "▌")
                                elif event == "final":
                                    answer = ev["answer"]          # validated answer replaces the streamed draft
                                    ss.sources = ev["sources"]
                                    placeholder.markdown(answer)
                                    render_sources()
                                if (text := describe(ev)):
                                    ss.activity.append(text)
                                    render_activity()
            except httpx.HTTPError as exc:
                answer = f"⚠️ Cannot reach the API ({type(exc).__name__}). Is the backend running?"
                placeholder.markdown(answer)
    ss.messages.append({"role": "assistant", "content": answer})
    st.rerun()
