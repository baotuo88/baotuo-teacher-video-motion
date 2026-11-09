import json
import socket

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import main, providers
from app.models import ModelDiscoveryInput, ProviderInput
from app.store import Store


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv('PROVIDER_ENCRYPTION_KEY', Fernet.generate_key().decode())
    return Store(tmp_path)


def payload(**kwargs):
    return ModelDiscoveryInput(base_url='https://models.example/v1', **kwargs)


def saved(db):
    return providers.save(db, ProviderInput(name='Demo', base_url='https://models.example/v1',
                                            model='manual-model', api_key='test-secret-key'))


def fake_transport(monkeypatch, data, status=200):
    captured = []
    class Response:
        def __init__(self): self.status = status
        def read(self, size):
            encoded = data if isinstance(data, bytes) else json.dumps(data).encode()
            return encoded[:size]
    class Connection:
        def __init__(self, host, address, timeout=90):
            captured.append({'host': host, 'address': address, 'timeout': timeout, 'closed':False})
        def request(self, method, path, body=None, headers=None):
            captured[-1].update(method=method, path=path, body=body, headers=headers)
        def getresponse(self): return Response()
        def close(self): captured[-1]['closed'] = True
    monkeypatch.setattr(providers, 'public_addresses', lambda host: ['8.8.8.8'])
    monkeypatch.setattr(providers, 'PinnedHTTPS', Connection)
    return captured


def test_draft_discovery_no_save_get_only(db, monkeypatch):
    captured = fake_transport(monkeypatch, {'data':[{'id':'z-model'},{'id':'a-model'},{'id':'a-model'},
        {'id':' bad '},{'id':'test-secret-key'},None,{'name':'wrong'}]})
    result = providers.discover_models(db, payload(api_key='test-secret-key'))
    assert result['models'] == [{'id':'a-model'},{'id':'z-model'}]
    assert result['skipped'] == 4
    assert db.provider_rows() == []
    request = captured[0]
    assert request['method'] == 'GET' and request['path'] == '/v1/models' and request['body'] is None
    assert request['timeout'] == 20 and request['closed']
    assert request['headers']['Authorization'] == 'Bearer test-secret-key'
    assert 'test-secret-key' not in json.dumps(result)


def test_stored_key_and_no_config_mutation(db, monkeypatch):
    item = saved(db); before = db.provider(item['id'])
    captured = fake_transport(monkeypatch, {'data':[]})
    assert providers.discover_models(db,payload(provider_id=item['id']))['models'] == []
    assert db.provider(item['id']) == before
    assert captured[0]['headers']['Authorization'] == 'Bearer test-secret-key'


@pytest.mark.parametrize('address',['https://another.example/v1','https://models.example/other'])
def test_changed_endpoint_cannot_reuse_stored_key(db, monkeypatch, address):
    item = saved(db)
    captured = fake_transport(monkeypatch, {'data':[]})
    with pytest.raises(providers.ProviderError,match='地址已变化'):
        providers.discover_models(db, ModelDiscoveryInput(base_url=address,provider_id=item['id']))
    assert captured == []
    with pytest.raises(providers.ProviderError,match='重新填写'):
        providers.save(db,ProviderInput(name='changed',base_url=address,model='x'),item['id'])


def test_explicit_replacement_key_can_use_new_address(db, monkeypatch):
    item = saved(db)
    captured = fake_transport(monkeypatch, {'data':[{'id':'x'}]})
    result = providers.discover_models(db,ModelDiscoveryInput(base_url='https://other.example/v1',
              provider_id=item['id'],api_key='new-secret'))
    assert result['models'] == [{'id':'x'}]
    assert captured[0]['headers']['Authorization'] == 'Bearer new-secret'
    assert db.provider(item['id'])['config'] == json.dumps({'name':'Demo','base_url':'https://models.example/v1','model':'manual-model','enabled':True},ensure_ascii=False)


@pytest.mark.parametrize('status', [301,401,403,404,405,429,500])
def test_remote_error_is_sanitized_and_not_retried(db, monkeypatch, status):
    captured = fake_transport(monkeypatch, b'test-secret-key remote-body', status)
    with pytest.raises(providers.ProviderError) as error:
        providers.discover_models(db,payload(api_key='test-secret-key'))
    assert str(status) in str(error.value)
    assert 'test-secret-key' not in str(error.value) and 'remote-body' not in str(error.value)
    assert len(captured) == 1 and captured[0]['closed']


@pytest.mark.parametrize('data',[b'not-json',{'models':['x']},[],{'data':'wrong'},b'x'*(2*1024*1024+1)])
def test_malformed_or_large_responses(db, monkeypatch, data):
    fake_transport(monkeypatch,data)
    with pytest.raises(providers.ProviderError):
        providers.discover_models(db,payload(api_key='test-secret-key'))


def test_private_dns_is_blocked_before_connection(db, monkeypatch):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,1,6,'',('127.0.0.1',443))])
    with pytest.raises(providers.ProviderError,match='非公网'):
        providers.discover_models(db,payload(api_key='test-secret-key'))


def test_bad_encryption_key_fails_safely(db, monkeypatch):
    item=saved(db)
    monkeypatch.setenv('PROVIDER_ENCRYPTION_KEY',Fernet.generate_key().decode())
    with pytest.raises(providers.ProviderError,match='无法解密'):
        providers.discover_models(db,payload(provider_id=item['id']))


def test_discovery_requires_auth_and_csrf(db, monkeypatch):
    monkeypatch.setattr(main,'DATA',db.root)
    monkeypatch.setenv('ADMIN_PASSWORD','model-discovery-test-password')
    fake_transport(monkeypatch,{'data':[{'id':'chosen-model'}]})
    client=TestClient(main.app)
    path='/api/providers/models/discover'
    body={'base_url':'https://models.example/v1','api_key':'test-secret-key'}
    assert client.post(path,json=body).status_code == 401
    login=client.post('/api/auth/login',json={'password':'model-discovery-test-password'})
    assert client.post(path,json=body).status_code == 403
    response=client.post(path,json=body,headers={'X-CSRF-Token':login.json()['csrf']})
    assert response.status_code == 200 and response.json()['models'] == [{'id':'chosen-model'}]
    assert 'test-secret-key' not in response.text


@pytest.mark.parametrize('status', [500, 502, 503])
def test_paid_chat_server_error_is_unknown_outcome(monkeypatch, status):
    fake_transport(monkeypatch, b'not logged', status=status)
    with pytest.raises(providers.UnknownOutcome, match='结果待确认'):
        providers.post_json({'base_url': 'https://models.example/v1'}, 'secret', '/chat/completions', {})


def test_paid_chat_timeout_is_unknown_but_discovery_is_not(monkeypatch):
    fake_transport(monkeypatch, {})
    class TimeoutConnection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): raise TimeoutError('secret must not be logged')
        def close(self): pass
    monkeypatch.setattr(providers, 'PinnedHTTPS', TimeoutConnection)
    with pytest.raises(providers.UnknownOutcome) as error:
        providers.post_json({'base_url': 'https://models.example/v1'}, 'secret', '/chat/completions', {})
    assert 'secret' not in str(error.value)
    with pytest.raises(providers.ProviderError) as error:
        providers.request_json({'base_url': 'https://models.example/v1'}, 'secret', '/models', method='GET')
    assert not isinstance(error.value, providers.UnknownOutcome)
