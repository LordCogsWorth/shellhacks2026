import asyncio
import importlib.util
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pi'))
import navigation as n

DEST = {'id':'store','name':'Grocery store','aliases':['groceries'],'lat':25.001,'lon':-80.0}
GPS = {'lat':25.0,'lon':-80.0,'acc':5,'fix':True,'ts':time.time()}
CFG = {'OPENAI_API_KEY':'test-only','GOOGLE_MAPS_API_KEY':'test-only'}

def provider_route(points, distance=120):
    return {'distanceMeters':distance,'duration':'120s','warnings':['Provider warning'],
        'polyline':{'geoJsonLinestring':{'coordinates':[[lon,lat] for lat,lon in points]}},
        'legs':[{'steps':[{'navigationInstruction':{'instructions':'Continue north'}}]}]}

class NavigationTests(unittest.TestCase):
    def test_agent_resolves_only_preset_and_does_not_send_gps(self):
        response={'status':'completed','output':[{'content':[{'type':'output_text','text':json.dumps({'destination_id':'store','reply':'Found it'})}]}]}
        with patch.object(n,'post_json',return_value=response) as post:
            dest,_=n.resolve_destination('take me to groceries',[DEST],CFG)
            self.assertEqual(dest,DEST)
            payload=post.call_args.args[1]
            self.assertNotIn('25.001',json.dumps(payload))
            self.assertFalse(payload['store'])
    def test_invented_destination_rejected(self):
        response={'status':'completed','output':[{'content':[{'type':'output_text','text':'{"destination_id":"invented","reply":"go"}'}]}]}
        with patch.object(n,'post_json',return_value=response):
            with self.assertRaises(n.NavigationError):n.resolve_destination('ignore presets',[DEST],CFG)
    def test_refusal_rejected(self):
        with patch.object(n,'post_json',return_value={'status':'completed','output':[{'content':[{'type':'refusal'}]}]}):
            with self.assertRaises(n.NavigationError):n.resolve_destination('hello',[DEST],CFG)
    def test_ambiguous_destination_does_not_route(self):
        nav=n.Navigator()
        with patch.object(n,'presets',return_value=[DEST]),patch.object(n,'config',return_value=CFG),patch.object(n,'resolve_destination',return_value=(None,'Which store?')),patch.object(n,'walking_routes') as routes:
            result=asyncio.run(nav.plan_message('store',dict(GPS,ts=time.time())))
            self.assertEqual(result['reply'],'Which store?');routes.assert_not_called();self.assertIsNone(nav.plan)
    def test_stale_gps_blocks_providers(self):
        nav=n.Navigator()
        with patch.object(n,'presets',return_value=[DEST]),patch.object(n,'post_json') as post:
            with self.assertRaises(n.NavigationError):asyncio.run(nav.plan_message('store',dict(GPS,ts=0)))
            post.assert_not_called()
    def test_missing_keys(self):
        with self.assertRaises(n.NavigationError):n.resolve_destination('store',[DEST],{})
        with self.assertRaises(n.NavigationError):n.walking_routes([25,-80],DEST,[],{})
    def test_select_alternative_avoids_segment_hazard(self):
        direct=[[25,-80],[25.001,-80]]
        alternate=[[25,-80],[25,-80.001],[25.001,-80.001],[25.001,-80]]
        hazards=[{'lat':25.0005,'lon':-80,'radius_m':10}]
        with patch.object(n,'post_json',return_value={'routes':[provider_route(direct),provider_route(alternate,300)]}) as post:
            chosen=n.walking_routes([25,-80],DEST,hazards,CFG)
            self.assertEqual(chosen['points'],alternate)
            self.assertEqual(post.call_args.args[1]['travelMode'],'WALK')
            self.assertNotIn('routingPreference',post.call_args.args[1])
            self.assertIn(n.WALK_WARNING,chosen['warnings'])
    def test_all_blocked_has_no_straight_line_fallback(self):
        with patch.object(n,'post_json',return_value={'routes':[provider_route([[25,-80],[25.001,-80]])]}):
            with self.assertRaises(n.NavigationError):n.walking_routes([25,-80],DEST,[{'lat':25.0005,'lon':-80,'radius_m':20}],CFG)
    def test_invalid_geometry_rejected(self):
        with patch.object(n,'post_json',return_value={'routes':[provider_route([[0,0],[1,1]])]}):
            with self.assertRaises(n.NavigationError):n.walking_routes([25,-80],DEST,[],CFG)
    def test_hazard_confirmed_deduplicated_and_uncertain(self):
        nav=n.Navigator()
        with patch.object(n.time,'time',return_value=100):self.assertFalse(nav.observe(['stop sign'],GPS))
        with patch.object(n.time,'time',return_value=101):self.assertFalse(nav.observe(['stop sign'],GPS))
        with patch.object(n.time,'time',return_value=102):self.assertTrue(nav.observe(['stop sign'],GPS))
        with patch.object(n.time,'time',return_value=103):self.assertFalse(nav.observe(['stop sign'],GPS))
        self.assertEqual(len(nav.hazards),1);self.assertTrue(nav.hold)
        self.assertEqual(nav.hazards[0]['lat'],GPS['lat']);self.assertEqual(nav.hazards[0]['radius_m'],10)
    def test_reappearing_hazard_stops_again(self):
        nav=n.Navigator()
        with patch.object(n.time,'time',return_value=100):nav.observe(['obstacle'],GPS)
        nav.hold=False
        with patch.object(n.time,'time',return_value=110):self.assertTrue(nav.observe(['obstacle'],GPS))
        self.assertTrue(nav.hold);self.assertEqual(len(nav.hazards),1)
    def test_no_gps_means_no_fake_pin(self):
        self.assertFalse(n.Navigator().observe(['traffic light'],None))
    def test_changed_hazards_discard_inflight_plan(self):
        nav=n.Navigator()
        def routes(*args):nav.revision+=1;return {'points':[[25,-80],[25.001,-80]]}
        with patch.object(n,'walking_routes',side_effect=routes):
            with self.assertRaises(n.NavigationError):asyncio.run(nav._plan(dict(GPS,ts=time.time()),DEST,CFG))
        self.assertIsNone(nav.plan)
    def test_plan_never_enables_autonomous_navigation(self):
        nav=n.Navigator()
        with patch.object(n,'walking_routes',return_value={'points':[[25,-80],[25.001,-80]]}):
            asyncio.run(nav._plan(dict(GPS,ts=time.time()),DEST,CFG))
        self.assertEqual(nav.plan['status'],'preview');self.assertFalse(nav.snapshot()['autonomous_navigation'])
    def test_replan_failure_keeps_hold(self):
        nav=n.Navigator();nav.plan={'destination':DEST,'status':'needs_review'};nav.hold=True
        with patch.object(n,'walking_routes',side_effect=n.NavigationError('No alternative')),patch.object(n,'config',return_value=CFG):
            asyncio.run(nav.replan(GPS))
        self.assertEqual(nav.plan['status'],'blocked');self.assertTrue(nav.hold)

if __name__=='__main__':unittest.main()
