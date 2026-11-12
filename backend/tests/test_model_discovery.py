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


@pytest.mark.parametrize('failure,code', [
    (TimeoutError('private-detail'), 'MODEL_TIMEOUT'),
    (__import__('ssl').SSLCertVerificationError('private-detail'), 'MODEL_TLS_CERT'),
    (ConnectionRefusedError('private-detail'), 'MODEL_CONNECT'),
])
def test_discovery_transport_errors_are_actionable(monkeypatch, failure, code):
    fake_transport(monkeypatch, {})
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): raise failure
        def close(self): pass
    monkeypatch.setattr(providers, 'PinnedHTTPS', Connection)
    with pytest.raises(providers.ProviderError) as error:
        providers.request_json({'base_url':'https://models.example/v1'}, 'secret', '/models', method='GET')
    assert code in str(error.value)
    assert 'private-detail' not in str(error.value)
    assert 'secret' not in str(error.value)


@pytest.mark.parametrize('content,code', [
    (b'<html>private-detail secret</html>', 'MODEL_HTML'),
    (b'', 'MODEL_EMPTY'),
    (b'not-json private-detail secret', 'MODEL_JSON'),
])
def test_discovery_invalid_content_identifies_cause(monkeypatch, content, code):
    fake_transport(monkeypatch, content)
    with pytest.raises(providers.ProviderError) as error:
        providers.request_json({'base_url':'https://models.example/v1'}, 'secret', '/models', method='GET')
    assert code in str(error.value)
    assert 'private-detail' not in str(error.value)
    assert 'secret' not in str(error.value)


def test_pinned_connection_falls_back_before_http_request(monkeypatch):
    calls = []
    class Socket:
        def settimeout(self, timeout): pass
        def close(self): pass
    sock = Socket()
    def connect(address, timeout):
        calls.append(address)
        if len(calls) == 1:
            raise TimeoutError()
        return sock
    class TLS:
        def wrap_socket(self, value, server_hostname):
            assert value is sock and server_hostname == 'models.example'
            return value
    monkeypatch.setattr(providers.socket, 'create_connection', connect)
    connection = providers.PinnedHTTPS('models.example', '104.21.25.215', timeout=20)
    connection.fallback_addresses = ['172.67.134.188']
    connection._context = TLS()
    connection.connect()
    assert calls == [('104.21.25.215', 443), ('172.67.134.188', 443)]
    assert connection.sock is sock


@pytest.mark.parametrize('phase,failure,code', [
    ('send', TimeoutError('private-secret'), 'GEN_TIMEOUT'),
    ('headers', __import__('http.client', fromlist=['RemoteDisconnected']).RemoteDisconnected('private-secret'), 'GEN_DISCONNECTED'),
    ('body', __import__('http.client', fromlist=['IncompleteRead']).IncompleteRead(b'private-secret'), 'GEN_INCOMPLETE'),
])
def test_paid_request_records_failure_phase_without_replay(monkeypatch, phase, failure, code):
    fake_transport(monkeypatch, {})
    calls = []
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs):
            calls.append('request')
            if phase == 'send': raise failure
        def getresponse(self):
            if phase == 'headers': raise failure
            return self
        status = 200
        def read(self, *args): raise failure
        def close(self): calls.append('close')
    monkeypatch.setattr(providers, 'PinnedHTTPS', Connection)
    with pytest.raises(providers.UnknownOutcome) as error:
        providers.post_json({'base_url':'https://models.example/v1'}, 'secret', '/chat/completions', {})
    message = str(error.value)
    assert code in message and {'send':'发送请求','headers':'等待响应','body':'读取响应'}[phase] in message
    assert 'private-secret' not in message
    assert calls == ['request','close']


def test_explicit_proxy_tunnels_to_pinned_ip_with_target_tls(monkeypatch):
    monkeypatch.setenv('PROVIDER_HTTP_PROXY', 'http://127.0.0.1:7890')
    calls = []
    class Socket:
        def settimeout(self, timeout): pass
        def close(self): pass
    sock = Socket()
    class Tunnel:
        def __init__(self, host, port, timeout):
            assert (host,port)==('127.0.0.1',7890)
            self.sock = sock
        def set_tunnel(self, host, port): calls.append(('tunnel',host,port))
        def connect(self): calls.append(('connect',))
        def close(self): pass
    class TLS:
        def wrap_socket(self, value, server_hostname):
            assert value is sock
            calls.append(('tls',server_hostname))
            return sock
    monkeypatch.setattr(providers.http.client, 'HTTPConnection', Tunnel)
    connection=providers.PinnedHTTPS('models.example','8.8.8.8',timeout=20)
    connection._context=TLS()
    connection.connect()
    assert calls==[('tunnel','8.8.8.8',443),('connect',),('tls','models.example')]


@pytest.mark.parametrize('url',['https://127.0.0.1:7890','http://user:pass@127.0.0.1:7890','http://127.0.0.1:7890/path'])
def test_invalid_explicit_proxy_fails_closed(monkeypatch,url):
    monkeypatch.setenv('PROVIDER_HTTP_PROXY',url)
    connection=providers.PinnedHTTPS('models.example','8.8.8.8',timeout=20)
    with pytest.raises(providers.ProviderError,match='代理'):
        connection.connect()


def test_preconnect_failure_does_not_claim_remote_billing(monkeypatch):
    monkeypatch.delenv('PROVIDER_HTTP_PROXY', raising=False)
    monkeypatch.setattr(providers, 'public_addresses', lambda host: ['8.8.8.8'])
    def unreachable(*args, **kwargs): raise TimeoutError('sensitive')
    monkeypatch.setattr(providers.socket, 'create_connection', unreachable)
    with pytest.raises(providers.ProviderError) as error:
        providers.post_json({'base_url':'https://models.example/v1'}, 'secret', '/chat/completions', {})
    assert not isinstance(error.value, providers.UnknownOutcome)
    assert '[GEN_CONNECT]' in str(error.value) and '尚未发送' in str(error.value)
