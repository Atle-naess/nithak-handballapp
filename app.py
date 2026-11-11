import os,json,sqlite3,secrets,datetime,functools,re,unicodedata,io,csv
from pathlib import Path
from flask import Flask,request,session,redirect,url_for,render_template,jsonify,abort
from werkzeug.security import generate_password_hash,check_password_hash

BASE=Path(__file__).parent
app=Flask(__name__)
app.config.update(SECRET_KEY=os.environ.get('SECRET_KEY') or secrets.token_hex(32),SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=True,MAX_CONTENT_LENGTH=2*1024*1024)
DB=os.environ.get('DATABASE_PATH','/tmp/nithak_demo.sqlite3')
STATUSES=['Deltok','Sent oppmøte','Gyldig fravær','Ikke deltatt','Ikke invitert']
ROLES=['admin','trener','spiller']

def conn():
 c=sqlite3.connect(DB);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c

def init():
 if os.environ.get('DEMO_MODE')!='1':
  raise RuntimeError('Denne pakken er bare for demonstrasjon. Sett DEMO_MODE=1.')
 with conn() as c:
  c.executescript('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('admin','trener','spiller')),player_id INTEGER REFERENCES players(id),active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS players(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS training(id INTEGER PRIMARY KEY,date TEXT NOT NULL UNIQUE,note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS attendance(training_id INTEGER NOT NULL REFERENCES training(id) ON DELETE CASCADE,player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,status TEXT NOT NULL,PRIMARY KEY(training_id,player_id));
CREATE TABLE IF NOT EXISTS match_plans(id INTEGER PRIMARY KEY,match_date TEXT NOT NULL,opponent TEXT NOT NULL DEFAULT '',mode TEXT NOT NULL,minutes INTEGER NOT NULL,interval_minutes INTEGER NOT NULL,goalkeepers TEXT NOT NULL,plan_json TEXT NOT NULL,created_by INTEGER REFERENCES users(id),created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS live_matches(id INTEGER PRIMARY KEY,plan_id INTEGER NOT NULL UNIQUE REFERENCES match_plans(id),state_json TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS playtime(id INTEGER PRIMARY KEY,player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,match_date TEXT NOT NULL,minutes INTEGER NOT NULL CHECK(minutes>=0 AND minutes<=120),position TEXT NOT NULL DEFAULT '',note TEXT NOT NULL DEFAULT '');''')
  if c.execute('SELECT COUNT(*) FROM players').fetchone()[0]==0:
   seed=json.loads((BASE/'seed.json').read_text())
   for name in seed['players']:c.execute('INSERT INTO players(name) VALUES (?)',(name,))
   ids={r['name']:r['id'] for r in c.execute('SELECT * FROM players')}
   for l in seed['logs']:
    c.execute('INSERT OR IGNORE INTO training(date,note) VALUES (?,?)',(l['date'],l.get('note','')))
    tid=c.execute('SELECT id FROM training WHERE date=?',(l['date'],)).fetchone()[0]
    for name,status in l.get('status',{}).items():
     if name in ids and status in STATUSES:c.execute('INSERT OR REPLACE INTO attendance VALUES (?,?,?)',(tid,ids[name],status))
  if c.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0:
   password=os.environ.get('ADMIN_PASSWORD')
   if not password or len(password)<12:raise RuntimeError('Sett ADMIN_PASSWORD til et unikt passord på minst 12 tegn før første oppstart.')
   username=os.environ.get('ADMIN_USERNAME','admin').strip().lower()
   c.execute('INSERT INTO users(username,password_hash,role) VALUES (?,?,?)',(username,generate_password_hash(password),'admin'))

def current():
 uid=session.get('uid')
 if not uid:return None
 with conn() as c:return c.execute('SELECT id,username,role,player_id FROM users WHERE id=? AND active=1',(uid,)).fetchone()

def login_required(f):
 @functools.wraps(f)
 def wrapped(*a,**kw):
  if not current():return jsonify(error='Ikke innlogget'),401
  return f(*a,**kw)
 return wrapped

def roles(*allowed):
 def deco(f):
  @functools.wraps(f)
  @login_required
  def wrapped(*a,**kw):
   if current()['role'] not in allowed:return jsonify(error='Ingen tilgang'),403
   return f(*a,**kw)
  return wrapped
 return deco

@app.before_request
def validate_origin():
 if request.path.startswith('/api/') and request.method in ('POST','PUT','PATCH','DELETE'):
  origin=request.headers.get('Origin')
  if origin:
   from urllib.parse import urlsplit
   target=urlsplit(request.host_url)
   source=urlsplit(origin)
   if source.netloc!=target.netloc or source.scheme!=target.scheme:
    return jsonify(error='Ugyldig forespørselskilde'),403

@app.after_request
def security_headers(response):
 response.headers['Strict-Transport-Security']='max-age=31536000'
 response.headers['X-Content-Type-Options']='nosniff';response.headers['X-Frame-Options']='DENY';response.headers['Referrer-Policy']='no-referrer';response.headers['Cache-Control']='no-store'
 response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; base-uri 'self'; form-action 'self'"
 return response

@app.get('/health')
def health():return jsonify(status='ok',mode='demo')

@app.get('/')
def home():return render_template('index.html')

@app.post('/api/login')
def login():
 d=request.get_json(silent=True) or {};name=str(d.get('username','')).strip().lower();password=str(d.get('password',''))
 with conn() as c:u=c.execute('SELECT * FROM users WHERE username=? AND active=1',(name,)).fetchone()
 if not u or not check_password_hash(u['password_hash'],password):return jsonify(error='Feil brukernavn eller passord'),401
 session.clear();session['uid']=u['id'];return jsonify(ok=True)

@app.post('/api/logout')
def logout():session.clear();return jsonify(ok=True)

@app.get('/api/me')
def me():
 u=current();return jsonify(user=dict(u) if u else None)

@app.get('/api/data')
@login_required
def data():
 u=current();pid=u['player_id'] if u['role']=='spiller' else None
 with conn() as c:
  players=[dict(x) for x in c.execute('SELECT * FROM players WHERE (? IS NULL OR id=?) ORDER BY name',(pid,pid))] if u['role']!='spiller' or pid else []
  trainings=[dict(x) for x in c.execute('SELECT * FROM training ORDER BY date DESC')]
  attendance=[dict(x) for x in c.execute('SELECT a.* FROM attendance a WHERE (? IS NULL OR a.player_id=?)',(pid,pid))] if u['role']!='spiller' or pid else []
  playtime=[dict(x) for x in c.execute('SELECT * FROM playtime WHERE (? IS NULL OR player_id=?) ORDER BY match_date DESC',(pid,pid))] if u['role']!='spiller' or pid else []
  users=[dict(x) for x in c.execute('SELECT id,username,role,player_id,active FROM users ORDER BY username')] if u['role']=='admin' else []
 
  plans=[dict(x) for x in c.execute('SELECT id,match_date,opponent,mode,minutes,interval_minutes,plan_json FROM match_plans ORDER BY id DESC LIMIT 30')] if u['role']!='spiller' else []
 return jsonify(players=players,trainings=trainings,attendance=attendance,playtime=playtime,users=users,plans=plans,role=u['role'],username=u['username'],statuses=STATUSES)

# Spond file import: preview first, explicit confirmation before database changes.
from openpyxl import load_workbook

def normalize_name(v):
 v=unicodedata.normalize('NFKD',str(v or '').casefold())
 return re.sub(r'[^a-z0-9]','', ''.join(c for c in v if not unicodedata.combining(c)))

def parse_date(v):
 if isinstance(v,datetime.datetime):return v.date().isoformat()
 if isinstance(v,datetime.date):return v.isoformat()
 if isinstance(v,(int,float)) and 20000<v<90000:
  from openpyxl.utils.datetime import from_excel
  return from_excel(v).date().isoformat()
 t=str(v or '').strip()
 for fmt in ('%Y-%m-%d','%d.%m.%Y','%d/%m/%Y','%d-%m-%Y','%Y-%m-%d %H:%M:%S','%d.%m.%Y %H:%M'):
  try:return datetime.datetime.strptime(t,fmt).date().isoformat()
  except ValueError:pass
 return None

def status_value(v):
 key=normalize_name(v)
 aliases={
 'deltok':'Deltok','deltatt':'Deltok','tilstede':'Deltok','attended':'Deltok','present':'Deltok','ja':'Deltok','d':'Deltok',
 'sent':'Sent oppmøte','sentoppmote':'Sent oppmøte','forsinket':'Sent oppmøte','late':'Sent oppmøte','s':'Sent oppmøte',
 'gyldigfravar':'Gyldig fravær','gyldig':'Gyldig fravær','lovligfravar':'Gyldig fravær','excused':'Gyldig fravær','g':'Gyldig fravær',
 'ikkedeltatt':'Ikke deltatt','fravar':'Ikke deltatt','fravaerende':'Ikke deltatt','absent':'Ikke deltatt','nei':'Ikke deltatt','i':'Ikke deltatt',
 'ikkeinvitert':'Ikke invitert','notinvited':'Ikke invitert','x':'Ikke invitert',
 '':'', 'ikkeregistrert':'', 'ukjent':''}
 return aliases.get(key)

def extract_spond(file_bytes,filename):
 if filename.lower().endswith('.csv'):
  decoded=file_bytes.decode('utf-8-sig')
  sample=decoded[:2048];dialect=csv.Sniffer().sniff(sample,delimiters=';,\t,')
  rows=list(csv.reader(io.StringIO(decoded),dialect))
  sheets=[('CSV',rows)]
 else:
  book=load_workbook(io.BytesIO(file_bytes),read_only=True,data_only=True)
  sheets=[(sh.title,list(sh.values)) for sh in book.worksheets]
 with conn() as c:players=[dict(r) for r in c.execute('SELECT id,name FROM players')]
 lookup={normalize_name(p['name']):p for p in players}
 entries=[];unknown=set();unrecognized=set();dates=set();matched=set();formats=set()
 for sheetname,rows in sheets:
  rows=[list(r) for r in rows]
  # Matrix layout: Dato | Kommentar | Player A | Player B ...
  for index,header in enumerate(rows[:25]):
   heads=[normalize_name(x) for x in header]
   dcol=next((j for j,h in enumerate(heads) if h in ('dato','date','treningsdato','eventdate')),None)
   matches={j:lookup[h] for j,h in enumerate(heads) if h in lookup}
   if dcol is not None and matches:
    formats.add('matrise')
    for row in rows[index+1:]:
     day=parse_date(row[dcol] if len(row)>dcol else None)
     if not day:continue
     dates.add(day)
     for col,p in matches.items():
      raw=row[col] if len(row)>col else None
      if raw is None or str(raw).strip()=='':continue
      status=status_value(raw)
      if status is None:unrecognized.add(str(raw)[:80]);continue
      if status:entries.append({'date':day,'player_id':p['id'],'player':p['name'],'status':status});matched.add(p['id'])
    break
  else:
   # Row layout: name | date | attendance (Spond export variants)
   for index,header in enumerate(rows[:25]):
    heads=[normalize_name(x) for x in header]
    namecol=next((j for j,h in enumerate(heads) if h in ('navn','name','spiller','medlem','member','deltaker','participant','fullname','fulltnavn')),None)
    datecol=next((j for j,h in enumerate(heads) if h in ('dato','date','treningsdato','eventdate','aktivitetsdato')),None)
    statuscol=next((j for j,h in enumerate(heads) if h in ('status','oppmote','attendance','svar','response','deltakelse')),None)
    if namecol is None or datecol is None or statuscol is None:continue
    formats.add('liste')
    for row in rows[index+1:]:
     name=str(row[namecol] or '').strip() if len(row)>namecol else ''
     day=parse_date(row[datecol] if len(row)>datecol else None)
     raw=row[statuscol] if len(row)>statuscol else None
     if not name or not day:continue
     dates.add(day)
     p=lookup.get(normalize_name(name))
     if not p:unknown.add(name);continue
     status=status_value(raw)
     if status is None:unrecognized.add(str(raw)[:80]);continue
     if status:entries.append({'date':day,'player_id':p['id'],'player':p['name'],'status':status});matched.add(p['id'])
    break
 # Resolve duplicate cells by latest occurrence in file.
 unique={(e['date'],e['player_id']):e for e in entries}
 return {'entries':list(unique.values()),'matched_players':len(matched),'dates':sorted(dates),'unknown_players':sorted(unknown),'unknown_statuses':sorted(unrecognized),'formats':sorted(formats)}

@app.post('/api/spond/preview')
@roles('admin','trener')
def spond_preview():
 f=request.files.get('file')
 if not f or not f.filename.lower().endswith(('.xlsx','.csv')):return jsonify(error='Velg en XLSX- eller CSV-fil fra Spond'),400
 try:result=extract_spond(f.read(),f.filename)
 except Exception:return jsonify(error='Kunne ikke lese filen. Kontroller at filen er en gyldig XLSX eller UTF-8 CSV.'),400
 # Do not expose the entire imported dataset unnecessarily in the preview.
 return jsonify(count=len(result['entries']),matched_players=result['matched_players'],dates=result['dates'],unknown_players=result['unknown_players'],unknown_statuses=result['unknown_statuses'],formats=result['formats'],sample=result['entries'][:12])

@app.post('/api/spond/import')
@roles('admin','trener')
def spond_import():
 f=request.files.get('file')
 if not f or not f.filename.lower().endswith(('.xlsx','.csv')):return jsonify(error='Velg XLSX eller CSV'),400
 if request.form.get('confirm')!='yes':return jsonify(error='Bekreft importen først'),400
 try:result=extract_spond(f.read(),f.filename)
 except Exception:return jsonify(error='Kunne ikke lese filen'),400
 if not result['entries']:return jsonify(error='Ingen gyldige oppmøteregistreringer funnet. Ingen endringer utført.'),400
 with conn() as c:
  for day in sorted({e['date'] for e in result['entries']}):
   c.execute('INSERT OR IGNORE INTO training(date,note) VALUES (?,?)',(day,'Importert fra Spond'))
  ids={r['date']:r['id'] for r in c.execute('SELECT id,date FROM training WHERE date IN ('+','.join('?' for _ in result['dates'])+')',result['dates'])} if result['dates'] else {}
  for e in result['entries']:
   c.execute('INSERT INTO attendance(training_id,player_id,status) VALUES (?,?,?) ON CONFLICT(training_id,player_id) DO UPDATE SET status=excluded.status',(ids[e['date']],e['player_id'],e['status']))
 return jsonify(ok=True,imported=len(result['entries']),dates=len({e['date'] for e in result['entries']}),unknown_players=result['unknown_players'],unknown_statuses=result['unknown_statuses'])

@app.post('/api/training')
@roles('admin','trener')
def training():
 d=request.get_json(silent=True) or {};date=d.get('date','');note=str(d.get('note',''))[:500]
 try:datetime.date.fromisoformat(date)
 except (ValueError,TypeError):return jsonify(error='Ugyldig dato'),400
 with conn() as c:
  c.execute('INSERT INTO training(date,note) VALUES (?,?) ON CONFLICT(date) DO UPDATE SET note=excluded.note',(date,note))
 return jsonify(ok=True)

@app.post('/api/attendance')
@roles('admin','trener')
def attendance():
 d=request.get_json(silent=True) or {};status=d.get('status');tid=d.get('training_id');pid=d.get('player_id')
 if status not in STATUSES+[None,'']:return jsonify(error='Ugyldig status'),400
 with conn() as c:
  if not c.execute('SELECT 1 FROM training WHERE id=?',(tid,)).fetchone() or not c.execute('SELECT 1 FROM players WHERE id=?',(pid,)).fetchone():return jsonify(error='Ukjent trening eller spiller'),400
  if not status:c.execute('DELETE FROM attendance WHERE training_id=? AND player_id=?',(tid,pid))
  else:c.execute('INSERT INTO attendance VALUES (?,?,?) ON CONFLICT(training_id,player_id) DO UPDATE SET status=excluded.status',(tid,pid,status))
 return jsonify(ok=True)

@app.post('/api/playtime')
@roles('admin','trener')
def playtime():
 d=request.get_json(silent=True) or {}
 try:datetime.date.fromisoformat(d['match_date']);minutes=int(d['minutes']);assert 0<=minutes<=120
 except (KeyError,ValueError,TypeError,AssertionError):return jsonify(error='Ugyldig dato eller antall minutter'),400
 with conn() as c:
  if not c.execute('SELECT 1 FROM players WHERE id=?',(d.get('player_id'),)).fetchone():return jsonify(error='Ukjent spiller'),400
  c.execute('INSERT INTO playtime(player_id,match_date,minutes,position,note) VALUES (?,?,?,?,?)',(d['player_id'],d['match_date'],minutes,str(d.get('position',''))[:60],str(d.get('note',''))[:300]))
 return jsonify(ok=True)

@app.post('/api/players')
@roles('admin')
def add_player():
 name=str((request.get_json(silent=True) or {}).get('name','')).strip()
 if len(name)<2 or len(name)>120:return jsonify(error='Ugyldig navn'),400
 try:
  with conn() as c:c.execute('INSERT INTO players(name) VALUES (?)',(name,))
 except sqlite3.IntegrityError:return jsonify(error='Spilleren finnes allerede'),409
 return jsonify(ok=True)

@app.post('/api/users')
@roles('admin')
def add_user():
 d=request.get_json(silent=True) or {};name=str(d.get('username','')).strip().lower();pw=str(d.get('password',''));role=d.get('role');pid=d.get('player_id')
 if len(name)<3 or len(name)>60 or len(pw)<12 or role not in ROLES:return jsonify(error='Brukernavn må være minst 3 tegn og passord minst 12 tegn'),400
 if role=='spiller' and not pid:return jsonify(error='Velg hvilken spiller kontoen tilhører'),400
 if role!='spiller':pid=None
 with conn() as c:
  if pid and not c.execute('SELECT 1 FROM players WHERE id=?',(pid,)).fetchone():return jsonify(error='Ukjent spiller'),400
  try:c.execute('INSERT INTO users(username,password_hash,role,player_id) VALUES (?,?,?,?)',(name,generate_password_hash(pw),role,pid))
  except sqlite3.IntegrityError:return jsonify(error='Brukernavnet er opptatt'),409
 return jsonify(ok=True)

@app.post('/api/users/<int:uid>/active')
@roles('admin')
def toggle_user(uid):
 d=request.get_json(silent=True) or {};active=1 if d.get('active') else 0
 if uid==current()['id'] and not active:return jsonify(error='Du kan ikke deaktivere deg selv'),400
 with conn() as c:
  c.execute('UPDATE users SET active=? WHERE id=?',(active,uid))
 return jsonify(ok=True)

@app.post('/api/password')
@login_required
def change_password():
 d=request.get_json(silent=True) or {};old=str(d.get('old',''));new=str(d.get('new',''))
 if len(new)<12:return jsonify(error='Nytt passord må ha minst 12 tegn'),400
 with conn() as c:
  u=c.execute('SELECT password_hash FROM users WHERE id=?',(current()['id'],)).fetchone()
  if not check_password_hash(u['password_hash'],old):return jsonify(error='Gammelt passord er feil'),400
  c.execute('UPDATE users SET password_hash=? WHERE id=?',(generate_password_hash(new),current()['id']))
 return jsonify(ok=True)


@app.post('/api/match-plan')
@roles('admin','trener')
def create_match_plan():
 d=request.get_json(silent=True) or {}
 try:
  date=datetime.date.fromisoformat(d.get('date',''))
  duration=int(d.get('minutes',50));interval=int(d.get('interval',5))
  ids=[int(x) for x in d.get('players',[])]
  goalies=[int(x) for x in d.get('goalkeepers',[])]
  assert d.get('mode') in ('equal','attendance')
  assert 10<=duration<=120 and 1<=interval<=20 and duration%interval==0
  assert len(ids)>=7 and len(ids)<=30 and len(ids)==len(set(ids))
  assert len(goalies)>=1 and len(goalies)<=3 and len(set(goalies))==len(goalies) and set(goalies).issubset(ids)
  assert len(set(ids)-set(goalies))>=6
 except (ValueError,TypeError,AssertionError):return jsonify(error='Velg minst 6 utespillere og 1–3 målvakter. Kampvarighet må være delelig med bytteintervall.'),400
 with conn() as c:
  known={r[0] for r in c.execute('SELECT id FROM players')}
  if not set(ids).issubset(known):return jsonify(error='Ukjent spiller'),400
  since=(date-datetime.timedelta(days=59)).isoformat()
  rows=c.execute('''SELECT a.player_id,a.status FROM attendance a JOIN training t ON t.id=a.training_id WHERE t.date>=? AND t.date<=?''',(since,date.isoformat())).fetchall()
  stats={i:[0,0] for i in ids}
  for r in rows:
   if r['player_id'] not in stats:continue
   if r['status'] in ('Deltok','Sent oppmøte'):stats[r['player_id']][0]+=1
   if r['status'] in ('Deltok','Sent oppmøte','Gyldig fravær','Ikke deltatt'):stats[r['player_id']][1]+=1
  rates={i:(stats[i][0]/stats[i][1] if stats[i][1] else None) for i in ids}
  # A floor prevents exclusion; unknown attendance is neutral, not zero.
  weights={i:(1 if d['mode']=='equal' or rates[i] is None else 0.5+rates[i]) for i in ids}
  field=[i for i in ids if i not in goalies]
  groups=[(field,6),(goalies,1)]
  totals={i:0 for i in ids};last={i:-1000 for i in ids};segments=[]
  for step,start in enumerate(range(0,duration,interval)):
   active=[]
   for group,seats in groups:
    budget=duration*seats
    weight_sum=sum(weights[i] for i in group)
    targets={i:budget*weights[i]/weight_sum for i in group}
    # Prioritize largest deficit to target, then rest since previous selection.
    ranked=sorted(group,key=lambda i:((targets[i]*(start+interval)/duration-totals[i])/weights[i],step-last[i],-i),reverse=True)
    picked=ranked[:seats]
    for i in picked:totals[i]+=interval;last[i]=step
    active+=picked
   segments.append({'start':start,'end':start+interval,'goalkeeper':active[-1],'field':active[:-1]})
  output={'segments':segments,'totals':totals,'rates':rates,'weights':weights,'mode':d['mode'],'minutes':duration,'interval':interval,'goalkeepers':goalies}
  opponent=str(d.get('opponent','')).strip()[:120]
  c.execute('INSERT INTO match_plans(match_date,opponent,mode,minutes,interval_minutes,goalkeepers,plan_json,created_by) VALUES (?,?,?,?,?,?,?,?)',(date.isoformat(),opponent,d['mode'],duration,interval,json.dumps(goalies),json.dumps(output),current()['id']))
  output['id']=c.execute('SELECT last_insert_rowid()').fetchone()[0]
 return jsonify(output)

@app.get('/api/match-plan/<int:plan_id>')
@roles('admin','trener')
def get_match_plan(plan_id):
 with conn() as c:r=c.execute('SELECT * FROM match_plans WHERE id=?',(plan_id,)).fetchone()
 if not r:return jsonify(error='Bytteplanen finnes ikke'),404
 return jsonify(id=r['id'],date=r['match_date'],opponent=r['opponent'],**json.loads(r['plan_json']))



# Kampklokken bruker servertid, og lagrer status etter hver handling.
# Tiden teller bare mens kampen er i gang. En avsluttet kamp kan ikke endres.
def live_now():return datetime.datetime.now(datetime.timezone.utc).timestamp()
def live_elapsed(st,now=None):
 now=now or live_now()
 return min(float(st['duration_seconds']),float(st['elapsed'])+(max(0,now-st['started_at']) if st['running'] else 0))
def live_snapshot(st):
 out=dict(st);out['elapsed_now']=round(live_elapsed(st),2);return out

def live_settle(st,now):
 elapsed=live_elapsed(st,now);delta=max(0,elapsed-st['accounted_until'])
 if delta:
  for pid in st['on_court']:st['actual_seconds'][str(pid)]=st['actual_seconds'].get(str(pid),0)+delta
 st['accounted_until']=elapsed;st['elapsed']=elapsed;st['started_at']=now
 return elapsed

@app.post('/api/live/<int:plan_id>/create')
@roles('admin','trener')
def live_create(plan_id):
 with conn() as c:
  plan=c.execute('SELECT * FROM match_plans WHERE id=?',(plan_id,)).fetchone()
  if not plan:return jsonify(error='Bytteplanen finnes ikke'),404
  old=c.execute('SELECT state_json FROM live_matches WHERE plan_id=?',(plan_id,)).fetchone()
  if old:return jsonify(live_snapshot(json.loads(old['state_json'])))
  p=json.loads(plan['plan_json']);first=p['segments'][0]
  court=[first['goalkeeper'],*first['field']];roster=list(map(int,p['totals'].keys()))
  st={'plan_id':plan_id,'date':plan['match_date'],'opponent':plan['opponent'],'duration_seconds':p['minutes']*60,'elapsed':0,'accounted_until':0,'started_at':0,'running':False,'finished':False,'on_court':court,'roster':roster,'goalkeepers':p['goalkeepers'],'actual_seconds':{str(i):0 for i in roster},'events':[{'at':0,'kind':'opprettet','on_court':court}],'saved':False}
  c.execute('INSERT INTO live_matches(plan_id,state_json) VALUES (?,?)',(plan_id,json.dumps(st)))
 return jsonify(live_snapshot(st))

@app.get('/api/live/<int:plan_id>')
@roles('admin','trener')
def live_get(plan_id):
 with conn() as c:r=c.execute('SELECT state_json FROM live_matches WHERE plan_id=?',(plan_id,)).fetchone()
 if not r:return jsonify(error='Ingen kamp startet'),404
 return jsonify(live_snapshot(json.loads(r['state_json'])))

@app.post('/api/live/<int:plan_id>/action')
@roles('admin','trener')
def live_action(plan_id):
 d=request.get_json(silent=True) or {};action=d.get('action')
 if action not in ('start','pause','swap','finish'):return jsonify(error='Ukjent handling'),400
 now=live_now()
 with conn() as c:
  c.execute('BEGIN IMMEDIATE')
  r=c.execute('SELECT state_json FROM live_matches WHERE plan_id=?',(plan_id,)).fetchone()
  if not r:return jsonify(error='Kampen finnes ikke'),404
  st=json.loads(r['state_json'])
  if st['finished']:return jsonify(error='Kampen er allerede avsluttet'),409
  elapsed=live_settle(st,now)
  if action=='start':
   if elapsed>=st['duration_seconds']:return jsonify(error='Kamptiden er brukt opp. Avslutt kampen.'),400
   st['running']=True;st['started_at']=now
  elif action=='pause':st['running']=False
  elif action=='swap':
   try:out=int(d['out']);inside=int(d['in'])
   except (KeyError,TypeError,ValueError):return jsonify(error='Velg spillere'),400
   if out not in st['on_court'] or inside in st['on_court'] or inside not in st['roster']:return jsonify(error='Ugyldig spillerbytte'),400
   if (out in st['goalkeepers']) != (inside in st['goalkeepers']):return jsonify(error='Bytt målvakt mot målvakt, eller utespiller mot utespiller'),400
   st['on_court'][st['on_court'].index(out)]=inside
   st['events'].append({'at':round(elapsed,2),'kind':'bytte','out':out,'in':inside})
  elif action=='finish':
   st['running']=False;st['finished']=True
   # Faktisk spilletid lagres én gang per spiller, i hele minutter avrundet.
   if not st['saved']:
    for pid,seconds in st['actual_seconds'].items():
     if seconds>0:
      c.execute('INSERT INTO playtime(player_id,match_date,minutes,position,note) VALUES (?,?,?,?,?)',(int(pid),st['date'],min(120,round(seconds/60)),'Målvakt' if int(pid) in st['goalkeepers'] else 'Utespiller',f'Live kampplan #{plan_id} ({round(seconds)} sekunder)'))
    st['saved']=True
  st['events'].append({'at':round(elapsed,2),'kind':action})
  c.execute('UPDATE live_matches SET state_json=?,updated_at=CURRENT_TIMESTAMP WHERE plan_id=?',(json.dumps(st),plan_id))
 return jsonify(live_snapshot(st))

if __name__=='__main__':
 init();app.run(host='127.0.0.1',port=int(os.environ.get('PORT','5000')),debug=False)
