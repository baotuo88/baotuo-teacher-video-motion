import copy

import pytest

from app.models import ProjectInput
from app.store import Store


@pytest.fixture
def fixture(tmp_path):
    db = Store(tmp_path)
    p = db.create(ProjectInput(title='讲解', scenes=[{'title':'旧稿','narration':'原口播','points':['要点']}]).model_dump())
    db.confirm(p['id'],1)
    job = db.enqueue(p['id'],1,'storyboard',{'auto_apply':True},None,'auto-fixture')
    db.claim()
    scenes = ProjectInput(title='test',scenes=[{'title':'生成分镜','narration':'新口播','points':[]}]).model_dump()['scenes']
    return db,p,job,{'scenes':scenes,'project_version':1}


def test_auto_apply_is_atomic_idempotent_and_reversible(fixture):
    db,p,j,result=fixture
    db.complete_generated(j['id'],result)
    current=db.project(p['id'])
    assert current['version']==2 and not current['confirmed']
    assert current['scenes'][0]['title']=='生成分镜'
    done=db.job(j['id'])
    assert done['status']=='succeeded' and done['result']['application']['version']==2
    assert done['result']['review']['method']=='local_rules'
    assert any('没有画面要点' in x for x in done['result']['review']['suggestions'])
    assert done['snapshot']['project']['scenes'][0]['title']=='旧稿'
    db.complete_generated(j['id'],result)
    assert db.project(p['id'])['version']==2
    assert len(db.revisions(p['id']))==2


def test_conflict_keeps_result_without_overwriting(fixture):
    db,p,j,result=fixture
    document={k:p[k] for k in ('title','topic','style','scenes')}
    document['title']='人工修改'
    db.edit(p['id'],1,document)
    db.complete_generated(j['id'],result)
    assert db.project(p['id'])['title']=='人工修改'
    assert db.project(p['id'])['scenes'][0]['title']=='旧稿'
    assert db.job(j['id'])['result']['application']['status']=='conflict'
    assert db.job(j['id'])['status']=='succeeded'


def test_cancel_does_not_apply(fixture):
    db,p,j,result=fixture
    db.cancel(j['id'])
    db.complete_generated(j['id'],result)
    assert db.project(p['id'])['version']==1
    assert db.job(j['id'])['status']=='cancelled'


@pytest.mark.parametrize('confirmed', [False, True])
@pytest.mark.parametrize('kind', ['image','speech'])
def test_media_applies_exact_scene_and_preserves_other_fields(tmp_path,kind,confirmed):
    import io,wave
    from PIL import Image
    from app.assets import upload
    db=Store(tmp_path)
    p=db.create(ProjectInput(title='媒体',scenes=[{'title':'第一','narration':'测试','points':['一']},{'title':'第二','narration':'测试','points':['二']}]).model_dump())
    if confirmed: db.confirm(p['id'], 1)
    data=io.BytesIO()
    if kind=='image': Image.new('RGB',(80,80)).save(data,format='PNG')
    else:
        with wave.open(data,'wb') as f:
            f.setparams((1,2,24000,0,'NONE','not compressed')); f.writeframes(b'\0\0'*24000)
    asset=upload(db,'fixture','image' if kind=='image' else 'audio',data.getvalue())
    j=db.enqueue(p['id'],1,kind,{'auto_apply':True,'scene_index':1},None,'fixture')
    db.claim()
    db.complete_generated(j['id'],{'asset':asset,'scene_index':1})
    new=db.project(p['id'])
    field='image_id' if kind=='image' else 'audio_id'
    assert new['scenes'][1][field]==asset['id']
    assert not new['scenes'][0][field]
    assert new['scenes'][1]['narration']=='测试'
    assert new['confirmed'] == confirmed
    document = {key:new[key] for key in ('title','topic','style','scenes')}
    document['scenes'][1]['narration'] = '修改口播'
    edited = db.edit(p['id'], 2, document)
    assert not edited['confirmed']
