"""Isolated acceptance: mocked providers, real API/store/worker/assets/MP4 render.

No real external service calls or paid API keys. Creates an isolated workspace
under .data/e2e; uses the already verified local runtime without modifying it.
"""
import base64
import io
import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from app import main, media_generation, providers
from app.store import Store
from app.worker import execute

os.environ['ADMIN_PASSWORD'] = 'isolated-generation-acceptance-password'
os.environ['PROVIDER_ENCRYPTION_KEY'] = Fernet.generate_key().decode()
runtimes = ROOT / '.data/runtimes'
rid = json.loads((runtimes / 'active.json').read_text())['runtime_id']
workspace = ROOT / '.data/e2e' / ('generation-' + uuid.uuid4().hex[:8])
store = Store(workspace)
main.DATA, main.ROOT = workspace, runtimes
client = TestClient(main.app)
auth = ('admin', os.environ['ADMIN_PASSWORD'])


def post(url, body):
    response = client.post(url, json=body, auth=auth)
    if response.status_code != 200:
        raise RuntimeError(f'{url}: {response.status_code} {response.text}')
    return response.json()


configs = {}
for kind in ('storyboard', 'image', 'speech'):
    configs[kind] = post('/api/providers', {'name':'Mock '+kind,'capability':kind,
        'base_url':'https://mock.example/v1','api_key':'synthetic-not-a-real-key','model':kind+'-model'})
project = post('/api/projects', {'title':'AI生成链路验收（模拟服务）','topic':'图片和配音分别生成，再渲染成片'})
text_job = post('/api/projects/'+project['id']+'/storyboard', {'version':1,'provider_id':configs['storyboard']['id'],
    'confirm_cost':True,'idempotency_key':uuid.uuid4().hex})
text_response = {'choices':[{'message':{'content':json.dumps({'scenes':[{'title':'生成素材，再完成讲解',
    'narration':'这段演示用于验证图片和语音生成链路。','points':['模型生成图片','音频规范化入库','人工确认后渲染'],
    'layout':'points','duration':3}]},ensure_ascii=False)}}]}
with patch.object(providers,'post_json',return_value=text_response):
    execute(store,store.claim(),runtimes)
assert store.job(text_job['id'])['status']=='succeeded'
project=store.project(project['id'])
assert store.job(text_job['id'])['result']['application']['status']=='applied'

image=Image.new('RGB',(900,600),'#edf5f0');draw=ImageDraw.Draw(image)
for i in range(3):
    x=100+i*260;draw.rounded_rectangle((x,170,x+190,380),radius=20,fill=['#508d77','#cdaf6e','#7393ac'][i])
    draw.text((x+45,250),str(i+1),fill='white',font_size=54)
out=io.BytesIO();image.save(out,format='PNG');picture=out.getvalue()
# Synthetic audible WAV test tone, explicitly not real human narration.
import math, struct, wave
out=io.BytesIO()
with wave.open(out,'wb') as f:
    f.setparams((1,2,24000,0,'NONE','not compressed'))
    f.writeframes(b''.join(struct.pack('<h',int(1200*math.sin(2*math.pi*440*n/24000))) for n in range(72000)))
audio=out.getvalue()

project=post('/api/projects/'+project['id']+'/confirm',{'version':project['version']})
for kind in ('image','speech'):
    assert project['confirmed'], 'Media auto-apply must preserve confirmation'
    job=post('/api/projects/'+project['id']+'/generate-media',{'version':project['version'],
        'provider_id':configs[kind]['id'],'scene_index':0,'prompt':'A simple diagram',
        'confirm_cost':True,'idempotency_key':uuid.uuid4().hex})
    content=json.dumps({'data':[{'b64_json':base64.b64encode(picture).decode()}]}).encode() if kind=='image' else audio
    with patch.object(media_generation,'fetch_bytes',return_value=content):
        execute(store,store.claim(),runtimes)
    finished=store.job(job['id'])
    assert finished['status']=='succeeded', finished['error']
    project=store.project(project['id'])
    assert finished['result']['application']['status']=='applied'
    assert project['confirmed']

project=post('/api/projects/'+project['id']+'/confirm',{'version':project['version']})
job=post('/api/projects/'+project['id']+'/render',{'version':project['version'],'audio':'uploaded',
    'fps':12,'idempotency_key':uuid.uuid4().hex})
execute(store,store.claim(),runtimes)
finished=store.job(job['id'])
assert finished['status']=='succeeded', finished['error']
report={'workspace':str(workspace),'job':job['id'],'runtime':rid,'mocked_providers':True,
        'actual_render':True,'artifacts':finished['result']['artifacts']}
(ROOT/'.data/e2e/generation-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
