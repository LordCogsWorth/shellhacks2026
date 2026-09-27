import tempfile,time,unittest,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pi'))
from object_memory import ObjectMemory
from saved_places import SavedPlaces
class SavedMapTests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'memory.db';self.memory=ObjectMemory(self.path);self.places=SavedPlaces(self.memory);self.gps={'fix':True,'ts':time.time(),'lat':25.7,'lon':-80.3,'acc':9}
 def tearDown(self):self.tmp.cleanup()
 async def test_chat_created_icons_persist_and_move(self):
  self.assertEqual(self.memory.snapshot()['objects'],[])
  r=self.memory.chat('add moster as one of my things',self.gps)
  self.memory.chat('add water bottle to my things',self.gps)
  objects=ObjectMemory(self.path).snapshot()['objects']
  self.assertEqual({o['icon'] for o in objects},{'monster','bottle'})
  self.assertEqual(objects[0]['source'],'user_saved')
  self.memory.chat('I moved my monster')
  self.assertEqual(self.memory.snapshot()['objects'][0]['status'],'missing')
  self.memory.set_zone('Kitchen')
  self.memory.observe('GUIDEDOG:OBJECT:'+r['object_id'],'Kitchen',b'photo',self.gps)
  self.assertEqual(self.memory.snapshot()['objects'][0]['source'],'tag')
 async def test_no_fake_position_without_gps(self):
  self.memory.chat('add monster to my things',dict(self.gps,ts=0))
  self.assertIsNone(self.memory.snapshot()['objects'][0]['gps'])
 async def test_object_command_not_intercepted(self):
  self.assertIsNone(await self.places.chat('save monster as one of my things',self.gps))
 async def test_here_and_missing_key(self):
  with patch('saved_places.config',return_value={}):
   result=await self.places.chat('set the FIU publix as my local grocery store',self.gps)
   self.assertIn('No place or marker',result['reply']);self.assertEqual(self.places.rows(),[])
   await self.places.chat('set here as my home',self.gps)
   result=await SavedPlaces(self.memory).snapshot();self.assertEqual(result[0]['lat'],25.7)
 async def test_google_requires_confirmation_persists_id_only(self):
  result={'places':[{'id':'abc','displayName':{'text':'Publix'},'location':{'latitude':25.7,'longitude':-80.3}}]}
  with patch('saved_places.config',return_value={'GOOGLE_MAPS_API_KEY':'test'}),patch('saved_places.post_json',return_value=result):
   reply=await self.places.chat('set the FIU publix as my local grocery store',self.gps)
   self.assertEqual(self.places.rows(),[])
   token=reply['place_choices'][0]['token'];self.places.confirm(token)
   row=self.places.rows()[0];self.assertEqual(row['place_id'],'abc');self.assertIsNone(row['lat'])
   self.assertEqual((await self.places.destinations())[0]['name'],'local grocery store')
   with self.assertRaises(ValueError):self.places.confirm(token)
