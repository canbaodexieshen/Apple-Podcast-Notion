"""Read back every migrated Apple episode and related metadata."""
from sync import Notion, safe_error
from presentation import children, plain, TAB_NAMES
from urllib.parse import urlsplit


def main():
    n=Notion()
    episodes=n.index('Episode','Eid')
    maps=0
    for eid,page in episodes.items():
        blocks=children(n,page['id'])
        containers=[b for b in blocks if b['type']=='tab']
        tabs=next((children(n,b['id']) for b in containers
                   if [plain(x) for x in children(n,b['id'])]==list(TAB_NAMES)),None)
        if tabs is None:
            raise ValueError('Missing four native tabs for '+eid)
        if not page.get('icon') or not page.get('cover'):
            raise ValueError('Missing episode icon/cover: '+eid)
        props=page['properties']
        progress=props.get('进度更新时间',{}).get('date')
        listening=props.get('最近收听时间',{}).get('date')
        if progress!=listening:
            raise ValueError('Listening date differs from position timestamp: '+eid)
        if any(b['type']=='toggle' and plain(b).startswith('Apple Podcasts ·') for b in blocks):
            raise ValueError('Old generated toggles remain: '+eid)
        maps+=sum(b['type']=='embed' for b in children(n,tabs[1]['id']))
    all_shows=list(n.paginate('databases/'+n.dbs['Podcast']+'/query',{}))
    for p in all_shows:
        if not p['properties'].get('全部',{}).get('relation'):
            raise ValueError('Podcast missing 全部 relation')
    authors=list(n.paginate('databases/'+n.dbs['Author']+'/query',{}))
    if any(not p.get('icon') for p in authors):
        raise ValueError('Author missing icon')
    if '思维导图' not in n.dbs:raise ValueError('Mindmap database missing')
    library=list(n.paginate('databases/'+n.dbs['思维导图']+'/query',{}))
    targets=set()
    for record in library:
        props=record['properties']
        relations=props.get('播客单集',{}).get('relation',[])
        if len(relations)!=1 or relations[0]['id'] in targets:
            raise ValueError('Mindmap relation missing or duplicate')
        targets.add(relations[0]['id'])
        files=props.get('思维导图封面',{}).get('files',[])
        cover=(record.get('cover') or {}).get('file',{}).get('url','')
        image=files[0].get('file',{}).get('url','') if len(files)==1 else ''
        if not cover or not image or urlsplit(cover).path!=urlsplit(image).path:
            raise ValueError('Mindmap cover and files property do not share the saved PNG')
        blocks=children(n,record['id'])
        if len(blocks)<2 or [b['type'] for b in blocks[:2]]!=['heading_2','heading_1']:
            raise ValueError('Mindmap body hierarchy mismatch')
        if plain(blocks[0])!='脑图' or not all(b[b['type']].get('is_toggleable') for b in blocks[:2]):
            raise ValueError('Mindmap headings are not toggleable')
        if not any(b['type']=='embed' for b in children(n,blocks[0]['id'])):
            raise ValueError('Mindmap HTML missing')
    print(f'Verified: {len(episodes)} Apple episodes with four tabs, images and dates; '
          f'{maps} interactive maps; {len(library)} mindmap records with PNG covers and files; '
          f'{len(all_shows)} linked podcasts; {len(authors)} author icons')


if __name__=='__main__':
    try:
        main()
    except Exception as e:
        print('Layout validation failed: '+safe_error(e))
        raise SystemExit(1)
