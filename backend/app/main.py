import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import datetime as dt
from .config import CORS, AS_OF, GROQ_API_KEY, GROQ_MODEL
from .db import get_conn, init_db, audit
from . import rules, ai

@asynccontextmanager
async def lifespan(app): init_db(); yield
app = FastAPI(title="Meridian Finance Command Center", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=CORS, allow_methods=["*"], allow_headers=["*"])

def user(x_user_id: int = Header(4)):
    c = get_conn(); u = c.execute("select * from users where id=?",(x_user_id,)).fetchone(); c.close()
    if not u: raise HTTPException(401,"Unknown user")
    return dict(u)
def need(u, *roles, action=""):
    if u["role"] not in roles:
        c = get_conn(); audit(c,u,"DENIED",action,f"role {u['role']} not permitted"); c.close()
        raise HTTPException(403,f"Role '{u['role']}' is not allowed to {action}.")
WRITE = ("analyst","manager","controller")
def rows(c,sql,p=()): return [dict(x) for x in c.execute(sql,p).fetchall()]
def get_ex(c,i):
    e = c.execute("select e.*,a.name agency from exceptions e join agencies a on a.id=e.agency_id where e.id=?",(i,)).fetchone()
    if not e: raise HTTPException(404,"Exception not found")
    return dict(e)

@app.get("/api/health")
def health(): return {"ok":True,"as_of":str(AS_OF),"llm":bool(GROQ_API_KEY),"model":GROQ_MODEL,"data":"SYNTHETIC - sample data only"}
@app.get("/api/users")
def users():
    c=get_conn(); r=rows(c,"select * from users"); c.close(); return r

@app.get("/api/dashboard")
def dashboard(u=Depends(user)):
    c=get_conn(); one=lambda s:c.execute(s).fetchone()[0]
    ex=rows(c,"select e.*,a.name agency from exceptions e join agencies a on a.id=e.agency_id where status!='Resolved' order by score desc")
    rec=rows(c,"select status,count(*) n from reconciliations group by status"); dups=one("select count(*) from exceptions where category='Probable Duplicate'"); groups=one("select count(distinct dup_group) from exceptions where dup_group is not null")
    out={"as_of":str(AS_OF),
     "kpis":{"total_receipts":one("select sum(amount) from receipts"),"unapplied_cash":one("select coalesce(sum(amount),0) from receipts where invoice_id is null"),
      "overdue_receivables":one(f"select coalesce(sum(amount-paid),0) from invoices where due<'{AS_OF}' and amount-paid>0"),
      "carrier_payables_due":one(f"select coalesce(sum(payable_due),0) from carrier_statements where due_date<='{AS_OF+dt.timedelta(days=14)}'"),
      "commission_exceptions":{"count":one("select count(*) from exceptions where category='Commission Variance'"),"amount":one("select coalesce(sum(amount),0) from exceptions where category='Commission Variance'")},
      "reconciliation":{r["status"]:r["n"] for r in rec},"close_readiness":rules.close_readiness(c)},
     "by_severity":rows(c,"select severity,count(*) n,sum(amount) amount from exceptions where status!='Resolved' group by severity"),
     "by_category":rows(c,"select category,count(*) n,sum(amount) amount from exceptions where status!='Resolved' group by category order by n desc"),
     "by_agency":rows(c,"select a.name agency,count(*) n,sum(e.amount) amount from exceptions e join agencies a on a.id=e.agency_id where e.status!='Resolved' group by a.name order by amount desc"),
     "top":ex[:6],
     "success_metrics":{"alerts_before_grouping":len(ex)+groups,"alerts_after_grouping":len(ex),"duplicate_alerts_removed":groups,"duplicate_exceptions":dups,"open_exceptions":len(ex),"resolved":one("select count(*) from exceptions where status='Resolved'")}}
    c.close(); return out

