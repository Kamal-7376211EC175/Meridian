"""Deterministic business rules & financial calculations. No LLM involved here."""
import math, json, datetime as dt
from .config import AS_OF, CLOSE_DATE
CATW = {"Unapplied Cash":8,"Probable Duplicate":4,"Overdue Receivable":6,"Carrier Settlement":10,"Commission Variance":7,"Close Blocker":9}
OWNER = {"Unapplied Cash":"Priya Nair","Probable Duplicate":"Priya Nair","Overdue Receivable":"Marcus Lee","Carrier Settlement":"Marcus Lee","Commission Variance":"Priya Nair","Close Blocker":"Sofia Alvarez"}
NEEDS_APPROVAL = {"Unapplied Cash","Probable Duplicate","Carrier Settlement","Commission Variance"}  # cannot be Resolved without approval
SENSITIVE = {"payment","ledger_posting","commission_change"}
D = lambda s: dt.date.fromisoformat(s)

def severity(s): return "Critical" if s >= 70 else "High" if s >= 50 else "Medium" if s >= 30 else "Low"

def score(cat, amt, age, deadline):
    """Priority score 0-100 = amount(40, log-scaled) + age(25) + deadline proximity(25) + category weight(<=10)."""
    a = min(40, 40*math.log10(1+amt)/math.log10(50001)); g = min(25, age/90*25)
    days = (deadline - AS_OF).days
    d = 25 if days <= 0 else 20 if days <= 3 else 12 if days <= 7 else 5
    return round(min(100, a+g+d+CATW[cat]), 1)

