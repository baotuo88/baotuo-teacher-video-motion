import base64
import io
import json
import shutil
import wave
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from PIL import Image

from app import main, media_generation as media, providers
from app.assets import get as get_asset
from app.models import ProviderInput, ProjectInput
from app.store import Store
from app.worker import execute


def image_data():
    out=io.BytesIO();Image.new('RGB',(320,200),'#66aa99').save(out,format='PNG');return out.getvalue()


def audio_data():
    out=io.BytesIO()
    with wave.open(out,'wb') as f:
        f.setparams((1,2,24000,0,'NONE','not compressed'));f.writeframes(b'\0\0'*48000)
    return out.getvalue()


@pytest.fixture
def db(tmp_path,monkeypatch):
    monkeypatch.setenv('PROVIDER_ENCRYPTION_KEY',Fernet.generate_key().decode())
    return Store(tmp_path)


def provider(db,kind):
    return providers.save(db,ProviderInput(name=kind,capability=kind,base_url='https://generation.example/v1',
        model=kind+'-model',api_key='secret-value',voice='demo-voice',speed=1.2))


def project(db):
    p=db.create(ProjectInput(title='test',scenes=[{'title':'Scene','narration':'Hello world','points':['Point']}]).model_dump())
    return db.confirm(p['id'],p['version'])


def task(db,kind):
    p=project(db);c=provider(db,kind)
    j=db.enqueue(p['id'],p['version'],kind,{'provider_id':c['id'],'provider_version':c['updated'],
        'scene_index':0,'prompt':'A diagram'},'runtime-placeholder','generation-key-'+kind)
    return db.claim()


def test_capabilities_and_credential_reuse(db):
    original=provider(db,'storyboard')
    new=providers.save(db,ProviderInput(name='Images',capability='image',base_url=original['base_url'],
        model='image',credential_source_id=original['id']))
    assert new['capability']=='image' and new['has_key']
    assert 'secret-value' not in json.dumps(new)
    with pytest.raises(providers.ProviderError):
        providers.save(db,ProviderInput(name='bad',capability='image',base_url='https://other.example/v1',
            model='image',credential_source_id=original['id']))


def test_image_job_creates_asset_without_overwriting(db,monkeypatch):
    job=task(db,'image');seen=[]
    def response(base,key=None,**kw):
        seen.append(kw);return json.dumps({'data':[{'b64_json':base64.b64encode(image_data()).decode()}]}).encode()
    monkeypatch.setattr(media,'fetch_bytes',response)
    execute(db,job,db.root/'runtimes')
    done=db.job(job['id']);assert done['status']=='succeeded'
    a=get_asset(db,done['result']['asset']['id'])
    assert a['kind']=='image' and a['generation']['job_id']==job['id']
    assert not db.project(job['project_id'])['scenes'][0]['image_id']
    assert seen[0]['suffix']=='/images/generations' and seen[0]['payload']['n']==1
    assert 'secret-value' not in json.dumps(done)


def test_speech_job_normalizes_real_audio(db,monkeypatch):
    if not shutil.which('ffmpeg'):pytest.skip('ffmpeg required')
    job=task(db,'speech');seen=[]
    def response(base,key=None,**kw):seen.append(kw);return audio_data()
    monkeypatch.setattr(media,'fetch_bytes',response)
    execute(db,job,db.root/'runtimes')
    done=db.job(job['id']);assert done['status']=='succeeded',done
    assert done['result']['asset']['duration']==2
    assert seen[0]['payload']['voice']=='demo-voice' and seen[0]['payload']['speed']==1.2
    assert seen[0]['suffix']=='/audio/speech'


def test_generation_unknown_outcome_never_retried(db,monkeypatch):
    job=task(db,'image');calls=[]
    def fail(*args,**kw):calls.append(1);raise media.UnknownOutcome('结果待确认')
    monkeypatch.setattr(media,'fetch_bytes',fail)
    execute(db,job,db.root/'runtimes')
    assert db.job(job['id'])['status']=='unknown_outcome' and len(calls)==1
    assert db.claim() is None


