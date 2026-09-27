"""SQLite object memory. Identity is confirmed by a camera-scanned physical tag."""
import json
from contextlib import contextmanager
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path

class ObjectMemory:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS objects(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE COLLATE NOCASE,status TEXT NOT NULL DEFAULT 'unseen',zone TEXT,last_seen REAL,photo BLOB,gps TEXT);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,object_id TEXT,kind TEXT,zone TEXT,previous_zone TEXT,at REAL);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
            ''')
            columns={r['name'] for r in db.execute('PRAGMA table_info(objects)')}
            if 'saved' not in columns:db.execute('ALTER TABLE objects ADD COLUMN saved INTEGER NOT NULL DEFAULT 1')
            if 'source' not in columns:db.execute("ALTER TABLE objects ADD COLUMN source TEXT NOT NULL DEFAULT 'tag'")
            if not db.execute("SELECT 1 FROM settings WHERE key='chat_map_v2'").fetchone():
                # Archive earlier demo seeds, preserving their records and event history.
                db.execute("UPDATE objects SET saved=0 WHERE lower(name) IN ('cane','walker') OR (lower(name)='medicine bottle' AND last_seen IS NULL)")
                db.execute("INSERT INTO settings(key,value) VALUES('chat_map_v2','1')")

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def text(value, limit=80):
        if not isinstance(value,str) or not value.strip() or len(value.strip()) > limit:
            raise ValueError(f'Enter a name of 1–{limit} characters.')
        return value.strip()

    def snapshot(self):
        with self.lock,self.db() as db:
            objects=[]
            for row in db.execute('SELECT id,name,status,zone,last_seen,gps,source,photo IS NOT NULL AS has_photo FROM objects WHERE saved=1 ORDER BY name'):
                item=dict(row);item['gps']=json.loads(item['gps']) if item['gps'] else None
                item['icon']=self.icon(item['name'])
                item['tag']='GUIDEDOG:OBJECT:'+item['id']
                item['photo_url']='/objects/'+item['id']+'/photo' if item['has_photo'] else None
                objects.append(item)
            setting=db.execute("SELECT value FROM settings WHERE key='zone'").fetchone()
            events=[dict(r) for r in db.execute('SELECT events.*,objects.name FROM events JOIN objects ON objects.id=events.object_id ORDER BY events.id DESC LIMIT 30')]
            return {'objects':objects,'events':events,'zone':setting['value'] if setting else None,'location_method':'Operator-selected zone; camera-scanned object tag'}

    def set_zone(self,zone):
        zone=self.text(zone)
        with self.lock,self.db() as db:
            db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('zone',?)",(zone,))
        return zone

    def add(self,name):
        name=self.text(name)
        with self.lock,self.db() as db:
            if db.execute('SELECT count(*) FROM objects').fetchone()[0]>=50:raise ValueError('Maximum 50 objects.')
            db.execute('INSERT INTO objects(id,name,saved) VALUES(?,?,1)',(uuid.uuid4().hex,name))
        return self.snapshot()

    def mark_moved(self,object_id):
        with self.lock,self.db() as db:
            row=db.execute('SELECT * FROM objects WHERE id=? AND saved=1',(object_id,)).fetchone()
            if not row:raise ValueError('Unknown object.')
            if not row['last_seen']:raise ValueError('Scan this object once before marking it moved.')
            if row['status']=='missing':return
            db.execute("UPDATE objects SET status='missing' WHERE id=?",(object_id,))
            db.execute('INSERT INTO events(object_id,kind,zone,previous_zone,at) VALUES(?,?,?,?,?)',(object_id,'reported_moved',None,row['zone'],time.time()))

    def observe(self,tag,zone,frame,gps=None,observed_at=None):
        if not isinstance(tag,str) or not tag.startswith('GUIDEDOG:OBJECT:'):raise ValueError('Not a Guide Dog object tag.')
        object_id=tag.removeprefix('GUIDEDOG:OBJECT:')
        zone=self.text(zone)
        now=time.time()
        with self.lock,self.db() as db:
            setting=db.execute("SELECT value FROM settings WHERE key='zone'").fetchone()
            if not setting or setting['value']!=zone:raise ValueError('Zone changed during scan. Scan again in the selected zone.')
            row=db.execute('SELECT * FROM objects WHERE id=? AND saved=1',(object_id,)).fetchone()
            if not row:raise ValueError('Tag not registered on this robot.')
            if row['status']=='missing':
                moved=db.execute("SELECT MAX(at) FROM events WHERE object_id=? AND kind='reported_moved'",(object_id,)).fetchone()[0]
                if observed_at is not None and moved and observed_at < moved:raise ValueError('Frame predates the move. Scan again.')
                kind='rediscovered'
            elif row['zone'] and row['zone']!=zone:kind='moved'
            elif not row['last_seen']:kind='remembered'
            else:kind='seen'
            if kind=='seen' and now-row['last_seen']<10:return {'kind':'seen','object_id':object_id,'name':row['name'],'zone':zone,'changed':False}
            db.execute("UPDATE objects SET status='located',source='tag',zone=?,last_seen=?,photo=?,gps=? WHERE id=?",(zone,now,frame,json.dumps(gps) if gps else None,object_id))
            if kind!='seen':
                db.execute('INSERT INTO events(object_id,kind,zone,previous_zone,at) VALUES(?,?,?,?,?)',(object_id,kind,zone,row['zone'],now))
            return {'kind':kind,'object_id':object_id,'name':row['name'],'zone':zone,'previous_zone':row['zone'],'changed':kind!='seen'}

    def photo(self,object_id):
        with self.lock,self.db() as db:
            row=db.execute('SELECT photo FROM objects WHERE id=?',(object_id,)).fetchone()
            return row['photo'] if row else None

    @staticmethod
    def canonical(name):
        name=re.sub(r'^(?:my|the|an?|this)\s+','',name.strip(),flags=re.I).strip()
        if re.fullmatch(r'(?:monster|moster)(?: energy)?(?: can| cane| drink)?',name,re.I):return 'Monster Energy can'
        if re.fullmatch(r'(?:water|water bottle)',name,re.I):return 'Water bottle'
        return ObjectMemory.text(name)

    @staticmethod
    def icon(name):
        name=name.lower()
        return 'monster' if 'monster' in name else 'bottle' if 'water' in name else 'medicine' if any(w in name for w in ('pill','medicine','medication')) else 'object'

    def save_reported(self,name,gps=None,frame=None):
        name=self.canonical(name);now=time.time()
        usable=bool(gps and gps.get('fix') and now-gps.get('ts',0)<15)
        with self.lock,self.db() as db:
            old=db.execute('SELECT * FROM objects WHERE name=? COLLATE NOCASE',(name,)).fetchone()
            oid=old['id'] if old else uuid.uuid4().hex
            if not old:
                if db.execute('SELECT count(*) FROM objects WHERE saved=1').fetchone()[0]>=50:raise ValueError('Maximum 50 saved objects.')
                db.execute("INSERT INTO objects(id,name,saved,source) VALUES(?,?,1,'user_saved')",(oid,name))
            else:db.execute('UPDATE objects SET saved=1 WHERE id=?',(oid,))
            if usable:
                db.execute("UPDATE objects SET status='reported',source='user_saved',zone='Saved phone position',last_seen=?,gps=?,photo=? WHERE id=?",(now,json.dumps(gps),frame,oid))
                db.execute('INSERT INTO events(object_id,kind,zone,previous_zone,at) VALUES(?,?,?,?,?)',(oid,'user_saved','Saved phone position',old['zone'] if old else None,now))
            return {'reply':f"Saved {name} to your things. Its icon marks this phone GPS position (±{round(gps.get('acc') or 25)} m), reported by you." if usable else f"Added {name} to your things, but there is no fresh GPS fix. No map pin was created. Start phone GPS, then say ‘update {name} here’.",'object_memory':True,'object_id':oid,'memory_changed':True}

    def chat(self,message,gps=None,frame=None):
        if not isinstance(message,str):return None
        text=message.strip().rstrip('.!?')
        add=re.fullmatch(r'(?:please\s+)?(?:add|save)\s+(.+?)\s+(?:as\s+(?:one of\s+)?(?:my|their)\s+things|to\s+(?:my|their)\s+things)',text,re.I)
        if add:return self.save_reported(add.group(1),gps,frame)
        if re.fullmatch(r'(?:stop|pause) scanning(?: objects| tags)?',text,re.I):return {'reply':'Object tag scanner stopped.','object_memory':True,'action':'stop_scan'}
        if re.fullmatch(r'(?:start |resume )?(?:scan|scanning)(?: my)? (?:objects|things|tags)',text,re.I):return {'reply':'Scanning registered object tags. Keep the phone camera visible and point it at an attached label.','object_memory':True,'action':'start_scan'}
        zone=re.fullmatch(r'(?:set )?(?:camera )?zone (?:to )?(.+)',text,re.I)
        if zone:
            self.set_zone(zone.group(1));return {'reply':f'Camera zone set to {zone.group(1)}.','object_memory':True,'memory_changed':True}
        update=re.fullmatch(r'(?:update|remember|save) (.+?) here',text,re.I)
        if update:return self.save_reported(update.group(1),gps,frame)
        lower=text.lower()
        aliases={'monster energy can':['monster','moster','monster can','energy drink'],'water bottle':['water bottle','water'],'medicine bottle':['medicine','pills','pill bottle','medication'],'cane':['walking stick']}
        objects=self.snapshot()['objects']
        matches=[o for o in objects if any(re.search(r'\b'+re.escape(name)+r'\b',lower) for name in [o['name'].lower(),*aliases.get(o['name'].lower(),[])])]
        if not matches:return None
        if len(matches)>1:return {'reply':'Which object do you mean? Please name one at a time.','object_memory':True}
        obj=matches[0]
        if re.search(r'\b(moved|move|relocated)\b',lower):
            self.mark_moved(obj['id'])
            reply=f"Marked {obj['name']} as moved. Its old icon now marks an unconfirmed previous location. Say ‘update {obj['name']} here’ at its new position, or scan its attached tag."
        elif re.search(r'\b(scan|remember|learn)\b',lower):
            return {'reply':f"Scanning for {obj['name']}'s attached label.",'object_memory':True,'object_id':obj['id'],'action':'start_scan'}
        elif not obj['last_seen']:
            reply=f"{obj['name']} has no saved location yet. Start GPS and say ‘update {obj['name']} here’."
        elif obj['status']=='missing':
            reply=f"{obj['name']} was reported moved. Its previous location is no longer confirmed. I highlighted the old marker."
        else:
            age=max(0,int(time.time()-obj['last_seen']))
            reply=f"{obj['name']} was {'saved by you' if obj['source']=='user_saved' else 'seen by its tag'} {age} seconds ago at {obj['zone']}. I highlighted its map icon."
        return {'reply':reply,'object_memory':True,'object_id':obj['id']}
