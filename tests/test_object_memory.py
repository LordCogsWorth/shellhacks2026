import sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pi'))
from object_memory import ObjectMemory
from manual_control import manual_command

class ObjectTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'objects.sqlite3';self.store=ObjectMemory(self.path)
  self.store.add('Cane')
  self.obj=next(o for o in self.store.snapshot()['objects'] if o['name']=='Cane')
 def tearDown(self):self.temp.cleanup()
 def test_full_remember_move_rediscover_persists(self):
  self.store.set_zone('Entryway');first=self.store.observe(self.obj['tag'],'Entryway',b'first photo')
  self.assertEqual(first['kind'],'remembered');self.store.mark_moved(self.obj['id'])
  missing=next(o for o in self.store.snapshot()['objects'] if o['id']==self.obj['id'])
  self.assertEqual(missing['status'],'missing');self.assertEqual(missing['zone'],'Entryway')
  self.store.set_zone('Kitchen table');again=self.store.observe(self.obj['tag'],'Kitchen table',b'new photo')
  self.assertEqual(again['kind'],'rediscovered');self.assertEqual(again['previous_zone'],'Entryway')
  restarted=ObjectMemory(self.path);found=next(o for o in restarted.snapshot()['objects'] if o['id']==self.obj['id'])
  self.assertEqual(found['zone'],'Kitchen table');self.assertEqual(restarted.photo(self.obj['id']),b'new photo')
  self.assertEqual([e['kind'] for e in restarted.snapshot()['events']],['rediscovered','reported_moved','remembered'])
 def test_automatic_zone_change_updates_location(self):
  self.store.set_zone('Entryway');self.store.observe(self.obj['tag'],'Entryway',b'photo')
  self.store.set_zone('Living room');self.assertEqual(self.store.observe(self.obj['tag'],'Living room',b'photo')['kind'],'moved')
 def test_zone_mismatch_and_unknown_tags_rejected(self):
  self.store.set_zone('Entryway')
  with self.assertRaises(ValueError):self.store.observe(self.obj['tag'],'Kitchen',b'photo')
  with self.assertRaises(ValueError):self.store.observe('GUIDEDOG:OBJECT:fake','Entryway',b'photo')
 def test_last_seen_never_fabricated(self):
  self.assertIsNone(self.obj['last_seen']);self.assertIsNone(self.obj['zone'])
  self.assertIn("no saved location",self.store.chat('Where is my cane?')['reply'])
  with self.assertRaises(ValueError):self.store.mark_moved(self.obj['id'])
 def test_stale_frame_cannot_undo_reported_move(self):
  self.store.set_zone('Entryway');self.store.observe(self.obj['tag'],'Entryway',b'photo');before=time.time()-1
  self.store.mark_moved(self.obj['id'])
  with self.assertRaises(ValueError):self.store.observe(self.obj['tag'],'Entryway',b'old',observed_at=before)
 def test_chat_preserves_uncertainty_and_distinguishes_routes(self):
  self.store.set_zone('Entryway');self.store.observe(self.obj['tag'],'Entryway',b'photo')
  self.assertIn('Entryway',self.store.chat('Find my walking stick')['reply'])
  self.store.chat('I moved my cane')
  self.assertIn('no longer confirmed',self.store.chat('Where is my cane?')['reply'])
  self.assertIsNone(self.store.chat('Take me to the grocery store'))
 def test_repeated_frames_do_not_spam_history(self):
  self.store.set_zone('Entryway');self.store.observe(self.obj['tag'],'Entryway',b'photo')
  for _ in range(5):self.store.observe(self.obj['tag'],'Entryway',b'photo')
  self.assertEqual(len(self.store.snapshot()['events']),1)

class ManualTests(unittest.TestCase):
 def test_close_obstacle_blocks_forward_but_allows_reverse(self):
  command,error=manual_command({'lin':1},8,True);self.assertIsNone(command);self.assertIn('Forward blocked',error)
  self.assertEqual(manual_command({'lin':-1},8,True)[0],(180,40,0))
 def test_turn_and_speed_cap(self):self.assertEqual(manual_command({'ang':1},8,True)[0],(0,0,40))
 def test_invalid_numbers_and_disconnection(self):
  for msg in ({'lin':float('nan')},{'ang':float('inf')},{'lin':2}):self.assertIsNone(manual_command(msg,100,True)[0])
  self.assertIsNone(manual_command({'lin':1},100,False)[0])
 def test_forward_requires_valid_clear_reading(self):
  for dist in (None,-1,0,24):self.assertIsNone(manual_command({'lin':1},dist,True)[0])
  self.assertEqual(manual_command({'lin':1},40,True)[0],(0,40,0))