@app.get("/api/exceptions")
def list_ex(q:str="",category:str="",severity:str="",status:str="",agency_id:int=0,u=Depends(user)):
    c=get_conn(); sql="select e.id,e.category,e.amount,e.age_days,e.severity,e.score,e.deadline,e.owner,e.status,e.dup_group,a.name agency from exceptions e join agencies a on a.id=e.agency_id where 1=1"; p=[]
    for col,v in (("e.category",category),("e.severity",severity),("e.status",status)):
        if v: sql+=f" and {col}=?"; p.append(v)
    if agency_id: sql+=" and e.agency_id=?"; p.append(agency_id)
    if q: sql+=" and (e.id like ? or a.name like ? or e.owner like ? or e.facts like ?)"; p+=[f"%{q}%"]*4
    r=rows(c,sql+" order by e.score desc",p); c.close(); return r

@app.get("/api/exceptions/{eid}")
def detail(eid:str,u=Depends(user)):
    c=get_conn(); e=get_ex(c,eid); e["facts"]=json.loads(e["facts"]); ag=e["agency_id"]; s=e["subject_id"]; L={}
    if e["subject_table"]=="receipts":
        r=c.execute("select * from receipts where id=?",(s,)).fetchone(); L["receipts"]=[dict(r)]+rows(c,"select * from receipts where id!=? and agency_id=? and payer=? and amount=?",(s,ag,r["payer"],r["amount"])); L["invoices"]=rules.candidates(c,r)
    elif e["subject_table"]=="invoices":
        L["invoices"]=rows(c,"select * from invoices where id=?",(s,)); L["receipts"]=rows(c,"select * from receipts where invoice_id=? or (invoice_id is null and agency_id=? and payer=?)",(s,ag,L["invoices"][0]["client"]))
    elif e["subject_table"]=="carrier_statements": L["statements"]=rows(c,"select * from carrier_statements where id=?",(s,))
    elif e["subject_table"]=="commissions":
        m=c.execute("select * from commissions where id=?",(s,)).fetchone(); L["commissions"]=rows(c,"select * from commissions where producer=? and period=?",(m["producer"],m["period"]))
    else: L["close_tasks"]=rows(c,"select * from close_tasks where id=?",(s,)); L["receipts"]=rows(c,"select * from receipts where invoice_id is null and agency_id=?",(ag,))
    L["reconciliations"]=rows(c,"select * from reconciliations where agency_id=?",(ag,))
    out={"exception":e,"linked":L,"notes":rows(c,"select * from notes where exception_id=? order by id desc",(eid,)),"approvals":rows(c,"select * from approvals where exception_id=? order by id desc",(eid,)),
         "history":rows(c,"select ts,actor,role,action,detail from audit_log where entity=? order by id desc",(eid,))}
    audit(c,u,"VIEW",eid); c.close(); return out

@app.get("/api/exceptions/{eid}/analysis")
def analysis(eid:str,u=Depends(user)):
    c=get_conn(); r=rules.analyze(c,get_ex(c,eid)); c.close(); return r

class Assign(BaseModel): owner:str
class Status(BaseModel): status:str
class Note(BaseModel): text:str
class ApprovalReq(BaseModel): action_type:str; reason:str=""
class Decision(BaseModel): approve:bool; reason:str=""
class Ask(BaseModel): question:str

@app.post("/api/exceptions/{eid}/assign")
def assign(eid:str,b:Assign,u=Depends(user)):
    need(u,*WRITE,action="assign exceptions"); c=get_conn(); e=get_ex(c,eid)
    if not c.execute("select 1 from users where name=? and role!='viewer'",(b.owner,)).fetchone(): raise HTTPException(400,"Unknown owner")
    c.execute("update exceptions set owner=? where id=?",(b.owner,eid)); c.commit(); audit(c,u,"ASSIGN",eid,f"{e['owner']} -> {b.owner}"); c.close(); return {"ok":True}

@app.post("/api/exceptions/{eid}/status")
def status(eid:str,b:Status,u=Depends(user)):
    need(u,*WRITE,action="update status"); c=get_conn(); e=get_ex(c,eid)
    if b.status not in ("Open","Investigating","Pending Approval","Resolved"): raise HTTPException(400,"Invalid status")
    if b.status=="Resolved" and e["category"] in rules.NEEDS_APPROVAL and not c.execute("select 1 from approvals where exception_id=? and status='Approved'",(eid,)).fetchone():
        audit(c,u,"BLOCKED",eid,"Resolve attempted without approval"); c.close(); raise HTTPException(409,"Human approval required before resolving this exception.")
    c.execute("update exceptions set status=? where id=?",(b.status,eid)); c.commit(); audit(c,u,"STATUS",eid,f"{e['status']} -> {b.status}"); c.close(); return {"ok":True}

