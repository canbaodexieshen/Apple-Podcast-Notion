"""Read back every migrated Apple episode and related metadata."""
from sync import Notion, safe_error
from presentation import children, plain, TAB_NAMES


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
        listening=props.get('收听时间',{}).get('date')
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
    print(f'Verified: {len(episodes)} Apple episodes with four tabs, images and dates; '
          f'{maps} interactive maps; {len(all_shows)} linked podcasts; {len(authors)} author icons')


if __name__=='__main__':
    try:
        main()
    except Exception as e:
        print('Layout validation failed: '+safe_error(e))
        raise SystemExit(1)
