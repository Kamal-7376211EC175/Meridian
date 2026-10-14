import sqlite3, random, json, hashlib, datetime as dt
from .config import DB_PATH, AS_OF
from . import rules
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,name TEXT,role TEXT);
CREATE TABLE IF NOT EXISTS agencies(id INTEGER PRIMARY KEY,name TEXT,region TEXT);
CREATE TABLE IF NOT EXISTS invoices(id INTEGER PRIMARY KEY,agency_id INT,client TEXT,carrier TEXT,amount REAL,issued TEXT,due TEXT,paid REAL);
CREATE TABLE IF NOT EXISTS receipts(id INTEGER PRIMARY KEY,agency_id INT,payer TEXT,amount REAL,received TEXT,reference TEXT,method TEXT,invoice_id INT);
CREATE TABLE IF NOT EXISTS carrier_statements(id INTEGER PRIMARY KEY,agency_id INT,carrier TEXT,period TEXT,expected REAL,paid REAL,payable_due REAL,due_date TEXT);
CREATE TABLE IF NOT EXISTS commissions(id INTEGER PRIMARY KEY,agency_id INT,producer TEXT,policy TEXT,period TEXT,expected REAL,paid REAL);
CREATE TABLE IF NOT EXISTS reconciliations(id INTEGER PRIMARY KEY,agency_id INT,account TEXT,period TEXT,book_balance REAL,bank_balance REAL,status TEXT);
CREATE TABLE IF NOT EXISTS close_tasks(id INTEGER PRIMARY KEY,agency_id INT,name TEXT,owner TEXT,due TEXT,status TEXT,blocker TEXT);
CREATE TABLE IF NOT EXISTS exceptions(id TEXT PRIMARY KEY,agency_id INT,category TEXT,subject_table TEXT,subject_id INT,amount REAL,detected TEXT,age_days INT,deadline TEXT,owner TEXT,status TEXT,severity TEXT,score REAL,facts TEXT,dup_group TEXT);
CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY,exception_id TEXT,author TEXT,text TEXT,ts TEXT);
CREATE TABLE IF NOT EXISTS approvals(id INTEGER PRIMARY KEY,exception_id TEXT,action_type TEXT,amount REAL,requested_by TEXT,status TEXT,decided_by TEXT,reason TEXT,ts TEXT);
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY,ts TEXT,actor TEXT,role TEXT,action TEXT,entity TEXT,detail TEXT,prev_hash TEXT,hash TEXT);
"""
TABLES = ["users","agencies","invoices","receipts","carrier_statements","commissions","reconciliations","close_tasks","exceptions","notes","approvals","audit_log"]

def get_conn():
    c = sqlite3.connect(DB_PATH); c.row_factory = sqlite3.Row; return c

def audit(c, u, action, entity, detail=""):
    p = c.execute("select hash from audit_log order by id desc limit 1").fetchone()
    p = p[0] if p else "GENESIS"
    ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    h = hashlib.sha256(f"{p}|{ts}|{u['name']}|{action}|{entity}|{detail}".encode()).hexdigest()
    c.execute("insert into audit_log(ts,actor,role,action,entity,detail,prev_hash,hash) values(?,?,?,?,?,?,?,?)",
              (ts, u["name"], u["role"], action, entity, detail, p, h)); c.commit()

def init_db(force=False):
    c = get_conn(); c.executescript(SCHEMA)
    if force or not c.execute("select count(*) from agencies").fetchone()[0]:
        seed(c); rules.detect(c)
    c.close()

def seed(c):
    for t in TABLES: c.execute(f"delete from {t}")
    r = random.Random(42)  # repeatable synthetic data
    day = lambda n: (AS_OF - dt.timedelta(days=n)).isoformat()
    c.executemany("insert into users values(?,?,?)", [(1,"Priya Nair","analyst"),(2,"Marcus Lee","analyst"),(3,"Sofia Alvarez","manager"),(4,"Daniel Okoye","controller"),(5,"Ava Chen","viewer")])
    ags = ["Harbor Insurance Group","Summit Risk Advisors","Lakeside Benefits","Ironwood Commercial","Coastal Personal Lines"]
    c.executemany("insert into agencies values(?,?,?)", [(i+1,n,reg) for i,(n,reg) in enumerate(zip(ags,["Northeast","Mountain","Midwest","Southeast","West"]))])
    clients = ["Alder Logistics","Brightwater Dental","Cobalt Fabrication","Dunmore Farms","Evergreen Schools","Foxglove Retail","Granite Builders","Hollis Pharmacy","Juniper Hotels","Kestrel Freight","Larkspur Clinics","Mosaic Media"]
    carriers = ["Aegis Mutual","Beacon Casualty","Crestline Re","Delta Shield","Everton Assurance"]
    producers = ["J. Whitfield","R. Banerjee","T. Castillo","M. Oyelaran","K. Lindqvist","S. Park","D. Moreau"]
    inv = []
    for i in range(1, 141):
        a = r.randint(1,5); amt = round(r.uniform(1500,48000),2); age = r.randint(5,150)
        iss = AS_OF - dt.timedelta(days=age); m = r.random()
        paid = amt if m < .6 else round(amt*r.uniform(.3,.8),2) if m < .75 else 0
        cl = r.choice(clients)
        c.execute("insert into invoices values(?,?,?,?,?,?,?,?)",(i,a,cl,r.choice(carriers),amt,iss.isoformat(),(iss+dt.timedelta(days=30)).isoformat(),paid))
        inv.append((i,a,cl,amt,paid))
        if paid:
            rec = min(AS_OF, iss + dt.timedelta(days=r.randint(3,40)))
            c.execute("insert into receipts(agency_id,payer,amount,received,reference,method,invoice_id) values(?,?,?,?,?,?,?)",(a,cl,paid,rec.isoformat(),f"INV-{i}",r.choice(["ACH","Wire","Check"]),i))
    openi = [x for x in inv if x[3]-x[4] > 0]
    for n,x in enumerate(r.sample(openi,12)):  # cash received but not applied
        out = round(x[3]-x[4],2); amt = out if n % 10 < 7 else round(out*.5,2)
        c.execute("insert into receipts(agency_id,payer,amount,received,reference,method,invoice_id) values(?,?,?,?,?,?,?)",(x[1],x[2],amt,day(r.randint(1,25)),f"WIRE-{r.randint(1000,9999)}","Wire",None))
    for a in (1,3,4):
        c.execute("insert into receipts(agency_id,payer,amount,received,reference,method,invoice_id) values(?,?,?,?,?,?,?)",(a,"UNKNOWN REMITTER",round(r.uniform(900,15000),2),day(r.randint(2,20)),"BANK-FEED","ACH",None))
    for o in c.execute("select * from receipts where invoice_id is not null order by id").fetchall()[:60:10]:  # duplicate deposits
        c.execute("insert into receipts(agency_id,payer,amount,received,reference,method,invoice_id) values(?,?,?,?,?,?,?)",(o["agency_id"],o["payer"],o["amount"],o["received"],o["reference"],"Lockbox",None))
    for i in range(1, 31):
        e = round(r.uniform(8000,90000),2); short = r.random() < .35
        c.execute("insert into carrier_statements values(?,?,?,?,?,?,?,?)",(i,r.randint(1,5),r.choice(carriers),"2026-09",e,round(e*(1-r.uniform(.02,.12)),2) if short else e,round(e*r.uniform(.5,.8),2),(AS_OF+dt.timedelta(days=r.randint(-10,20))).isoformat()))
    for i in range(1, 71):
        e = round(r.uniform(150,6000),2); v = r.random() < .25
        c.execute("insert into commissions values(?,?,?,?,?,?,?)",(i,r.randint(1,5),r.choice(producers),f"POL-{r.randint(10000,99999)}","2026-09",e,round(e*(1+r.uniform(-.15,.15)),2) if v else e))
    n = 0
    for a in range(1,6):
        for acct in ("Operating","Premium Trust"):
            n += 1; book = round(r.uniform(200000,900000),2); diff = 0 if r.random() < .6 else round(r.uniform(500,25000),2)
            c.execute("insert into reconciliations values(?,?,?,?,?,?,?)",(n,a,acct,"2026-09",book,round(book-diff,2),"Matched" if not diff else "Unmatched"))
    n = 0
    for a in range(1,6):
        for t in ["Bank reconciliation sign-off","Apply all cash receipts","Carrier statement reconciliation","Commission accrual review","AR aging review","Trust account tie-out"]:
            n += 1; s = r.choices(["Done","In Progress","Blocked"],[45,30,25])[0]
            c.execute("insert into close_tasks values(?,?,?,?,?,?,?)",(n,a,t,r.choice(["Priya Nair","Marcus Lee","Sofia Alvarez"]),(AS_OF+dt.timedelta(days=r.randint(-2,14))).isoformat(),s,"Waiting on unapplied cash / unmatched items" if s=="Blocked" else None))
    c.commit()