def detect(c):
    c.execute("delete from exceptions"); rows = []
    def add(cat, ag, tbl, sid, amt, age, dl, facts, dup=None):
        s = score(cat, amt, age, dl); rows.append((cat,ag,tbl,sid,round(amt,2),(AS_OF-dt.timedelta(days=age)).isoformat(),age,dl.isoformat(),OWNER[cat],"Open",severity(s),s,json.dumps(facts),dup))
    for r in c.execute("select * from receipts where invoice_id is null order by id").fetchall():
        o = c.execute("select id from receipts where id<? and agency_id=? and payer=? and amount=? order by id limit 1",(r["id"],r["agency_id"],r["payer"],r["amount"])).fetchone()
        age = (AS_OF-D(r["received"])).days
        f = [["Receipt",f"R-{r['id']}"],["Payer",r["payer"]],["Reference",r["reference"]],["Received",r["received"]],["Linked invoice","None"]]
        if o: add("Probable Duplicate",r["agency_id"],"receipts",r["id"],r["amount"],age,CLOSE_DATE,f+[["Matches earlier receipt",f"R-{o['id']}"]],f"DG-R{o['id']}")
        else: add("Unapplied Cash",r["agency_id"],"receipts",r["id"],r["amount"],age,CLOSE_DATE,f)
    for i in c.execute("select * from invoices where due<? and amount-paid>=500 order by id",(AS_OF.isoformat(),)).fetchall():
        age = (AS_OF-D(i["due"])).days
        add("Overdue Receivable",i["agency_id"],"invoices",i["id"],i["amount"]-i["paid"],age,D(i["due"])+dt.timedelta(days=30),[["Invoice",f"INV-{i['id']}"],["Client",i["client"]],["Invoice amount",i["amount"]],["Paid to date",i["paid"]],["Due",i["due"]],["Days past due",age]])
    for s in c.execute("select * from carrier_statements where paid < expected*0.995 order by id").fetchall():
        sh = s["expected"]-s["paid"]; age = max(0,(AS_OF-D(s["due_date"])).days)
        add("Carrier Settlement",s["agency_id"],"carrier_statements",s["id"],sh,age,D(s["due_date"]),[["Statement",f"CS-{s['id']}"],["Carrier",s["carrier"]],["Expected",s["expected"]],["Paid",s["paid"]],["Shortfall %",round(sh/s["expected"]*100,1)],["Due",s["due_date"]]])
    for m in c.execute("select * from commissions order by id").fetchall():
        v = m["paid"]-m["expected"]
        if abs(v) >= 50 and abs(v)/m["expected"] > .02:
            add("Commission Variance",m["agency_id"],"commissions",m["id"],abs(v),14,CLOSE_DATE,[["Commission",f"CM-{m['id']}"],["Producer",m["producer"]],["Policy",m["policy"]],["Expected",m["expected"]],["Paid",m["paid"]],["Variance",round(v,2)],["Direction","Overpaid" if v>0 else "Underpaid"]])
    for t in c.execute("select * from close_tasks where status='Blocked' order by id").fetchall():
        un = c.execute("select coalesce(sum(amount),0) from receipts where agency_id=? and invoice_id is null",(t["agency_id"],)).fetchone()[0]
        add("Close Blocker",t["agency_id"],"close_tasks",t["id"],un,max(0,(AS_OF-D(t["due"])).days),D(t["due"]),[["Task",t["name"]],["Status","Blocked"],["Blocker",t["blocker"]],["Due",t["due"]],["Agency unapplied cash",round(un,2)]])
    rows.sort(key=lambda x: (list(CATW).index(x[0]), -x[11]))
    for n,x in enumerate(rows): c.execute("insert into exceptions(id,category,agency_id,subject_table,subject_id,amount,detected,age_days,deadline,owner,status,severity,score,facts,dup_group) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(f"EX-{1001+n}",)+x)
    c.commit()

def close_readiness(c):
    t = c.execute("select status,count(*) n from close_tasks group by status").fetchall(); d = {x["status"]:x["n"] for x in t}; tot = sum(d.values()) or 1
    return round((d.get("Done",0)+.5*d.get("In Progress",0))/tot*100,1)

def candidates(c, r):
    out = c.execute("select * from invoices where agency_id=? and client=? and amount-paid>0",(r["agency_id"],r["payer"])).fetchall()
    return [dict(i, outstanding=round(i["amount"]-i["paid"],2)) for i in out]

def analyze(c, ex):
    """Returns verified facts (from data) separately from AI/heuristic hypotheses (unverified)."""
    cat, amt = ex["category"], ex["amount"]; hyp = []; steps = []; dup = []
    tot = c.execute("select coalesce(sum(amount),0) from receipts where agency_id=?",(ex["agency_id"],)).fetchone()[0] or 1
    pct = round(amt/tot*100,2); lvl = "High" if pct >= 2 else "Medium" if pct >= .5 else "Low"
    if cat in ("Unapplied Cash","Probable Duplicate"):
        r = c.execute("select * from receipts where id=?",(ex["subject_id"],)).fetchone()
        if cat == "Probable Duplicate":
            og = ex["dup_group"].replace("DG-R","")
            dup = [dict(x) for x in c.execute("select id,payer,amount,received,method,invoice_id from receipts where id=? or id in (select subject_id from exceptions where dup_group=?)",(og,ex["dup_group"]))]
            hyp.append(("Duplicate deposit from lockbox/bank-feed double import.",.8 if len(dup)>1 else .6,"Same agency, payer, amount and date as an already-applied receipt."))
            steps = ["Confirm with bank statement that only one deposit cleared","If duplicate, request approval to reverse the posting (ledger_posting)","Notify cash-application lead to tune the import filter"]
        else:
            cands = candidates(c, r); ex_m = [i for i in cands if abs(i["outstanding"]-r["amount"]) < 1]
            if ex_m: hyp.append((f"Payment for INV-{ex_m[0]['id']} - amount equals outstanding balance; remittance reference missing.",.85,"Exact amount + same payer + invoice still open."))
            elif cands: hyp.append((f"Partial payment against one of {len(cands)} open invoice(s) for {r['payer']}.",.55,"Same payer has open invoices but amounts differ."))
            else: hyp.append(("Unidentified remitter - hold in suspense and request remittance advice.",.3,"No matching payer or open invoice found."))
            steps = ["Match receipt to the candidate invoice and attach remittance evidence","Request approval for the cash application (ledger_posting)","Contact payer if no match within 3 business days"]
    elif cat == "Overdue Receivable":
        i = c.execute("select * from invoices where id=?",(ex["subject_id"],)).fetchone()
        un = c.execute("select * from receipts where invoice_id is null and agency_id=? and payer=? and abs(amount-?)<1",(i["agency_id"],i["client"],i["amount"]-i["paid"])).fetchone()
        if un: hyp.append((f"Cash already received (R-{un['id']}) but not applied - receivable may be overstated.",.8,"Unapplied receipt equals outstanding balance for the same client."))
        else: hyp.append(("Genuine collection delay - client has not paid.",.6,"No unapplied receipt matches this balance."))
        if ex["age_days"] > 90: hyp.append(("Collectability risk - consider allowance review.",.5,"Over 90 days past due."))
        steps = ["Check unapplied cash for this client first","Send reminder / dunning notice (prepare notification)","Escalate to agency principal if > 60 days"]
    elif cat == "Carrier Settlement":
        pc = float(dict(json.loads(ex["facts"]))["Shortfall %"])
        hyp += [("Carrier netted chargebacks or adjustments not on our statement.",.45,"Shortfall pattern typical of netting."),("Timing - balance paid on next statement cycle.",.35,"Short payments often catch up the following period.")]
        if pc > 8: hyp.append(("Commission schedule / rate mismatch with carrier.",.5,f"Shortfall of {pc}% exceeds normal netting range."))
        steps = ["Request carrier detail for the short payment","Compare statement lines to policy-level expectations","Escalate to carrier relations if unresolved by due date"]
    elif cat == "Commission Variance":
        f = dict(json.loads(ex["facts"])); over = f["Direction"] == "Overpaid"
        hyp += [("Producer rate or split applied incorrectly in the commission schedule.",.5,"Variance exceeds 2% tolerance."),("Policy endorsement / premium adjustment not reflected.",.4,"Common cause of one-period variances.")]
        steps = ["Review the producer's schedule and policy record",("Any recovery or adjustment of producer pay needs approval (commission_change)" if over else "Underpayment correction needs approval (commission_change)"),"Do NOT change producer compensation until approved"]
    else:
        hyp.append(("Task is blocked by open cash items in the same agency.",.7,"Blocker text and agency unapplied cash > 0."))
        steps = ["Clear the agency's unapplied cash exceptions","Re-run reconciliation and update task status"]
    return {"classification":cat,"verified_facts":json.loads(ex["facts"]),"hypotheses":[{"text":t,"confidence":cf,"basis":b,"verified":False} for t,cf,b in hyp],
            "materiality":{"pct_of_agency_receipts":pct,"level":lvl},"recommended_steps":steps,"duplicate_group":dup,
            "guardrail":"Hypotheses are AI/heuristic suggestions, not facts. Payments, ledger postings and compensation changes require human approval."}
