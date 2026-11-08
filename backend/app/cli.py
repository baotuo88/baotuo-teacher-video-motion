import argparse
import json
from pathlib import Path

from .runtime import ENGINE_REPO, SKILL_REPO, remote_head, stage
from .verification import activate, verify


def main():
    parser = argparse.ArgumentParser(description='上游 Skill 运行时管理（不会自动升级生产版本）')
    parser.add_argument('--root', type=Path, default=Path('.data/runtimes'))
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('check')
    candidate = sub.add_parser('stage')
    candidate.add_argument('--skill', required=True)
    candidate.add_argument('--engine', required=True)
    for name in ('verify', 'activate'):
        p = sub.add_parser(name)
        p.add_argument('runtime_id')
        if name == 'verify':
            p.add_argument('--trust-reviewed-code', action='store_true', required=True,
                           help='确认已审阅候选源码；该步骤会安装 npm 依赖并执行上游脚本')
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == 'check':
        result = {'skill': remote_head(SKILL_REPO), 'engine': remote_head(ENGINE_REPO)}
    elif args.command == 'stage':
        result = stage(root, args.skill, args.engine)
    elif args.command == 'verify':
        result = verify(root, args.runtime_id)
    else:
        result = activate(root, args.runtime_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
