"""Read-only project snapshot plus an isolated demonstration of check's limits."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CLI = ROOT/'strateg/tools/strateg.py'

def command(args, env=None):
    r = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8')
    return {'code':r.returncode,'stdout':r.stdout,'stderr':r.stderr}

def main():
    snapshot = {'date_moscow':'2026-11-16',
        'commit':command(['git','-c',f'safe.directory={ROOT.as_posix()}','rev-parse','HEAD'])['stdout'].strip(),
        'projects':sorted(p.name for p in (ROOT/'strateg/projects').iterdir() if p.is_dir()),
        'knowledge_files':[p.relative_to(ROOT).as_posix() for p in (ROOT/'strateg/knowledge').rglob('*') if p.is_file()],
        'check_polka':command([sys.executable, '-X','utf8',str(CLI),'check','polka']),
        'cost_polka':command([sys.executable, '-X','utf8',str(CLI),'cost','polka']),
        'scope':'No access to secret values or real interview recordings; no full end-to-end new-session test.'}
    # Own synthetic fixture. Verify cleanup target is inside the intended workspace.
    with tempfile.TemporaryDirectory(prefix='t22-proof-', dir=ROOT.parent) as tmp:
        assert Path(tmp).resolve().is_relative_to(ROOT.parent.resolve())
        env = dict(os.environ, STRATEG_PROJECTS=tmp)
        records=[]
        def cli(*args):
            r=command([sys.executable,'-X','utf8',str(CLI),*args],env)
            records.append({'args':list(args),**r})
            return r
        assert cli('new','proof-gap')['code']==0
        p=Path(tmp)/'proof-gap'
        (p/'materials/source.txt').write_text('Учебный источник. Размер рынка неизвестен. Данных о 900 млрд рублей здесь нет.\n',encoding='utf-8')
        assert cli('source','proof-gap','--kind','doc','--title','Собственный источник для проверки','--ref','materials/source.txt','--local','materials/source.txt')['code']==0
        assert cli('claim','proof-gap','--type','fact','--text','Размер рынка составляет 900 млрд рублей','--source','S-001:строка 1')['code']==0
        passed=cli('check','proof-gap')
        snapshot['unsupported_claim_probe']={'source_text':(p/'materials/source.txt').read_text(encoding='utf-8'),
            'records':records,'accepted':passed['code']==0,
            'meaning':'Structural check accepts an unsupported fact with an existing source ID and arbitrary location. It does not verify entailment.'}
    out=HERE/'snapshot.json'
    out.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'commit':snapshot['commit'],'projects':snapshot['projects'],
        'knowledge_files':snapshot['knowledge_files'],'unsupported_claim_accepted':snapshot['unsupported_claim_probe']['accepted'],
        'check_exit':snapshot['check_polka']['code']},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
