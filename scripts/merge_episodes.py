"""Merge a reviewed legacy duplicate with identical stored content, using a backup."""
import argparse
import json
from pathlib import Path
from sync import Notion, text_value, prop, safe_error


def signature(page):
    ignored={'created_time','last_edited_time','formula','rollup','unique_id'}
    result={}
    for name,value in page['properties'].items():
        kind=value['type']
        if kind not in ignored:result[name]=(kind,value.get(kind))
    return result


def merge(notion,eid,canonical,backup):
    rows=list(notion.paginate('databases/'+notion.dbs['Episode']+'/query',
        {'filter':{'property':'Eid','rich_text':{'equals':eid}}}))
    if len(rows)==1:
        print('Episode already unique; no merge needed');return rows[0]
    if len(rows)!=2:raise ValueError('Expected exactly two reviewed duplicate episode records')
    keep=next((p for p in rows if p['id'].replace('-','')==canonical.replace('-','')),None)
    if not keep:raise ValueError('Canonical page is not one of the duplicate records')
    duplicate=next(p for p in rows if p['id']!=keep['id'])
    bodies={p['id']:list(notion.paginate('blocks/'+p['id']+'/children')) for p in rows}
    # This migration is intentionally narrow; complex/conflicting notes require review.
    if signature(keep)!=signature(duplicate):raise ValueError('Duplicate properties differ; both pages preserved')
    if any(bodies.values()):raise ValueError('Duplicate has body content; both pages preserved for review')
    incoming=[]
    for db in notion.dbs.values():
        schema=notion.call('GET','databases/'+db)['properties']
        for field,value in schema.items():
            if value['type']!='relation' or value['relation']['database_id'].replace('-','')!=notion.dbs['Episode'].replace('-',''):
                continue
            for page in notion.paginate('databases/'+db+'/query',
                {'filter':{'property':field,'relation':{'contains':duplicate['id']}}}):
                if page['properties'][field].get('has_more'):raise ValueError('Relation requires extended pagination; no merge applied')
                incoming.append({'page':page,'field':field})
    if backup.exists():raise ValueError('Backup exists; choose a new path')
    backup.parent.mkdir(parents=True,exist_ok=True)
    backup.write_text(json.dumps({'canonical':keep,'duplicate':duplicate,'bodies':bodies,'incoming':incoming},
        ensure_ascii=False),encoding='utf-8')
    for item in incoming:
        page,field=item['page'],item['field']
        values=list(dict.fromkeys(keep['id'] if r['id']==duplicate['id'] else r['id']
            for r in page['properties'][field]['relation']))
        notion.call('PATCH','pages/'+page['id'],{'properties':{field:prop('relation',[{'id':v} for v in values])}})
    # Comments remain attached to the recoverable archived page, never silently removed.
    notion.call('PATCH','pages/'+duplicate['id'],{'archived':True})
    verified=list(notion.paginate('databases/'+notion.dbs['Episode']+'/query',
        {'filter':{'property':'Eid','rich_text':{'equals':eid}}}))
    if len(verified)!=1 or verified[0]['id']!=keep['id']:raise ValueError('Merge verification failed')
    print(f'Legacy episode merged; {len(incoming)} incoming relations moved; duplicate soft-archived')
    return keep


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--eid',required=True)
    parser.add_argument('--canonical',required=True)
    parser.add_argument('--backup',type=Path,required=True)
    args=parser.parse_args()
    try:merge(Notion(),args.eid,args.canonical,args.backup)
    except Exception as e:
        print('Episode merge failed: '+safe_error(e));raise SystemExit(1)