def test_cancelled_job_does_not_call_provider(db,monkeypatch):
    job=task(db,'image');db.cancel(job['id'])
    monkeypatch.setattr(media,'fetch_bytes',lambda *a,**k:pytest.fail('must not call provider'))
    execute(db,job,db.root/'runtimes');assert db.job(job['id'])['status']=='cancelled'


def test_image_download_receives_no_credential(db,monkeypatch):
    calls=[]
    def response(url,key=None,**kwargs):
        calls.append((url,key,kwargs))
        return json.dumps({'data':[{'url':'https://cdn.example/image?signature=x'}]}).encode() if len(calls)==1 else image_data()
    monkeypatch.setattr(media,'fetch_bytes',response)
    result=media.image_bytes({'base_url':'https://generation.example/v1','model':'x'},'secret-value','prompt')
    assert result==image_data()
    assert calls[1][1] is None and calls[1][2]=={'download':True}


@pytest.mark.parametrize('url',['http://example.com/x','https://127.0.0.1/x','https://u:p@example.com/x',
                               'https://example.com/x#fragment','https://example.com/\nx'])
def test_unsafe_image_download_refused(url):
    with pytest.raises(providers.ProviderError):media.fetch_bytes(url,download=True)


def test_transport_no_redirect_or_secret_leak(monkeypatch):
    calls=[]
    class Connection:
        def __init__(self,*a,**kw):pass
        def request(self,*a,**kw):calls.append(kw)
        def getresponse(self):return type('R',(),{'status':302})()
        def close(self):pass
    monkeypatch.setattr(providers,'PinnedHTTPS',Connection)
    monkeypatch.setattr(providers,'public_addresses',lambda h:['8.8.8.8'])
    with pytest.raises(providers.ProviderError,match='302'):
        media.fetch_bytes('https://cdn.example/image?sig=x',download=True)
    assert 'Authorization' not in calls[0]['headers'] and len(calls)==1


def test_timeout_marked_uncertain(monkeypatch):
    class Connection:
        def __init__(self,*a,**kw):pass
        def request(self,*a,**kw):raise TimeoutError()
        def close(self):pass
    monkeypatch.setattr(providers,'PinnedHTTPS',Connection)
    monkeypatch.setattr(providers,'public_addresses',lambda h:['8.8.8.8'])
    with pytest.raises(media.UnknownOutcome):media.fetch_bytes('https://api.example/v1','secret-value',payload={})


def test_generation_api_confirmation_apply_and_stale_version(db,monkeypatch):
    monkeypatch.setattr(main,'DATA',db.root)
    monkeypatch.setattr(main,'active_runtime',lambda:'test-runtime')
    monkeypatch.setenv('ADMIN_PASSWORD','long-media-test-password')
    client=TestClient(main.app);auth=('admin','long-media-test-password')
    p=project(db);c=provider(db,'image')
    body={'version':p['version'],'provider_id':c['id'],'scene_index':0,'confirm_cost':False,'idempotency_key':'media-api-test-key'}
    endpoint='/api/projects/'+p['id']+'/generate-media'
    assert client.post(endpoint,json=body,auth=auth).status_code==400
    body['confirm_cost']=True
    submitted=client.post(endpoint,json=body,auth=auth);assert submitted.status_code==200,submitted.text
    monkeypatch.setattr(media,'fetch_bytes',lambda *a,**kw:json.dumps({'data':[{'b64_json':base64.b64encode(image_data()).decode()}]}).encode())
    job=db.claim();execute(db,job,db.root)
    endpoint='/api/jobs/'+job['id']+'/apply'
    applied=client.post(endpoint,json={'version':1},auth=auth)
    assert applied.status_code==200 and applied.json()['scenes'][0]['image_id']
    assert not applied.json()['confirmed']
    assert client.post(endpoint,json={'version':1},auth=auth).status_code==409


def test_wrong_capability_and_modified_config_refused(db):
    job=task(db,'image')
    with pytest.raises(providers.ProviderError,match='能力'):
        providers.resolve(db,job['snapshot']['options'],'speech')
    row=db.provider(job['snapshot']['options']['provider_id'])
    db.save_provider(row['id'],json.loads(row['config']),row['secret'])
    with pytest.raises(providers.ProviderError,match='已更新'):
        providers.resolve(db,job['snapshot']['options'],'image')
