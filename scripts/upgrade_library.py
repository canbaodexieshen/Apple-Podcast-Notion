"""Upgrade existing Notion content without Apple login or any paid AI requests."""
from sync import Notion, finalize_metadata, safe_error, text_value
from mindmap_library import ensure_database, lookup, retire_markdown_property
from presentation import saved_outline, set_mindmap


def main():
    notion=Notion()
    notion.prepare(True)
    ensure_database(notion)
    finalize_metadata(notion)
    count=0
    episodes=list(notion.index('Episode','Eid').values())
    for index,page in enumerate(episodes,1):
        if not (lookup(notion,page['id'],create=False) or text_value(page,'脑图指纹') or
                'save_markmap' in text_value(page,'AI状态')):
            continue
        print(f'Inspecting saved mindmap {index}/{len(episodes)}',flush=True)
        outline=saved_outline(notion,page['id'])
        if outline:
            set_mindmap(notion,page['id'],outline)
            count+=1
    retire_markdown_property(notion)
    print(f'Upgrade complete: {count} existing mindmaps refreshed; no AI requests made',flush=True)
    print('Mindmap database: https://www.notion.so/'+notion.dbs['思维导图'].replace('-',''),flush=True)


if __name__=='__main__':
    try:main()
    except Exception as e:
        print('Upgrade failed: '+safe_error(e));raise SystemExit(1)
