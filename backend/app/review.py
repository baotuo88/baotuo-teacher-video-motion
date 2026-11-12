"""Local advisory checks, not factual, visual or speech quality verification."""
from .models import ProjectInput


def review_document(document, kind):
    suggestions = []
    scenes = document['scenes']
    titles = set()
    for i, scene in enumerate(scenes):
        page = i + 1
        title = scene['title'].strip()
        if title in titles:
            suggestions.append(f'第{page}页标题重复，建议确认是否有重复讲解。')
        titles.add(title)
        if not scene['points']:
            suggestions.append(f'第{page}页没有画面要点，建议补充关键信息。')
        if len(scene['narration']) > 200:
            suggestions.append(f'第{page}页口播较长，建议拆页并试听节奏。')
        if any(len(point) > 70 for point in scene['points']):
            suggestions.append(f'第{page}页要点较长，建议精简并检查文字排版。')
    suggestions.append({'storyboard': '请核对知识事实、数字与术语，确认受众难度和前后逻辑。',
                        'image': '请查看图片与本页主题是否一致，并检查文字、细节和版权来源。',
                        'speech': '请试听发音、专有名词、停顿与音量；导出后检查字幕同步。'}[kind])
    return {'method': 'local_rules', 'scope': '仅结构与长度规则，不验证事实、图像语义或语音质量；未调用额外模型。',
            'suggestions': suggestions}


def result_document(job, result):
    project = job['snapshot']['project']
    document = {key: project[key] for key in ('title', 'topic', 'style', 'scenes')}
    # Validation produces a deep copy; never mutate the job snapshot.
    document = ProjectInput.model_validate(document).model_dump()
    if job['kind'] == 'storyboard':
        document['scenes'] = result['scenes']
    else:
        index = result['scene_index']
        if index != job['snapshot']['options']['scene_index']:
            raise ValueError('生成结果页码与任务不一致')
        document['scenes'][index]['image_id' if job['kind'] == 'image' else 'audio_id'] = result['asset']['id']
    return ProjectInput.model_validate(document).model_dump()


def media_revision_compatible(source, candidate, index, field):
    """Conservative merge without scene IDs: only media bindings may differ.

    Full ordered content equality protects page identity and generation context.
    The target binding must never have changed, including edit-then-restore.
    """
    def content(document):
        return {**document, 'scenes': [
            {key: value for key, value in scene.items() if key not in ('image_id', 'audio_id')}
            for scene in document['scenes']
        ]}
    return (content(source) == content(candidate)
            and source['scenes'][index].get(field) == candidate['scenes'][index].get(field))