@app.post("/api/exceptions/{eid}/notes")
def add_note(eid:str,b:Note,u=Depends(user)):
    need(u,*WRITE,action="add notes"); c=get_conn(); get_ex(c,eid)
    c.execute("insert into notes(exception_id,author,text,ts) values(?,?,?,?)",(eid,u["name"],b.text,dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))); c.commit(); audit(c,u,"NOTE",eid,b.text[:80]); c.close(); return {"ok":True}

@app.post("/api/exceptions/{eid}/notify")
def notify(eid:str,u=Depends(user)):
    need(u,*WRITE,action="prepare notifications"); c=get_conn(); e=get_ex(c,eid); f=dict(json.loads(e["facts"]))
    d={"to":e["owner"],"subject":f"[{e['severity']}] {e['id']} - {e['category']} at {e['agency']}","body":f"{e['category']} of ${e['amount']:,.2f} ({e['age_days']} days old, deadline {e['deadline']}). Details: "+"; ".join(f"{k}: {v}" for k,v in f.items())+". Please review and update the exception.","sent":False,"note":"Draft only - nothing is sent automatically."}
    audit(c,u,"NOTIFY_DRAFT",eid,d["subject"]); c.close(); return d

@app.post("/api/exceptions/{eid}/approvals")
def request_approval(eid:str,b:ApprovalReq,u=Depends(user)):
    need(u,*WRITE,action="request approvals"); c=get_conn(); e=get_ex(c,eid)
    if b.action_type not in rules.SENSITIVE: raise HTTPException(400,"action_type must be payment, ledger_posting or commission_change")
    c.execute("insert into approvals(exception_id,action_type,amount,requested_by,status,ts,reason) values(?,?,?,?,?,?,?)",(eid,b.action_type,e["amount"],u["name"],"Pending",dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),b.reason))
    c.execute("update exceptions set status='Pending Approval' where id=?",(eid,)); c.commit(); audit(c,u,"APPROVAL_REQUEST",eid,b.action_type); c.close(); return {"ok":True}

@app.get("/api/approvals")
def approvals(u=Depends(user)):
    c=get_conn(); r=rows(c,"select * from approvals order by id desc"); c.close(); return r

@app.post("/api/approvals/{aid}/decide")
def decide(aid:int,b:Decision,u=Depends(user)):
    need(u,"manager","controller",action="decide approvals"); c=get_conn(); a=c.execute("select * from approvals where id=?",(aid,)).fetchone()
    if not a or a["status"]!="Pending": raise HTTPException(404,"No pending approval")
    if a["requested_by"]==u["name"]: raise HTTPException(409,"Requester cannot approve their own request.")
    if u["role"]!="controller": audit(c,u,"DENIED",f"approval {aid}","Controller required"); c.close(); raise HTTPException(403,"Only a controller can approve payments, ledger postings or compensation changes.")
    st="Approved" if b.approve else "Rejected"; c.execute("update approvals set status=?,decided_by=?,reason=? where id=?",(st,u["name"],b.reason,aid))
    if not b.approve: c.execute("update exceptions set status='Investigating' where id=?",(a["exception_id"],))
    c.commit(); audit(c,u,f"APPROVAL_{st.upper()}",a["exception_id"],f"{a['action_type']} - execution remains a manual step in the ledger/payment system"); c.close(); return {"ok":True,"status":st,"note":"Approval recorded. No payment, posting or compensation change was executed by this app."}

@app.get("/api/audit")
def audit_log(u=Depends(user)):
    c=get_conn(); r=rows(c,"select * from audit_log order by id desc limit 200"); c.close(); return r
@app.post("/api/copilot")
def copilot(b:Ask,u=Depends(user)):
    c=get_conn(); r=ai.ask(c,b.question); audit(c,u,"COPILOT",b.question[:60],r["source"]); c.close(); return r
