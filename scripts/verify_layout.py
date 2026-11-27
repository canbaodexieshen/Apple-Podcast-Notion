"""Read back every migrated Apple episode and related metadata."""
from sync import Notion, safe_error
from presentation import children, plain, TAB_NAMES, library_outline
from mindmap_library import outline_tree, heading_kind
from urllib.parse import urlsplit


def verify_headings(notion,parent,nodes):
    blocks=children(notion,parent)
    if len(blocks)!=len(nodes):raise ValueError('Mindmap heading count differs from saved HTML')
    for block,node in zip(blocks,nodes):
        kind=heading_kind(node)
        if block['type']!=kind or not block[kind].get('is_toggleable') or plain(block)!=node['label']:
            raise ValueError('Mindmap requires native toggleable heading levels')
        if node['children']:
            verify_headings(notion,block['id'],node['children'])
        elif block.get('has_children'):
            raise ValueError('Unexpected nested mindmap content')


def main():
    n=Notion()
    episodes=n.index('Episode','Eid')
    maps=0
    brains={}
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
        brains[page['id']]=children(n,tabs[1]['id'])
        maps+=sum(b['type']=='embed' for b in brains[page['id']])
    all_shows=list(n.paginate('databases/'+n.dbs['Podcast']+'/query',{}))
    for p in all_shows:
        if not p['properties'].get('全部',{}).get('relation'):
            raise ValueError('Podcast missing 全部 relation')
    authors=list(n.paginate('databases/'+n.dbs['Author']+'/query',{}))
    if any(not p.get('icon') for p in authors):
        raise ValueError('Author missing icon')
    if '思维导图' not in n.dbs:raise ValueError('Mindmap database missing')
    if '脑图Markdown' in n.call('GET','databases/'+n.dbs['思维导图'])['properties']:
        raise ValueError('Obsolete 脑图Markdown property remains')
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
        outline=library_outline(n,record)
        title,nodes=outline_tree(outline)
        if plain(blocks[1])!=title:raise ValueError('Mindmap title differs from saved HTML')
        verify_headings(n,blocks[1]['id'],nodes)
        episode_blocks=brains.get(relations[0]['id'],[])
        index=next((i for i,b in enumerate(episode_blocks) if b['type']=='embed'),None)
        if index is None or index+1>=len(episode_blocks):raise ValueError('Episode mindmap mention missing')
        link=episode_blocks[index+1]
        runs=link.get('paragraph',{}).get('rich_text',[])
        if not (link['type']=='paragraph' and len(runs)==1 and runs[0].get('type')=='mention' and
                runs[0]['mention'].get('page',{}).get('id')==record['id']):
            raise ValueError('Episode mindmap requires native page mention immediately below HTML')
    print(f'Verified: {len(episodes)} Apple episodes with four tabs, images and dates; '
          f'{maps} interactive maps; {len(library)} mindmap records with PNG covers and files; '
          f'{len(all_shows)} linked podcasts; {len(authors)} author icons')


if __name__=='__main__':
    try:
        main()
    except Exception as e:
        print('Layout validation failed: '+safe_error(e))
        raise SystemExit(1)
