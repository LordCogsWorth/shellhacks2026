"""Chat-configured places. Persist aliases and Google place IDs, not Google geometry."""
import asyncio
import re
import time
import uuid
import urllib.request
import json
from navigation import config, post_json, NavigationError, coordinate


def fresh(gps):
    return bool(gps and gps.get('fix') and time.time()-gps.get('ts',0)<15)

class SavedPlaces:
    def __init__(self,memory):
        self.memory=memory
        self.cache={}
        self.pending={}
        self.busy=False
        self.last_search=float('-inf')
        with memory.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS places(id TEXT PRIMARY KEY,alias TEXT UNIQUE COLLATE NOCASE,query TEXT,place_id TEXT,lat REAL,lon REAL,accuracy REAL,created_at REAL)')

    def rows(self):
        with self.memory.db() as db:return [dict(r) for r in db.execute('SELECT * FROM places ORDER BY alias')]

    def save(self,alias,query,place_id=None,gps=None,details=None):
        alias=self.memory.text(alias)
        if not place_id and not fresh(gps):raise ValueError('A fresh phone GPS fix is required to save this location.')
        with self.memory.db() as db:
            existing=db.execute('SELECT id FROM places WHERE alias=? COLLATE NOCASE',(alias,)).fetchone()
            pid=existing['id'] if existing else uuid.uuid4().hex
            db.execute('INSERT OR REPLACE INTO places(id,alias,query,place_id,lat,lon,accuracy,created_at) VALUES(?,?,?,?,?,?,?,?)',
                (pid,alias,query,place_id,None if place_id else gps['lat'],None if place_id else gps['lon'],None if place_id else gps.get('acc'),time.time()))
        if details:self.cache[place_id]=(time.monotonic(),details)
        return pid

    async def snapshot(self):
        cfg=config();out=[]
        for row in self.rows():
            place_id=row['place_id'];item={**row,'name':row['alias'],'kind':'place','source':'google' if place_id else 'user_saved','icon':'store' if any(x in row['alias'].lower() for x in ('grocery','store','shop')) else 'home' if 'home' in row['alias'].lower() else 'place'}
            if place_id:
                cached=self.cache.get(place_id)
                if not cached or time.monotonic()-cached[0]>3600:
                    if cfg.get('GOOGLE_MAPS_API_KEY'):
                        try:
                            details=await asyncio.to_thread(self.details,place_id,cfg)
                            self.cache[place_id]=(time.monotonic(),details);cached=self.cache[place_id]
                        except NavigationError:
                            self.cache[place_id]=(time.monotonic(),{'lat':None,'lon':None,'unresolved':True});cached=self.cache[place_id]
                    else:cached=None
                if cached:item.update(cached[1])
                else:item.update(lat=None,lon=None,unresolved=True)
            out.append(item)
        return out

    @staticmethod
    def parse_place(p):
        lat,lon=coordinate(p['location']['latitude'],p['location']['longitude'])
        return {'place_id':p['id'],'title':p.get('displayName',{}).get('text','Place'), 'address':p.get('formattedAddress',''), 'lat':lat,'lon':lon,'attributions':p.get('attributions',[])}

    def details(self,place_id,cfg):
        # Place IDs are opaque, so quote before putting one into a URL.
        from urllib.parse import quote
        req=urllib.request.Request('https://places.googleapis.com/v1/places/'+quote(place_id,safe=''),headers={'X-Goog-Api-Key':cfg['GOOGLE_MAPS_API_KEY'],'X-Goog-FieldMask':'id,displayName,formattedAddress,location,attributions'})
        try:
            with urllib.request.urlopen(req,timeout=12) as r:return self.parse_place(json.load(r))
        except (OSError,ValueError,KeyError):raise NavigationError('Could not refresh the saved Google place. Check API access.') from None

    async def chat(self,message,gps):
        if not isinstance(message,str):return None
        text=message.strip().rstrip('.!?')
        match=re.fullmatch(r'(?:please\s+)?(?:set|save|remember)\s+(?:the\s+)?(.+?)\s+as\s+(?:my\s+)?(.+)',text,re.I)
        if not match:return None
        query,alias=(x.strip() for x in match.groups())
        if re.fullmatch(r'(?:one of )?(?:my |their )?things',alias,re.I):return None
        self.memory.text(query,180);self.memory.text(alias)
        if query.lower() in ('here','this location','my current location','current location'):
            pid=self.save(alias,query,gps=gps)
            return {'reply':f'Saved this phone location as {alias}. Its place icon is on the map.', 'place_id':pid,'memory_changed':True}
        cfg=config()
        if not cfg.get('GOOGLE_MAPS_API_KEY'):
            return {'reply':f'I need a Google Places API key to look up {query}. No place or marker was saved. If you are physically there, say “set here as my {alias}”.'}
        if self.busy or time.monotonic()-self.last_search<3:raise ValueError('Place search is busy. Please wait a moment.')
        self.busy=True;self.last_search=time.monotonic()
        try:
            payload={'textQuery':query,'pageSize':5,'languageCode':'en'}
            if fresh(gps):payload['locationBias']={'circle':{'center':{'latitude':gps['lat'],'longitude':gps['lon']},'radius':10000}}
            result=await asyncio.to_thread(post_json,'https://places.googleapis.com/v1/places:searchText',payload,{'X-Goog-Api-Key':cfg['GOOGLE_MAPS_API_KEY'],'X-Goog-FieldMask':'places.id,places.displayName,places.formattedAddress,places.location,places.attributions'})
            choices=[]
            self.pending={k:v for k,v in self.pending.items() if time.monotonic()-v['at']<300}
            for p in result.get('places',[])[:5]:
                try:details=self.parse_place(p)
                except (KeyError,TypeError,ValueError):continue
                token=uuid.uuid4().hex
                self.pending[token]={'at':time.monotonic(),'alias':alias,'query':query,'details':details}
                choices.append({'token':token,'name':details['title'],'address':details['address'],'attributions':details['attributions']})
            if not choices:return {'reply':f'No Google Places match for {query}. Try a street address; nothing was saved.'}
            return {'reply':f'Choose the exact place to save as {alias}. No location has been saved yet.','place_choices':choices,'provider':'Google Maps'}
        finally:self.busy=False

    def confirm(self,token):
        pending=self.pending.pop(token,None)
        if not pending or time.monotonic()-pending['at']>300:raise ValueError('Place choice expired. Search again.')
        details=pending['details']
        pid=self.save(pending['alias'],pending['query'],place_id=details['place_id'],details=details)
        return {'reply':f"Saved {details['title']} as {pending['alias']}.",'place_id':pid,'memory_changed':True}

    async def destinations(self):
        return [{'id':'saved_'+p['id'],'name':p['name'],'lat':p['lat'],'lon':p['lon'],
                 'aliases':[p['query'],p['name'].removeprefix('local ')]} for p in await self.snapshot() if p.get('lat') is not None]
