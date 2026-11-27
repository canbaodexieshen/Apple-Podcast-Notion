"""Merge reviewed cross-platform shows. Preserves legacy IDs and all episode pages."""
import argparse
import json
from pathlib import Path
from sync import Notion,podcast_aliases,text_value,prop,safe_error


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--backup-dir',type=Path,required=True)
    args=parser.parse_args()
    n=Notion()
    rows=list(n.paginate('databases/'+n.dbs['Podcast']+'/query',{}))
    by_pid={text_value(p,'Pid'):p for p in rows}
    plans=[]
    for apple,legacy in podcast_aliases().items():
        original=by_pid.get(legacy)
        duplicate=by_pid.get('apple:'+apple)
        if not original:raise ValueError('Missing canonical legacy show: '+legacy)
        if not duplicate:continue
        if text_value(original,'播客')!=text_value(duplicate,'播客'):
            raise ValueError('Reviewed titles no longer match; stop for inspection')
        body=list(n.paginate('blocks/'+duplicate['id']+'/children'))
        if body:raise ValueError('Duplicate has page content; preserve for manual review')
        episodes=list(n.paginate('databases/'+n.dbs['Episode']+'/query',
            {'filter':{'property':'Podcast','relation':{'contains':duplicate['id']}}}))
        plans.append({'canonical':original,'duplicate':duplicate,'episodes':episodes})
    args.backup_dir.mkdir(parents=True,exist_ok=True)
    backup=args.backup_dir/'podcast-merge-backup.json'
    if backup.exists():raise ValueError('Backup already exists; choose a new backup directory')
    backup.write_text(json.dumps(plans,ensure_ascii=False),encoding='utf-8')
    print('Reviewed pairs:',len(plans),'episode relations:',sum(len(p['episodes']) for p in plans),flush=True)
    if not args.apply:return
    for plan in plans:
        canonical,duplicate=plan['canonical'],plan['duplicate']
        # Keep the original page, Pid, URLs, listening totals, ratings and notes.
        for episode in plan['episodes']:
            relations=episode['properties']['Podcast']['relation']
            targets=list(dict.fromkeys(canonical['id'] if r['id']==duplicate['id'] else r['id'] for r in relations))
            n.call('PATCH','pages/'+episode['id'],{'properties':{'Podcast':prop('relation',[{'id':r} for r in targets])}})
        authors=list(dict.fromkeys(r['id'] for p in (canonical,duplicate)
            for r in p['properties'].get('作者',{}).get('relation',[])))
        n.call('PATCH','pages/'+canonical['id'],{'properties':{'作者':prop('relation',[{'id':r} for r in authors])}})
        apple_url=duplicate['properties'].get('链接',{}).get('url')
        body=list(n.paginate('blocks/'+canonical['id']+'/children'))
        if apple_url and not any(b['type']=='bookmark' and b['bookmark']['url']==apple_url for b in body):
            n.call('PATCH','blocks/'+canonical['id']+'/children',{'children':[
                {'object':'block','type':'bookmark','bookmark':{'url':apple_url}}]})
        # Verify all incoming episode links moved before soft-archiving the duplicate.
        remaining=list(n.paginate('databases/'+n.dbs['Episode']+'/query',
            {'filter':{'property':'Podcast','relation':{'contains':duplicate['id']}}}))
        if remaining:raise ValueError('Episode references remain; duplicate not archived')
        n.call('PATCH','pages/'+duplicate['id'],{'archived':True})
        print('Merged:',text_value(canonical,'播客'),'; retained legacy ID; moved',len(plan['episodes']),'episode links',flush=True)
    resolved=n.index('Podcast','Pid')
    for apple,legacy in podcast_aliases().items():
        if text_value(resolved['apple:'+apple],'Pid')!=legacy:
            raise ValueError('Alias resolution verification failed')
    print('Merge and future alias resolution verified',flush=True)


if __name__=='__main__':
    try:main()
    except Exception as e:
        print('Merge failed:',safe_error(e));raise SystemExit(1)
