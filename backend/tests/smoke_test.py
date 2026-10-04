"""Local-demo integration checks. Run with API listening on 127.0.0.1:8000.
Uses seeded demo accounts. Adds login audit records; does not change inventory.
"""
import asyncio
import json
import urllib.error
import urllib.request
from pathlib import Path
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

BASE = 'http://127.0.0.1:8000/api/v1'
checks = []

def call(path, token=None, data=None, expected=200):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(BASE + path, headers=headers,
          data=json.dumps(data).encode() if data is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            status, body = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read().decode()
    ok = status == expected
    checks.append({'path': path.split('?')[0], 'expected': expected, 'actual': status, 'pass': ok})
    print(('PASS' if ok else 'FAIL'), path.split('?')[0], status)
    assert ok, body[:200]
    try: return json.loads(body)
    except ValueError: return body

async def sockets(token):
    async with connect('ws://127.0.0.1:8000/api/v1/ws/telemetry?token='+token) as ws:
        msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
        assert msg['type'] == 'snapshot'
        msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
        assert msg['type'] == 'frame'
        checks.append({'path':'websocket authenticated snapshot + frame','pass':True})
    try:
        async with connect('ws://127.0.0.1:8000/api/v1/ws/telemetry'):
            raise AssertionError('Unauthenticated websocket accepted')
    except InvalidStatus as e:
        assert e.response.status_code == 403
        checks.append({'path':'websocket unauthenticated rejected','pass':True})
    print('PASS WebSocket authenticated frames and unauthenticated rejection')

if __name__ == '__main__':
    call('/health')
    call('/kpis', expected=401)
    call('/auth/login',data={'username':'commander','password':''},expected=401)
    call('/auth/login',data={'username':'commander','password':'wrong'},expected=401)
    tokens = {u:call('/auth/login',data={'username':u,'password':u})['token']
              for u in ['commander','logistics','quartermaster','admin']}
    t=tokens['commander']
    for path in ['/auth/me','/auth/roles','/meta','/theatre','/kpis','/alerts','/convoys',
                 '/inventory','/inventory?node=DP-A','/sensors','/forecast/series',
                 '/forecast/leaderboard','/scenarios','/simulations','/admin/audit']:
        call(path,t)
    for token in ['bad','a.b.c','a.b.a',t+'x']:
        call('/auth/me', token, expected=401)
    call('/auth/me?token='+t, expected=401)
    call('/admin/users', t, expected=403)
    call('/admin/users', tokens['admin'])
    call('/admin/retrain',t,{},expected=403)
    call('/simulate',tokens['quartermaster'],{},expected=403)
    call('/alerts/1/ack',t,{},expected=403)
    call('/forecast?horizon=0',t,expected=422)
    call('/simulations/999999',t,expected=404)
    hist=call('/simulations',t)
    if hist['items']:
        sid=hist['items'][0]['id']
        call(f'/simulations/{sid}',t)
        call(f'/simulations/{sid}/briefing',t)
    asyncio.run(sockets(t))
    out=Path(__file__).resolve().parents[2]/'docs/verification/api-results.json'
    out.write_text(json.dumps({'checks':checks,'passed':len(checks)},indent=2))
    print(f'{len(checks)} checks passed; {out}')
