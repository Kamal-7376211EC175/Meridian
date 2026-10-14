"""Finance Copilot: facts come from SQL (rules layer); the LLM (Groq/Qwen) only phrases them."""
import re, json, httpx
from .config import GROQ_API_KEY, GROQ_MODEL, AS_OF
from .rules import close_readiness

def _ex(c, cats, n=6):
    return [dict(x) for x in c.execute(f"select id,category,agency_id,amount,deadline,severity,score from exceptions where category in ({','.join('?'*len(cats))}) and status!='Resolved' order by amount desc limit ?",(*cats,n))]

def gather(c, q):
    ql = q.lower()
    if "unapplied" in ql or "cash" in ql:
        ev = _ex(c, ["Unapplied Cash","Probable Duplicate"]); t = c.execute("select coalesce(sum(amount),0) from receipts where invoice_id is null").fetchone()[0]
        return dict(topic="Unapplied cash",total=round(t,2),evidence=ev,confidence=.9,assumptions=["Unapplied = receipts with no invoice link.","Probable duplicates may overstate the total until bank-confirmed."])
    if "carrier" in ql or "settlement" in ql:
        ev = _ex(c, ["Carrier Settlement"]); t = sum(e["amount"] for e in ev)
        return dict(topic="Carrier settlements at risk",total=round(t,2),evidence=ev,confidence=.85,assumptions=["At risk = paid below expected by >0.5%.","Totals cover the top 6 by amount."])
    if "close" in ql or "delay" in ql:
        ev = _ex(c, ["Close Blocker"]); b = c.execute("select count(*) from close_tasks where status='Blocked'").fetchone()[0]; u = c.execute("select count(*) from reconciliations where status='Unmatched'").fetchone()[0]
        return dict(topic="Month-end close delay",total=None,evidence=ev,confidence=.8,readiness=close_readiness(c),blocked_tasks=b,unmatched_reconciliations=u,assumptions=["Readiness = Done + 50% of In Progress tasks.","Blockers reference unapplied cash in the same agency."])
    if "commission" in ql:
        ev = [dict(x) for x in c.execute("select id,category,agency_id,amount,deadline,severity,score from exceptions where category='Commission Variance' and status!='Resolved' order by score desc limit 6")]
        return dict(topic="Commission discrepancies to review first",total=round(sum(e["amount"] for e in ev),2),evidence=ev,confidence=.85,assumptions=["Ranked by priority score (amount, age, deadline).","Variance tolerance is 2% and $50."])
    ev = [dict(x) for x in c.execute("select id,category,agency_id,amount,deadline,severity,score from exceptions where status!='Resolved' order by score desc limit 5")]
    return dict(topic="Top priority exceptions",total=round(sum(e["amount"] for e in ev),2),evidence=ev,confidence=.5,assumptions=["Question did not match a specific topic; showing overall priorities."])

def fallback(g):
    ln = [f"{g['topic']}: " + (f"${g['total']:,.2f} total." if g.get("total") is not None else f"close readiness {g.get('readiness')}%, {g.get('blocked_tasks')} blocked tasks, {g.get('unmatched_reconciliations')} unmatched reconciliations.")]
    ln += [f"- {e['id']} ({e['category']}, {e['severity']}): ${e['amount']:,.2f}, due {e['deadline']}" for e in g["evidence"][:5]]
    return "\n".join(ln)

def ask(c, q):
    g = gather(c, q); text = fallback(g); source = "rules"
    if GROQ_API_KEY:
        try:
            r = httpx.post("https://api.groq.com/openai/v1/chat/completions", timeout=25, headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={"model":GROQ_MODEL,"temperature":.2,"messages":[
                {"role":"system","content":"You are a finance operations copilot. Answer ONLY from the FACTS json. Cite exception IDs and exact amounts. Never invent numbers. Max 110 words. Plain text, short bullets allowed."},
                {"role":"user","content":f"Question: {q}\nAs of: {AS_OF}\nFACTS: {json.dumps(g)}"}]})
            r.raise_for_status(); out = re.sub(r"<think>.*?</think>","",r.json()["choices"][0]["message"]["content"],flags=re.S).strip()
            if out: text, source = out, f"groq:{GROQ_MODEL}"
        except Exception as e: g["assumptions"].append(f"LLM unavailable ({type(e).__name__}); showing rule-based answer.")
    else: g["assumptions"].append("GROQ_API_KEY not set; showing rule-based answer.")
    return {"answer":text,"evidence":g["evidence"],"total":g.get("total"),"confidence":g["confidence"],"assumptions":g["assumptions"],"source":source}
