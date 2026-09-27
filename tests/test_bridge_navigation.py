import asyncio
import json
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pi'))
import httpx
import bridge
from fastapi import WebSocketDisconnect
from object_memory import ObjectMemory
from navigation import Navigator

class FakeSocket:
    def __init__(self,message):self.message=message;self.replies=[]
    async def accept(self):pass
    async def receive_text(self):
        if self.message is None:raise WebSocketDisconnect()
        message=self.message;self.message=None;return json.dumps(message)
    async def send_json(self,message):self.replies.append(message)

class BridgeNavigationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();bridge.object_store=ObjectMemory(Path(self.temp.name)/"objects.sqlite3");bridge.manual_owner=None
        bridge.navigator=Navigator();bridge.arduino=Mock();bridge.arduino.connected=True
        bridge.state.update(mode='idle',gps=None,dist=100)
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=bridge.app),base_url='http://test')
    async def asyncTearDown(self):
        await self.client.aclose();self.temp.cleanup()
    async def test_no_presets_chat_error_stops_robot(self):
        bridge.state['mode']='manual'
        with patch('navigation.presets',return_value=[]):
            result=await self.client.post('/chat',json={'message':'grocery store'})
        self.assertEqual(result.status_code,409);self.assertEqual(bridge.state['mode'],'idle')
        bridge.arduino.stop.assert_called();bridge.arduino.move.assert_not_called()
    async def test_raw_route_cannot_start_motors(self):
        socket=FakeSocket({'type':'route','points':[[25,-80],[25.1,-80]]})
        await bridge.ws_endpoint(socket)
        self.assertEqual(bridge.state['mode'],'idle');self.assertEqual(socket.replies[0]['type'],'error')
        bridge.arduino.move.assert_not_called()
    async def test_drive_requires_manual_session(self):
        bridge.navigator.hold=True
        await bridge.ws_endpoint(FakeSocket({'type':'drive','lin':1,'ang':0,'strafe':0}))
        self.assertEqual(bridge.state['mode'],'idle');bridge.arduino.move.assert_not_called()
    async def test_review_cannot_override_close_obstacle(self):
        bridge.navigator.hold=True;bridge.state['dist']=8
        response=await self.client.post('/navigation/acknowledge')
        self.assertEqual(response.status_code,409);self.assertTrue(bridge.navigator.hold)
    async def test_secrets_not_exposed(self):
        with patch.object(bridge,'navigation_config',return_value={'OPENAI_API_KEY':'secret-A','GOOGLE_MAPS_API_KEY':'secret-B','GOOGLE_MAPS_BROWSER_KEY':'public-C'}):
            response=await self.client.get('/navigation')
        self.assertNotIn('secret-A',response.text);self.assertNotIn('secret-B',response.text)
        self.assertIn('public-C',response.text)
    async def test_stale_camera_detections_ignored(self):
        bridge.frames.updated=float('-inf')
        await bridge.ws_endpoint(FakeSocket({'type':'detections','labels':['stop sign']}))
        self.assertFalse(bridge.navigator.hazards)

if __name__=='__main__':unittest.main()
